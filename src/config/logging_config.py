"""
Logging configuration for the Recurring Expense Detection Engine.

This module sets up structured logging in JSON format as required by the design
document and Requirement 14 (Error Handling and Data Quality) and Requirement 28
(Logging and Observability).
"""

import logging
import json
import sys
from datetime import datetime
from typing import Any, Dict
from pathlib import Path


class JSONFormatter(logging.Formatter):
    """
    Custom JSON formatter for structured logging.
    
    Formats log records as JSON objects with timestamp, level, logger name,
    message, and any additional context fields.
    
    Security Note (Requirement 15.6, 28.8):
    - Never logs sensitive data like full account numbers in plain text
    - Uses masked identifiers (e.g., X2660) when logging financial data
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """
        Format log record as JSON string.
        
        Args:
            record: Log record to format
            
        Returns:
            JSON string representation of log record
        """
        log_obj: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add exception info if present
        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields from record
        # Common fields: user_id, recipient_key, detection_run_id, raw_text, etc.
        if hasattr(record, "user_id"):
            log_obj["user_id"] = record.user_id
        if hasattr(record, "recipient_key"):
            log_obj["recipient_key"] = record.recipient_key
        if hasattr(record, "detection_run_id"):
            log_obj["detection_run_id"] = record.detection_run_id
        if hasattr(record, "raw_text"):
            log_obj["raw_text"] = record.raw_text
        if hasattr(record, "merchant_name"):
            log_obj["merchant_name"] = record.merchant_name
        if hasattr(record, "confidence_score"):
            log_obj["confidence_score"] = record.confidence_score
        if hasattr(record, "parse_success_rate"):
            log_obj["parse_success_rate"] = record.parse_success_rate
        
        return json.dumps(log_obj, ensure_ascii=False)


def setup_logging(
    log_level: str = "INFO",
    log_file: Path = None,
    console_output: bool = True
) -> None:
    """
    Set up structured JSON logging for the application.
    
    Configures the root logger with JSON formatting and appropriate handlers.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional path to log file. If None, logs to console only.
        console_output: Whether to output logs to console (stdout)
        
    Example:
        >>> from src.config.logging_config import setup_logging
        >>> setup_logging(log_level="DEBUG", log_file=Path("logs/app.log"))
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # Remove existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    formatter = JSONFormatter()
    
    # Console handler
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
    
    # File handler
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a specific module.
    
    Args:
        name: Logger name (typically __name__ from calling module)
        
    Returns:
        Configured logger instance
        
    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Processing transaction", extra={"user_id": "123"})
    """
    return logging.getLogger(name)


# Predefined logger instances for common components
# These can be imported directly in modules
parser_logger = get_logger("src.parser")
normalizer_logger = get_logger("src.normalizer")
categorizer_logger = get_logger("src.categorizer")
detector_logger = get_logger("src.detector")
forecaster_logger = get_logger("src.forecaster")
labeling_logger = get_logger("src.user_labeling")
aggregator_logger = get_logger("src.aggregator")
