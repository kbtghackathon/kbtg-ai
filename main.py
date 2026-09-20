"""
FastAPI Application for Recurring Expense Detection Microservice

This is a stateless microservice that analyzes bank statements and detects
recurring expenses without any database dependencies.
"""

import base64
import json
import logging
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException, status, File, UploadFile, Form
from pydantic import BaseModel, Field, TypeAdapter, ValidationError
import uvicorn

from src.pipeline.stateless_pipeline import analyze, analyze_from_text
from src.parser.pdf_extractor import PDFExtractionError
from src.categorizer.categorization_module import CategorizationModule
from src.recommender import (
    CashflowSignals,
    ExpenseSignal,
    SavingsRecommendationModule,
    SavingsSignals,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Request limits
MAX_PDF_FILES = 6
MAX_PDF_BYTES = 10 * 1024 * 1024      # 10 MB per statement PDF
MAX_TEXT_BYTES = 2 * 1024 * 1024      # 2 MB per statement text
PDF_MAGIC = b"%PDF"

# The savings recommender holds only its configuration and does no I/O, so one
# instance serves every request.
_savings_recommender = SavingsRecommendationModule()

# Merchant dictionary state (populated at startup)
merchant_dict_loaded = False
merchant_count = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load merchant dictionary on startup"""
    global merchant_dict_loaded, merchant_count
    try:
        CategorizationModule()
        cache = CategorizationModule._merchant_dict_cache or []
        merchant_count = len(cache)
        merchant_dict_loaded = merchant_count > 0
        if merchant_dict_loaded:
            logger.info(f"Merchant dictionary loaded successfully: {merchant_count} entries")
        else:
            logger.warning("Merchant dictionary is empty")
    except Exception as e:
        logger.error(f"Failed to load merchant dictionary: {e}")
        merchant_dict_loaded = False
    yield


app = FastAPI(
    title="Recurring Expense Detection API",
    description="Stateless microservice for analyzing bank statements and detecting recurring expenses",
    version="1.0.0",
    lifespan=lifespan,
)


def _openapi_with_binary_file_arrays():
    """
    FastAPI describes uploaded files as OpenAPI 3.1 `contentMediaType` strings. Swagger UI
    renders a file picker for a single such field but plain text boxes for an *array* of
    them (List[UploadFile]). Adding the classic `format: binary` makes the array render as
    file pickers too. Purely cosmetic for /docs; the endpoint behaviour is unchanged.
    """
    if app.openapi_schema:
        return app.openapi_schema
    schema = _default_openapi()
    for component in schema.get("components", {}).get("schemas", {}).values():
        for prop in component.get("properties", {}).values():
            items = prop.get("items")
            if isinstance(items, dict) and items.get("contentMediaType") == "application/octet-stream":
                items["format"] = "binary"
    app.openapi_schema = schema
    return schema


_default_openapi = app.openapi
app.openapi = _openapi_with_binary_file_arrays


# Pydantic models for request/response
class UserLabel(BaseModel):
    """User category label for a recipient"""
    recipient_key: str = Field(..., description="Unique recipient identifier")
    category: str = Field(..., description="Category code (e.g., 'rent', 'internet')")
    category_label_th: str = Field(..., description="Category label in Thai")


USER_LABEL_LIST = TypeAdapter(List[UserLabel])


class AnalyzeRequest(BaseModel):
    """Request model for /analyze endpoint"""
    statements_pdf_base64: List[str] = Field(
        ...,
        description="List of bank statement PDFs encoded as base64 strings (1-6 statements)",
        min_length=1,
        max_length=MAX_PDF_FILES,
    )
    current_salary: float = Field(..., description="User's current month salary", gt=0)
    existing_user_labels: List[UserLabel] = Field(
        default_factory=list,
        description="Existing user category labels for recurring expenses"
    )


class RecurringExpenseItem(BaseModel):
    """Single recurring expense item"""
    category: str
    category_label_th: str
    amount: float
    confidence: float
    recipient_key: str
    recurring_type: str = Field(
        default="monthly_fixed",
        description="monthly_fixed | monthly_variable | periodic_non_monthly",
    )
    amount_cv: float = Field(
        default=0.0,
        description="Coefficient of variation of the amount. 0 is a flat bill; "
                    "higher is one worth leaving headroom for.",
    )
    day_of_month: int = Field(
        default=0,
        description="Typical day of the month it lands on; 0 when undetermined",
    )
    n_months_present: int = Field(default=0, description="Months it was seen in")


class SampleTransaction(BaseModel):
    """Sample transaction for pending label"""
    date: Optional[str]
    amount: str
    recipient: str


class PendingLabel(BaseModel):
    """Pending user label item"""
    recipient_key: str
    detected_amount: float
    n_months_detected: int
    category_suggestions: List[str]
    sample_transactions: List[SampleTransaction]


class AnalyzeResponse(BaseModel):
    """Response model for /analyze endpoint"""
    salary_this_month: float = Field(..., description="User's current month salary")
    recurring_expenses: List[RecurringExpenseItem] = Field(..., description="List of detected recurring expenses")
    total_recurring: float = Field(..., description="Total recurring expenses amount")
    remaining_after_reserve: float = Field(..., description="Remaining income after recurring expenses")
    pending_user_labels: List[PendingLabel] = Field(..., description="Recurring expenses needing user category labels")
    updated_user_labels: List[UserLabel] = Field(..., description="Updated user labels (stateless mode: always empty)")
    data_completeness_warning: Optional[str] = Field(None, description="Warning message if data is incomplete (< 6 months)")
    data_months_available: int = Field(..., description="Number of months of data analyzed")
    parsed_transaction_count: int = Field(..., description="Total transactions parsed from PDFs")
    parse_success_rate: float = Field(..., description="Share of transaction records that parsed (0.0-1.0)")

    # Cash-flow signals: what the statement says about money moving, as
    # distinct from what is committed above.
    closing_balance: float = Field(default=0.0, description="Balance after the most recent transaction")
    observed_income: float = Field(default=0.0, description="Income actually seen, averaged per month it appeared in")
    income_months: int = Field(default=0, description="Months in which income was observed")
    payday_day_of_month: Optional[int] = Field(default=None, description="Day income usually lands; null when none was seen")
    variable_spend_monthly: float = Field(default=0.0, description="Monthly spend on everything not classified as recurring")
    avg_daily_spend: float = Field(default=0.0, description="Total outgoings divided by the days the statement spans")


class HealthResponse(BaseModel):
    """Health check response"""
    status: str = Field(..., description="Service status")
    merchant_dict_loaded: bool = Field(..., description="Whether merchant dictionary loaded")
    merchant_count: int = Field(..., description="Number of merchants in dictionary")


# ---------------------------------------------------------------------------
# Savings recommendation
# ---------------------------------------------------------------------------
# NOTE: every amount below is SATANG (1 baht = 100 satang), as an integer --
# unlike the analysis endpoints above, which speak float baht.
#
# The difference is deliberate. This number becomes a transfer between two real
# accounts, and float64 cannot hold 399.00 exactly; a savings feature that loses
# a satang a month to binary rounding is one with a reconciliation bug. The
# analysis contract keeps its floats; this one does not share them.


class ExpenseSignalItem(BaseModel):
    """One committed monthly cost, with the analyser's view of it."""

    amount: int = Field(default=0, description="Typical monthly amount (satang)")
    day_of_month: int = Field(default=0, alias="dayOfMonth", description="Day it lands; 0 = unknown, treated as still to come")
    amount_cv: float = Field(default=0.0, alias="amountCv", description="Coefficient of variation; 0 is a flat bill")
    recurring_type: str = Field(default="", alias="recurringType")
    recipient_key: str = Field(default="", alias="recipientKey")
    label_th: str = Field(default="", alias="labelTh")

    model_config = {"populate_by_name": True}


class CashflowSignalsItem(BaseModel):
    """What the statement said about the account, as opposed to what is committed."""

    closing_balance: int = Field(default=0, alias="closingBalance")
    observed_income: int = Field(default=0, alias="observedIncome", description="Income actually seen, per month it appeared in (satang)")
    income_months: int = Field(default=0, alias="incomeMonths")
    payday_day_of_month: int = Field(default=0, alias="paydayDayOfMonth")
    variable_spend_monthly: int = Field(default=0, alias="variableSpendMonthly")
    avg_daily_spend: int = Field(default=0, alias="avgDailySpend")

    model_config = {"populate_by_name": True}


class RecommendRequest(BaseModel):
    """One month of a person's finances. All amounts in satang."""

    user_id: str = Field(default="", alias="userId", description="Caller's user identifier")
    month: str = Field(default="", description="Month being planned, YYYY-MM")

    balance: int = Field(default=0, description="Current account balance (satang)")
    income: int = Field(..., gt=0, description="Expected income for the month (satang)")
    fixed_costs: int = Field(default=0, alias="fixedCosts", description="Committed monthly outflow (satang)")
    variable_spend: int = Field(default=0, alias="variableSpend", description="Discretionary spending so far this month (satang)")
    free_cash_flow: int = Field(default=0, alias="freeCashFlow", description="income - fixedCosts - variableSpend (satang)")
    avg_daily_spend: int = Field(default=0, alias="avgDailySpend", description="Average discretionary spend per elapsed day (satang)")
    days_remaining: int = Field(default=1, alias="daysRemaining", ge=0, description="Days left in the month, counting today")

    # The caller's guardrails. Sent so the recommendation can aim inside them;
    # the caller enforces them regardless of what comes back.
    min_per_month: int = Field(default=0, alias="minPerMonth", description="Caller's monthly minimum (satang)")
    max_per_month: int = Field(default=0, alias="maxPerMonth", description="Caller's monthly ceiling (satang)")
    buffer_balance: int = Field(default=0, alias="bufferBalance", description="Balance that must always remain (satang)")
    aggressiveness: str = Field(default="BALANCED", description="SAFE | BALANCED | BOLD")

    # How much statement the fixed-cost figure came from. Zero means the caller
    # has no analysis on file and used its own transaction history instead.
    data_months: int = Field(default=0, alias="dataMonths", ge=0, description="Months of statement analysed")
    parse_success_rate: float = Field(default=1.0, alias="parseSuccessRate", description="Share of statement lines parsed (0-1)")

    # The committed costs broken out, plus what the statement said about the
    # account. Optional: a caller with no analysis on file sends neither, and
    # the rules that depend on them simply do not fire.
    expenses: List[ExpenseSignalItem] = Field(default_factory=list, description="Committed costs, individually")
    cashflow: CashflowSignalsItem = Field(default_factory=CashflowSignalsItem)

    model_config = {"populate_by_name": True}


class SavingsReasonItem(BaseModel):
    """One line of the decision trace, shown to the user before they confirm."""

    label: str
    amount: int = Field(..., description="Running amount after this step (satang)")
    note: str = ""


class RecommendResponse(BaseModel):
    """The recommendation, before the caller applies its own limits."""

    recommended_amount: int = Field(..., alias="recommendedAmount", description="Amount to save this month (satang)")
    confidence: float = Field(..., description="0-1, how complete the underlying data was")
    model_version: str = Field(..., alias="modelVersion")
    reasons: List[SavingsReasonItem] = Field(default_factory=list)
    skip: bool = Field(default=False, description="Leave this month alone for a cash-flow reason")
    skip_reason: str = Field(default="", alias="skipReason")

    model_config = {"populate_by_name": True}



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _parse_labels_json(raw: Optional[str]) -> List[dict]:
    """Parse and validate the JSON-string form of existing_user_labels."""
    if not raw or not raw.strip():
        return []
    try:
        labels = USER_LABEL_LIST.validate_json(raw)
    except ValidationError as e:
        raise _bad_request(
            "existing_user_labels must be a JSON array of "
            "{recipient_key, category, category_label_th}: " + e.errors()[0].get("msg", "invalid")
        )
    return [label.model_dump() for label in labels]


def _check_pdf_bytes(pdf_bytes: bytes, label: str) -> None:
    """Reject payloads that are empty, too large, or not PDFs (by magic bytes, not client content-type)."""
    if not pdf_bytes:
        raise _bad_request(f"{label} is empty")
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"{label} exceeds the {MAX_PDF_BYTES // (1024 * 1024)} MB limit",
        )
    if not pdf_bytes.lstrip().startswith(PDF_MAGIC):
        raise _bad_request(f"{label} is not a PDF")


