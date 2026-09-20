"""
Stateless Main Processing Pipeline

This module implements the stateless orchestration function for the recurring expense
detection system for microservice deployment.

All components work with in-memory data only - no database persistence.
"""

import logging
import base64
from typing import List, Optional, Dict, Any, Tuple
from datetime import date, datetime
from dataclasses import dataclass, asdict
from uuid import uuid4

from ..parser.pdf_extractor import PDFTextExtractor, PDFExtractionError
from ..parser.record_parser import RecordParser, RawTransaction, ParseStats
from ..parser.columnar_parser import ColumnarStatementParser, looks_like_columnar
from ..normalizer.transaction_normalizer import TransactionNormalizer
from ..categorizer.categorization_module import CategorizationModule
from ..detector.recurring_detection_engine import RecurringDetectionEngine, RecurringType
from ..forecaster.amount_forecast_module import AmountForecastModule
from ..aggregator.aggregation_service import AggregationService
from ..aggregator.cashflow_signals import derive_cashflow_signals
from ..config.detection_config import DetectionConfig
from ..config.forecast_config import ForecastConfig

logger = logging.getLogger(__name__)

NO_TRANSACTIONS_PDF_WARNING = "ไม่สามารถแยกวิเคราะห์ธุรกรรมจาก PDF ที่ให้มา"
NO_TRANSACTIONS_TEXT_WARNING = "ไม่สามารถแยกวิเคราะห์ธุรกรรมจากข้อความที่ให้มา"


@dataclass
class AnalyzeResponse:
    """Complete response from analyze function"""
    salary_this_month: float
    recurring_expenses: List[Dict[str, Any]]
    total_recurring: float
    remaining_after_reserve: float
    pending_user_labels: List[Dict[str, Any]]
    updated_user_labels: List[Dict[str, Any]]
    data_completeness_warning: Optional[str]
    data_months_available: int
    parsed_transaction_count: int
    parse_success_rate: float

    # Cash-flow signals: what the statement says about money moving, as
    # distinct from what is committed. All default so an empty response and
    # the text pipeline stay valid without restating them.
    closing_balance: float = 0.0
    observed_income: float = 0.0
    income_months: int = 0
    payday_day_of_month: Optional[int] = None
    variable_spend_monthly: float = 0.0
    avg_daily_spend: float = 0.0


def analyze(
    pdf_files: List[bytes],
    current_salary: float,
    existing_user_labels: Optional[List[dict]] = None,
    statement_months: Optional[List[date]] = None,
    detection_config: Optional[DetectionConfig] = None,
    forecast_config: Optional[ForecastConfig] = None
) -> AnalyzeResponse:
    """
    Main stateless pipeline for recurring expense detection.

    Pipeline:
    1. Extract text from PDFs
    2. Parse transactions from raw text
    3-8. Shared pipeline (see _run_pipeline)

    Args:
        pdf_files: List of PDF file contents as bytes (1-6 months of statements)
        current_salary: User's current month salary
        existing_user_labels: List of dicts with keys: recipient_key, category, category_label_th
        statement_months: Optional override for each statement's month. If None, each
                          transaction's statement month is derived from its own date.
        detection_config: Detection thresholds (default if None)
        forecast_config: Forecasting parameters (default if None)

    Returns:
        AnalyzeResponse with complete summary and metadata

    Raises:
        PDFExtractionError: If any PDF cannot be read
    """
    logger.info(
        f"Starting stateless pipeline: {len(pdf_files)} PDFs, "
        f"salary={current_salary:.2f}, "
        f"existing_labels={len(existing_user_labels or [])}"
    )

    # STEP 1: PDF Text Extraction
    logger.info(f"Step 1: Extracting text from {len(pdf_files)} PDF files")
    extractor = PDFTextExtractor()
    raw_texts: List[str] = []
    for i, pdf_bytes in enumerate(pdf_files):
        try:
            raw_texts.append(extractor.extract_text_from_pdf_bytes(pdf_bytes))
            logger.info(f"Successfully extracted text from PDF {i+1}")
        except PDFExtractionError as e:
            logger.error(f"Failed to extract text from PDF {i+1}: {str(e)}")
            raise

    # STEP 2: Transaction Parsing (a failing statement is skipped, others continue)
    all_raw_transactions, parse_stats = _parse_statements(raw_texts, statement_months, raise_on_error=False)

    if not all_raw_transactions:
        logger.warning("No transactions successfully parsed from any PDF")
        return _empty_response(current_salary, NO_TRANSACTIONS_PDF_WARNING)

    return _run_pipeline(
        all_raw_transactions,
        current_salary,
        existing_user_labels or [],
        detection_config or DetectionConfig(),
        forecast_config or ForecastConfig(),
        parse_stats,
    )


