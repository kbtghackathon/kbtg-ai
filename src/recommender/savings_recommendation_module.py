"""
Savings recommendation module.

Answers "how much should this person save this month" from the figures the
caller already holds. It is a pure function of its inputs -- no I/O, no state,
no database -- so the whole of it is testable at the table-driven level that
money deserves.

**Every amount in this module is satang (1 baht = 100 satang), as integers.**

That differs from the rest of this service, which speaks float baht, and the
difference is deliberate: this number becomes a transfer between two real
accounts. float64 cannot hold 399.00 exactly, and a savings feature that loses
a satang per month to binary rounding is a savings feature with a reconciliation
bug. The analysis endpoints keep their float contract; this one does not share it.

## What this module does not decide

The caller's own limits -- minimum, maximum, and the balance that must always
remain -- are enforced by the caller after this returns. They are passed in so
the recommendation can aim inside them, not so it can enforce them. A model that
starts returning wild numbers can make a saving smaller or skip a month, and
nothing worse. That separation is the whole safety argument and it does not move
into this file.
"""

import calendar
import math
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

from src.config.savings_config import SavingsConfig

# Bumped whenever the arithmetic below changes, so a stored recommendation can
# be traced back to the logic that produced it.
MODEL_VERSION = "savings-rule-v1"


@dataclass
class ExpenseSignal:
    """
    One committed monthly cost, with the analyser's view of it.

    The total of these is what `fixed_costs` already carries. They are sent
    individually because the total hides the two things that matter for
    deciding how much can safely leave the account: **when** each one goes out,
    and **how much it moves** from month to month.
    """

    amount: int = 0
    # Day of the month it typically lands. 0 means undetermined, and is treated
    # as still to come -- the cautious reading.
    day_of_month: int = 0
    # Coefficient of variation of the amount. 0 is a flat bill.
    amount_cv: float = 0.0
    recurring_type: str = ""
    recipient_key: str = ""
    label_th: str = ""


@dataclass
class CashflowSignals:
    """What the statement said about the account, as opposed to what is committed."""

    closing_balance: int = 0
    observed_income: int = 0
    income_months: int = 0
    payday_day_of_month: int = 0
    variable_spend_monthly: int = 0
    avg_daily_spend: int = 0


@dataclass
class SavingsSignals:
    """
    One month of a person's finances, as the caller sees them.

    Amounts are satang. The caller derives these from its own ledger plus the
    statement analysis this service produced at onboarding.
    """

    income: int = 0
    fixed_costs: int = 0
    spent_so_far: int = 0
    avg_daily_spend: int = 0
    days_remaining: int = 1
    balance: int = 0

    # The caller's guardrails. Carried so the recommendation can aim inside
    # them; enforced by the caller regardless of what is returned here.
    min_per_month: int = 0
    max_per_month: int = 0
    buffer_balance: int = 0
    aggressiveness: str = "BALANCED"

    # How much statement this month's fixed costs were derived from.
    # data_months of 0 means the caller has no analysis on file and derived the
    # costs from its own transaction history instead.
    data_months: int = 0
    parse_success_rate: float = 1.0

    # The committed costs broken out, and what the statement said about the
    # account. Both empty for a caller that has no analysis on file, in which
    # case the rules that use them simply do not fire.
    expenses: List[ExpenseSignal] = field(default_factory=list)
    cashflow: CashflowSignals = field(default_factory=CashflowSignals)
    # Month being planned, "YYYY-MM". Used only to work out today's date from
    # days_remaining; falls back to the real today when absent.
    month: str = ""


@dataclass
class SavingsReason:
    """One line of the decision trace, rendered in the app as the explanation."""

    label: str
    amount: int
    note: str = ""


@dataclass
class SavingsRecommendation:
    """
    What to save, and why.

    `reasons` is not decoration. The person is about to let software move part
    of their salary every month, and the only evidence they have that it
    understood their situation is whether this list reads like their situation.
    A recommendation with no reasoning is one people switch off.
    """

    amount: int = 0
    confidence: float = 0.0
    model_version: str = MODEL_VERSION
    reasons: List[SavingsReason] = field(default_factory=list)

    # skip says the month should be left alone for a cash-flow reason. It is
    # distinct from recommending zero: zero reads as "the model had nothing to
    # say", which the caller treats as a failure and falls back from.
    skip: bool = False
    skip_reason: str = ""


