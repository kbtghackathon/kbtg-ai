"""
Main Processing Pipeline Module

This module orchestrates the end-to-end recurring expense detection pipeline.
"""

from .main_pipeline import (
    process_recurring_expense_detection,
    configure_structured_logging,
    PipelineError,
    PipelineResult
)

__all__ = [
    'process_recurring_expense_detection',
    'configure_structured_logging',
    'PipelineError',
    'PipelineResult'
]