def analyze_from_base64(
    statements_pdf_base64: List[str],
    current_salary: float,
    existing_user_labels: Optional[List[dict]] = None
) -> Dict[str, Any]:
    """
    Convenience function that accepts base64-encoded PDFs.

    Returns:
        Dict representation of AnalyzeResponse
    """
    pdf_files = []
    for i, pdf_base64 in enumerate(statements_pdf_base64):
        try:
            pdf_files.append(base64.b64decode(pdf_base64, validate=True))
        except Exception as e:
            logger.error(f"Failed to decode base64 PDF {i+1}: {str(e)}")
            raise ValueError(f"Invalid base64 encoding for PDF {i+1}")

    response = analyze(
        pdf_files=pdf_files,
        current_salary=current_salary,
        existing_user_labels=existing_user_labels
    )
    return asdict(response)


def analyze_from_text(
    statement_texts: List[str],
    current_salary: float,
    existing_user_labels: Optional[List[dict]] = None,
    statement_months: Optional[List[date]] = None
) -> Dict[str, Any]:
    """
    Convenience function that accepts raw statement text directly.
    Skips PDF extraction step - useful when PDF fonts are problematic.

    Args:
        statement_texts: List of raw statement text strings (1-6 months)
        current_salary: User's current month salary
        existing_user_labels: Existing user category labels
        statement_months: Optional override for each statement's month

    Returns:
        Dict representation of AnalyzeResponse

    Raises:
        ValueError: If a statement text cannot be parsed
    """
    logger.info(
        f"Starting text-based pipeline: {len(statement_texts)} texts, "
        f"salary={current_salary:.2f}, "
        f"existing_labels={len(existing_user_labels or [])}"
    )

    all_transactions, parse_stats = _parse_statements(statement_texts, statement_months, raise_on_error=True)

    if not all_transactions:
        logger.warning("No transactions parsed from statement texts")
        return asdict(_empty_response(current_salary, NO_TRANSACTIONS_TEXT_WARNING))

    response = _run_pipeline(
        all_transactions,
        current_salary,
        existing_user_labels or [],
        DetectionConfig(),
        ForecastConfig(),
        parse_stats,
    )
    return asdict(response)


def _parse_statements(
    raw_texts: List[str],
    statement_months: Optional[List[date]],
    raise_on_error: bool,
) -> Tuple[List[RawTransaction], ParseStats]:
    """
    Parse every statement text into RawTransactions, with the parser's own
    account of how much of them it could read.

    Each transaction's source_statement_month is the first day of the month of its
    own transaction date, unless statement_months overrides it. This is what makes
    month counting downstream correct: previously every statement was stamped with
    the current month, so total_months was always 1.
    """
    if statement_months is not None and len(statement_months) != len(raw_texts):
        raise ValueError(
            f"statement_months has {len(statement_months)} entries "
            f"but {len(raw_texts)} statements were provided"
        )

    # Which parser to use is decided from the statements themselves rather than
    # configured: the person uploading a PDF knows what their bank calls it, not
    # which of our layouts it matches. One parser serves every statement in the
    # batch -- they come from one account, so a batch that needs two parsers is
    # a batch with something wrong in it.
    parser = _select_parser(raw_texts)
    all_transactions: List[RawTransaction] = []

    for i, raw_text in enumerate(raw_texts):
        override_month = statement_months[i] if statement_months else None
        placeholder = override_month or date.today().replace(day=1)
        try:
            transactions = parser.parse_statement_text(raw_text, placeholder)
        except Exception as e:
            logger.error(f"Failed to parse statement {i+1}: {e}", exc_info=True)
            if raise_on_error:
                raise ValueError(f"Failed to parse statement text {i+1}: {str(e)}")
            continue

        if override_month is None:
            for tx in transactions:
                tx.source_statement_month = tx.date.replace(day=1)

        all_transactions.extend(transactions)
        logger.info(f"Parsed {len(transactions)} transactions from statement {i+1}")

    return all_transactions, parser.stats


def _select_parser(raw_texts: List[str]):
    """
    Pick the parser whose layout these statements match.

    Defaults to the K PLUS parser, which is the one that has to work.
    Recognising the columnar layout takes positive evidence -- two rows that
    parse -- so an unfamiliar statement falls back to the original behaviour
    and its original diagnostics rather than being handed to a parser that
    would reject it for a different reason.
    """
    if any(looks_like_columnar(text) for text in raw_texts):
        logger.info("Statement format: columnar (date / description / amount / balance)")
        return ColumnarStatementParser()

    logger.info("Statement format: K PLUS")

    return RecordParser()


