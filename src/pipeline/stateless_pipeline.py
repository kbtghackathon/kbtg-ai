"""
Stateless Main Processing Pipeline

This module implements the stateless orchestration function for the recurring expense
detection system for microservice deployment.

All components work with in-memory data only - no database persistence.
"""

import logging
import base64
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import date, datetime
from dataclasses import dataclass, asdict
from io import BytesIO

from ..parser.pdf_extractor import PDFTextExtractor, PDFExtractionError
from ..parser.record_parser import RecordParser, RawTransaction
from ..normalizer.transaction_normalizer import TransactionNormalizer
from ..categorizer.categorization_module import CategorizationModule
from ..detector.recurring_detection_engine import RecurringDetectionEngine, RecurringType
from ..forecaster.amount_forecast_module import AmountForecastModule
from ..aggregator.aggregation_service import AggregationService, RecurringSummary
from ..config.detection_config import DetectionConfig
from ..config.forecast_config import ForecastConfig
from ..config.user_labeling_config import UserLabelingConfig

logger = logging.getLogger(__name__)


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
    
    This is a pure function that takes all inputs as parameters and returns
    results without any side effects or database persistence.
    
    Pipeline:
    1. Extract text from PDFs
    2. Parse transactions from raw text
    3. Normalize transactions
    4. Categorize using merchant dict + existing user labels
    5. Detect recurring patterns
    6. Forecast amounts
    7. Generate pending labels
    8. Aggregate summary
    
    Args:
        pdf_files: List of PDF file contents as bytes (1-6 months of statements)
        current_salary: User's current month salary
        existing_user_labels: List of dicts with keys: recipient_key, category, category_label_th
        statement_months: List of statement months (if None, extracted from PDFs)
        detection_config: Detection thresholds (default if None)
        forecast_config: Forecasting parameters (default if None)
        
    Returns:
        AnalyzeResponse with complete summary and metadata
    """
    start_time = datetime.utcnow()
    
    # Use default configs if not provided
    detection_config = detection_config or DetectionConfig()
    forecast_config = forecast_config or ForecastConfig()
    existing_user_labels = existing_user_labels or []
    
    logger.info(
        f"Starting stateless pipeline: {len(pdf_files)} PDFs, "
        f"salary={current_salary:.2f}, "
        f"existing_labels={len(existing_user_labels)}"
    )
    
    # ============================================================
    # STEP 1: PDF Text Extraction
    # ============================================================
    logger.info(f"Step 1: Extracting text from {len(pdf_files)} PDF files")
    
    extractor = PDFTextExtractor()
    raw_texts: List[str] = []
    
    for i, pdf_bytes in enumerate(pdf_files):
        try:
            # Extract text from bytes
            raw_text = extractor.extract_text_from_pdf_bytes(pdf_bytes)
            raw_texts.append(raw_text)
            logger.info(f"Successfully extracted text from PDF {i+1}")
        except PDFExtractionError as e:
            logger.error(f"Failed to extract text from PDF {i+1}: {str(e)}")
            raise
    
    # ============================================================
    # STEP 2: Transaction Parsing
    # ============================================================
    logger.info("Step 2: Parsing transactions from raw text")
    
    parser = RecordParser()
    all_raw_transactions: List[RawTransaction] = []
    
    # If statement_months not provided, use sequential months
    if statement_months is None:
        base_month = datetime.utcnow().replace(day=1)
        statement_months = [
            date(base_month.year, base_month.month, 1)
            for _ in range(len(raw_texts))
        ]
    
    for raw_text, statement_month in zip(raw_texts, statement_months):
        try:
            transactions = parser.parse_statement_text(raw_text, statement_month)
            all_raw_transactions.extend(transactions)
            logger.info(
                f"Parsed {len(transactions)} transactions from statement {statement_month.isoformat()}"
            )
        except Exception as e:
            logger.error(f"Error parsing statement {statement_month}: {str(e)}")
            # Continue with other statements
    
    if not all_raw_transactions:
        # No transactions parsed - return empty summary
        logger.warning("No transactions successfully parsed from any PDF")
        
        return AnalyzeResponse(
            salary_this_month=current_salary,
            recurring_expenses=[],
            total_recurring=0.0,
            remaining_after_reserve=current_salary,
            pending_user_labels=[],
            updated_user_labels=[],
            data_completeness_warning="ไม่สามารถแยกวิเคราะห์ธุรกรรมจาก PDF ที่ให้มา",
            data_months_available=0,
            parsed_transaction_count=0,
            parse_success_rate=0.0
        )
    
    total_transactions = len(all_raw_transactions)
    parse_success_rate = 1.0  # Simplified - could track failures
    
    logger.info(f"Total transactions parsed: {total_transactions}")
    
    # ============================================================
    # STEP 3: Transaction Normalization
    # ============================================================
    logger.info("Step 3: Normalizing transactions")
    
    normalizer = TransactionNormalizer()
    # Use a dummy user_id since we're stateless
    from uuid import uuid4
    user_id = uuid4()
    normalized_transactions = normalizer.normalize_transactions(
        all_raw_transactions, 
        user_id
    )
    
    logger.info(f"Normalized {len(normalized_transactions)} transactions")
    
    # ============================================================
    # STEP 4: Categorization
    # ============================================================
    logger.info("Step 4: Categorizing transactions")
    
    categorizer = CategorizationModule()
    categorized_transactions = categorizer.categorize_transactions(
        normalized_transactions,
        existing_user_labels
    )
    
    logger.info(f"Categorized {len(categorized_transactions)} transactions")
    
    # ============================================================
    # STEP 5: Recurring Pattern Detection
    # ============================================================
    logger.info("Step 5: Detecting recurring patterns")
    
    detector = RecurringDetectionEngine(detection_config)
    
    # Calculate total months from distinct statement months
    distinct_months = set([tx.source_statement_month for tx in all_raw_transactions])
    total_months = len(distinct_months)
    
    recurring_patterns = detector.detect_recurring_expenses(
        categorized_transactions,
        total_months
    )
    
    logger.info(f"Detected {len(recurring_patterns)} patterns")
    
    # ============================================================
    # STEP 6: Amount Forecasting
    # ============================================================
    logger.info("Step 6: Forecasting amounts")
    
    forecaster = AmountForecastModule(forecast_config)
    
    for pattern in recurring_patterns:
        # Only forecast for actual recurring expenses
        if pattern.recurring_type in [
            RecurringType.MONTHLY_FIXED,
            RecurringType.MONTHLY_VARIABLE,
            RecurringType.PERIODIC_NON_MONTHLY
        ]:
            pattern.forecast_amount = forecaster.forecast_amount(pattern)
        else:
            pattern.forecast_amount = 0.0
    
    logger.info("Completed amount forecasting")
    
    # ============================================================
    # STEP 7: Generate Summary
    # ============================================================
    logger.info("Step 7: Generating summary")
    
    aggregator = AggregationService()
    summary = aggregator.generate_summary(
        recurring_patterns,
        current_salary,
        total_months
    )
    
    # ============================================================
    # STEP 8: Extract updated user labels
    # ============================================================
    # For patterns that need labeling but weren't previously labeled,
    # return them as part of pending labels
    # User can label them and pass back in next request
    
    updated_labels = []
    # In stateless mode, we don't update labels - just return pending ones
    # Frontend will handle collecting labels and passing them back
    
    # Calculate execution time
    end_time = datetime.utcnow()
    execution_time = (end_time - start_time).total_seconds()
    
    logger.info(
        f"Pipeline completed successfully in {execution_time:.2f}s: "
        f"total_recurring={summary.total_recurring:.2f}, "
        f"remaining={summary.remaining_after_reserve:.2f}, "
        f"pending_labels={len(summary.pending_user_labels)}"
    )
    
    # Convert summary to response format
    return AnalyzeResponse(
        salary_this_month=summary.salary_this_month,
        recurring_expenses=[
            {
                "category": exp.category,
                "category_label_th": exp.category_label_th,
                "amount": exp.amount,
                "confidence": exp.confidence,
                "recipient_key": exp.recipient_key
            }
            for exp in summary.recurring_expenses
        ],
        total_recurring=summary.total_recurring,
        remaining_after_reserve=summary.remaining_after_reserve,
        pending_user_labels=[
            {
                "recipient_key": label.recipient_key,
                "detected_amount": label.detected_amount,
                "n_months_detected": label.n_months_detected,
                "category_suggestions": label.category_suggestions,
                "sample_transactions": label.sample_transactions
            }
            for label in summary.pending_user_labels
        ],
        updated_user_labels=updated_labels,
        data_completeness_warning=summary.data_completeness_warning,
        data_months_available=summary.data_months_available,
        parsed_transaction_count=total_transactions,
        parse_success_rate=parse_success_rate
    )


def analyze_from_base64(
    statements_pdf_base64: List[str],
    current_salary: float,
    existing_user_labels: Optional[List[dict]] = None
) -> Dict[str, Any]:
    """
    Convenience function that accepts base64-encoded PDFs.
    
    Args:
        statements_pdf_base64: List of base64-encoded PDF strings
        current_salary: User's current month salary
        existing_user_labels: Existing user category labels
        
    Returns:
        Dict representation of AnalyzeResponse
    """
    # Decode base64 PDFs to bytes
    pdf_files = []
    for i, pdf_base64 in enumerate(statements_pdf_base64):
        try:
            pdf_bytes = base64.b64decode(pdf_base64)
            pdf_files.append(pdf_bytes)
        except Exception as e:
            logger.error(f"Failed to decode base64 PDF {i+1}: {str(e)}")
            raise ValueError(f"Invalid base64 encoding for PDF {i+1}")
    
    # Call main analyze function
    response = analyze(
        pdf_files=pdf_files,
        current_salary=current_salary,
        existing_user_labels=existing_user_labels
    )
    
    # Convert to dict
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
        statement_months: List of statement months (if None, uses current month for all)
        
    Returns:
        Dict representation of AnalyzeResponse
    """
    from datetime import date
    
    start_time = datetime.utcnow()
    
    # Use default configs
    detection_config = DetectionConfig()
    forecast_config = ForecastConfig()
    existing_user_labels = existing_user_labels or []
    
    logger.info(
        f"Starting text-based pipeline: {len(statement_texts)} texts, "
        f"salary={current_salary:.2f}, "
        f"existing_labels={len(existing_user_labels)}"
    )
    
    # Generate statement months if not provided
    if statement_months is None:
        current_month = date.today().replace(day=1)
        statement_months = [current_month] * len(statement_texts)
    
    # ============================================================
    # STEP 2: Parse transactions from text (skip PDF extraction)
    # ============================================================
    logger.info(f"Step 2: Parsing transactions from {len(statement_texts)} texts")
    
    parser = RecordParser()
    all_transactions = []
    
    for i, (text, statement_month) in enumerate(zip(statement_texts, statement_months)):
        try:
            transactions = parser.parse_statement_text(text, statement_month)
            all_transactions.extend(transactions)
            logger.info(f"Parsed {len(transactions)} transactions from text {i+1}")
        except Exception as e:
            logger.error(f"Failed to parse text {i+1}: {e}", exc_info=True)
            raise ValueError(f"Failed to parse statement text {i+1}: {str(e)}")
    
    total_parsed = len(all_transactions)
    logger.info(f"Parsed total {total_parsed} transactions from {len(statement_texts)} texts")
    
    if total_parsed == 0:
        logger.warning("No transactions parsed from statement texts")
        return _empty_response(current_salary, len(statement_texts), "ไม่สามารถแยกวิเคราะห์ธุรกรรมจากข้อความที่ให้มา")
    
    # ============================================================
    # STEP 3: Normalize transactions
    # ============================================================
    logger.info("Step 3: Normalizing transactions")
    
    normalizer = TransactionNormalizer()
    from uuid import uuid4
    user_id = uuid4()
    normalized_transactions = normalizer.normalize_transactions(
        all_transactions,
        user_id
    )
    
    logger.info(f"Normalized {len(normalized_transactions)} transactions")
    
    # ============================================================
    # STEP 4: Categorization
    # ============================================================
    logger.info("Step 4: Categorizing transactions")
    
    categorizer = CategorizationModule()
    categorized_transactions = categorizer.categorize_transactions(
        normalized_transactions,
        existing_user_labels
    )
    
    logger.info(f"Categorized {len(categorized_transactions)} transactions")
    
    # ============================================================
    # STEP 5: Recurring Detection
    # ============================================================
    logger.info("Step 5: Detecting recurring patterns")
    
    total_months = len(statement_texts)
    detector = RecurringDetectionEngine(detection_config)
    
    recurring_patterns = detector.detect_recurring_expenses(
        categorized_transactions,
        total_months
    )
    
    logger.info(f"Detected {len(recurring_patterns)} patterns")
    
    # ============================================================
    # STEP 6: Amount Forecasting
    # ============================================================
    logger.info("Step 6: Forecasting amounts")
    
    forecaster = AmountForecastModule(forecast_config)
    
    for pattern in recurring_patterns:
        if pattern.recurring_type in [
            RecurringType.MONTHLY_FIXED,
            RecurringType.MONTHLY_VARIABLE,
            RecurringType.PERIODIC_NON_MONTHLY
        ]:
            pattern.forecast_amount = forecaster.forecast_amount(pattern)
        else:
            pattern.forecast_amount = 0.0
    
    logger.info("Completed amount forecasting")
    
    # ============================================================
    # STEP 7: Generate Summary
    # ============================================================
    logger.info("Step 7: Generating summary")
    
    aggregator = AggregationService()
    summary = aggregator.generate_summary(
        recurring_patterns,
        current_salary,
        total_months
    )
    
    # ============================================================
    # STEP 8: Build response
    # ============================================================
    updated_labels = []  # Stateless mode
    
    # Data completeness warning
    data_warning = None
    if total_months < 6:
        data_warning = f"มีข้อมูลเพียง {total_months} เดือน แนะนำให้ใช้ข้อมูล 6 เดือนเพื่อความแม่นยำสูงสุด"
    
    parse_success_rate = 1.0 if total_parsed > 0 else 0.0
    
    response = AnalyzeResponse(
        salary_this_month=current_salary,
        recurring_expenses=[asdict(item) for item in summary.recurring_expenses],
        total_recurring=summary.total_recurring,
        remaining_after_reserve=summary.remaining_after_reserve,
        pending_user_labels=[asdict(item) for item in summary.pending_user_labels],
        updated_user_labels=updated_labels,
        data_completeness_warning=data_warning,
        data_months_available=total_months,
        parsed_transaction_count=total_parsed,
        parse_success_rate=parse_success_rate
    )
    
    elapsed = (datetime.utcnow() - start_time).total_seconds()
    logger.info(f"Text-based pipeline completed in {elapsed:.2f}s")
    
    return asdict(response)


def _empty_response(salary: float, months: int, warning: str) -> Dict[str, Any]:
    """Generate empty response when no data parsed"""
    return {
        "salary_this_month": salary,
        "recurring_expenses": [],
        "total_recurring": 0.0,
        "remaining_after_reserve": salary,
        "pending_user_labels": [],
        "updated_user_labels": [],
        "data_completeness_warning": warning,
        "data_months_available": months,
        "parsed_transaction_count": 0,
        "parse_success_rate": 0.0
    }

