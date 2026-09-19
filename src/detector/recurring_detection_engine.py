"""
Recurring Detection Engine

This module implements the core algorithm for detecting recurring expense patterns
using rules-based analysis with configurable thresholds.

Requirements: 6.1-6.13, 13.1-13.14, 17.3, 23.1-23.8, 24.1-24.8, 25.1-25.7, 26.1-26.5
"""

import logging
import math
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Dict, List, Optional

from ..categorizer.categorization_module import CategorizedTransaction, CategoryGroup
from ..config.detection_config import DetectionConfig

logger = logging.getLogger(__name__)


class RecurringType(Enum):
    """Type of recurring pattern detected"""
    MONTHLY_FIXED = "monthly_fixed"           # Fixed amount, regular date (e.g., rent, Netflix)
    MONTHLY_VARIABLE = "monthly_variable"     # Variable amount, regular date (e.g., electricity)
    PERIODIC_NON_MONTHLY = "periodic_non_monthly"  # Non-monthly cycle (e.g., quarterly insurance)
    FREQUENT_SMALL_SPEND = "frequent_small_spend"  # Daily/frequent small transactions (excluded)
    NOT_RECURRING = "not_recurring"           # No recurring pattern detected


@dataclass
class RecurringPattern:
    """Detected recurring expense pattern"""
    recipient_key: str
    recurring_type: RecurringType
    category: Optional[str]
    category_label_th: Optional[str]
    n_months_present: int              # Number of months this expense appeared
    amount_cv: float                   # Coefficient of variation (std/mean)
    day_std: float                     # Standard deviation of transaction day-of-month
    n_transactions_per_month: float    # Average transactions per month
    mean_amount: float                 # Average transaction amount
    median_amount: float               # Median transaction amount
    cycle_days: Optional[float]        # For periodic non-monthly: average cycle length
    confidence_score: float            # Overall confidence (0.0-1.0)
    needs_user_label: bool             # True if Group B and category is None
    transactions: List[CategorizedTransaction]  # Source transactions
    forecast_amount: float = 0.0       # Forecasted amount for next month (set by forecaster)


