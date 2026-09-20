from datetime import date

import pytest

from src.aggregator.cashflow_signals import derive_cashflow_signals
from src.detector.recurring_detection_engine import (
    RecurringDetectionEngine,
    RecurringPattern,
    RecurringType,
)
from src.config.detection_config import DetectionConfig
from src.parser.record_parser import RecordParser
from src.pipeline.stateless_pipeline import analyze_from_text
from tests.conftest import SYNTHETIC_STATEMENT, make_categorized, make_raw_transaction


def pattern(recurring_type: RecurringType, dates, amounts, key="MERCHANT:SHOP") -> RecurringPattern:
    txs = make_categorized(dates, amounts, recipient_key=key)
    return RecurringPattern(
        recipient_key=key,
        recurring_type=recurring_type,
        category=None,
        category_label_th=None,
        n_months_present=len({(d.year, d.month) for d in dates}),
        amount_cv=0.0,
        day_std=0.0,
        day_of_month=dates[0].day if dates else 0,
        n_transactions_per_month=1.0,
        mean_amount=sum(amounts) / len(amounts) if amounts else 0.0,
        median_amount=amounts[0] if amounts else 0.0,
        cycle_days=None,
        confidence_score=0.9,
        needs_user_label=False,
        transactions=txs,
    )


def raw(day: int, amount: float, month: int = 1, tx_type: str = "ชำระเงิน", balance: float = 0.0):
    tx = make_raw_transaction(date(2026, month, day), amount, transaction_type=tx_type)
    tx.balance_after = balance
    return tx


def test_no_transactions_is_all_zeroes():
    signals = derive_cashflow_signals([], [], [], 0)
    assert signals.closing_balance == 0.0
    assert signals.payday_day_of_month is None


def test_closing_balance_is_the_latest_transaction():
    # Deliberately out of order: the statement is sorted by date, not by
    # the order rows happened to arrive in.
    txs = [raw(20, 100, balance=5000), raw(5, 100, balance=9000), raw(28, 100, balance=3000)]
    assert derive_cashflow_signals(txs, [], [], 1).closing_balance == 3000


# The discretionary figure has to come from the patterns the recurring summary
# discarded, so the two halves always add up to the whole.
def test_variable_spend_is_what_the_summary_left_out():
    days = [date(2026, m, 10) for m in (1, 2, 3, 4)]
    patterns = [
        pattern(RecurringType.MONTHLY_FIXED, days, [6500] * 4, key="ACCOUNT:X2660"),
        pattern(RecurringType.NOT_RECURRING, [date(2026, 2, 3)], [1200], key="MERCHANT:ONEOFF"),
        pattern(RecurringType.FREQUENT_SMALL_SPEND, days, [80] * 4, key="MERCHANT:COFFEE"),
    ]

    signals = derive_cashflow_signals([raw(1, 1)], [], patterns, total_months=4)

    # The rent is committed and excluded; the one-off and the habit are not.
    assert signals.variable_spend_monthly == pytest.approx((1200 + 320) / 4)


def test_variable_spend_is_zero_when_everything_recurs():
    days = [date(2026, m, 10) for m in (1, 2, 3, 4)]
    patterns = [pattern(RecurringType.MONTHLY_FIXED, days, [6500] * 4)]
    assert derive_cashflow_signals([raw(1, 1)], [], patterns, 4).variable_spend_monthly == 0.0


# Spanned days, not calendar months: a statement covering the 3rd to the 26th
# describes 24 days of behaviour, and dividing by 30 understates the rate.
def test_avg_daily_spend_uses_the_days_the_statement_spans():
    txs = [raw(1, 300), raw(11, 700)]  # 11 days spanned, 1,000 out
    assert derive_cashflow_signals(txs, [], [], 1).avg_daily_spend == pytest.approx(1000 / 11)


def test_avg_daily_spend_ignores_credits():
    txs = [raw(1, 300), raw(11, 45000, tx_type="รับโอนเงิน")]
    assert derive_cashflow_signals(txs, [], [], 1).avg_daily_spend == pytest.approx(300 / 11)


def test_a_single_day_statement_does_not_divide_by_zero():
    assert derive_cashflow_signals([raw(5, 500)], [], [], 1).avg_daily_spend == 500.0


# Income is what the statement shows, which the caller cannot see any other way
# -- it is the one figure the caller declares rather than measures.
def test_observed_income_averages_over_the_months_it_appeared_in():
    txs = [
        raw(25, 30000, month=1, tx_type="รับโอนเงิน"),
        raw(25, 32000, month=2, tx_type="รับโอนเงิน"),
        raw(3, 500, month=2),
    ]
    signals = derive_cashflow_signals(txs, [], [], total_months=2)

    assert signals.observed_income == pytest.approx(31000)
    assert signals.income_months == 2
    assert signals.payday_day_of_month == 25


