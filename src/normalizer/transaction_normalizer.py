"""
Transaction Normalizer Module

This module normalizes transaction data and creates unique recipient keys
for pattern detection and grouping.
"""

import re
import logging
from dataclasses import dataclass
from typing import List, Optional
from uuid import UUID

from ..parser.record_parser import RawTransaction

logger = logging.getLogger(__name__)


@dataclass
class NormalizedTransaction:
    """Normalized transaction with recipient_key"""
    raw_transaction: RawTransaction
    recipient_key: str                     # Unique identifier for grouping
    normalized_merchant_name: Optional[str] # Uppercase, trimmed, cleaned
    normalized_recipient_name: Optional[str] # Uppercase, trimmed, cleaned
    user_id: UUID                          # Owner of this transaction


class TransactionNormalizer:
    """Normalize transaction data for pattern detection"""
    
    def normalize_transactions(
        self, 
        transactions: List[RawTransaction], 
        user_id: UUID
    ) -> List[NormalizedTransaction]:
        """
        Normalize all transactions and create recipient keys
        
        This is now a stateless function that returns in-memory data only.
        No database persistence.
        
        Args:
            transactions: Raw parsed transactions
            user_id: User who owns these transactions
            
        Returns:
            Normalized transactions ready for categorization
        """
        normalized_transactions = []
        
        for transaction in transactions:
            # Normalize merchant and recipient names
            normalized_merchant_name = self._normalize_name(transaction.merchant_name)
            normalized_recipient_name = self._normalize_name(transaction.recipient_name)
            
            # Create recipient key
            recipient_key = self._create_recipient_key(
                transaction,
                normalized_merchant_name,
                normalized_recipient_name
            )
            
            # Create normalized transaction
            normalized_tx = NormalizedTransaction(
                raw_transaction=transaction,
                recipient_key=recipient_key,
                normalized_merchant_name=normalized_merchant_name,
                normalized_recipient_name=normalized_recipient_name,
                user_id=user_id
            )
            
            normalized_transactions.append(normalized_tx)
            
            logger.debug(
                f"Normalized transaction: type={transaction.transaction_type}, "
                f"recipient_key={recipient_key}, merchant={normalized_merchant_name}, "
                f"recipient={normalized_recipient_name}"
            )
        
        logger.info(f"Normalized {len(normalized_transactions)} transactions for user {user_id}")
        return normalized_transactions
    
    def _normalize_name(self, name: Optional[str]) -> Optional[str]:
        """
        Normalize merchant/recipient name
        - Strip leading/trailing whitespace
        - Remove excessive internal whitespace
        - Convert to uppercase for matching
        - Remove ++ masking suffix from K PLUS
        
        Returns:
            Normalized name or None
        """
        if name is None or not name.strip():
            return None
        
        # Strip leading/trailing whitespace
        normalized = name.strip()
        
        # Remove ++ masking suffix from K PLUS (trailing + signs)
        # Keep removing trailing + signs until we don't have any left
        while normalized.endswith('+'):
            normalized = normalized[:-1].rstrip()
        
        # Check if we're left with nothing after removing artifacts
        if not normalized:
            return None
        
        # Remove excessive internal whitespace (multiple spaces to single space)
        normalized = re.sub(r'\s+', ' ', normalized)
        
        # Convert to uppercase for consistent matching
        normalized = normalized.upper()
        
        return normalized if normalized else None
    
    def _create_recipient_key(
        self,
        transaction: RawTransaction,
        normalized_merchant_name: Optional[str],
        normalized_recipient_name: Optional[str]
    ) -> str:
        """
        Create unique recipient key for grouping
        Priority:
        1. recipient_account_masked (most accurate)
        2. normalized merchant_name
        3. normalized recipient_name (for person-to-person transfers)

        ref_no is intentionally excluded: it is a per-transaction reference, so
        including it split the same merchant into one key per payment and made
        recurring detection impossible.

        Returns:
            Unique recipient key string
        """
        # Priority 1: Use recipient_account_masked if available
        if transaction.recipient_account_masked:
            return f"ACCOUNT:{transaction.recipient_account_masked}"

        # Priority 2: normalized merchant name
        if normalized_merchant_name:
            return f"MERCHANT:{normalized_merchant_name}"
        
        # Priority 3: Use normalized recipient_name as fallback
        if normalized_recipient_name:
            return f"RECIPIENT:{normalized_recipient_name}"
        
        # Last resort: use raw detail text hash (should rarely happen)
        # This ensures we always have a key, but it won't group well
        import hashlib
        raw_hash = hashlib.md5(transaction.raw_detail_text.encode()).hexdigest()[:8]
        logger.warning(
            f"Could not create meaningful recipient key, using hash fallback: {raw_hash}. "
            f"Transaction: {transaction.raw_detail_text[:100]}"
        )
        return f"UNKNOWN:{raw_hash}"
