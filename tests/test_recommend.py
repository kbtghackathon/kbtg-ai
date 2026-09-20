import pytest
from fastapi.testclient import TestClient

from main import app
from src.config.savings_config import SavingsConfig
from src.recommender import SavingsRecommendationModule, SavingsSignals


@pytest.fixture
def client():
    with TestClient(app) as c:  # context manager runs startup hooks
        yield c


def baht(v: float) -> int:
    return round(v * 100)


def mid_month(**overrides) -> SavingsSignals:
    """A normal month, halfway through: salary in, rent paid, a fortnight of
    ordinary spending done and a fortnight still to get through."""
    signals = SavingsSignals(
        income=baht(45000),
        fixed_costs=baht(7000),
        spent_so_far=baht(7500),
        avg_daily_spend=baht(500),
        days_remaining=15,
        balance=baht(60000),
        min_per_month=baht(500),
        max_per_month=baht(5000),
        buffer_balance=baht(3000),
        aggressiveness="BALANCED",
        data_months=6,
        parse_success_rate=1.0,
    )
    for k, v in overrides.items():
        setattr(signals, k, v)
    return signals


def recommend(**overrides):
    return SavingsRecommendationModule().recommend(mid_month(**overrides))


# 45,000 - 7,000 - 7,500 - (500 x 15) = 23,000 surplus
@pytest.mark.parametrize(
    "level,expected",
    [("SAFE", 3450), ("BALANCED", 6900), ("BOLD", 11500)],
)
def test_share_of_surplus_by_aggressiveness(level, expected):
    result = recommend(aggressiveness=level)
    assert result.skip is False
    assert result.amount == baht(expected)


def test_unknown_aggressiveness_falls_back_to_balanced():
    assert recommend(aggressiveness="RECKLESS").amount == recommend(aggressiveness="BALANCED").amount
    assert recommend(aggressiveness="").amount == baht(6900)
    assert recommend(aggressiveness="balanced").amount == baht(6900)


# The whole reason this module exists: on the 1st nothing has been spent, and
# income-minus-costs would offer the entire month's spending money to a pocket.
def test_the_first_of_the_month_reserves_the_whole_month():
    result = recommend(spent_so_far=0, avg_daily_spend=baht(500), days_remaining=30)
    assert result.amount == baht(6900)  # 45,000 - 7,000 - 0 - 15,000 = 23,000


def test_the_last_day_reserves_only_today():
    result = recommend(spent_so_far=baht(14500), avg_daily_spend=baht(500), days_remaining=1)
    assert result.amount == baht(6900)  # 45,000 - 7,000 - 14,500 - 500 = 23,000


def test_a_heavy_spender_is_left_with_less():
    result = recommend(spent_so_far=baht(15000), avg_daily_spend=baht(1000))
    assert result.amount == baht(2400)  # 8,000 surplus


# Saying "the month is already spoken for" is a different answer from
# recommending zero, which the caller treats as a failure.
@pytest.mark.parametrize(
    "overrides",
    [
        {"fixed_costs": baht(30000), "spent_so_far": baht(8000), "avg_daily_spend": baht(600)},
        {"fixed_costs": baht(50000)},
        {"income": 0},
    ],
)
def test_skips_when_nothing_is_left(overrides):
    result = recommend(**overrides)
    assert result.skip is True
    assert result.amount == 0
    assert result.skip_reason, "a skip the user cannot read is a bug"
    assert result.reasons, "a refusal with no working is indistinguishable from a bug"


def test_saves_less_when_it_has_read_less():
    full = recommend(data_months=6, parse_success_rate=1.0)

    for months, rate in [(4, 1.0), (1, 1.0), (6, 0.8), (4, 0.5)]:
        thin = recommend(data_months=months, parse_success_rate=rate)
        assert thin.amount < full.amount, f"{months} months / {rate} parse proposed too much"
        assert thin.amount > 0, "the discount must not zero the proposal out"

    # Monotonic: less statement never proposes more.
    previous = full.amount
    for months in range(6, 0, -1):
        amount = recommend(data_months=months).amount
        assert amount <= previous
        previous = amount


# A caller with no statement on file derived the costs from its own ledger,
# which is the same account read from the source -- not weaker evidence.
def test_no_statement_is_not_penalised():
    assert recommend(data_months=0).amount == baht(6900)
    assert SavingsRecommendationModule().data_quality(mid_month(data_months=0)) == 1.0


@pytest.mark.parametrize(
    "months,rate,expected",
    [
        (0, 1.0, 1.0),
        (6, 1.0, 1.0),
        (4, 1.0, 0.75 + 0.25 * 4 / 6),
        (6, 0.5, 0.85),
        (99, 1.0, 1.0),          # more months than the maximum is not more confidence
        (6, 1.4, 1.0),           # nonsense about its own parse rate is not evidence
        (6, -1.0, 1.0),
    ],
)
def test_data_quality(months, rate, expected):
    module = SavingsRecommendationModule()
    got = module.data_quality(mid_month(data_months=months, parse_success_rate=rate))
    assert got == pytest.approx(expected, abs=1e-4)
    assert module.config.min_data_quality <= got <= 1.0


