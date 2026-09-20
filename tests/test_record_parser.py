from datetime import date

import pytest

from src.parser.record_parser import RecordParser, normalize_thai_text
from tests.conftest import REAL_STATEMENT

STATEMENT_MONTH = date(2026, 1, 1)


@pytest.fixture
def parser():
    return RecordParser()


def test_amount_regex_handles_with_and_without_thousands_separator(parser):
    text = "1500.00 20,000.00 266.50 01-03-26 10:30 Ref X8955"
    assert parser._extract_amounts(text) == [1500.0, 20000.0, 266.5]


def test_opening_balance_is_parsed_with_zero_amount(parser):
    tx = parser._parse_single_record("01-01-26 ยอดยกมา 5,000.00", STATEMENT_MONTH, None)
    assert tx is not None
    assert tx.transaction_type == "ยอดยกมา"
    assert tx.amount == 0.0
    assert tx.balance_after == 5000.0


def test_opening_balance_seeds_balance_validation(parser, caplog):
    text = (
        "01-01-26 ยอดยกมา 5,000.00\n"
        "05-01-26 09:00 ชำระเงิน 399.00 4,601.00 K PLUS เพื่อชำระ Ref X1001 NETFLIX\n"
    )
    txs = parser.parse_statement_text(text, STATEMENT_MONTH)
    assert [t.transaction_type for t in txs] == ["ชำระเงิน"]  # opening balance excluded from output
    assert "Balance validation failed" not in caplog.text


def test_opening_balance_enables_balance_mismatch_warning(parser, caplog):
    # Only possible when previous_balance was seeded from the opening balance line
    text = (
        "01-01-26 ยอดยกมา 5,000.00\n"
        "05-01-26 09:00 ชำระเงิน 399.00 9,999.00 K PLUS เพื่อชำระ Ref X1001 NETFLIX\n"
    )
    with caplog.at_level("WARNING"):
        txs = parser.parse_statement_text(text, STATEMENT_MONTH)
    assert len(txs) == 1  # a mismatch warns but does not drop the record
    assert "Balance validation failed" in caplog.text


def test_both_thai_unicode_spellings_parse_identically(parser):
    sara_am = "05-01-26 09:00 ชำระเงิน 399.00 4,601.00 K PLUS เพื่อชำระ Ref X1001 NETFLIX"
    nikhahit = sara_am.replace("ำ", "ํา")
    assert sara_am != nikhahit  # sanity: the two spellings really differ
    a = parser.parse_statement_text(sara_am, STATEMENT_MONTH)[0]
    b = parser.parse_statement_text(nikhahit, STATEMENT_MONTH)[0]
    assert (a.transaction_type, a.merchant_name, a.amount) == ("ชำระเงิน", "NETFLIX", 399.0)
    assert (b.transaction_type, b.merchant_name, b.amount) == (a.transaction_type, a.merchant_name, a.amount)


def test_normalize_thai_text_folds_nikhahit_sara_aa():
    assert normalize_thai_text("ชําระ") == "ชำระ"


def test_qr_payment_ref_is_not_used_as_account(parser):
    text = "12-01-26 12:30 ชำระเงิน 85.00 19,516.00 EDC/K SHOP/MYQR เพื่อชำระ Ref X2001 ร้านกาแฟ (ชื่อบัญชี: นาย กาแฟ ดี)"
    tx = parser.parse_statement_text(text, STATEMENT_MONTH)[0]
    assert tx.ref_no == "X2001"
    assert tx.recipient_account_masked is None
    assert tx.recipient_name == "นาย กาแฟ ดี"
    assert tx.merchant_name == "ร้านกาแฟ"


def test_transfer_recipient_and_promptpay_flag(parser):
    text = "20-02-26 18:00 โอนเงิน 6,500.00 34,532.00 K PLUS โอนไป พร้อมเพย์ X2660 นาย เจ้าของ ห้อง++"
    tx = parser.parse_statement_text(text, STATEMENT_MONTH)[0]
    assert tx.transaction_type == "โอนเงิน"
    assert tx.recipient_account_masked == "X2660"
    assert tx.recipient_name == "นาย เจ้าของ ห้อง"
    assert tx.is_promptpay is True
    assert tx.amount == 6500.0


def test_synthetic_statement_parses_all_records(parser, synthetic_statement_text):
    txs = parser.parse_statement_text(synthetic_statement_text, STATEMENT_MONTH)
    assert len(txs) == 14  # every dated line except the opening balance
    assert all(t.transaction_type != "ยอดยกมา" for t in txs)
    assert {(t.date.year, t.date.month) for t in txs} == {(2026, 1), (2026, 2), (2026, 3), (2026, 4)}


@pytest.mark.skipif(not REAL_STATEMENT.exists(), reason="drop a real K PLUS statement at tests/fixtures/kplus_sample.txt")
def test_real_statement_parses_without_unknown_keys(parser):
    from uuid import uuid4
    from src.normalizer.transaction_normalizer import TransactionNormalizer

    txs = parser.parse_statement_text(REAL_STATEMENT.read_text(encoding="utf-8"), STATEMENT_MONTH)
    assert txs, "no transactions parsed from the real statement"
    keys = [n.recipient_key for n in TransactionNormalizer().normalize_transactions(txs, uuid4())]
    unknown = [k for k in keys if k.startswith("UNKNOWN:")]
    assert not unknown, f"{len(unknown)}/{len(keys)} transactions fell back to hash keys"


def test_indented_layout_lines_are_parsed(parser):
    # pdfplumber layout=True indents every line; the record must still be recognised
    text = (
        "        01-01-26 ยอดยกมา 5,000.00        \n"
        "        05-01-26 09:00 ชำระเงิน 399.00 4,601.00 K PLUS เพื่อชำระ Ref X1001 NETFLIX        \n"
    )
    txs = parser.parse_statement_text(text, STATEMENT_MONTH)
    assert len(txs) == 1
    assert txs[0].merchant_name == "NETFLIX"