class RecurringDetectionEngine:
    """Detect recurring expense patterns using rules-based analysis"""
    
    def __init__(self, config: DetectionConfig):
        """
        Initialize detection engine with configuration
        
        Args:
            config: Detection configuration with thresholds
            
        Requirements: 13.1-13.14
        """
        self.config = config
    
    def detect_recurring_expenses(
        self, 
        transactions: List[CategorizedTransaction], 
        total_months: int = 6
    ) -> List[RecurringPattern]:
        """
        Detect recurring patterns from categorized transactions
        
        Args:
            transactions: Categorized transactions for analysis
            total_months: Total months of data available (default 6)
            
        Returns:
            List of detected recurring patterns
            
        Requirements: 6.1-6.13, 17.3, 25.1-25.7, 26.1-26.5
        """
        # Filter out credit transactions (รับโอนเงิน) - Requirement 17.3
        debit_transactions = [
            t for t in transactions 
            if t.normalized_transaction.raw_transaction.transaction_type != "รับโอนเงิน"
        ]
        
        logger.info(
            f"Detecting recurring patterns from {len(debit_transactions)} debit transactions "
            f"({len(transactions) - len(debit_transactions)} credit transactions filtered out)"
        )
        
        # Group transactions by recipient_key
        recipient_groups = self._group_by_recipient_key(debit_transactions)
        
        logger.info(f"Grouped transactions into {len(recipient_groups)} recipient groups")
        
        # Analyze each recipient group
        patterns = []
        
        for recipient_key, group_transactions in recipient_groups.items():
            pattern = self._analyze_recurring_pattern(
                recipient_key,
                group_transactions,
                total_months
            )
            patterns.append(pattern)
        
        # Log summary statistics
        pattern_counts = {}
        for pattern in patterns:
            pattern_type = pattern.recurring_type.value
            pattern_counts[pattern_type] = pattern_counts.get(pattern_type, 0) + 1
        
        logger.info(
            f"Detection complete: {len(patterns)} patterns analyzed",
            extra={"pattern_distribution": pattern_counts}
        )
        
        return patterns
    
    def _group_by_recipient_key(
        self, 
        transactions: List[CategorizedTransaction]
    ) -> Dict[str, List[CategorizedTransaction]]:
        """
        Group transactions by recipient_key
        
        Args:
            transactions: List of categorized transactions
            
        Returns:
            Dict mapping recipient_key to list of transactions
            
        Requirements: 6.1
        """
        groups: Dict[str, List[CategorizedTransaction]] = {}
        
        for transaction in transactions:
            recipient_key = transaction.normalized_transaction.recipient_key
            
            if recipient_key not in groups:
                groups[recipient_key] = []
            
            groups[recipient_key].append(transaction)
        
        return groups
    
    def _calculate_metrics(
        self, 
        transactions: List[CategorizedTransaction]
    ) -> Dict[str, float]:
        """
        Calculate statistical metrics for transactions
        
        Args:
            transactions: List of transactions for same recipient
            
        Returns:
            Dict with keys: n_months_present, amount_cv, day_std, 
            n_transactions_per_month, mean_amount, median_amount
            
        Requirements: 6.2, 6.3, 6.4, 23.1-23.8
        """
        if not transactions:
            return {
                "n_months_present": 0,
                "amount_cv": 0.0,
                "day_std": 0.0,
                "n_transactions_per_month": 0.0,
                "mean_amount": 0.0,
                "median_amount": 0.0,
            }
        
        # Extract amounts and dates
        amounts = [t.normalized_transaction.raw_transaction.amount for t in transactions]
        dates = [t.normalized_transaction.raw_transaction.date for t in transactions]
        days_of_month = [d.day for d in dates]
        
        # Calculate n_months_present (count distinct months)
        month_tuples = set((d.year, d.month) for d in dates)
        n_months_present = len(month_tuples)
        
        # Calculate mean and median amounts
        mean_amount = sum(amounts) / len(amounts) if amounts else 0.0
        sorted_amounts = sorted(amounts)
        n = len(sorted_amounts)
        if n == 0:
            median_amount = 0.0
        elif n % 2 == 0:
            median_amount = (sorted_amounts[n // 2 - 1] + sorted_amounts[n // 2]) / 2
        else:
            median_amount = sorted_amounts[n // 2]
        
        # Calculate amount CV (coefficient of variation = std/mean)
        # Requirement 6.3, 23.1, 23.2
        if mean_amount > 0 and len(amounts) > 1:
            variance = sum((x - mean_amount) ** 2 for x in amounts) / len(amounts)
            std_amount = math.sqrt(variance)
            amount_cv = std_amount / mean_amount
        else:
            amount_cv = 0.0 if mean_amount > 0 else float('inf')
        
        # Calculate day_std (standard deviation of day-of-month)
        # Requirement 6.4, 23.3, 23.4
        if len(days_of_month) > 1:
            mean_day = sum(days_of_month) / len(days_of_month)
            variance_day = sum((x - mean_day) ** 2 for x in days_of_month) / len(days_of_month)
            day_std = math.sqrt(variance_day)
        else:
            day_std = 0.0
        
        # Calculate n_transactions_per_month
        # Requirement 23.5, 23.6
        n_transactions_per_month = len(transactions) / n_months_present if n_months_present > 0 else 0.0
        
        return {
            "n_months_present": n_months_present,
            "amount_cv": amount_cv,
            "day_std": day_std,
            "n_transactions_per_month": n_transactions_per_month,
            "mean_amount": mean_amount,
            "median_amount": median_amount,
        }
    
    def _calculate_transaction_gaps(
        self, 
        transactions: List[CategorizedTransaction]
    ) -> List[int]:
        """
        Calculate gaps between consecutive transactions in days
        
        Args:
            transactions: List of transactions (will be sorted by date)
            
        Returns:
            List of gap lengths in days
            
        Requirements: 6.8, 18.6
        """
        if len(transactions) < 2:
            return []
        
        # Sort transactions by date
        sorted_transactions = sorted(
            transactions,
            key=lambda t: t.normalized_transaction.raw_transaction.date
        )
        
        gaps = []
        for i in range(1, len(sorted_transactions)):
            prev_date = sorted_transactions[i - 1].normalized_transaction.raw_transaction.date
            curr_date = sorted_transactions[i].normalized_transaction.raw_transaction.date
            gap_days = (curr_date - prev_date).days
            gaps.append(gap_days)
        
        return gaps
    
    def _classify_recurring_type(
        self, 
        metrics: Dict[str, float],
        transactions: List[CategorizedTransaction],
        total_months: int,
        adjusted_config: DetectionConfig
    ) -> RecurringType:
        """
        Classify recurring type based on metrics and config thresholds
        
        Rules (in order):
        1. Frequent small spend: n_transactions_per_month > threshold AND mean_amount < threshold
        2. Monthly fixed: n_months_present >= threshold AND day_std < threshold AND amount_cv < threshold
        3. Monthly variable: n_months_present >= threshold AND day_std < threshold AND amount_cv < threshold
        4. Periodic non-monthly: Check transaction gaps and gap_std
        5. Not recurring: Default if no rules match
        
        Args:
            metrics: Calculated metrics
            transactions: List of transactions
            total_months: Total months of data available
            adjusted_config: Config adjusted for incomplete data
            
        Returns:
            RecurringType classification
            
        Requirements: 6.5-6.9, 26.1-26.2
        """
        n_months_present = metrics["n_months_present"]
        amount_cv = metrics["amount_cv"]
        day_std = metrics["day_std"]
        n_transactions_per_month = metrics["n_transactions_per_month"]
        mean_amount = metrics["mean_amount"]
        
        # Rule 1: Frequent small spend exclusion
        # Requirement 6.5, 26.1, 26.2
        if (n_transactions_per_month > adjusted_config.frequent_spend_transactions_per_month and
            mean_amount < adjusted_config.frequent_spend_mean_amount_threshold):
            
            logger.debug(
                f"Classified as FREQUENT_SMALL_SPEND: "
                f"transactions/month={n_transactions_per_month:.2f}, mean_amount={mean_amount:.2f}"
            )
            return RecurringType.FREQUENT_SMALL_SPEND
        
        # Rule 2: Monthly fixed bill
        # Requirement 6.6
        if (n_months_present >= adjusted_config.monthly_fixed_min_months and
            day_std < adjusted_config.monthly_fixed_day_std_max and
            amount_cv < adjusted_config.monthly_fixed_amount_cv_max):
            
            logger.debug(
                f"Classified as MONTHLY_FIXED: "
                f"months={n_months_present}, day_std={day_std:.2f}, cv={amount_cv:.4f}"
            )
            return RecurringType.MONTHLY_FIXED
        
        # Rule 3: Monthly variable bill
        # Requirement 6.7
        if (n_months_present >= adjusted_config.monthly_variable_min_months and
            day_std < adjusted_config.monthly_variable_day_std_max and
            amount_cv < adjusted_config.monthly_variable_amount_cv_max):
            
            logger.debug(
                f"Classified as MONTHLY_VARIABLE: "
                f"months={n_months_present}, day_std={day_std:.2f}, cv={amount_cv:.4f}"
            )
            return RecurringType.MONTHLY_VARIABLE
        
        # Rule 4: Periodic non-monthly
        # Requirement 6.8
        if len(transactions) >= adjusted_config.periodic_min_transactions:
            gaps = self._calculate_transaction_gaps(transactions)
            
            if gaps:
                mean_gap = sum(gaps) / len(gaps)
                
                if len(gaps) > 1:
                    variance_gap = sum((x - mean_gap) ** 2 for x in gaps) / len(gaps)
                    std_gap = math.sqrt(variance_gap)
                else:
                    std_gap = 0.0
                
                if (std_gap < adjusted_config.periodic_gap_std_max and
                    mean_gap > adjusted_config.periodic_gap_min_days):
                    
                    logger.debug(
                        f"Classified as PERIODIC_NON_MONTHLY: "
                        f"mean_gap={mean_gap:.1f} days, gap_std={std_gap:.2f}"
                    )
                    return RecurringType.PERIODIC_NON_MONTHLY
        
        # Default: Not recurring
        # Requirement 6.9
        logger.debug("Classified as NOT_RECURRING: no pattern rules matched")
        return RecurringType.NOT_RECURRING
    
    def _adjust_thresholds_for_incomplete_data(
        self, 
        total_months: int
    ) -> DetectionConfig:
        """
        Adjust detection thresholds when data < 6 months
        Lower n_months_present requirement proportionally
        
        Args:
            total_months: Actual months of data available
            
        Returns:
            Adjusted config for incomplete data
            
        Requirements: 6.11, 25.2, 25.3
        """
        if total_months >= 6:
            return self.config
        
        # Create a copy with adjusted thresholds
        adjusted = DetectionConfig(
            # Adjust monthly fixed min months proportionally
            # Example: if 2 months available, require 2 instead of 4
            # Formula: min(total_months, ceiling(original * total_months / 6))
            monthly_fixed_min_months=min(
                total_months,
                math.ceil(self.config.monthly_fixed_min_months * total_months / 6)
            ),
            
            # Adjust monthly variable min months proportionally
            monthly_variable_min_months=min(
                total_months,
                math.ceil(self.config.monthly_variable_min_months * total_months / 6)
            ),
            
            # Keep other thresholds unchanged
            frequent_spend_transactions_per_month=self.config.frequent_spend_transactions_per_month,
            frequent_spend_mean_amount_threshold=self.config.frequent_spend_mean_amount_threshold,
            monthly_fixed_day_std_max=self.config.monthly_fixed_day_std_max,
            monthly_fixed_amount_cv_max=self.config.monthly_fixed_amount_cv_max,
            monthly_variable_day_std_max=self.config.monthly_variable_day_std_max,
            monthly_variable_amount_cv_max=self.config.monthly_variable_amount_cv_max,
            periodic_min_transactions=self.config.periodic_min_transactions,
            periodic_gap_std_max=self.config.periodic_gap_std_max,
            periodic_gap_min_days=self.config.periodic_gap_min_days,
            confidence_data_completeness_weight=self.config.confidence_data_completeness_weight,
            confidence_pattern_consistency_weight=self.config.confidence_pattern_consistency_weight,
        )
        
        logger.info(
            f"Adjusted thresholds for {total_months} months of data: "
            f"monthly_fixed_min_months={adjusted.monthly_fixed_min_months}, "
            f"monthly_variable_min_months={adjusted.monthly_variable_min_months}"
        )
        
        return adjusted
    
    def _calculate_confidence_score(
        self, 
        recurring_type: RecurringType,
        metrics: Dict[str, float],
        total_months: int
    ) -> float:
        """
        Calculate confidence score (0.0-1.0) based on pattern strength
        
        Factors:
        - Data completeness (n_months_present / total_months)
        - Pattern consistency (inverse of CV and day_std)
        - Sample size (number of transactions)
        
        Args:
            recurring_type: Detected recurring type
            metrics: Calculated metrics
            total_months: Total months of data available
            
        Returns:
            Confidence score between 0.0 and 1.0
            
        Requirements: 6.10, 6.12, 24.1-24.8
        """
        # FREQUENT_SMALL_SPEND and NOT_RECURRING have zero confidence
        # Requirements 24.6
        if recurring_type in [RecurringType.FREQUENT_SMALL_SPEND, RecurringType.NOT_RECURRING]:
            return 0.0
        
        n_months_present = metrics["n_months_present"]
        amount_cv = metrics["amount_cv"]
        day_std = metrics["day_std"]
        
        # Factor 1: Data completeness (0.0-1.0)
        # Requirement 24.2, 24.3
        data_completeness = min(1.0, n_months_present / total_months) if total_months > 0 else 0.0
        
        # Reduce confidence for incomplete data (Requirement 6.12, 24.4)
        if total_months < 6:
            # Apply additional penalty for incomplete data
            completeness_penalty = total_months / 6
            data_completeness *= completeness_penalty
        
        # Factor 2: Pattern consistency (0.0-1.0)
        # Inverse of CV and day_std - lower values = higher consistency
        # Requirement 24.5
        
        # Normalize CV (0.0 = perfect, 0.3+ = poor)
        cv_score = max(0.0, 1.0 - (amount_cv / 0.3))
        
        # Normalize day_std (0.0 = perfect, 5.0+ = poor for monthly patterns)
        day_score = max(0.0, 1.0 - (day_std / 5.0))
        
        # Pattern consistency is average of CV and day scores
        pattern_consistency = (cv_score + day_score) / 2
        
        # Weighted combination
        # Requirement 24.1, 13.13
        confidence = (
            self.config.confidence_data_completeness_weight * data_completeness +
            self.config.confidence_pattern_consistency_weight * pattern_consistency
        )
        
        # Ensure bounds [0.0, 1.0]
        confidence = max(0.0, min(1.0, confidence))
        
        logger.debug(
            f"Confidence calculation: data_completeness={data_completeness:.3f}, "
            f"pattern_consistency={pattern_consistency:.3f}, final={confidence:.3f}"
        )
        
        return confidence
    
    def _analyze_recurring_pattern(
        self, 
        recipient_key: str,
        transactions: List[CategorizedTransaction],
        total_months: int
    ) -> RecurringPattern:
        """
        Analyze single recipient's transaction pattern
        
        Args:
            recipient_key: Unique recipient identifier
            transactions: All transactions for this recipient
            total_months: Total months of data available
            
        Returns:
            RecurringPattern with detected type and metrics
            
        Requirements: 6.1-6.13
        """
        # Calculate metrics
        metrics = self._calculate_metrics(transactions)
        
        # Adjust thresholds for incomplete data
        adjusted_config = self._adjust_thresholds_for_incomplete_data(total_months)
        
        # Classify recurring type
        recurring_type = self._classify_recurring_type(
            metrics,
            transactions,
            total_months,
            adjusted_config
        )
        
        # Calculate cycle_days for periodic patterns
        cycle_days = None
        if recurring_type == RecurringType.PERIODIC_NON_MONTHLY:
            gaps = self._calculate_transaction_gaps(transactions)
            if gaps:
                cycle_days = sum(gaps) / len(gaps)
        
        # Calculate confidence score
        confidence_score = self._calculate_confidence_score(
            recurring_type,
            metrics,
            total_months
        )
        
        # Determine category (from first transaction in group)
        # All transactions in group should have same category
        category = transactions[0].category
        category_label_th = transactions[0].category_label_th
        category_group = transactions[0].category_group
        
        # Set needs_user_label flag for Group B without category
        # Requirement 6.13
        needs_user_label = (
            category_group == CategoryGroup.GROUP_B and 
            category is None and
            recurring_type not in [RecurringType.FREQUENT_SMALL_SPEND, RecurringType.NOT_RECURRING]
        )
        
        pattern = RecurringPattern(
            recipient_key=recipient_key,
            recurring_type=recurring_type,
            category=category,
            category_label_th=category_label_th,
            n_months_present=metrics["n_months_present"],
            amount_cv=metrics["amount_cv"],
            day_std=metrics["day_std"],
            n_transactions_per_month=metrics["n_transactions_per_month"],
            mean_amount=metrics["mean_amount"],
            median_amount=metrics["median_amount"],
            cycle_days=cycle_days,
            confidence_score=confidence_score,
            needs_user_label=needs_user_label,
            transactions=transactions
        )
        
        logger.debug(
            f"Pattern analysis complete for {recipient_key}: "
            f"type={recurring_type.value}, confidence={confidence_score:.3f}, "
            f"needs_label={needs_user_label}"
        )
        
        return pattern