def test_data_quality_is_floored():
    module = SavingsRecommendationModule()
    assert module.data_quality(mid_month(data_months=1, parse_success_rate=0.0)) == pytest.approx(
        module.config.min_data_quality
    )


# The reasoning is the product: a proposal nobody can audit is one they switch off.
def test_shows_its_working():
    result = recommend(data_months=4)

    assert all(r.label for r in result.reasons)
    assert result.reasons[0].amount == baht(38000)     # income less fixed costs
    assert result.reasons[-1].amount == result.amount  # ends on the number proposed

    amounts = [r.amount for r in result.reasons]
    assert amounts == sorted(amounts, reverse=True), "a step conjured money"

    assert "statement 4 เดือน" in result.reasons[0].note
    assert any("กันไว้ใช้อีก 15 วัน" in r.label for r in result.reasons)


@pytest.mark.parametrize(
    "overrides",
    [
        {"days_remaining": 0},
        {"days_remaining": -10},
        {"income": 0, "fixed_costs": 0, "spent_so_far": 0, "avg_daily_spend": 0},
        {"parse_success_rate": float("nan")},
    ],
)
def test_survives_degenerate_signals(overrides):
    result = recommend(**overrides)
    assert result.amount >= 0, "a proposal must never be a withdrawal"


def test_custom_config_changes_the_share():
    config = SavingsConfig(aggressiveness_ratios={"BALANCED": 0.10}, default_aggressiveness="BALANCED")
    result = SavingsRecommendationModule(config).recommend(mid_month())
    assert result.amount == baht(2300)  # 23,000 x 10%


# ---------------------------------------------------------------------------
# endpoint
# ---------------------------------------------------------------------------

def payload(**overrides) -> dict:
    body = {
        "userId": "user-somchai",
        "month": "2026-09",
        "balance": baht(60000),
        "income": baht(45000),
        "fixedCosts": baht(7000),
        "variableSpend": baht(7500),
        "freeCashFlow": baht(30500),
        "avgDailySpend": baht(500),
        "daysRemaining": 15,
        "minPerMonth": baht(500),
        "maxPerMonth": baht(5000),
        "bufferBalance": baht(3000),
        "aggressiveness": "BALANCED",
        "dataMonths": 6,
        "parseSuccessRate": 1.0,
    }
    body.update(overrides)
    return body


def test_recommend_endpoint(client):
    resp = client.post("/v1/savings/recommend", json=payload())
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["recommendedAmount"] == baht(6900)
    assert body["skip"] is False
    assert body["modelVersion"] == "savings-rule-v1"
    assert body["confidence"] == 1.0
    assert body["reasons"], "the app renders these; an empty list is a blank screen"
    assert all(isinstance(r["amount"], int) for r in body["reasons"]), "satang must stay integers"


def test_recommend_endpoint_reports_a_skip(client):
    resp = client.post("/v1/savings/recommend", json=payload(fixedCosts=baht(50000)))
    assert resp.status_code == 200, resp.text

    body = resp.json()
    assert body["skip"] is True
    assert body["recommendedAmount"] == 0
    assert body["skipReason"]


def test_recommend_endpoint_rejects_a_non_positive_income(client):
    for income in (0, -1):
        resp = client.post("/v1/savings/recommend", json=payload(income=income))
        assert resp.status_code == 422, resp.text


def test_recommend_endpoint_accepts_snake_case_too(client):
    """The Go client sends camelCase; keeping snake_case working means a curl
    from a Python developer does not mysteriously return a different number."""
    body = payload()
    snake = {
        "income": body["income"],
        "fixed_costs": body["fixedCosts"],
        "variable_spend": body["variableSpend"],
        "avg_daily_spend": body["avgDailySpend"],
        "days_remaining": body["daysRemaining"],
        "data_months": body["dataMonths"],
    }
    resp = client.post("/v1/savings/recommend", json=snake)
    assert resp.status_code == 200, resp.text
    assert resp.json()["recommendedAmount"] == baht(6900)


# ---------------------------------------------------------------------------
# signals only the statement analyser can supply
# ---------------------------------------------------------------------------

from src.recommender import CashflowSignals, ExpenseSignal  # noqa: E402


def expense(amount: float, day: int = 0, cv: float = 0.0) -> ExpenseSignal:
    return ExpenseSignal(amount=baht(amount), day_of_month=day, amount_cv=cv)


# The caller declares a salary; the analyser measured what actually arrived.
# A statement showing ฿30,000 against a declared ฿45,000 means planning on
# ฿45,000 would over-save this person into an overdraft.
def test_measured_income_below_the_declared_one_wins():
    declared = recommend()
    measured = recommend(
        cashflow=CashflowSignals(observed_income=baht(30000), income_months=4)
    )

    assert measured.amount < declared.amount
    # 30,000 - 7,000 - 7,500 - 7,500 = 8,000 surplus
    assert measured.amount == baht(2400)
    assert "statement" in measured.reasons[0].note