def _run_pdf_analysis(pdf_files: List[bytes], current_salary: float, labels: List[dict]) -> AnalyzeResponse:
    """Run the PDF pipeline and map domain errors onto HTTP statuses."""
    try:
        result = analyze(pdf_files=pdf_files, current_salary=current_salary, existing_user_labels=labels)
    except PDFExtractionError as e:
        # Corrupt, encrypted or text-less PDF: the client's problem, not ours
        logger.warning(f"PDF rejected: {e}")
        raise _bad_request(f"Could not read PDF: {e}")
    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        raise _bad_request(str(e))
    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Analysis failed")

    logger.info(
        f"Analysis complete: {result.parsed_transaction_count} transactions, "
        f"{len(result.recurring_expenses)} recurring expenses, total={result.total_recurring:.2f}"
    )
    return AnalyzeResponse(**result.__dict__)


def _run_text_analysis(texts: List[str], current_salary: float, labels: List[dict]) -> AnalyzeResponse:
    """Run the text pipeline and map domain errors onto HTTP statuses."""
    try:
        result = analyze_from_text(statement_texts=texts, current_salary=current_salary, existing_user_labels=labels)
    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        raise _bad_request(str(e))
    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Analysis failed")

    logger.info(
        f"Analysis complete: {result['parsed_transaction_count']} transactions, "
        f"{len(result['recurring_expenses'])} recurring expenses"
    )
    return AnalyzeResponse(**result)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
