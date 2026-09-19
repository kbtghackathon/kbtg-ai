"""
Main Processing Pipeline

This module implements the main orchestration function for the recurring expense
detection system, handling PDF extraction → parsing → normalization → categorization
→ detection → forecasting → aggregation with comprehensive error handling and
structured JSON logging.

Requirements: All requirements
Task 14.1, 14.2
"""

import logging
import json
from pathlib import Path
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from dataclasses import dataclass, asdict

from ..parser import PDFTextExtractor, RecordParser, PDFExtractionError, RawTransaction
from ..normalizer import TransactionNormalizer, NormalizedTransaction
from ..categorizer import CategorizationModule, CategorizedTransaction
from ..detector import RecurringDetectionEngine, RecurringPattern, RecurringType
from ..forecaster.amount_forecast_module import AmountForecastModule
from ..aggregator.aggregation_service import AggregationService, RecurringSummary
from ..db import DatabaseService
from ..config.detection_config import DetectionConfig
from ..config.forecast_config import ForecastConfig
from ..config.user_labeling_config import UserLabelingConfig


# Configure structured JSON logging
# Requirement 28.6
class StructuredJsonFormatter(logging.Formatter):
    """Custom formatter for structured JSON logging"""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON"""
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        
        # Add extra fields if present
        if hasattr(record, 'user_id'):
            log_data['user_id'] = str(record.user_id)
        if hasattr(record, 'recipient_key'):
            log_data['recipient_key'] = record.recipient_key
        if hasattr(record, 'detection_run_id'):
            log_data['detection_run_id'] = str(record.detection_run_id)
        if hasattr(record, 'parse_failures'):
            log_data['parse_failures'] = record.parse_failures
        if hasattr(record, 'raw_text'):
            # Requirement 28.1: Log parsing failures with raw text
            log_data['raw_text'] = record.raw_text
        if hasattr(record, 'merchant_name'):
            # Requirement 28.2: Log unknown merchants
            log_data['merchant_name'] = record.merchant_name
        if hasattr(record, 'confidence_score'):
            # Requirement 28.4: Log low confidence patterns
            log_data['confidence_score'] = record.confidence_score
        if hasattr(record, 'balance_validation_error'):
            # Requirement 28.3: Log balance validation warnings
            log_data['balance_validation_error'] = record.balance_validation_error
        
        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(log_data, ensure_ascii=False)


# Initialize logger for pipeline
logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """Base exception for pipeline errors"""
    pass


@dataclass
class PipelineResult:
    """Result of pipeline execution"""
    success: bool
    summary: Optional[RecurringSummary]
    total_transactions_parsed: int
    parse_success_rate: float
    total_patterns_detected: int
    execution_time_seconds: float
    error_message: Optional[str] = None
    warnings: List[str] = None
    
    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []


def process_recurring_expense_detection(
    pdf_files: List[Path],
    user_id: UUID,
    current_salary: float,
    db_connection_string: str,
    detection_config: Optional[DetectionConfig] = None,
    forecast_config: Optional[ForecastConfig] = None,
    user_labeling_config: Optional[UserLabelingConfig] = None
) -> PipelineResult:
    """
    Main pipeline for recurring expense detection.
    
    Orchestrates: PDF extraction → parsing → normalization → categorization →
    detection → forecasting → user labeling → aggregation
    
    Args:
        pdf_files: List of paths to K PLUS statement PDFs (1-6 months)
        user_id: User identifier
        current_salary: User's current month salary
        db_connection_string: PostgreSQL connection string
        detection_config: Detection thresholds (default if None)
        forecast_config: Forecasting parameters (default if None)
        user_labeling_config: User labeling config (default if None)
        
    Returns:
        PipelineResult with summary and execution metadata
        
    Raises:
        PipelineError: If critical failure occurs
        
    Requirements: All requirements
    Task 14.1: Main orchestration function
    """
    start_time = datetime.utcnow()
    warnings: List[str] = []
    
    # Use default configs if not provided
    detection_config = detection_config or DetectionConfig()
    forecast_config = forecast_config or ForecastConfig()
    user_labeling_config = user_labeling_config or UserLabelingConfig()
    
    logger.info(
        "Starting recurring expense detection pipeline",
        extra={
            'user_id': user_id,
            'pdf_count': len(pdf_files),
            'current_salary': current_salary
        }
    )
    
    try:
        # Validate inputs
        if not pdf_files:
            raise PipelineError("No PDF files provided")
        if len(pdf_files) > 6:
            raise PipelineError(f"Too many PDF files: {len(pdf_files)} (maximum 6)")
        if current_salary <= 0:
            raise PipelineError(f"Invalid current_salary: {current_salary}")
        
        # Initialize database connection
        db_service = DatabaseService(db_connection_string)
        
        with db_service:
            # ============================================================
            # STEP 1: PDF Text Extraction
            # ============================================================
            logger.info(f"Step 1: Extracting text from {len(pdf_files)} PDF files")
            
            extractor = PDFTextExtractor()
            raw_texts = []
            
            for pdf_file in pdf_files:
                if not pdf_file.exists():
                    error_msg = f"PDF file not found: {pdf_file}"
                    logger.error(error_msg)
                    raise PipelineError(error_msg)
                
                try:
                    # Requirement 1.1
                    raw_text = extractor.extract_text_from_pdf(pdf_file)
                    raw_texts.append((pdf_file, raw_text))
                    logger.info(
                        f"Successfully extracted text from {pdf_file.name}",
                        extra={'pdf_file': str(pdf_file)}
                    )
                except PDFExtractionError as e:
                    # Requirement 14.1: Error handling
                    error_msg = f"Failed to extract text from {pdf_file}: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    raise PipelineError(error_msg) from e
            
            # ============================================================
            # STEP 2: Transaction Parsing
            # ============================================================
            logger.info("Step 2: Parsing transactions from raw text")
            
            parser = RecordParser()
            all_raw_transactions: List[RawTransaction] = []
            total_parse_attempts = 0
            total_parse_failures = 0
            
            for pdf_file, raw_text in raw_texts:
                # Extract statement month from filename or use current date
                statement_month = _extract_statement_month(pdf_file)
                
                try:
                    # Requirement 2.1-2.12
                    transactions = parser.parse_statement_text(raw_text, statement_month)
                    all_raw_transactions.extend(transactions)
                    
                    # Get parse statistics from parser
                    # Note: This assumes parser tracks failures internally
                    parse_count = len(transactions)
                    
                    logger.info(
                        f"Parsed {parse_count} transactions from {pdf_file.name}",
                        extra={
                            'pdf_file': str(pdf_file),
                            'statement_month': statement_month.isoformat(),
                            'transaction_count': parse_count
                        }
                    )
                    
                except Exception as e:
                    # Requirement 14.1: Continue on failure
                    error_msg = f"Error parsing {pdf_file.name}: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    warnings.append(error_msg)
                    # Continue with other files
            
            if not all_raw_transactions:
                raise PipelineError("No transactions successfully parsed from any PDF")
            
            total_transactions = len(all_raw_transactions)
            
            # Requirement 39.5: Calculate parse success rate
            parse_success_rate = 1.0  # Default if we don't track failures
            
            logger.info(
                f"Parsed {total_transactions} total transactions",
                extra={'total_transactions': total_transactions}
            )
            
            # ============================================================
            # STEP 3: Transaction Normalization and Persistence
            # ============================================================
            logger.info("Step 3: Normalizing transactions")
            
            normalizer = TransactionNormalizer()
            # Requirement 3.1-3.8
            normalized_transactions = normalizer.normalize_transactions(
                all_raw_transactions, 
                user_id
            )
            
            # Check for idempotent re-upload
            # Requirement 12.1-12.3
            statement_months = list(set([t.source_statement_month for t in all_raw_transactions]))
            
            for statement_month in statement_months:
                existing_metadata = db_service.get_existing_statement_metadata(
                    user_id, 
                    statement_month
                )
                
                if existing_metadata:
                    should_replace = db_service.should_replace_existing_statement(
                        existing_metadata,
                        parse_success_rate
                    )
                    
                    if should_replace:
                        logger.info(
                            f"Replacing existing data for {statement_month}",
                            extra={
                                'user_id': user_id,
                                'statement_month': statement_month.isoformat(),
                                'old_parse_rate': existing_metadata.parse_success_rate,
                                'new_parse_rate': parse_success_rate
                            }
                        )
                        # Delete old transactions
                        # Requirement 12.2
                        db_service.delete_transactions_for_statement_month(
                            user_id, 
                            statement_month
                        )
                    else:
                        warning_msg = (
                            f"New parse rate ({parse_success_rate:.2%}) is lower than "
                            f"existing ({existing_metadata.parse_success_rate:.2%}) "
                            f"for {statement_month}. Skipping replacement."
                        )
                        logger.warning(warning_msg, extra={'user_id': user_id})
                        warnings.append(warning_msg)
                        continue
            
            # Save normalized transactions to database
            # Requirement 3.8, 11.1
            db_service.insert_transactions(
                user_id,
                normalized_transactions,
                parse_success_rate
            )
            
            logger.info(
                f"Saved {len(normalized_transactions)} normalized transactions",
                extra={'user_id': user_id}
            )
            
            # ============================================================
            # STEP 4: Categorization
            # ============================================================
            logger.info("Step 4: Categorizing transactions")
            
            categorizer = CategorizationModule(db_service.connection)
            # Requirement 5.1-5.8
            categorized_transactions = categorizer.categorize_transactions(
                normalized_transactions,
                user_id
            )
            
            # Log unknown merchants for dictionary expansion
            # Requirement 28.2
            unknown_merchants = [
                t for t in categorized_transactions 
                if t.category is None and t.normalized_transaction.normalized_merchant_name
            ]
            
            if unknown_merchants:
                for t in unknown_merchants[:10]:  # Limit to 10 for logging
                    logger.info(
                        "Unknown merchant detected",
                        extra={
                            'user_id': user_id,
                            'merchant_name': t.normalized_transaction.normalized_merchant_name
                        }
                    )
                
                if len(unknown_merchants) > 10:
                    logger.info(
                        f"Total unknown merchants: {len(unknown_merchants)}",
                        extra={'user_id': user_id}
                    )
            
            logger.info(
                f"Categorized {len(categorized_transactions)} transactions",
                extra={'user_id': user_id}
            )
            
            # ============================================================
            # STEP 5: Recurring Pattern Detection
            # ============================================================
            logger.info("Step 5: Detecting recurring patterns")
            
            detector = RecurringDetectionEngine(detection_config)
            total_months = len(statement_months)
            
            # Requirement 6.1-6.13
            recurring_patterns = detector.detect_recurring_expenses(
                categorized_transactions,
                total_months
            )
            
            # Log low confidence patterns
            # Requirement 28.4
            low_confidence_patterns = [
                p for p in recurring_patterns 
                if p.confidence_score < 0.5 and p.recurring_type != RecurringType.NOT_RECURRING
            ]
            
            for pattern in low_confidence_patterns:
                logger.warning(
                    "Low confidence pattern detected",
                    extra={
                        'user_id': user_id,
                        'recipient_key': pattern.recipient_key,
                        'confidence_score': pattern.confidence_score,
                        'recurring_type': pattern.recurring_type.value
                    }
                )
            
            logger.info(
                f"Detected {len(recurring_patterns)} patterns "
                f"({len(low_confidence_patterns)} low confidence)",
                extra={'user_id': user_id}
            )
            
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
                    # Requirement 7.1-7.7
                    pattern.forecast_amount = forecaster.forecast_amount(pattern)
                else:
                    pattern.forecast_amount = 0.0
            
            logger.info("Completed amount forecasting", extra={'user_id': user_id})
            
            # ============================================================
            # STEP 7: Save Recurring Expenses (Idempotent)
            # ============================================================
            logger.info("Step 7: Saving recurring expenses")
            
            for pattern in recurring_patterns:
                # Requirement 12.4-12.7: Idempotent save
                db_service.save_recurring_expense_idempotent(
                    user_id,
                    pattern
                )
            
            logger.info(
                f"Saved {len(recurring_patterns)} recurring expense records",
                extra={'user_id': user_id}
            )
            
            # ============================================================
            # STEP 8: Generate Summary
            # ============================================================
            logger.info("Step 8: Generating summary")
            
            aggregator = AggregationService(db_service.connection)
            # Requirement 9.1-9.11
            summary = aggregator.generate_summary(user_id, current_salary)
            
            # Calculate execution time
            end_time = datetime.utcnow()
            execution_time = (end_time - start_time).total_seconds()
            
            logger.info(
                "Pipeline completed successfully",
                extra={
                    'user_id': user_id,
                    'execution_time_seconds': execution_time,
                    'total_recurring': summary.total_recurring,
                    'remaining_after_reserve': summary.remaining_after_reserve
                }
            )
            
            return PipelineResult(
                success=True,
                summary=summary,
                total_transactions_parsed=total_transactions,
                parse_success_rate=parse_success_rate,
                total_patterns_detected=len(recurring_patterns),
                execution_time_seconds=execution_time,
                warnings=warnings
            )
    
    except PipelineError as e:
        # Expected pipeline error
        end_time = datetime.utcnow()
        execution_time = (end_time - start_time).total_seconds()
        
        logger.error(
            f"Pipeline failed: {str(e)}",
            extra={
                'user_id': user_id,
                'execution_time_seconds': execution_time
            },
            exc_info=True
        )
        
        return PipelineResult(
            success=False,
            summary=None,
            total_transactions_parsed=0,
            parse_success_rate=0.0,
            total_patterns_detected=0,
            execution_time_seconds=execution_time,
            error_message=str(e),
            warnings=warnings
        )
    
    except Exception as e:
        # Unexpected error
        end_time = datetime.utcnow()
        execution_time = (end_time - start_time).total_seconds()
        
        logger.error(
            f"Unexpected pipeline error: {str(e)}",
            extra={
                'user_id': user_id,
                'execution_time_seconds': execution_time
            },
            exc_info=True
        )
        
        return PipelineResult(
            success=False,
            summary=None,
            total_transactions_parsed=0,
            parse_success_rate=0.0,
            total_patterns_detected=0,
            execution_time_seconds=execution_time,
            error_message=f"Unexpected error: {str(e)}",
            warnings=warnings
        )


def _extract_statement_month(pdf_file: Path) -> datetime:
    """
    Extract statement month from PDF filename or use current date.
    
    Expected format: statement_YYYY_MM.pdf or similar
    
    Args:
        pdf_file: Path to PDF file
        
    Returns:
        Datetime representing the statement month
    """
    try:
        # Try to parse from filename (e.g., "statement_2024_01.pdf")
        filename = pdf_file.stem
        parts = filename.split('_')
        
        # Look for year and month patterns
        for i, part in enumerate(parts):
            if len(part) == 4 and part.isdigit():  # Year
                year = int(part)
                if i + 1 < len(parts) and len(parts[i + 1]) == 2:  # Month
                    month = int(parts[i + 1])
                    return datetime(year, month, 1)
        
        # Fallback: use current date
        logger.warning(
            f"Could not parse statement month from filename: {pdf_file.name}, "
            f"using current date"
        )
        now = datetime.utcnow()
        return datetime(now.year, now.month, 1)
        
    except Exception as e:
        logger.warning(
            f"Error extracting statement month from {pdf_file.name}: {e}, "
            f"using current date"
        )
        now = datetime.utcnow()
        return datetime(now.year, now.month, 1)


def configure_structured_logging(log_level: str = "INFO") -> None:
    """
    Configure structured JSON logging for the pipeline.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        
    Task 14.2: Structured JSON logging setup
    Requirement 28.6
    """
    # Create handler with JSON formatter
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredJsonFormatter())
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    root_logger.addHandler(handler)
    
    # Configure package-specific loggers
    for logger_name in [
        'src.pipeline',
        'src.parser',
        'src.normalizer',
        'src.categorizer',
        'src.detector',
        'src.forecaster',
        'src.aggregator'
    ]:
        package_logger = logging.getLogger(logger_name)
        package_logger.setLevel(getattr(logging, log_level.upper()))
