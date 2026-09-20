"""
Parser for column-laid-out statements: date, description, signed amount, balance.

This is the second statement format the service understands. The first, handled
by RecordParser, is the K PLUS layout: a Thai transaction-type word in each row
and a DD-MM-YY Buddhist-era date. This one is the shape most other banks export:

    DATE       DESCRIPTION                      AMOUNT (THB)   BALANCE (THB)
    03/05/2026 Direct Deposit - First Job Salary  +22,000.00      37,000.00
    05/28/2026 Apartment Rent (Shared)             -6,000.00      69,701.00

Three differences drive everything below:

  * **direction is a sign, not a word.** There is no ``ชำระเงิน`` to key on, so
    ``+``/``-`` decides whether money came in or went out.
  * **the date order is not given.** ``03/05/2026`` is March 5th or the 3rd of
    May depending on the bank, and guessing wrong silently reorders someone's
    financial history. It is detected from the whole document rather than
    assumed -- see ``detect_date_order``.
  * **the description is free text.** It becomes the merchant name, which is
    what the recurring detector groups by, so it is passed through unchanged
    rather than cleaned up: two spellings of the same payee must stay two
    spellings here and be reconciled downstream, not merged on a guess.
"""

import logging
import re
from datetime import date
from typing import List, Optional, Tuple

from .record_parser import ParseStats, RawTransaction, normalize_thai_text

logger = logging.getLogger(__name__)

# One transaction row: a date, free-text description, a signed amount (or a
# dash on balance-carried rows), and the balance afterwards.
ROW = re.compile(
    r"^(\d{1,2})[/-](\d{1,2})[/-](\d{4})"      # 03/05/2026
    r"\s+(.+?)"                                  # description
    r"\s+([+-][\d,]+\.\d{2}|[—–-])"             # +22,000.00 | -800.00 | —
    r"\s+[฿$]?([\d,]+\.\d{2})\s*$"              # 37,000.00
)

# A row whose amount is a dash carries the balance forward instead of moving
# money: the opening and closing lines of a statement.
NO_AMOUNT = {"—", "–", "-"}

# The transaction types the rest of the pipeline speaks. The detector excludes
# credits from recurring-expense analysis by matching this exact string, so the
# mapping has to produce it rather than anything more descriptive.
CREDIT = "รับโอนเงิน"
DEBIT = "ชำระเงิน"
OPENING = "ยอดยกมา"

# Rows that are structurally transactions but are really the statement's own
# bookkeeping. Matched on the description, case-insensitively.
BALANCE_ROWS = ("opening balance", "ending balance", "closing balance", "balance brought forward")


def looks_like_columnar(text: str) -> bool:
    """
    Whether this text is a statement in the columnar layout.

    Two rows is the threshold. One is a coincidence -- an invoice with a date
    and a total can produce a single match -- and requiring two costs nothing
    for a real statement, which has dozens.
    """
    matches = 0

    for line in text.split("\n"):
        if ROW.match(line.strip()):
            matches += 1
            if matches >= 2:
                return True

    return False


def detect_date_order(text: str) -> str:
    """
    Whether the rows read day-first or month-first, as "DMY" or "MDY".

    Decided by evidence, not convention: any field above 12 cannot be a month,
    which settles it outright. Many statements contain such a row -- a
    transaction after the 12th of any month -- and this one is read from the
    whole document, so a single unambiguous row resolves every ambiguous one.

    With no such row anywhere (a statement whose every transaction falls in the
    first twelve days), it falls back to day-first, which is what Thai banks
    print. The alternative is silently reordering someone's history on a guess,
    so this is the one place the fallback is documented rather than felt.
    """
    first_max = 0
    second_max = 0

    for line in text.split("\n"):
        match = ROW.match(line.strip())
        if not match:
            continue

        first_max = max(first_max, int(match.group(1)))
        second_max = max(second_max, int(match.group(2)))

    if second_max > 12:
        return "MDY"

    if first_max > 12:
        return "DMY"

    logger.warning(
        "Date order is ambiguous: no row has a field above 12. Assuming day-first."
    )

    return "DMY"


class ColumnarStatementParser:
    """Parse a columnar statement into the same RawTransactions RecordParser produces."""

    def __init__(self):
        # Accumulates across every statement handed to one parser, matching
        # RecordParser so the pipeline can hold either without caring which.
        self.stats = ParseStats()

    def parse_statement_text(
        self,
        raw_text: str,
        statement_month: date,
    ) -> List[RawTransaction]:
        """Parse statement text into transaction records."""
        text = normalize_thai_text(raw_text)
        order = detect_date_order(text)

        transactions: List[RawTransaction] = []

        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue

            match = ROW.match(line)
            if not match:
                continue  # headers, footers, notes -- not a claim to be a row

            self.stats.attempted += 1

            try:
                transaction = self._to_transaction(match, line, order, statement_month)
            except (ValueError, TypeError) as e:
                logger.warning("Could not read row %r: %s", line[:100], e)
                self.stats.failed += 1
                continue

            if transaction is None:
                # A balance-carried row. Recognised and deliberately dropped,
                # which is success, so it is counted apart from failures.
                self.stats.opening_balance += 1
                continue

            transactions.append(transaction)
            self.stats.parsed += 1

        logger.info(
            "Parsed %d transactions from columnar statement (%s, success rate %.0f%%)",
            len(transactions), order, self.stats.success_rate * 100,
        )

        return transactions

    def _to_transaction(
        self,
        match: re.Match,
        line: str,
        order: str,
        statement_month: date,
    ) -> Optional[RawTransaction]:
        """Build one transaction, or None for a balance-carried row."""
        first, second, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        description = match.group(4).strip()
        raw_amount = match.group(5).strip()
        balance = _money(match.group(6))

        day, month = (second, first) if order == "MDY" else (first, second)
        when = date(year, month, day)

        if raw_amount in NO_AMOUNT or _is_balance_row(description):
            return None

        amount = _money(raw_amount)
        credit = amount > 0

        return RawTransaction(
            date=when,
            time=None,
            transaction_type=CREDIT if credit else DEBIT,
            # The pipeline works in magnitudes; direction lives in the type.
            amount=abs(amount),
            balance_after=balance,
            channel="",
            ref_no=None,
            raw_detail_text=line,
            recipient_name=None,
            recipient_account_masked=None,
            # The description is the only identity a payee has in this format,
            # and it is what the recurring detector groups by.
            merchant_name=description,
            is_promptpay=False,
            source_statement_month=statement_month,
        )


def _money(text: str) -> float:
    """Read a formatted amount: strips separators, currency marks, and spaces."""
    cleaned = text.replace(",", "").replace("฿", "").replace("$", "").strip()

    return float(cleaned)


def _is_balance_row(description: str) -> bool:
    lowered = description.lower()

    return any(marker in lowered for marker in BALANCE_ROWS)
