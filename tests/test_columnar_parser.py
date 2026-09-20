from datetime import date

import pytest

from src.parser.columnar_parser import (
    ColumnarStatementParser,
    detect_date_order,
    looks_like_columnar,
)
from src.parser.pdf_extractor import PDFTextExtractor
from src.parser.record_parser import RecordParser
from src.pipeline.stateless_pipeline import _select_parser, analyze, analyze_from_text
from tests.conftest import FIXTURES, SYNTHETIC_STATEMENT

COLUMNAR_STATEMENT = FIXTURES / "columnar_statement.txt"
COLUMNAR_PDF = FIXTURES / "columnar_statement.pdf"

MONTH = date(2026, 3, 1)


@pytest.fixture
def columnar_text() -> str:
    return COLUMNAR_STATEMENT.read_text(encoding="utf-8")


def rows(*lines: str) -> str:
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# format detection
# ---------------------------------------------------------------------------

def test_recognises_a_columnar_statement(columnar_text):
    assert looks_like_columnar(columnar_text) is True


def test_does_not_claim_a_kplus_statement(synthetic_statement_text):
    assert looks_like_columnar(synthetic_statement_text) is False


# One row is a coincidence -- an invoice has a date and a total too.
def test_a_single_matching_row_is_not_a_statement():
    assert looks_like_columnar("03/05/2026 Total due +1,234.00 1,234.00") is False


def test_the_pipeline_picks_the_parser_from_the_text(columnar_text, synthetic_statement_text):
    assert isinstance(_select_parser([columnar_text]), ColumnarStatementParser)
    assert isinstance(_select_parser([synthetic_statement_text]), RecordParser)
    # Nothing recognisable falls back to the original parser and its diagnostics.
    assert isinstance(_select_parser(["not a statement at all"]), RecordParser)


# ---------------------------------------------------------------------------
# date order
# ---------------------------------------------------------------------------

# 03/05/2026 is March 5th or the 3rd of May depending on the bank, and guessing
# wrong silently reorders someone's financial history.
def test_date_order_is_settled_by_a_field_above_twelve():
    assert detect_date_order(rows(
        "03/05/2026 Salary +22,000.00 37,000.00",
        "05/28/2026 Rent -6,000.00 31,000.00",      # 28 cannot be a month
    )) == "MDY"

    assert detect_date_order(rows(
        "03/05/2026 Salary +22,000.00 37,000.00",
        "28/05/2026 Rent -6,000.00 31,000.00",      # 28 cannot be a month
    )) == "DMY"


def test_a_single_unambiguous_row_settles_every_other_row():
    parser = ColumnarStatementParser()
    txs = parser.parse_statement_text(rows(
        "03/05/2026 Salary +22,000.00 37,000.00",   # ambiguous on its own
        "05/28/2026 Rent -6,000.00 31,000.00",      # proves month-first
    ), MONTH)

    assert [t.date for t in txs] == [date(2026, 3, 5), date(2026, 5, 28)]


def test_an_entirely_ambiguous_statement_falls_back_to_day_first():
    # Every transaction in the first twelve days, so nothing settles it.
    assert detect_date_order(rows(
        "03/05/2026 Salary +22,000.00 37,000.00",
        "04/06/2026 Rent -6,000.00 31,000.00",
    )) == "DMY"


def test_the_real_statement_is_month_first(columnar_text):
    assert detect_date_order(columnar_text) == "MDY"


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------

def test_the_sign_decides_direction():
    txs = ColumnarStatementParser().parse_statement_text(rows(
        "03/05/2026 Direct Deposit - Salary +22,000.00 37,000.00",
        "03/10/2026 BTS/MRT Rabbit Card Top-up -800.00 36,200.00",
        "05/28/2026 Rent -6,000.00 30,200.00",
    ), MONTH)

    credit, debit = txs[0], txs[1]

    # The exact string the detector matches on to exclude income.
    assert credit.transaction_type == "รับโอนเงิน"
    assert debit.transaction_type == "ชำระเงิน"

    # Magnitudes only: direction lives in the type, not the sign.
    assert credit.amount == 22000.0
    assert debit.amount == 800.0


def test_the_description_becomes_the_payee():
    txs = ColumnarStatementParser().parse_statement_text(rows(
        "03/28/2026 Apartment Rent (Shared) -6,000.00 30,200.00",
        "04/28/2026 Apartment Rent (Shared) -6,000.00 24,200.00",
    ), MONTH)

    # Identical descriptions must produce identical payees, or a recurring
    # expense is split into one payee per month and never detected.
    assert txs[0].merchant_name == txs[1].merchant_name == "Apartment Rent (Shared)"


