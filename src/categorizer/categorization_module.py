"""
Categorization Module

This module categorizes transactions using merchant dictionary (Group A)
and pattern-based detection (Group B).

Refactored to be stateless - loads merchant dictionary from JSON file.

Requirements: 5.1-5.8, 4.1-4.7
"""

import logging
import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from ..normalizer.transaction_normalizer import NormalizedTransaction
from ..parser.record_parser import normalize_thai_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MerchantEntry:
    """One compiled merchant dictionary entry"""
    keyword: str            # Upper-cased, Thai-normalized keyword
    pattern: "re.Pattern"   # Word-bounded for ASCII keywords, plain substring for Thai
    category: str
    category_label_th: str
    priority: int


class CategoryGroup(Enum):
    """Transaction categorization group"""
    GROUP_A = "known_merchant"      # Matched with merchant dictionary
    GROUP_B = "pattern_based"       # Unknown merchant, needs pattern detection


@dataclass
class CategorizedTransaction:
    """Transaction with category information"""
    normalized_transaction: NormalizedTransaction
    category: Optional[str]          # rent/internet/mobile/subscription/utility/insurance/other
    category_label_th: Optional[str] # Display label in Thai
    category_group: CategoryGroup
    match_confidence: float          # 0.0-1.0


class CategorizationModule:
    """Categorize transactions using merchant dictionary and patterns"""
    
    # Class-level cache for merchant dictionary (shared across instances)
    _merchant_dict_cache: Optional[List[MerchantEntry]] = None
    _cache_timestamp: Optional[float] = None
    
    def __init__(self, merchant_dict_path: Optional[Path] = None):
        """
        Initialize categorization module with merchant dictionary
        
        Args:
            merchant_dict_path: Path to merchant_category_dict.json file.
                               If None, uses default: data/merchant_category_dict.json
            
        Requirements: 16.5
        """
        if merchant_dict_path is None:
            # Default path relative to project root
            project_root = Path(__file__).parent.parent.parent
            merchant_dict_path = project_root / "data" / "merchant_category_dict.json"
        
        self.merchant_dict_path = merchant_dict_path
        
        # Load merchant dictionary on initialization
        if CategorizationModule._merchant_dict_cache is None:
            self._load_and_cache_merchant_dictionary()
    
    def categorize_transactions(
        self, 
        transactions: List[NormalizedTransaction], 
        existing_user_labels: Optional[List[dict]] = None
    ) -> List[CategorizedTransaction]:
        """
        Categorize all transactions for a user
        
        Stateless version - accepts existing_user_labels as parameter instead of querying DB.
        
        Args:
            transactions: Normalized transactions
            existing_user_labels: List of user label dicts with keys:
                                  recipient_key, category, category_label_th
            
        Returns:
            Categorized transactions
            
        Requirements: 5.1-5.8, 16.5
        """
        # Convert existing_user_labels to lookup dict
        user_labels_lookup = {}
        if existing_user_labels:
            for label in existing_user_labels:
                recipient_key = label.get('recipient_key')
                category = label.get('category')
                category_label_th = label.get('category_label_th')
                if recipient_key and category:
                    user_labels_lookup[recipient_key] = (category, category_label_th or category)
        
        categorized_transactions = []
        
        for transaction in transactions:
            categorized = self._categorize_single(transaction, user_labels_lookup)
            categorized_transactions.append(categorized)
        
        logger.info(
            f"Categorized {len(categorized_transactions)} transactions",
            extra={
                "group_a_count": sum(1 for t in categorized_transactions if t.category_group == CategoryGroup.GROUP_A),
                "group_b_count": sum(1 for t in categorized_transactions if t.category_group == CategoryGroup.GROUP_B)
            }
        )
        
        return categorized_transactions
    
    @classmethod
    def invalidate_cache(cls):
        """
        Invalidate merchant dictionary cache
        
        Call this method when merchant dictionary file is updated.
        Requirements: 16.6
        """
        cls._merchant_dict_cache = None
        cls._cache_timestamp = None
        logger.info("Merchant dictionary cache invalidated")
    
    def _load_and_cache_merchant_dictionary(self):
        """
        Load merchant dictionary from JSON file and cache it
        
        This method updates the class-level cache.
        Requirements: 16.5, 16.6
        """
        import time
        
        merchant_dict = self._load_merchant_dictionary()
        
        # Update class-level cache
        CategorizationModule._merchant_dict_cache = merchant_dict
        CategorizationModule._cache_timestamp = time.time()
        
        logger.info(
            f"Merchant dictionary cached with {len(merchant_dict)} entries at "
            f"timestamp {CategorizationModule._cache_timestamp}"
        )
    
    def _load_merchant_dictionary(self) -> List[MerchantEntry]:
        """
        Load merchant_category_dict from JSON file and compile one pattern per keyword.

        ASCII keywords are matched on word boundaries so that "MEA" no longer hits
        "MEAL" and "AIS" no longer hits "RAISE". Thai keywords have no word
        delimiters, so they stay plain substring matches.

        Returns:
            List of compiled MerchantEntry (later duplicates of a keyword are dropped)

        Requirements: 4.1-4.7
        """
        try:
            with open(self.merchant_dict_path, 'r', encoding='utf-8') as f:
                merchant_data = json.load(f)

            entries: Dict[str, MerchantEntry] = {}

            for entry in merchant_data:
                keyword = normalize_thai_text(entry.get('keyword', '')).strip().upper()
                match_type = entry.get('match_type', 'substring')
                category = entry.get('category', '')
                category_label_th = entry.get('category_label_th', category)
                priority = entry.get('priority', 999)

                # Only support substring matching for now
                if match_type != 'substring' or not keyword or keyword in entries:
                    continue

                if keyword.isascii():
                    pattern = re.compile(r'(?<![A-Z0-9])' + re.escape(keyword) + r'(?![A-Z0-9])')
                else:
                    pattern = re.compile(re.escape(keyword))

                entries[keyword] = MerchantEntry(
                    keyword=keyword,
                    pattern=pattern,
                    category=category,
                    category_label_th=category_label_th,
                    priority=priority,
                )

            logger.info(f"Loaded {len(entries)} merchant dictionary entries from {self.merchant_dict_path}")

            return list(entries.values())

        except FileNotFoundError:
            logger.error(f"Merchant dictionary file not found: {self.merchant_dict_path}")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse merchant dictionary JSON: {str(e)}")
            return []
        except Exception as e:
            logger.error(f"Failed to load merchant dictionary: {str(e)}")
            return []
    
    def _match_merchant(
        self, 
        merchant_name: Optional[str]
    ) -> Optional[Tuple[str, str, float]]:
        """
        Match merchant name against dictionary
        Supports case-insensitive substring matching
        
        Args:
            merchant_name: Normalized merchant name to match
            
        Returns:
            (category, category_label_th, confidence) or None
            
        Requirements: 4.5, 5.7, 16.5
        """
        if not merchant_name or not CategorizationModule._merchant_dict_cache:
            return None

        # Case-insensitive, Thai-normalized matching
        merchant_upper = normalize_thai_text(merchant_name).upper()

        matches = [
            entry for entry in CategorizationModule._merchant_dict_cache
            if entry.pattern.search(merchant_upper)
        ]

        # No matches found
        if not matches:
            return None

        # Most specific keyword wins ("AIS FIBRE" beats "AIS"), then lowest priority number
        matches.sort(key=lambda e: (-len(e.keyword), e.priority))

        best_match = matches[0]
        category = best_match.category
        category_label_th = best_match.category_label_th
        priority = best_match.priority

        # Calculate confidence based on match characteristics
        # Higher confidence for:
        # - Higher priority (lower priority number)
        # - Exact match vs substring match
        is_exact_match = merchant_upper == best_match.keyword

        if is_exact_match:
            confidence = 1.0  # Exact match
        else:
            # Substring match: confidence decreases with priority
            # Priority 1-10: 0.9-0.95
            # Priority 11-50: 0.8-0.85
            # Priority 51+: 0.7-0.75
            if priority <= 10:
                confidence = 0.95
            elif priority <= 50:
                confidence = 0.85
            else:
                confidence = 0.75
        
        logger.debug(
            f"Matched merchant '{merchant_name}' to category '{category}' "
            f"with confidence {confidence:.2f}",
            extra={
                "merchant_name": merchant_name,
                "category": category,
                "match_confidence": confidence
            }
        )
        
        return (category, category_label_th, confidence)
    
    def _categorize_single(
        self, 
        transaction: NormalizedTransaction, 
        user_labels_lookup: Dict[str, Tuple[str, str]]
    ) -> CategorizedTransaction:
        """
        Categorize single transaction
        
        Logic:
        1. Check user_labels_lookup first (highest priority)
        2. Try merchant dictionary match (Group A)
        3. If โอนเงิน and no match -> Group B (pattern-based)
        4. If ชำระเงิน and no match -> Log as unknown merchant
        
        Args:
            transaction: Normalized transaction to categorize
            user_labels_lookup: Dict mapping recipient_key to (category, category_label_th)
            
        Returns:
            CategorizedTransaction
            
        Requirements: 5.3-5.8
        """
        raw_tx = transaction.raw_transaction
        merchant_name = transaction.normalized_merchant_name
        recipient_key = transaction.recipient_key
        
        # Step 1: Check user_labels_lookup first (highest priority)
        # User labels override everything (Group B override)
        user_label = user_labels_lookup.get(recipient_key)
        
        if user_label:
            category, category_label_th = user_label
            return CategorizedTransaction(
                normalized_transaction=transaction,
                category=category,
                category_label_th=category_label_th,
                category_group=CategoryGroup.GROUP_B,  # User label is Group B override
                match_confidence=1.0  # User labels have perfect confidence
            )
        
        # Step 2: Try merchant dictionary match (Group A)
        merchant_match = self._match_merchant(merchant_name)
        
        if merchant_match:
            category, category_label_th, confidence = merchant_match
            return CategorizedTransaction(
                normalized_transaction=transaction,
                category=category,
                category_label_th=category_label_th,
                category_group=CategoryGroup.GROUP_A,
                match_confidence=confidence
            )
        
        # Step 3: No dictionary match
        # Logic depends on transaction type
        
        # If โอนเงิน (transfer) with no match -> Group B (pattern-based)
        if raw_tx.transaction_type == "โอนเงิน":
            logger.debug(
                f"Transfer transaction with no merchant match, marked as Group B: {recipient_key}",
                extra={
                    "recipient_key": recipient_key,
                    "transaction_type": raw_tx.transaction_type
                }
            )
            return CategorizedTransaction(
                normalized_transaction=transaction,
                category=None,  # Will be determined by pattern detection
                category_label_th=None,
                category_group=CategoryGroup.GROUP_B,
                match_confidence=0.0  # No match yet
            )
        
        # If ชำระเงิน (payment) with no match -> Log as unknown merchant
        # Still Group B for pattern detection, but log for dictionary expansion
        if raw_tx.transaction_type == "ชำระเงิน":
            logger.warning(
                f"Unknown merchant for payment transaction: {merchant_name or 'N/A'}",
                extra={
                    "merchant_name": merchant_name,
                    "recipient_key": recipient_key,
                    "raw_detail_text": raw_tx.raw_detail_text[:200]
                }
            )
            return CategorizedTransaction(
                normalized_transaction=transaction,
                category=None,
                category_label_th=None,
                category_group=CategoryGroup.GROUP_B,
                match_confidence=0.0
            )
        
        # Other transaction types (รับโอนเงิน - received transfer)
        # These are typically not recurring expenses
        return CategorizedTransaction(
            normalized_transaction=transaction,
            category=None,
            category_label_th=None,
            category_group=CategoryGroup.GROUP_B,
            match_confidence=0.0
        )
