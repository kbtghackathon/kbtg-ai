"""
Amount Forecast Module

This module forecasts recurring expense amounts for the next month using
various strategies based on the recurring pattern type.

Requirements: 7.1-7.7, 30.1-30.6, 31.1-31.5
"""

import logging
import math
from typing import List

from ..categorizer.categorization_module import CategorizedTransaction
from ..config.forecast_config import ForecastConfig
from ..detector.recurring_detection_engine import RecurringPattern, RecurringType

logger = logging.getLogger(__name__)


class AmountForecastModule:
    """Forecast recurring expense amounts for next month"""
    
    def __init__(self, config: ForecastConfig):
        """
        Initialize forecast module with configuration
        
        Args:
            config: Forecast configuration with parameters
            
        Requirements: 13.14
        """
        self.config = config
    
    def forecast_amount(self, pattern: RecurringPattern) -> float:
        """
        Forecast next month's expense amount based on recurring type
        
        Args:
            pattern: Detected recurring pattern
            
        Returns:
            Forecasted amount for next month (non-negative)
            
        Requirements: 7.1-7.7
        """
        # Handle edge cases with insufficient data
        # Requirement 7.6
        if not pattern.transactions:
            logger.warning(f"No transactions for {pattern.recipient_key}, returning 0.0")
            return 0.0
        
        if len(pattern.transactions) < 2:
            # Use single available amount
            amount = pattern.transactions[0].normalized_transaction.raw_transaction.amount
            logger.info(
                f"Insufficient data for {pattern.recipient_key} "
                f"(only {len(pattern.transactions)} transaction), using single amount: {amount:.2f}"
            )
            return max(0.0, amount)
        
        # Route to appropriate forecast method based on recurring_type
        # Requirement 7.1-7.5
        if pattern.recurring_type == RecurringType.MONTHLY_FIXED:
            forecast = self._forecast_monthly_fixed(pattern.transactions)
        elif pattern.recurring_type == RecurringType.MONTHLY_VARIABLE:
            forecast = self._forecast_monthly_variable(pattern.transactions)
        elif pattern.recurring_type == RecurringType.PERIODIC_NON_MONTHLY:
            forecast = self._forecast_periodic_non_monthly(pattern)
        else:
            # FREQUENT_SMALL_SPEND and NOT_RECURRING should not be forecasted
            logger.debug(
                f"Pattern type {pattern.recurring_type.value} not forecasted, returning 0.0"
            )
            return 0.0
        
        # Ensure non-negative forecast amounts
        # Requirement 7.7
        forecast = max(0.0, forecast)
        
        logger.info(
            f"Forecast for {pattern.recipient_key} ({pattern.recurring_type.value}): {forecast:.2f}"
        )
        
        return forecast
    
    def _forecast_monthly_fixed(self, transactions: List[CategorizedTransaction]) -> float:
        """
        Forecast for monthly fixed expenses
        Strategy: Use most recent amount (last transaction)
        
        Args:
            transactions: List of transactions (unsorted)
            
        Returns:
            Last transaction amount
            
        Requirements: 7.1
        """
        # Sort by date to get most recent
        sorted_transactions = sorted(
            transactions,
            key=lambda t: t.normalized_transaction.raw_transaction.date
        )
        
        most_recent = sorted_transactions[-1]
        amount = most_recent.normalized_transaction.raw_transaction.amount
        
        logger.debug(
            f"Monthly fixed forecast: using most recent amount {amount:.2f} "
            f"from {most_recent.normalized_transaction.raw_transaction.date}"
        )
        
        return amount
    
    def _forecast_monthly_variable(self, transactions: List[CategorizedTransaction]) -> float:
        """
        Forecast for monthly variable expenses
        Strategy: Weighted moving average with recency bias
        
        Args:
            transactions: List of transactions
            
        Returns:
            Weighted average amount
            
        Requirements: 7.2
        """
        forecast = self._weighted_moving_average(transactions, recency_weight=True)
        
        logger.debug(f"Monthly variable forecast: weighted average {forecast:.2f}")
        
        return forecast
    
    def _forecast_periodic_non_monthly(self, pattern: RecurringPattern) -> float:
        """
        Forecast for periodic non-monthly expenses
        Strategy: Pro-rate average amount to monthly equivalent
        
        Formula: mean_amount / (cycle_days / days_per_month)
        
        Args:
            pattern: Recurring pattern with cycle_days
            
        Returns:
            Pro-rated monthly amount
            
        Requirements: 7.4, 7.5, 31.1-31.5
        """
        mean_amount = pattern.mean_amount
        cycle_days = pattern.cycle_days
        
        if cycle_days is None or cycle_days <= 0:
            logger.warning(
                f"Invalid cycle_days ({cycle_days}) for periodic pattern, "
                f"using mean_amount directly: {mean_amount:.2f}"
            )
            return mean_amount
        
        # Pro-rate to monthly equivalent
        # Requirement 31.1, 31.2, 31.3
        monthly_amount = mean_amount / (cycle_days / self.config.days_per_month)
        
        logger.debug(
            f"Periodic non-monthly forecast: mean_amount={mean_amount:.2f}, "
            f"cycle_days={cycle_days:.1f}, monthly_equivalent={monthly_amount:.2f}"
        )
        
        # Ensure non-negative result
        # Requirement 31.5
        return max(0.0, monthly_amount)
    
    def _weighted_moving_average(
        self, 
        transactions: List[CategorizedTransaction], 
        recency_weight: bool = True
    ) -> float:
        """
        Calculate weighted moving average of transaction amounts
        
        Args:
            transactions: List of transactions (will be sorted by date)
            recency_weight: If True, recent transactions have higher weight
            
        Returns:
            Weighted average amount
            
        Requirements: 7.2, 7.3, 30.1-30.6
        """
        if not transactions:
            return 0.0
        
        # Sort transactions by date (oldest to newest)
        sorted_transactions = sorted(
            transactions,
            key=lambda t: t.normalized_transaction.raw_transaction.date
        )
        
        amounts = [t.normalized_transaction.raw_transaction.amount for t in sorted_transactions]
        
        # Fallback to simple average for < 3 transactions
        # Requirement 30.1
        if len(amounts) < 3:
            simple_avg = sum(amounts) / len(amounts)
            logger.debug(
                f"Using simple average for {len(amounts)} transactions: {simple_avg:.2f}"
            )
            return simple_avg
        
        # Use exponential weighting for >= 3 transactions
        # Requirement 30.2, 30.3, 30.4
        if recency_weight:
            weights = self._calculate_recency_weights(len(amounts))
        else:
            # Equal weights (simple average)
            weights = [1.0 / len(amounts)] * len(amounts)
        
        # Calculate weighted average
        # Requirement 30.5
        weighted_sum = sum(amount * weight for amount, weight in zip(amounts, weights))
        
        logger.debug(
            f"Weighted moving average: {len(amounts)} transactions, "
            f"result={weighted_sum:.2f}"
        )
        
        # Requirement 30.6: weights sum to 1.0, so weighted_sum is the average
        return weighted_sum
    
    def _calculate_recency_weights(self, n_transactions: int) -> List[float]:
        """
        Calculate exponential recency weights
        More recent transactions get higher weights
        
        Args:
            n_transactions: Number of transactions
            
        Returns:
            List of weights summing to 1.0
            
        Requirements: 7.3, 30.2
        """
        if n_transactions <= 0:
            return []
        
        if n_transactions == 1:
            return [1.0]
        
        # Calculate exponential decay weights
        # Most recent (index n-1) gets highest weight
        # Oldest (index 0) gets lowest weight
        # Requirement 30.2, 30.3, 30.4
        decay_factor = self.config.recency_decay_factor
        
        # Generate weights: w[i] = decay_factor^(n-1-i)
        # This gives higher weight to more recent transactions
        raw_weights = [
            math.pow(decay_factor, n_transactions - 1 - i) 
            for i in range(n_transactions)
        ]
        
        # Normalize so weights sum to 1.0
        total_weight = sum(raw_weights)
        normalized_weights = [w / total_weight for w in raw_weights]
        
        logger.debug(
            f"Recency weights for {n_transactions} transactions: "
            f"oldest={normalized_weights[0]:.4f}, newest={normalized_weights[-1]:.4f}"
        )
        
        return normalized_weights