# Extra money that showed up once is not a raise.
def test_measured_income_above_the_declared_one_is_ignored():
    generous = recommend(
        cashflow=CashflowSignals(observed_income=baht(90000), income_months=4)
    )
    assert generous.amount == recommend().amount


# One payday is not a pattern. A statement window that catches a single credit
# must not rewrite a salary the person stated about themselves.
@pytest.mark.parametrize("months", [0, 1])
def test_income_seen_in_too_few_months_is_ignored(months):
    thin = recommend(
        cashflow=CashflowSignals(observed_income=baht(30000), income_months=months)
    )
    assert thin.amount == recommend().amount


def test_no_measured_income_changes_nothing():
    assert recommend(cashflow=CashflowSignals(observed_income=0)).amount == recommend().amount


# A person can be solvent across the month and still bounce rent on the 25th
# because the savings transfer went out on the 20th.
def test_bills_still_to_come_are_left_in_the_account():
    # Balance 10,000; rent of 9,000 has not gone out yet.
    result = recommend(
        balance=baht(10000),
        month="2026-09",
        days_remaining=15,  # day 16 of a 30-day month
        expenses=[expense(9000, day=25)],
    )

    assert result.amount == baht(1000), "must leave the rent in the account"
    assert any("บิลที่ยังไม่ออก" in r.label for r in result.reasons)


def test_bills_already_paid_are_not_reserved_twice():
    paid = recommend(
        balance=baht(10000),
        month="2026-09",
        days_remaining=15,   # day 16
        expenses=[expense(9000, day=3)],   # went out on the 3rd
    )
    # Nothing left to reserve, so the ordinary surplus rule stands.
    assert paid.amount == baht(6900)


# Assuming an unknown bill has already been paid is the assumption that
# overdraws someone.
def test_a_cost_with_no_known_day_is_treated_as_still_to_come():
    result = recommend(
        balance=baht(10000), month="2026-09", days_remaining=15,
        expenses=[expense(9000, day=0)],
    )
    assert result.amount == baht(1000)


# An electricity bill averaging ฿1,200 with a third of variation can land at
# ฿1,600; reserving the average reserves too little in the months that matter.
def test_a_volatile_bill_is_reserved_for_with_headroom():
    flat = recommend(
        balance=baht(10000), month="2026-09", days_remaining=15,
        expenses=[expense(8000, day=25, cv=0.0)],
    )
    volatile = recommend(
        balance=baht(10000), month="2026-09", days_remaining=15,
        expenses=[expense(8000, day=25, cv=0.5)],
    )

    assert volatile.amount < flat.amount
    assert flat.amount == baht(2000)        # 10,000 - 8,000
    assert volatile.amount == baht(0)       # 10,000 - 12,000 -> nothing spare


def test_headroom_is_capped_so_one_odd_month_cannot_zero_everything():
    # cv of 4.0 would reserve 5x the bill without the cap.
    result = recommend(
        balance=baht(100000), month="2026-09", days_remaining=15,
        expenses=[expense(10000, day=25, cv=4.0)],
    )
    # Capped at 2x: 100,000 - 20,000 = 80,000 spare, well above the proposal.
    assert result.amount == baht(6900)


def test_a_comfortable_balance_is_not_capped():
    result = recommend(
        balance=baht(200000), month="2026-09", days_remaining=15,
        expenses=[expense(9000, day=25)],
    )
    assert result.amount == baht(6900)
    assert not any("บิลที่ยังไม่ออก" in r.label for r in result.reasons)


def test_no_expenses_sent_means_the_rule_does_not_fire():
    assert recommend(balance=baht(1000), expenses=[]).amount == baht(6900)


@pytest.mark.parametrize("days_remaining,expected_day", [(30, 1), (15, 16), (1, 30)])
def test_day_of_month_is_derived_from_days_remaining(days_remaining, expected_day):
    module = SavingsRecommendationModule()
    signals = mid_month(month="2026-09", days_remaining=days_remaining)
    assert module._day_of_month(signals) == expected_day


def test_day_of_month_survives_a_missing_or_broken_month():
    module = SavingsRecommendationModule()
    for bad in ("", "not-a-month", "2026-13-99"):
        day = module._day_of_month(mid_month(month=bad, days_remaining=15))
        assert 1 <= day <= 31


def test_endpoint_accepts_the_richer_signals(client):
    body = payload(
        balance=baht(10000),
        expenses=[{"amount": baht(9000), "dayOfMonth": 25, "amountCv": 0.0}],
        cashflow={"observedIncome": baht(45000), "incomeMonths": 4, "closingBalance": baht(20000)},
    )
    resp = client.post("/v1/savings/recommend", json=body)
    assert resp.status_code == 200, resp.text

    out = resp.json()
    assert out["recommendedAmount"] == baht(1000)
    assert any("บิลที่ยังไม่ออก" in r["label"] for r in out["reasons"])