class SavingsRecommendationModule:
    """
    Computes the monthly savings recommendation.

    The shape of the calculation is the argument for it::

        surplus  = income - fixed costs - spent so far - the rest of the month
        proposed = surplus x aggressiveness x data quality

    **It reserves for the rest of the month.** On the 1st almost nothing has
    been spent, so income-minus-costs reports a fortune; sweep that into a
    savings pocket and the person then lives the next thirty days as they always
    do and ends the month short. Projecting the remaining days at the rate
    already observed is the difference between a number that looks generous and
    one that survives to the 30th.

    **It saves less when it has read less.** Four months of statement is a
    weaker basis than six, and a fixed cost that was never seen is one this
    surplus has not subtracted. The failure that avoids is specific: an annual
    insurance premium landing in a month that has already been swept clean.
    """

    def __init__(self, config: Optional[SavingsConfig] = None):
        self.config = config or SavingsConfig()

    def recommend(self, signals: SavingsSignals) -> SavingsRecommendation:
        """Produce the recommendation for one month."""
        days = max(1, signals.days_remaining)

        income, income_note = self._planning_income(signals)
        after_fixed = income - signals.fixed_costs
        after_spent = after_fixed - signals.spent_so_far
        reserved = signals.avg_daily_spend * days
        surplus = after_spent - reserved

        reasons = [
            SavingsReason(
                label="เงินเดือนหักรายจ่ายประจำ",
                amount=after_fixed,
                note=income_note or self._fixed_cost_note(signals),
            )
        ]

        if signals.spent_so_far > 0:
            reasons.append(
                SavingsReason(
                    label="หักที่ใช้ไปแล้วเดือนนี้",
                    amount=after_spent,
                    note=f"ใช้ไป {_baht(signals.spent_so_far)}",
                )
            )

        if reserved > 0:
            reasons.append(
                SavingsReason(
                    label=f"กันไว้ใช้อีก {days} วันจนสิ้นเดือน",
                    amount=surplus,
                    note=f"จากที่ใช้วันละประมาณ {_baht(signals.avg_daily_spend)}",
                )
            )

        quality = self.data_quality(signals)

        # Nothing left once the rest of the month is paid for. Saying so is a
        # different answer from "your balance is too low": this person may have
        # plenty in the account and still owe every baht of it to the month.
        if surplus <= 0:
            return SavingsRecommendation(
                amount=0,
                confidence=quality,
                reasons=reasons,
                skip=True,
                skip_reason=(
                    "กันเงินไว้ใช้จนสิ้นเดือนแล้วไม่เหลือพอออม "
                    "AI จึงพักการออมเดือนนี้ไว้ก่อน"
                ),
            )

        ratio = self.config.ratio_for(signals.aggressiveness)
        share = int(surplus * ratio)

        reasons.append(
            SavingsReason(
                label=f"ออม {ratio * 100:.0f}% ของส่วนที่เหลือ",
                amount=share,
                note=_aggressiveness_note(signals.aggressiveness),
            )
        )

        proposed = int(share * quality)

        if quality < 1:
            reasons.append(
                SavingsReason(
                    label=f"ลดลงตามความครบของข้อมูล {quality * 100:.0f}%",
                    amount=proposed,
                    note=self._quality_note(signals),
                )
            )

        proposed = self._cap_for_upcoming_bills(signals, proposed, reasons)

        return SavingsRecommendation(
            amount=max(0, proposed),
            confidence=quality,
            reasons=reasons,
        )

    def _planning_income(self, signals: SavingsSignals) -> tuple:
        """
        The income to plan against, and a note when it is not the declared one.

        The caller declares a salary; the analyser *measured* what actually
        arrived. When the measurement is lower, it wins -- someone whose
        statement shows ฿30,000 landing against a declared ฿45,000 is either
        between jobs, paid partly in cash, or was optimistic, and in all three
        cases planning against the larger number over-saves them into an
        overdraft.

        A measurement that is *higher* does not win. Extra money that showed up
        once is not a raise, and treating it as one would raise the baseline
        permanently off a single good month.

        Neither does a measurement seen in only one month. A statement window
        that happens to catch a single credit, or to cut across paydays, is not
        evidence about someone's salary, and overriding a figure the person
        stated about themselves needs better than that.
        """
        observed = signals.cashflow.observed_income

        if observed <= 0 or observed >= signals.income:
            return signals.income, ""

        if signals.cashflow.income_months < self.config.min_income_months:
            return signals.income, ""

        return observed, (
            f"ใช้รายได้ที่เห็นจริงใน statement {_baht(observed)} "
            f"แทนที่แจ้งไว้ {_baht(signals.income)}"
        )

    def _cap_for_upcoming_bills(
        self,
        signals: SavingsSignals,
        proposed: int,
        reasons: List[SavingsReason],
    ) -> int:
        """
        Keep enough in the account for the bills that have not gone out yet.

        The surplus arithmetic above is a whole-month view: it is right about
        how much of the month is spare, and says nothing about *when*. A person
        can be perfectly solvent across the month and still bounce a rent
        payment on the 25th because the savings transfer went out on the 20th.

        So the bills still ahead are totalled and left in the account. A bill
        that varies is reserved for at more than its typical amount -- an
        electricity bill averaging ฿1,200 with a third of variation can land at
        ฿1,600, and reserving the average is reserving too little exactly in
        the months that need it most.

        Costs with no known day are counted as still to come. Assuming an
        unknown bill has already been paid is the assumption that overdraws
        someone.
        """
        if proposed <= 0 or not signals.expenses:
            return proposed

        today = self._day_of_month(signals)

        upcoming = 0
        for expense in signals.expenses:
            if expense.day_of_month and expense.day_of_month < today:
                continue  # already gone out this month

            headroom = min(max(expense.amount_cv, 0.0), 1.0)
            upcoming += int(expense.amount * (1 + headroom))

        if upcoming <= 0:
            return proposed

        spare = signals.balance - upcoming
        if spare >= proposed:
            return proposed

        capped = max(0, spare)

        reasons.append(
            SavingsReason(
                label="กันไว้จ่ายบิลที่ยังไม่ออกเดือนนี้",
                amount=capped,
                note=f"ยังต้องจ่ายอีกประมาณ {_baht(upcoming)} ก่อนสิ้นเดือน",
            )
        )

        return capped

    @staticmethod
    def _day_of_month(signals: SavingsSignals) -> int:
        """
        Today's day of the month, derived from how much of it is left.

        Taken from days_remaining rather than the clock so the service stays a
        pure function of its request -- two identical requests give identical
        answers, which is what makes the arithmetic testable and a cached
        result meaningful.
        """
        try:
            year, month = (int(part) for part in signals.month.split("-"))
            days_in_month = calendar.monthrange(year, month)[1]
        except (ValueError, AttributeError):
            today = date.today()
            days_in_month = calendar.monthrange(today.year, today.month)[1]

        day = days_in_month - max(0, signals.days_remaining) + 1

        return min(max(day, 1), days_in_month)

    def data_quality(self, signals: SavingsSignals) -> float:
        """
        How much of this person's financial life the fixed-cost figure was
        derived from, as a multiplier bounded by ``min_data_quality`` and 1.0.

        Two inputs, both meaning the same thing -- how much did we get to read:
        months of statement, and the share of lines in them that parsed.

        Per-expense confidence is deliberately absent. A cost seen in half the
        months is reserved for at its full amount in ``fixed_costs`` already,
        which errs toward caution; discounting the proposal for it as well would
        penalise the same uncertainty twice in the same direction for no
        additional safety.

        ``data_months`` of 0 scores 1.0. It means the caller has no statement on
        file and derived the costs from its own ledger -- which is not less
        trustworthy than a PDF, it is the same account read from the source.
        """
        cfg = self.config

        if signals.data_months <= 0:
            return 1.0

        months = min(signals.data_months, cfg.max_analysis_months)
        months_factor = cfg.months_quality_floor + (
            (1.0 - cfg.months_quality_floor) * months / cfg.max_analysis_months
        )

        rate = signals.parse_success_rate
        # A service reporting nonsense about its own parse rate is not evidence
        # about this person's statements, so it is read as a clean parse.
        if rate is None or math.isnan(rate) or rate < 0 or rate > 1:
            rate = 1.0

        parse_factor = cfg.parse_quality_floor + (1.0 - cfg.parse_quality_floor) * rate

        return max(cfg.min_data_quality, min(1.0, months_factor * parse_factor))

    def _fixed_cost_note(self, signals: SavingsSignals) -> str:
        if signals.data_months <= 0:
            return f"รายจ่ายประจำ {_baht(signals.fixed_costs)} จากประวัติการใช้จ่าย"

        return (
            f"รายจ่ายประจำ {_baht(signals.fixed_costs)} "
            f"ที่ AI อ่านจาก statement {signals.data_months} เดือน"
        )

    def _quality_note(self, signals: SavingsSignals) -> str:
        """Names the weaker of the two factors, so the step reads as an
        explanation rather than an unexplained haircut."""
        rate = signals.parse_success_rate
        months = signals.data_months
        cfg = self.config

        if rate is not None and 0 <= rate < 1:
            missed = (1 - rate) * 100
            if months < cfg.max_analysis_months:
                return (
                    f"statement มี {months} เดือน และอ่านไม่ออก {missed:.0f}% ของรายการ"
                )
            return f"อ่านไม่ออก {missed:.0f}% ของรายการใน statement"

        return (
            f"statement มี {months} เดือน จาก {cfg.max_analysis_months} — "
            "อาจมีรายจ่ายที่ AI ยังไม่เคยเห็น"
        )


def _baht(satang: int) -> str:
    """Renders satang as baht for a note a person will read."""
    return f"฿{satang / 100:,.2f}"


def _aggressiveness_note(aggressiveness: str) -> str:
    return {
        "SAFE": "โหมดปลอดภัย",
        "BOLD": "โหมดดุดัน",
    }.get((aggressiveness or "").strip().upper(), "โหมดสมดุล")