def test_balances_and_separators_are_read():
    tx = ColumnarStatementParser().parse_statement_text(
        "03/05/2026 Salary +22,000.00 ฿1,037,000.50", MONTH
    )[0]

    assert tx.balance_after == 1037000.50


# Recognised and dropped on purpose: these carry a balance rather than move
# money, so they are counted apart from failures.
@pytest.mark.parametrize("line", [
    "03/01/2026 Opening Balance — 15,000.00",
    "08/31/2026 Ending Balance — ฿125,901.00",
    "03/01/2026 Balance Brought Forward - 15,000.00",
])
def test_balance_rows_are_dropped_without_counting_as_failures(line):
    parser = ColumnarStatementParser()
    txs = parser.parse_statement_text(line, MONTH)

    assert txs == []
    assert parser.stats.failed == 0
    assert parser.stats.opening_balance == 1
    assert parser.stats.success_rate == 1.0


def test_headers_footers_and_notes_are_ignored():
    parser = ColumnarStatementParser()
    txs = parser.parse_statement_text(rows(
        "BANGKOK COMMERCIAL BANK ACCOUNT STATEMENT",
        "DATE DESCRIPTION AMOUNT (THB) BALANCE (THB)",
        "03/05/2026 Salary +22,000.00 37,000.00",
        "Important Notes:",
        "Please report any discrepancies within 30 days.",
    ), MONTH)

    assert len(txs) == 1
    # Lines that never claimed to be rows are not failures.
    assert parser.stats.attempted == 1
    assert parser.stats.success_rate == 1.0


def test_an_impossible_date_is_a_failure_not_a_crash():
    parser = ColumnarStatementParser()
    txs = parser.parse_statement_text("13/45/2026 Salary +22,000.00 37,000.00", MONTH)

    assert txs == []
    assert parser.stats.failed == 1
    assert parser.stats.success_rate < 1.0


def test_stats_accumulate_across_statements(columnar_text):
    parser = ColumnarStatementParser()
    parser.parse_statement_text(columnar_text, MONTH)
    parser.parse_statement_text(columnar_text, MONTH)

    assert parser.stats.parsed == 36


# ---------------------------------------------------------------------------
# the real statement, end to end
# ---------------------------------------------------------------------------

def test_the_real_statement_parses_completely(columnar_text):
    parser = ColumnarStatementParser()
    txs = parser.parse_statement_text(columnar_text, MONTH)

    assert len(txs) == 18
    assert parser.stats.opening_balance == 2      # opening and ending rows
    assert parser.stats.failed == 0
    assert parser.stats.success_rate == 1.0

    assert min(t.date for t in txs) == date(2026, 3, 5)
    assert max(t.date for t in txs) == date(2026, 8, 18)


def test_the_real_pdf_runs_through_the_pipeline():
    result = analyze(pdf_files=[COLUMNAR_PDF.read_bytes()], current_salary=22000)

    assert result.parsed_transaction_count == 18
    assert result.data_months_available == 6
    assert result.parse_success_rate == 1.0

    # The cash-flow signals the caller cannot derive for itself.
    assert result.closing_balance == 125901.0
    assert result.observed_income == 22500.0      # six salary credits, averaged
    assert result.income_months == 6
    assert result.payday_day_of_month == 5
    assert result.avg_daily_spend > 0


# This statement has eleven payees, ten of which appear exactly once, and rent
# appears in two of six months. There is genuinely nothing here that recurs, and
# reporting none is the correct answer rather than a parsing failure -- which is
# why parse_success_rate above is 1.0 while this is empty.
def test_a_statement_with_no_repeating_payees_reports_none(columnar_text):
    result = analyze_from_text([columnar_text], current_salary=22000)

    assert result["parsed_transaction_count"] == 18
    assert result["recurring_expenses"] == []
    assert result["total_recurring"] == 0.0


# Both formats must keep working; picking one must not break the other.
def test_the_kplus_format_still_parses():
    result = analyze_from_text(
        [SYNTHETIC_STATEMENT.read_text(encoding="utf-8")], current_salary=30000
    )

    assert result["parsed_transaction_count"] == 14
    assert {e["recipient_key"] for e in result["recurring_expenses"]} == {
        "MERCHANT:NETFLIX", "MERCHANT:ร้านกาแฟ", "ACCOUNT:X2660"
    }
