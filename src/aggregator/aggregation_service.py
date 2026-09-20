"""
Aggregation Service

This module aggregates recurring expenses into summary format for API responses.

Refactored to be stateless - accepts recurring patterns directly instead of querying DB.

Requirements: 9.1-9.11, 10.1-10.10, 25.4, 25.5
"""

import logging
import math
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import date

from ..detector.recurring_detection_engine import RecurringPattern, RecurringType

logger = logging.getLogger(__name__)


@dataclass
class RecurringExpenseSummaryItem:
    """
    Single recurring expense item in summary.

    The four fields below the original five carry the detector's own view of
    the pattern to the consumer. Without them a caller sees only "฿6,500 a
    month" and cannot tell a rent payment from a volatile habit, or know
    whether this month's has already gone out -- both of which change how much
    of the remaining balance is genuinely spare.
    """
    category: str
    category_label_th: str
    amount: float
    confidence: float
    recipient_key: str
    # monthly_fixed | monthly_variable | periodic_non_monthly
    recurring_type: str = "monthly_fixed"
    # Coefficient of variation of the amount. 0 is a flat bill; higher is a
    # bill worth leaving headroom for.
    amount_cv: float = 0.0
    # Typical day of the month it lands on. 0 when it could not be determined.
    day_of_month: int = 0
    # How many distinct months it was seen in.
    n_months_present: int = 0


@dataclass
class PendingLabel:
    """Recurring expense pending user label"""
    recipient_key: str
    detected_amount: float
    n_months_detected: int
    category_suggestions: List[str]
    sample_transactions: List[Dict[str, Any]]


@dataclass
class RecurringSummary:
    """Complete recurring expenses summary for user"""
    salary_this_month: float
    recurring_expenses: List[RecurringExpenseSummaryItem]
    total_recurring: float
    remaining_after_reserve: float
    pending_user_labels: List[PendingLabel]
    data_completeness_warning: Optional[str]
    data_months_available: int


