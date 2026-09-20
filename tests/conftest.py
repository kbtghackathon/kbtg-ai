"""Shared fixtures and synthetic K PLUS statement builders."""

from datetime import date
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

import pytest

from src.categorizer.categorization_module import CategorizationModule, CategorizedTransaction, CategoryGroup
from src.normalizer.transaction_normalizer import NormalizedTransaction
from src.parser.record_parser import RawTransaction

FIXTURES = Path(__file__).parent / "fixtures"
SYNTHETIC_STATEMENT = FIXTURES / "kplus_synthetic.txt"
REAL_STATEMENT = FIXTURES / "kplus_sample.txt"


@pytest.fixture(autouse=True)
def fresh_merchant_cache():
    """Each test starts with a cold merchant dictionary cache."""
    CategorizationModule.invalidate_cache()
    yield
    CategorizationModule.invalidate_cache()


@pytest.fixture
def synthetic_statement_text() -> str:
    return SYNTHETIC_STATEMENT.read_text(encoding="utf-8")


def make_raw_transaction(
    tx_date: date,
    amount: float,
    merchant_name: Optional[str] = "SHOP",
    transaction_type: str = "ชำระเงิน",
    recipient_account_masked: Optional[str] = None,
) -> RawTransaction:
    return RawTransaction(
        date=tx_date,
        time=None,
        transaction_type=transaction_type,
        amount=amount,
        balance_after=0.0,
        channel="K PLUS",
        ref_no=None,
        raw_detail_text=f"{tx_date.isoformat()} {transaction_type} {amount}",
        recipient_name=None,
        recipient_account_masked=recipient_account_masked,
        merchant_name=merchant_name,
        is_promptpay=False,
        source_statement_month=tx_date.replace(day=1),
    )


def make_categorized(
    dates: List[date],
    amounts: List[float],
    recipient_key: str = "MERCHANT:SHOP",
    category: Optional[str] = None,
) -> List[CategorizedTransaction]:
    """Build a group of categorized transactions sharing one recipient key."""
    user_id = uuid4()
    out = []
    for d, a in zip(dates, amounts):
        raw = make_raw_transaction(d, a)
        norm = NormalizedTransaction(
            raw_transaction=raw,
            recipient_key=recipient_key,
            normalized_merchant_name="SHOP",
            normalized_recipient_name=None,
            user_id=user_id,
        )
        out.append(
            CategorizedTransaction(
                normalized_transaction=norm,
                category=category,
                category_label_th=category,
                category_group=CategoryGroup.GROUP_A if category else CategoryGroup.GROUP_B,
                match_confidence=1.0 if category else 0.0,
            )
        )
    return out
