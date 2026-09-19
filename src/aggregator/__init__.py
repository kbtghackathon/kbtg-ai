"""
Aggregation Service Module

This module aggregates recurring expenses into summary format for API consumption.
"""

from .aggregation_service import (
    AggregationService,
    RecurringSummary,
    RecurringExpenseSummaryItem,
    PendingLabel
)

__all__ = [
    'AggregationService',
    'RecurringSummary',
    'RecurringExpenseSummaryItem',
    'PendingLabel'
]