def _run_pipeline(
    raw_transactions: List[RawTransaction],
    current_salary: float,
    existing_user_labels: List[dict],
    detection_config: DetectionConfig,
    forecast_config: ForecastConfig,
    parse_stats: Optional[ParseStats] = None,
) -> AnalyzeResponse:
    """
    Shared steps 3-8: normalize -> categorize -> detect -> forecast -> aggregate -> respond.
    """
    start_time = datetime.now()
    total_transactions = len(raw_transactions)
    parse_success_rate = parse_stats.success_rate if parse_stats else 1.0
    logger.info(
        f"Total transactions parsed: {total_transactions} "
        f"(success rate {parse_success_rate:.0%})"
    )

    # STEP 3: Normalization (dummy user_id: stateless)
    logger.info("Step 3: Normalizing transactions")
    normalized_transactions = TransactionNormalizer().normalize_transactions(
        raw_transactions, uuid4()
    )

    # STEP 4: Categorization
    logger.info("Step 4: Categorizing transactions")
    categorized_transactions = CategorizationModule().categorize_transactions(
        normalized_transactions, existing_user_labels
    )

    # STEP 5: Recurring Pattern Detection
    # total_months is the number of distinct calendar months covered by the actual
    # transaction dates. It must never come from the statement count or a placeholder.
    total_months = len({(tx.date.year, tx.date.month) for tx in raw_transactions})
    logger.info(f"Step 5: Detecting recurring patterns over {total_months} month(s) of data")

    detector = RecurringDetectionEngine(detection_config)
    recurring_patterns = detector.detect_recurring_expenses(categorized_transactions, total_months)
    logger.info(f"Detected {len(recurring_patterns)} patterns")

    # STEP 6: Amount Forecasting
    logger.info("Step 6: Forecasting amounts")
    forecaster = AmountForecastModule(forecast_config)
    forecastable = {
        RecurringType.MONTHLY_FIXED,
        RecurringType.MONTHLY_VARIABLE,
        RecurringType.PERIODIC_NON_MONTHLY,
    }
    for pattern in recurring_patterns:
        pattern.forecast_amount = (
            forecaster.forecast_amount(pattern) if pattern.recurring_type in forecastable else 0.0
        )

    # STEP 7: Summary
    logger.info("Step 7: Generating summary")
    summary = AggregationService().generate_summary(recurring_patterns, current_salary, total_months)

    # STEP 7.5: Cash-flow signals
    # Runs here because this is the only point where the raw transactions, the
    # unfiltered patterns and the month count are all still in scope. The
    # summary above keeps what is committed; this keeps what is happening.
    logger.info("Step 7.5: Deriving cashflow signals")
    cashflow = derive_cashflow_signals(
        raw_transactions, categorized_transactions, recurring_patterns, total_months
    )

    # STEP 8: Response (stateless: updated_user_labels always empty; frontend collects labels)
    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info(
        f"Pipeline completed in {elapsed:.2f}s: "
        f"total_recurring={summary.total_recurring:.2f}, "
        f"remaining={summary.remaining_after_reserve:.2f}, "
        f"pending_labels={len(summary.pending_user_labels)}"
    )

    return AnalyzeResponse(
        salary_this_month=summary.salary_this_month,
        recurring_expenses=[asdict(item) for item in summary.recurring_expenses],
        total_recurring=summary.total_recurring,
        remaining_after_reserve=summary.remaining_after_reserve,
        pending_user_labels=[asdict(item) for item in summary.pending_user_labels],
        updated_user_labels=[],
        data_completeness_warning=summary.data_completeness_warning,
        data_months_available=summary.data_months_available,
        parsed_transaction_count=total_transactions,
        parse_success_rate=parse_success_rate,
        closing_balance=cashflow.closing_balance,
        observed_income=cashflow.observed_income,
        income_months=cashflow.income_months,
        payday_day_of_month=cashflow.payday_day_of_month,
        variable_spend_monthly=cashflow.variable_spend_monthly,
        avg_daily_spend=cashflow.avg_daily_spend,
    )


def _empty_response(salary: float, warning: str) -> AnalyzeResponse:
    """Response when no transactions could be parsed"""
    return AnalyzeResponse(
        salary_this_month=salary,
        recurring_expenses=[],
        total_recurring=0.0,
        remaining_after_reserve=salary,
        pending_user_labels=[],
        updated_user_labels=[],
        data_completeness_warning=warning,
        data_months_available=0,
        parsed_transaction_count=0,
        parse_success_rate=0.0,
    )
