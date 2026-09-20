from datetime import date

from src.pipeline.stateless_pipeline import analyze_from_text

ONE_OFFS = """01-03-26 ยอดยกมา 10,000.00
01-03-26 10:00 ชำระเงิน 1,200.00 8,800.00 K PLUS เพื่อชำระ Ref X1111 SOME RANDOM SHOP
15-03-26 11:00 โอนเงิน 500.00 8,300.00 K PLUS โอนไป X2660 นาย ทดสอบ ระบบ++
"""


def test_one_off_transactions_are_not_reported_as_recurring():
    result = analyze_from_text([ONE_OFFS], current_salary=30000)
    assert result["recurring_expenses"] == []
    assert result["total_recurring"] == 0.0
    assert result["remaining_after_reserve"] == 30000
    assert result["data_months_available"] == 1
    assert result["parsed_transaction_count"] == 2
    assert result["data_completeness_warning"]  # < 6 months


def test_months_are_counted_from_transaction_dates(synthetic_statement_text):
    result = analyze_from_text([synthetic_statement_text], current_salary=30000)
    assert result["data_months_available"] == 4


def test_synthetic_statement_detects_only_true_monthly_payees(synthetic_statement_text):
    result = analyze_from_text([synthetic_statement_text], current_salary=30000)
    by_key = {e["recipient_key"]: e for e in result["recurring_expenses"]}

    assert set(by_key) == {"MERCHANT:NETFLIX", "MERCHANT:ร้านกาแฟ", "ACCOUNT:X2660"}
    assert by_key["MERCHANT:NETFLIX"]["category"] == "subscription"
    assert by_key["MERCHANT:NETFLIX"]["amount"] == 399.0
    assert by_key["ACCOUNT:X2660"]["amount"] == 6500.0
    assert result["total_recurring"] == 399.0 + 85.0 + 6500.0

    # unknown payees are surfaced for labelling; the one-off shop and salary are not
    pending = {p["recipient_key"] for p in result["pending_user_labels"]}
    assert pending == {"MERCHANT:ร้านกาแฟ", "ACCOUNT:X2660"}


def test_existing_user_label_overrides_pending(synthetic_statement_text):
    labels = [{"recipient_key": "ACCOUNT:X2660", "category": "rent", "category_label_th": "ค่าเช่า"}]
    result = analyze_from_text([synthetic_statement_text], current_salary=30000, existing_user_labels=labels)
    rent = next(e for e in result["recurring_expenses"] if e["recipient_key"] == "ACCOUNT:X2660")
    assert rent["category"] == "rent"
    assert all(p["recipient_key"] != "ACCOUNT:X2660" for p in result["pending_user_labels"])


def test_multiple_statements_are_merged(synthetic_statement_text):
    jan = "\n".join(l for l in synthetic_statement_text.splitlines() if "-01-26" in l)
    feb = "\n".join(l for l in synthetic_statement_text.splitlines() if "-02-26" in l)
    result = analyze_from_text([jan, feb], current_salary=30000)
    assert result["data_months_available"] == 2
    assert result["parsed_transaction_count"] == 8


def test_statement_months_override_length_mismatch_raises():
    import pytest
    with pytest.raises(ValueError):
        analyze_from_text([ONE_OFFS], 30000, statement_months=[date(2026, 1, 1), date(2026, 2, 1)])


def test_unparseable_text_returns_empty_response():
    result = analyze_from_text(["nothing to see here"], current_salary=1000)
    assert result["recurring_expenses"] == []
    assert result["parsed_transaction_count"] == 0
    assert result["data_months_available"] == 0


def test_pdf_path_matches_text_path():
    from src.pipeline.stateless_pipeline import analyze
    from tests.conftest import FIXTURES

    pdf_bytes = (FIXTURES / "kplus_synthetic.pdf").read_bytes()
    text = (FIXTURES / "kplus_synthetic.txt").read_text(encoding="utf-8")

    from_pdf = analyze([pdf_bytes], current_salary=30000)
    from_text = analyze_from_text([text], current_salary=30000)

    assert from_pdf.parsed_transaction_count == from_text["parsed_transaction_count"] == 14
    assert from_pdf.data_months_available == 4
    assert {e["recipient_key"] for e in from_pdf.recurring_expenses} == {
        e["recipient_key"] for e in from_text["recurring_expenses"]
    }
