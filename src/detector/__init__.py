"""
Recurring Detection Engine Module

This module contains the core algorithm for detecting recurring expense patterns
using rules-based analysis.
"""

from .recurring_detection_engine import (
    RecurringType,
    RecurringPattern,
    RecurringDetectionEngine,
)

__all__ = [
    "RecurringType",
    "RecurringPattern",
    "RecurringDetectionEngine",
]
