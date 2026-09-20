"""
Cash-flow signals derived from a parsed statement.

Everything here was already computed inside the pipeline and then dropped on
the floor: the balance chain the parser validates, the patterns the aggregator
filters out as non-recurring, and the credits the detector excludes before it
starts. None of it survived into the response, so a caller wanting to know a
person's balance or their discretionary spending had to reconstruct it from
somewhere else -- or do without.

The recurring-expense summary answers "what is committed". This answers "what
is actually happening", which is the other half of any spending decision.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from ..categorizer.categorization_module import CategorizedTransaction
from ..detector.recurring_detection_engine import RecurringPattern, RecurringType
from ..parser.record_parser import RawTransaction

logger = logging.getLogger(__name__)

# The transaction type the statement uses for money coming in. The detector
# excludes it from recurring-expense analysis for the obvious reason; here it
# is the only thing we want.
CREDIT_TYPE = "รับโอนเงิน"

# Patterns the recurring summary excludes. Their transactions are, by
# definition, the spending that is not committed to anything.
DISCRETIONARY_TYPES = {
    RecurringType.FREQUENT_SMALL_SPEND,
    RecurringType.NOT_RECURRING,
}


@dataclass
class CashflowSignals:
    """What the statement says about money moving, beyond the fixed costs."""

    # Balance after the most recent transaction in the statement.
    closing_balance: float = 0.0

    # Income actually observed, averaged per month it appeared in. This is a
    # measurement, unlike the salary the caller declares, and the two differing
    # is itself worth knowing.
    observed_income: float = 0.0
    income_months: int = 0
    # Day of the month income typically lands. None when no credits were seen.
    payday_day_of_month: Optional[int] = None

    # Spending on everything the detector did not call recurring, per month.
    variable_spend_monthly: float = 0.0
    # Total debits divided by the days the statement spans.
    avg_daily_spend: float = 0.0


def derive_cashflow_signals(
    raw_transactions: List[RawTransaction],
    categorized_transactions: List[CategorizedTransaction],
    patterns: List[RecurringPattern],
    total_months: int,
) -> CashflowSignals:
    """
    Derive the cash-flow picture from one pipeline run's intermediate state.

    Pure: takes what the pipeline already holds and returns a value. No parsing,
    no I/O, nothing stored.
    """
    if not raw_transactions:
        return CashflowSignals()

    months = max(1, total_months)

    ordered = sorted(raw_transactions, key=lambda t: t.date)
    debits = [t for t in ordered if t.transaction_type != CREDIT_TYPE]
    credits = [t for t in ordered if t.transaction_type == CREDIT_TYPE]

    signals = CashflowSignals(
        closing_balance=ordered[-1].balance_after,
        variable_spend_monthly=_discretionary_per_month(patterns, months),
        avg_daily_spend=_avg_daily_spend(debits, ordered),
    )

    _apply_income(signals, credits)

    logger.debug(
        "Cashflow signals: balance=%.2f income=%.2f/%d months variable=%.2f/month daily=%.2f",
        signals.closing_balance, signals.observed_income, signals.income_months,
        signals.variable_spend_monthly, signals.avg_daily_spend,
    )

    return signals


def _discretionary_per_month(patterns: List[RecurringPattern], months: int) -> float:
    """
    Average monthly spend on everything not classified as a recurring expense.

    Taken from the patterns rather than by re-walking the transactions, so that
    what counts as discretionary here is exactly what the recurring summary
    left out. If the detector's rules change, these two move together instead
    of drifting into double-counting or a gap.
    """
    total = 0.0

    for pattern in patterns:
        if pattern.recurring_type not in DISCRETIONARY_TYPES:
            continue

        for tx in pattern.transactions:
            total += tx.normalized_transaction.raw_transaction.amount

    return total / months


def _avg_daily_spend(debits: List[RawTransaction], ordered: List[RawTransaction]) -> float:
    """
    Total outgoings divided by the days the statement actually spans.

    Spanned days, not calendar months: a statement covering the 3rd to the 26th
    describes 24 days of behaviour, and dividing it by 30 would understate the
    rate at which this person spends.
    """
    if not debits:
        return 0.0

    span_days = (ordered[-1].date - ordered[0].date).days + 1
    if span_days < 1:
        span_days = 1

    return sum(t.amount for t in debits) / span_days


def _apply_income(signals: CashflowSignals, credits: List[RawTransaction]) -> None:
    """
    Summarise money coming in.

    Income is averaged over the months it appeared in rather than over the whole
    statement: a statement that happens to start mid-month would otherwise
    report a month of half income and drag the average down.

    The payday is the most common day a credit lands on, not the mean -- a
    salary on the 25th and a one-off refund on the 5th average to the 15th,
    a day nothing has ever arrived.
    """
    if not credits:
        return

    by_month: Dict[tuple, float] = {}
    for credit in credits:
        by_month.setdefault((credit.date.year, credit.date.month), 0.0)
        by_month[(credit.date.year, credit.date.month)] += credit.amount

    signals.income_months = len(by_month)
    signals.observed_income = sum(by_month.values()) / len(by_month)

    day_counts: Dict[int, int] = {}
    for credit in credits:
        day_counts[credit.date.day] = day_counts.get(credit.date.day, 0) + 1

    # Ties break toward the later day: a salary is more often the month's last
    # inflow than its first, and the later date is the more cautious assumption
    # for anyone asking "has this month's income arrived yet".
    signals.payday_day_of_month = max(day_counts.items(), key=lambda kv: (kv[1], kv[0]))[0]