def test_two_credits_in_one_month_sum_rather_than_halve():
    txs = [
        raw(25, 30000, month=1, tx_type="รับโอนเงิน"),
        raw(28, 5000, month=1, tx_type="รับโอนเงิน"),
    ]
    signals = derive_cashflow_signals(txs, [], [], total_months=1)
    assert signals.observed_income == pytest.approx(35000)
    assert signals.income_months == 1


# A salary on the 25th and a one-off refund on the 5th average to the 15th,
# a day nothing has ever arrived on.
def test_payday_is_the_most_common_day_not_the_mean():
    txs = [
        raw(25, 30000, month=1, tx_type="รับโอนเงิน"),
        raw(25, 30000, month=2, tx_type="รับโอนเงิน"),
        raw(5, 200, month=2, tx_type="รับโอนเงิน"),
    ]
    assert derive_cashflow_signals(txs, [], [], 2).payday_day_of_month == 25


def test_no_credits_leaves_payday_unknown():
    signals = derive_cashflow_signals([raw(5, 500)], [], [], 1)
    assert signals.payday_day_of_month is None
    assert signals.observed_income == 0.0


# ---------------------------------------------------------------------------
# parse success rate
# ---------------------------------------------------------------------------

def test_parse_success_rate_is_one_for_a_clean_statement(synthetic_statement_text):
    parser = RecordParser()
    parser.parse_statement_text(synthetic_statement_text, date(2026, 1, 1))

    assert parser.stats.parsed == 14
    assert parser.stats.failed == 0
    assert parser.stats.success_rate == 1.0


def test_the_opening_balance_row_is_not_counted_as_a_failure(synthetic_statement_text):
    parser = RecordParser()
    parser.parse_statement_text(synthetic_statement_text, date(2026, 1, 1))

    # Dropping the opening balance is success, not a missed record, so it is
    # excluded from the denominator rather than counted against the rate.
    assert parser.stats.attempted == parser.stats.parsed + parser.stats.opening_balance
    assert parser.stats.success_rate == 1.0


def test_unreadable_records_lower_the_rate():
    parser = RecordParser()
    # Two well-formed rows and two that open with a date and then say nothing.
    text = "\n".join([
        "01-01-69 10:00 ชำระเงิน 100.00 9,900.00 K PLUS",
        "02-01-69 ???",
        "03-01-69 10:00 ชำระเงิน 200.00 9,700.00 K PLUS",
        "04-01-69 ???",
    ])
    parser.parse_statement_text(text, date(2026, 1, 1))

    assert parser.stats.attempted == 4
    assert parser.stats.success_rate < 1.0


def test_stats_accumulate_across_statements(synthetic_statement_text):
    parser = RecordParser()
    parser.parse_statement_text(synthetic_statement_text, date(2026, 1, 1))
    parser.parse_statement_text(synthetic_statement_text, date(2026, 2, 1))

    assert parser.stats.parsed == 28


# ---------------------------------------------------------------------------
# end to end through the pipeline
# ---------------------------------------------------------------------------

def test_pipeline_reports_the_cashflow_signals(synthetic_statement_text):
    result = analyze_from_text([synthetic_statement_text], current_salary=45000)

    # The fixture's salary credit is 30,000 while the caller declared 45,000.
    # Reporting both is the point: a caller can now notice the difference.
    assert result["observed_income"] == 30000.0
    assert result["income_months"] == 1
    assert result["closing_balance"] > 0
    assert result["avg_daily_spend"] > 0
    assert result["parse_success_rate"] == 1.0

    # The one-off ฿1,500 shop is the only non-recurring spend in the fixture.
    assert result["variable_spend_monthly"] == pytest.approx(1500 / 4)


def test_pipeline_reports_per_expense_statistics(synthetic_statement_text):
    result = analyze_from_text([synthetic_statement_text], current_salary=45000)
    by_key = {e["recipient_key"]: e for e in result["recurring_expenses"]}

    for expense in by_key.values():
        assert expense["n_months_present"] == 4
        assert 1 <= expense["day_of_month"] <= 31
        assert expense["recurring_type"] in {
            "monthly_fixed", "monthly_variable", "periodic_non_monthly"
        }
        # Flat amounts every month, so no volatility.
        assert expense["amount_cv"] == pytest.approx(0.0)

    # Each lands on its own day; a caller can tell what is still to come.
    days = {k: e["day_of_month"] for k, e in by_key.items()}
    assert len(set(days.values())) == 3, days


def test_day_of_month_is_the_median_not_the_mean():
    engine = RecurringDetectionEngine(DetectionConfig())
    # Paid on the 3rd three times, then once late on the 28th. The mean is the
    # 9th, a date it has never fallen on.
    txs = make_categorized(
        [date(2026, 1, 3), date(2026, 2, 3), date(2026, 3, 3), date(2026, 4, 28)],
        [500, 500, 500, 500],
    )
    metrics = engine._calculate_metrics(txs)
    assert metrics["day_of_month"] == 3
