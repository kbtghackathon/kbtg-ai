from datetime import date

import pytest

from src.config.detection_config import DetectionConfig
from src.detector.recurring_detection_engine import RecurringDetectionEngine, RecurringType
from tests.conftest import make_categorized


@pytest.fixture
def engine():
    return RecurringDetectionEngine(DetectionConfig())


def classify(engine, dates, amounts, total_months):
    patterns = engine.detect_recurring_expenses(make_categorized(dates, amounts), total_months)
    assert len(patterns) == 1
    return patterns[0]


def test_single_transaction_is_never_recurring(engine):
    p = classify(engine, [date(2026, 3, 1)], [1200.0], total_months=1)
    assert p.recurring_type == RecurringType.NOT_RECURRING
    assert p.confidence_score == 0.0


def test_two_one_off_months_with_one_month_of_data_not_recurring(engine):
    # even with thresholds scaled down, a floor of 2 months applies
    p = classify(engine, [date(2026, 3, 1)], [500.0], total_months=1)
    assert p.recurring_type == RecurringType.NOT_RECURRING


def test_same_amount_same_day_four_months_is_monthly_fixed(engine):
    dates = [date(2026, m, 5) for m in (1, 2, 3, 4)]
    p = classify(engine, dates, [399.0] * 4, total_months=4)
    assert p.recurring_type == RecurringType.MONTHLY_FIXED
    assert p.n_months_present == 4


def test_two_transactions_sixty_days_apart_not_periodic(engine):
    # With full data the monthly rules need 4 months, so only the periodic rule could fire;
    # a single gap must not be enough for it.
    p = classify(engine, [date(2026, 1, 10), date(2026, 3, 11)], [900.0, 900.0], total_months=6)
    assert p.recurring_type == RecurringType.NOT_RECURRING


def test_three_quarterly_transactions_are_periodic(engine):
    dates = [date(2025, 10, 1), date(2025, 12, 30), date(2026, 3, 30)]
    p = classify(engine, dates, [3000.0, 3000.0, 3000.0], total_months=6)
    assert p.recurring_type == RecurringType.PERIODIC_NON_MONTHLY
    assert p.cycle_days == pytest.approx(90, abs=1)


def test_threshold_floor_never_drops_below_two_months(engine):
    for months in (1, 2, 3):
        adjusted = engine._adjust_thresholds_for_incomplete_data(months)
        assert adjusted.monthly_fixed_min_months >= 2
        assert adjusted.monthly_variable_min_months >= 2
    assert engine._adjust_thresholds_for_incomplete_data(6) is engine.config