class AggregationService:
    """Aggregate recurring expenses into summary format"""
    
    def __init__(self):
        """
        Initialize aggregation service (stateless version)
        """
        pass
    
    def generate_summary(
        self, 
        recurring_patterns: List[RecurringPattern],
        current_salary: float,
        data_months_available: int
    ) -> RecurringSummary:
        """
        Generate complete recurring expenses summary
        
        Stateless version - accepts recurring_patterns directly.
        
        Args:
            recurring_patterns: List of detected recurring patterns
            current_salary: User's current month salary (from input)
            data_months_available: Number of months of transaction data available
            
        Returns:
            Complete summary with breakdown and calculations
            
        Requirements: 9.1-9.11
        """
        logger.info(f"Generating summary from {len(recurring_patterns)} patterns, salary={current_salary:.2f}")
        
        # Filter to include only actual recurring expenses
        filtered_expenses = self._filter_active_expenses(recurring_patterns)
        
        logger.debug(
            f"Filtered to {len(filtered_expenses)} active expenses "
            f"(excluded {len(recurring_patterns) - len(filtered_expenses)} "
            f"FREQUENT_SMALL_SPEND/NOT_RECURRING)"
        )
        
        # Convert to summary items
        summary_items = [
            RecurringExpenseSummaryItem(
                category=pattern.category or "other",
                category_label_th=pattern.category_label_th or "อื่นๆ",
                amount=pattern.forecast_amount,
                confidence=pattern.confidence_score,
                recipient_key=pattern.recipient_key,
                recurring_type=pattern.recurring_type.value,
                amount_cv=pattern.amount_cv if math.isfinite(pattern.amount_cv) else 0.0,
                day_of_month=pattern.day_of_month,
                n_months_present=pattern.n_months_present,
            )
            for pattern in filtered_expenses
        ]
        
        # Calculate total recurring expenses
        total_recurring = self._calculate_total_recurring(summary_items)
        
        # Calculate remaining income after reserve
        # Requirement 9.11
        remaining_after_reserve = current_salary - total_recurring
        
        # Check data completeness
        completeness_warning = self._check_data_completeness(data_months_available)
        
        # Get pending user labels
        pending_labels = self._get_pending_labels(recurring_patterns)
        
        logger.info(
            f"Summary complete: {len(summary_items)} expenses, "
            f"total_recurring={total_recurring:.2f}, "
            f"remaining={remaining_after_reserve:.2f}, "
            f"pending_labels={len(pending_labels)}"
        )
        
        # Requirement 9.9
        summary = RecurringSummary(
            salary_this_month=current_salary,
            recurring_expenses=summary_items,
            total_recurring=total_recurring,
            remaining_after_reserve=remaining_after_reserve,
            pending_user_labels=pending_labels,
            data_completeness_warning=completeness_warning,
            data_months_available=data_months_available
        )
        
        return summary
    
    def _filter_active_expenses(
        self, 
        patterns: List[RecurringPattern]
    ) -> List[RecurringPattern]:
        """
        Filter out non-recurring patterns
        Only include: MONTHLY_FIXED, MONTHLY_VARIABLE, PERIODIC_NON_MONTHLY
        Exclude: FREQUENT_SMALL_SPEND, NOT_RECURRING
        
        Args:
            patterns: List of all recurring patterns
            
        Returns:
            Filtered list of actual recurring expenses
            
        Requirements: 9.2, 9.3, 26.3
        """
        # Requirement 9.2, 9.3, 26.3
        included_types = {
            RecurringType.MONTHLY_FIXED,
            RecurringType.MONTHLY_VARIABLE, 
            RecurringType.PERIODIC_NON_MONTHLY
        }
        
        filtered = [
            pattern for pattern in patterns 
            if pattern.recurring_type in included_types
        ]
        
        logger.debug(
            f"Filtered expenses: {len(filtered)} included, "
            f"{len(patterns) - len(filtered)} excluded"
        )
        
        return filtered
    
    def _calculate_total_recurring(
        self, 
        expenses: List[RecurringExpenseSummaryItem]
    ) -> float:
        """
        Sum up all forecasted recurring expenses
        
        Args:
            expenses: List of recurring expense summary items
            
        Returns:
            Total recurring expenses amount (non-negative)
            
        Requirements: 9.4, 9.10
        """
        # Requirement 9.4
        total = sum(exp.amount for exp in expenses)
        
        # Requirement 9.10: ensure non-negative
        total = max(0.0, total)
        
        logger.debug(f"Calculated total_recurring: {total:.2f}")
        
        return total
    
    def _check_data_completeness(
        self, 
        months_available: int
    ) -> Optional[str]:
        """
        Check if user has complete 6 months data
        
        Args:
            months_available: Number of months of data available
            
        Returns:
            warning_message (None if data is complete)
            
        Requirements: 9.7, 9.8, 25.4, 25.5
        """
        logger.debug(f"Data has {months_available} months available")
        
        # Requirement 9.7, 9.8, 25.4, 25.5
        if months_available < 6:
            warning = self._format_completeness_warning(months_available)
            logger.info(
                f"Data incomplete: {months_available} months (warning issued)"
            )
        else:
            warning = None
        
        return warning
    
    def _format_completeness_warning(self, months_available: int) -> str:
        """
        Generate data completeness warning message in Thai
        
        Args:
            months_available: Number of months of data available
            
        Returns:
            Warning message in Thai
            
        Requirements: 9.7, 9.8
        """
        # Requirement 9.7, 9.8: warning message in Thai
        warning = (
            f"ข้อมูลของคุณมีเพียง {months_available} เดือน "
            f"การคาดการณ์อาจมีความแม่นยำน้อยกว่าข้อมูล 6 เดือนเต็ม"
        )
        
        return warning
    
    def _get_pending_labels(
        self, 
        patterns: List[RecurringPattern]
    ) -> List[PendingLabel]:
        """
        Get list of recurring expenses needing user labels
        
        Args:
            patterns: List of recurring patterns
            
        Returns:
            List of expenses pending label (needs_user_label=True)
            
        Requirements: 9.6
        """
        pending_labels = []
        
        for pattern in patterns:
            if pattern.needs_user_label:
                # Get sample transactions for this recipient
                sample_transactions = self._get_sample_transactions(pattern)
                
                # Generate category suggestions
                category_suggestions = self._suggest_categories(
                    pattern.forecast_amount,
                    pattern.n_months_present
                )
                
                pending_label = PendingLabel(
                    recipient_key=pattern.recipient_key,
                    detected_amount=pattern.forecast_amount,
                    n_months_detected=pattern.n_months_present,
                    category_suggestions=category_suggestions,
                    sample_transactions=sample_transactions
                )
                
                pending_labels.append(pending_label)
        
        logger.debug(f"Found {len(pending_labels)} pending labels")
        
        return pending_labels
    
    def _get_sample_transactions(
        self, 
        pattern: RecurringPattern
    ) -> List[Dict[str, Any]]:
        """
        Get up to 3 sample transactions for pending label
        
        Args:
            pattern: Recurring pattern
            
        Returns:
            List of sample transaction dictionaries
            
        Requirements: 36.1-36.5
        """
        # Get up to 3 most recent transactions from the pattern
        sorted_transactions = sorted(
            pattern.transactions,
            key=lambda t: t.normalized_transaction.raw_transaction.date,
            reverse=True
        )[:3]
        
        samples = []
        for tx in sorted_transactions:
            raw_tx = tx.normalized_transaction.raw_transaction
            recipient = (
                tx.normalized_transaction.normalized_merchant_name or 
                tx.normalized_transaction.normalized_recipient_name or
                "Unknown"
            )
            
            # Requirement 36.5: format with thousands separators
            samples.append({
                "date": raw_tx.date.isoformat() if raw_tx.date else None,
                "amount": f"{raw_tx.amount:,.2f}",
                "recipient": recipient
            })
        
        return samples
    
    def _suggest_categories(
        self, 
        amount: float, 
        n_months: int
    ) -> List[str]:
        """
        Suggest likely categories based on amount and pattern
        
        This is a simplified heuristic version.
        
        Args:
            amount: Forecast amount
            n_months: Number of months detected
            
        Returns:
            List of suggested category codes
            
        Requirements: 37.1-37.6
        """
        suggestions = []
        
        # Requirement 37.1: high amount suggests rent/loan
        if amount >= 3000.0:
            suggestions.extend(["rent", "loan_payment"])
        
        # Requirement 37.2: medium amount suggests internet/mobile
        elif 500.0 <= amount <= 2000.0:
            suggestions.extend(["internet", "mobile"])
        
        # Requirement 37.3: variable pattern suggests utility
        # (simplified heuristic - full version checks amount_cv)
        if 300.0 <= amount <= 1500.0:
            if "utility" not in suggestions:
                suggestions.append("utility")
        
        # Requirement 37.6: always include "other"
        suggestions.append("other")
        
        return suggestions