# Analysis handlers are plain `def` on purpose: PDF parsing is CPU-bound, and
# FastAPI runs sync handlers in a threadpool instead of blocking the event loop.

@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Health check endpoint. Returns service status and merchant dictionary info."""
    return HealthResponse(
        status="ok" if merchant_dict_loaded else "degraded",
        merchant_dict_loaded=merchant_dict_loaded,
        merchant_count=merchant_count,
    )


@app.post("/analyze", response_model=AnalyzeResponse, tags=["Analysis"])
def analyze_endpoint(request: AnalyzeRequest):
    """
    Analyze bank statements (base64-encoded PDFs) and detect recurring expenses.
    """
    logger.info(
        f"Received analyze request: {len(request.statements_pdf_base64)} PDFs, "
        f"salary={request.current_salary:.2f}, existing_labels={len(request.existing_user_labels)}"
    )

    pdf_files: List[bytes] = []
    for i, encoded in enumerate(request.statements_pdf_base64, start=1):
        try:
            pdf_bytes = base64.b64decode(encoded, validate=True)
        except Exception:
            raise _bad_request(f"PDF {i} is not valid base64")
        _check_pdf_bytes(pdf_bytes, f"PDF {i}")
        pdf_files.append(pdf_bytes)

    labels = [label.model_dump() for label in request.existing_user_labels]
    return _run_pdf_analysis(pdf_files, request.current_salary, labels)


@app.post("/analyze-upload", response_model=AnalyzeResponse, tags=["Analysis"])
def analyze_upload_endpoint(
    pdf_files: List[UploadFile] = File(..., description="PDF statement files (1-6 files)"),
    current_salary: float = Form(..., description="User's current month salary", gt=0),
    existing_user_labels: Optional[str] = Form(default="[]", description="JSON string of existing user labels"),
):
    """
    Analyze bank statements uploaded as multipart/form-data PDF files.

    Example (curl):
        curl -X POST http://localhost:8000/analyze-upload \\
          -F "pdf_files=@statement1.pdf" \\
          -F "pdf_files=@statement2.pdf" \\
          -F "current_salary=30000.0" \\
          -F "existing_user_labels=[]"
    """
    logger.info(f"Received analyze-upload request: {len(pdf_files)} PDFs, salary={current_salary:.2f}")

    if not (1 <= len(pdf_files) <= MAX_PDF_FILES):
        raise _bad_request(f"Must provide 1-{MAX_PDF_FILES} PDF files")

    labels = _parse_labels_json(existing_user_labels)

    contents: List[bytes] = []
    for i, upload in enumerate(pdf_files, start=1):
        # read(MAX+1) so an oversized file is detected without buffering all of it
        pdf_bytes = upload.file.read(MAX_PDF_BYTES + 1)
        _check_pdf_bytes(pdf_bytes, f"File {i}")
        contents.append(pdf_bytes)
        logger.info(f"Read PDF {i} ({len(pdf_bytes)} bytes)")

    return _run_pdf_analysis(contents, current_salary, labels)


@app.post("/analyze-text", response_model=AnalyzeResponse, tags=["Analysis"])
def analyze_text_endpoint(
    statement_text: str = Form(..., description="Bank statement text (raw text from PDF)"),
    current_salary: float = Form(..., description="User's current month salary", gt=0),
    existing_user_labels: Optional[str] = Form(default="[]", description="JSON string of existing user labels"),
):
    """
    Analyze bank statement from raw text directly (useful when PDF extraction is problematic).
    """
    logger.info(f"Received analyze-text request: salary={current_salary:.2f}")
    if len(statement_text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="statement_text too large")
    labels = _parse_labels_json(existing_user_labels)
    return _run_text_analysis([statement_text], current_salary, labels)


@app.post("/analyze-text-upload", response_model=AnalyzeResponse, tags=["Analysis"])
def analyze_text_upload_endpoint(
    text_file: UploadFile = File(..., description="Text file containing statement text"),
    current_salary: float = Form(..., description="User's current month salary", gt=0),
    existing_user_labels: Optional[str] = Form(default="[]", description="JSON string of existing user labels"),
):
    """
    Analyze bank statement from an uploaded UTF-8 .txt file.

    Example (curl):
        curl -X POST http://localhost:8000/analyze-text-upload \\
          -F "text_file=@statement_text.txt" \\
          -F "current_salary=30000.0" \\
          -F "existing_user_labels=[]"
    """
    content = text_file.file.read(MAX_TEXT_BYTES + 1)
    if len(content) > MAX_TEXT_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Text file too large")
    try:
        statement_text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise _bad_request("Text file must be UTF-8 encoded")

    logger.info(f"Received text file ({len(content)} bytes)")
    labels = _parse_labels_json(existing_user_labels)
    return _run_text_analysis([statement_text], current_salary, labels)


@app.post("/v1/savings/recommend", response_model=RecommendResponse, tags=["Savings"])
def recommend_savings_endpoint(request: RecommendRequest):
    """
    Recommend how much of this month's income to save.

    Amounts in and out are **satang** (integers), not baht -- see the note on
    RecommendRequest for why this endpoint differs from the analysis ones.

    The caller sends the figures it already holds rather than statements: this
    is called every time a plan is displayed, so it has to be fast, and the
    person's current balance and month-to-date spending live on the caller's
    side anyway.

    What comes back is a **proposal**. The caller applies the person's own
    minimum, maximum and safety buffer afterwards, so a bad recommendation can
    make a saving smaller or skip a month and nothing worse.

    `skip: true` means the month should be left alone for a cash-flow reason --
    the rest of it is already spoken for. That is different from recommending
    zero, which reads as "nothing useful to say" and has the caller fall back to
    its own rules.
    """
    signals = SavingsSignals(
        income=request.income,
        fixed_costs=request.fixed_costs,
        spent_so_far=request.variable_spend,
        avg_daily_spend=request.avg_daily_spend,
        days_remaining=request.days_remaining,
        balance=request.balance,
        min_per_month=request.min_per_month,
        max_per_month=request.max_per_month,
        buffer_balance=request.buffer_balance,
        aggressiveness=request.aggressiveness,
        data_months=request.data_months,
        parse_success_rate=request.parse_success_rate,
        month=request.month,
        expenses=[
            ExpenseSignal(
                amount=e.amount,
                day_of_month=e.day_of_month,
                amount_cv=e.amount_cv,
                recurring_type=e.recurring_type,
                recipient_key=e.recipient_key,
                label_th=e.label_th,
            )
            for e in request.expenses
        ],
        cashflow=CashflowSignals(
            closing_balance=request.cashflow.closing_balance,
            observed_income=request.cashflow.observed_income,
            income_months=request.cashflow.income_months,
            payday_day_of_month=request.cashflow.payday_day_of_month,
            variable_spend_monthly=request.cashflow.variable_spend_monthly,
            avg_daily_spend=request.cashflow.avg_daily_spend,
        ),
    )

    try:
        result = _savings_recommender.recommend(signals)
    except Exception as e:
        logger.error(f"Savings recommendation failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Savings recommendation failed",
        )

    logger.info(
        f"Recommendation for {request.user_id or 'anonymous'} {request.month}: "
        f"amount={result.amount} skip={result.skip} confidence={result.confidence:.2f}"
    )

    return RecommendResponse(
        recommended_amount=result.amount,
        confidence=result.confidence,
        model_version=result.model_version,
        reasons=[
            SavingsReasonItem(label=r.label, amount=r.amount, note=r.note)
            for r in result.reasons
        ],
        skip=result.skip,
        skip_reason=result.skip_reason,
    )


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint"""
    return {
        "service": "Recurring Expense Detection API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False, log_level="info")
