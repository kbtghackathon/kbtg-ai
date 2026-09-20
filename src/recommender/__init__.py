"""Savings recommendation: how much of this month's income can be put away."""

from src.recommender.savings_recommendation_module import (
    CashflowSignals,
    ExpenseSignal,
    SavingsReason,
    SavingsRecommendation,
    SavingsRecommendationModule,
    SavingsSignals,
)

__all__ = [
    "CashflowSignals",
    "ExpenseSignal",
    "SavingsReason",
    "SavingsRecommendation",
    "SavingsRecommendationModule",
    "SavingsSignals",
]
