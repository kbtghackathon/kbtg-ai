"""
Transaction Record Parser Module

This module parses raw K PLUS bank statement text into structured transaction records.
This is the HIGHEST RISK component of the system - merchant name and recipient info
parsing must handle all edge cases correctly.
"""

import re
import logging
from dataclasses import dataclass
from datetime import date, time
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class RawTransaction:
    """Parsed transaction record from statement"""
    date: date                              # Transaction date (converted from Thai Buddhist to Gregorian)
    time: Optional[time]                    # Transaction time (may be null for some records)
    transaction_type: str                   # ชำระเงิน | โอนเงิน | รับโอนเงิน | ยอดยกมา
    amount: float                           # Transaction amount (parsed from string with comma removal)
    balance_after: float                    # Balance after transaction
    channel: str                            # K PLUS | EDC/K SHOP/MYQR | Internet/Mobile GSB | etc.
    ref_no: Optional[str]                   # Reference number (e.g., X49WX)
    raw_detail_text: str                    # Full raw detail text for debugging/fallback
    recipient_name: Optional[str]           # Recipient/Payee name
    recipient_account_masked: Optional[str] # Masked account number (e.g., X2660)
    merchant_name: Optional[str]            # Merchant name for payments
    is_promptpay: bool                      # True if PromptPay transfer
    source_statement_month: date            # Month of source statement file


class RecordParser:
    """Parse raw statement text into structured transaction records"""
    
    # Date pattern for detecting transaction start: DD-MM-YY
    DATE_PATTERN = re.compile(r'^\d{2}-\d{2}-\d{2}')
    
    # Transaction type patterns - ORDER MATTERS! Check longer patterns first
    TRANSACTION_TYPES = {
        # Thai patterns
        'รับโอนเงิน': 'รับโอนเงิน',  # Check this BEFORE โอนเงิน
        'ชําระเงิน': 'ชำระเงิน',  # Note: may have different Unicode encoding
        'ชำระเงิน': 'ชำระเงิน',
        'โอนเงิน': 'โอนเงิน',
        'ยอดยกมา': 'ยอดยกมา',
        
        # English patterns - map to Thai canonical types
        'Transfer Deposit': 'รับโอนเงิน',
        'Transfer Withdrawal': 'โอนเงิน',
        'Payment': 'ชำระเงิน',
        'Beginning Balance': 'ยอดยกมา',
    }
    
    def parse_statement_text(self, raw_text: str, statement_month: date) -> List[RawTransaction]:
        """
        Parse raw statement text into transaction records
        
        Args:
            raw_text: Raw text extracted from PDF
            statement_month: Month of the statement for tracking
            
        Returns:
            List of parsed transaction records (excluding opening balance)
        """
        lines = raw_text.split('\n')
        transactions = []
        i = 0
        previous_balance = None
        
        while i < len(lines):
            line = lines[i].strip()
            
            # Skip empty lines
            if not line:
                i += 1
                continue
            
            # Check if line starts new transaction (DD-MM-YY pattern)
            if not self.DATE_PATTERN.match(line):
                i += 1
                continue
            
            # Merge multi-line record
            record_text, next_index = self._merge_multiline_record(lines, i)
            
            # Parse single record
            try:
                transaction = self._parse_single_record(record_text, statement_month, previous_balance)
                
                if transaction is None:
                    logger.debug(f"Skipping record (parse failed or opening balance): {record_text[:100]}")
                    i = next_index
                    continue
                
                # Skip opening balance
                if transaction.transaction_type == "ยอดยกมา":
                    previous_balance = transaction.balance_after
                    logger.debug(f"Opening balance: {previous_balance}")
                    i = next_index
                    continue
                
                # Validate balance if we have previous balance
                if previous_balance is not None:
                    is_valid = self._validate_amount_balance(
                        previous_balance,
                        transaction.amount,
                        transaction.balance_after,
                        transaction.transaction_type
                    )
                    
                    if not is_valid:
                        logger.warning(
                            f"Balance validation failed for transaction: "
                            f"prev={previous_balance}, amount={transaction.amount}, "
                            f"after={transaction.balance_after}, type={transaction.transaction_type}"
                        )
                
                transactions.append(transaction)
                previous_balance = transaction.balance_after
                
            except Exception as e:
                logger.error(f"Failed to parse record: {record_text[:200]}", exc_info=True)
            
            i = next_index
        
        logger.info(f"Parsed {len(transactions)} transactions from statement")
        return transactions
    
    def _merge_multiline_record(self, lines: List[str], start_index: int) -> Tuple[str, int]:
        """
        Merge lines belonging to same transaction record
        Records start with DD-MM-YY pattern
        
        Returns:
            (merged_text, next_record_index)
        """
        merged_lines = [lines[start_index]]
        i = start_index + 1
        
        # Continue until we hit the next date pattern or end of lines
        while i < len(lines):
            line = lines[i].strip()
            
            # If we hit a new transaction (starts with date), stop
            if self.DATE_PATTERN.match(line):
                break
            
            # Otherwise, this line belongs to current transaction
            if line:  # Skip empty lines
                merged_lines.append(line)
            
            i += 1
        
        merged_text = ' '.join(merged_lines)
        return merged_text, i
    
    def _parse_single_record(
        self, 
        record_text: str, 
        statement_month: date,
        previous_balance: Optional[float]
    ) -> Optional[RawTransaction]:
        """
        Parse single transaction record from merged text
        
        Returns:
            RawTransaction or None if parsing fails or is opening balance
        """
        # Extract date (DD-MM-YY format at start)
        date_match = re.match(r'^(\d{2})-(\d{2})-(\d{2})', record_text)
        if not date_match:
            return None
        
        day, month, year_short = date_match.groups()
        transaction_date = self._parse_date(day, month, year_short)
        
        # Extract time (HH:MM format after date, optional)
        time_match = re.search(r'\s(\d{2}:\d{2})\s', record_text)
        transaction_time = self._parse_time(time_match.group(1)) if time_match else None
        
        # Detect transaction type
        transaction_type = self._detect_transaction_type(record_text)
        if not transaction_type:
            logger.warning(f"Could not detect transaction type: {record_text[:100]}")
            return None
        
        # Extract amounts and balance
        # Look for numeric patterns: amount with commas like "1,500.00" or "266.50"
        # Balance appears after the transaction type or channel
        amounts = self._extract_amounts(record_text)
        
        if len(amounts) < 2:
            logger.warning(f"Could not extract amounts: {record_text[:100]}")
            return None
        
        # For most cases: first amount is transaction amount, second is balance
        # But need to handle cases where balance comes first
        amount = amounts[0]
        balance_after = amounts[1]
        
        # Validate: if we have previous balance, check which amount makes sense
        if previous_balance is not None and len(amounts) >= 2:
            # Try both orderings and pick the one that validates
            if self._validate_amount_balance(previous_balance, amounts[0], amounts[1], transaction_type):
                amount = amounts[0]
                balance_after = amounts[1]
            elif self._validate_amount_balance(previous_balance, amounts[1], amounts[0], transaction_type):
                amount = amounts[1]
                balance_after = amounts[0]
        
        # Extract channel
        channel = self._extract_channel(record_text)
        
        # Extract reference number
        ref_no = self._extract_ref_no(record_text)
        
        # Parse recipient info (for โอนเงิน)
        recipient_name, recipient_account_masked, is_promptpay = self._parse_recipient_info(record_text)
        
        # Parse merchant info (for ชำระเงิน)
        merchant_name = self._parse_merchant_info(record_text)
        
        return RawTransaction(
            date=transaction_date,
            time=transaction_time,
            transaction_type=transaction_type,
            amount=amount,
            balance_after=balance_after,
            channel=channel,
            ref_no=ref_no,
            raw_detail_text=record_text,
            recipient_name=recipient_name,
            recipient_account_masked=recipient_account_masked,
            merchant_name=merchant_name,
            is_promptpay=is_promptpay,
            source_statement_month=statement_month
        )
    
    def _parse_date(self, day: str, month: str, year_short: str) -> date:
        """Parse date from DD, MM, YY strings"""
        gregorian_year = self._convert_thai_buddhist_to_gregorian(int(year_short))
        return date(gregorian_year, int(month), int(day))
    
    def _parse_time(self, time_str: str) -> Optional[time]:
        """Parse time from HH:MM string"""
        try:
            hours, minutes = time_str.split(':')
            return time(int(hours), int(minutes))
        except:
            return None
    
    def _convert_thai_buddhist_to_gregorian(self, thai_year_short: int) -> int:
        """
        Convert Thai Buddhist year to Gregorian year
        Example: 26 (พ.ศ. 2569) -> 2026
        
        Thai Buddhist calendar is 543 years ahead of Gregorian.
        In K PLUS statements, 2-digit year format represents last 2 digits of BE year.
        For example: "26" in "01-03-26" means BE 2569 (25+69), which is Gregorian 2026.
        
        The conversion: short year 26 → BE 2569 → Gregorian 2026
        Formula: Gregorian = 2000 + thai_year_short
        """
        gregorian_year = 2000 + thai_year_short
        return gregorian_year
    
    def _detect_transaction_type(self, text: str) -> Optional[str]:
        """Detect transaction type from text (bilingual: Thai + English)"""
        # Check longer patterns first to avoid false matches
        longer_patterns = ['Transfer Deposit', 'Transfer Withdrawal', 'Beginning Balance', 'รับโอนเงิน']
        for pattern in longer_patterns:
            if pattern in text:
                return self.TRANSACTION_TYPES[pattern]
        
        # Then check shorter patterns
        for pattern, normalized_type in self.TRANSACTION_TYPES.items():
            if pattern in text:
                return normalized_type
        return None
    
    def _extract_amounts(self, text: str) -> List[float]:
        """
        Extract numeric amounts from text
        Handles formats like "1,500.00" or "266.50"
        """
        # Pattern to match numbers with optional commas and mandatory decimals
        # Must have at least one digit before decimal point
        pattern = r'\b(\d{1,3}(?:,\d{3})*\.\d{2})\b'
        matches = re.findall(pattern, text)
        
        amounts = []
        for match in matches:
            try:
                # Remove commas and convert to float
                amount_str = match.replace(',', '')
                amount = float(amount_str)
                amounts.append(amount)
            except ValueError:
                continue
        
        return amounts
    
    def _extract_channel(self, text: str) -> str:
        """Extract channel from transaction text"""
        channels = ['K PLUS', 'EDC/K SHOP/MYQR', 'Internet/Mobile GSB']
        
        for channel in channels:
            if channel in text:
                return channel
        
        # If no match, return unknown
        return "UNKNOWN"
    
    def _extract_ref_no(self, text: str) -> Optional[str]:
        """Extract reference number like X49WX, X8955, etc."""
        # Pattern: Ref followed by space and alphanumeric code
        match = re.search(r'Ref\s+([A-Z0-9]+)', text, re.IGNORECASE)
        return match.group(1) if match else None
    
    def _parse_recipient_info(self, detail_text: str) -> Tuple[Optional[str], Optional[str], bool]:
        """
        Extract recipient name, account, and PromptPay flag
        
        CRITICAL IMPLEMENTATION - handles multiple formats:
        - "โอนไป X2660 นาย ทรงทรัพย์ แก้ว++"
        - "โอนไป พร้อมเพย์ X8955 นายทรงทรัพย์ แก้วพ++" (PromptPay flag)
        - "(ชื่อบัญชี: นาย อินทร์ตา ชานิคม)" in EDC/QR payments
        - "จาก GSB X3753 นาย พีรดนย์ แก้วพร++" (for รับโอนเงิน)
        
        Returns:
            (recipient_name, recipient_account_masked, is_promptpay)
        """
        recipient_name = None
        recipient_account_masked = None
        is_promptpay = False
        
        # Check for PromptPay
        if 'พร้อมเพย์' in detail_text:
            is_promptpay = True
        
        # Pattern 1: โอนไป [พร้อมเพย์] X#### name++
        # Handles both "โอนไป X2660 นาย ทรงทรัพย์ แก้ว++" and "โอนไป พร้อมเพย์ X8955 นายทรงทรัพย์ แก้วพ++"
        transfer_match = re.search(
            r'โอนไป\s+(?:พร้อมเพย์\s+)?([A-Z]\d+)\s+(.+?)(?:\+\+)',
            detail_text
        )
        if transfer_match:
            recipient_account_masked = transfer_match.group(1)
            recipient_name = transfer_match.group(2).strip()
            # Remove any remaining ++ at the end
            recipient_name = recipient_name.rstrip('+').strip()
            return recipient_name, recipient_account_masked, is_promptpay
        
        # Pattern 2: จาก ... X#### name++ (for รับโอนเงิน)
        # Example: "จาก GSB X3753 นาย พีรดนย์ แก้วพร++"
        from_match = re.search(
            r'จาก\s+(?:[\w/]+\s+)?([A-Z]\d+)\s+(.+?)(?:\+\+)',
            detail_text
        )
        if from_match:
            recipient_account_masked = from_match.group(1)
            recipient_name = from_match.group(2).strip()
            recipient_name = recipient_name.rstrip('+').strip()
            return recipient_name, recipient_account_masked, is_promptpay
        
        # Pattern 3: (ชื่อบัญชี: ...) in EDC/QR payments
        # Example: "(ชื่อบัญชี: นาย อินทร์ตา ชานิคม)"
        account_holder_match = re.search(
            r'\(ชื่อบัญชี:\s*(.+?)\)',
            detail_text
        )
        if account_holder_match:
            recipient_name = account_holder_match.group(1).strip()
            # Try to find Ref X#### before the account holder info
            ref_match = re.search(r'Ref\s+([A-Z0-9]+)', detail_text)
            if ref_match:
                recipient_account_masked = ref_match.group(1)
            return recipient_name, recipient_account_masked, is_promptpay
        
        return recipient_name, recipient_account_masked, is_promptpay
    
    def _parse_merchant_info(self, detail_text: str) -> Optional[str]:
        """
        Extract merchant name from payment detail
        Handles multi-line merchant names (already merged by _merge_multiline_record)
        
        HIGHEST RISK COMPONENT - handles multiple formats:
        - "เพื่อชําระ Ref X8955 TrueMoney Wallet"
        - "เพื่อชําระ Ref X9481 ทูเดย์สเต็ก อาหาตามสั่ง"
        - Multi-line merchant names (now merged):
          * "Payment to ShopeeFood"
          * "CFM-Flat Thungmahameak"
          * "ถุงเงิน (กินแล้วรวย ก๋วยเตี๋ยวหมูเด้ง)"
        - Merchant name with account info:
          * "ทูเดย์สเต็ก อาหาตามสั่ง (ชื่อบัญชี: นาย อินทร์ตา ชานิคม)"
        
        Returns:
            Merchant name or None
        """
        # Pattern 0: English - "Paid for Ref X#### Merchant Name"
        paid_for_match = re.search(
            r'Paid for Ref\s+[A-Z0-9]+\s+(.+?)(?:\s+(?:Payment|Transfer|K PLUS)|\s*$)',
            detail_text,
            re.IGNORECASE
        )
        if paid_for_match:
            merchant_name = paid_for_match.group(1).strip()
            merchant_name = self._clean_merchant_name(merchant_name)
            return merchant_name if merchant_name else None
        
        # Pattern 1: Thai - เพื่อชําระ Ref X#### merchant_name
        payment_match = re.search(
            r'เพื่อชําระ\s+Ref\s+[A-Z0-9]+\s+(.+?)(?:\s+(?:ชําระเงิน|โอนเงิน)|\s*\(ชื่อบัญชี:|$)',
            detail_text,
            re.IGNORECASE
        )
        if payment_match:
            merchant_name = payment_match.group(1).strip()
            merchant_name = self._clean_merchant_name(merchant_name)
            return merchant_name if merchant_name else None
        
        # Pattern 2: ชำระเงิน (direct, with different Unicode encoding)
        # Handles cases like "ชำระเงิน 50.00" followed by merchant in next part
        payment_match2 = re.search(
            r'ชําระเงิน\s+[\d,]+\.\d{2}\s+(.+?)(?:\s+ชําระเงิน|\s*\(ชื่อบัญชี:|$)',
            detail_text,
            re.IGNORECASE
        )
        if payment_match2:
            merchant_name = payment_match2.group(1).strip()
            merchant_name = self._clean_merchant_name(merchant_name)
            return merchant_name if merchant_name else None
        
        # Pattern 3: EDC/K SHOP/MYQR format with Ref and merchant before (ชื่อบัญชี:
        # Example: "EDC/K SHOP/MYQR เพื่อชําระ Ref X9481 ทูเดย์สเต็ก อาหาตามสั่ง (ชื่อบัญชี: ..."
        edc_match = re.search(
            r'EDC/K SHOP/MYQR\s+เพื่อชําระ\s+Ref\s+[A-Z0-9]+\s+(.+?)(?:\s+ชําระเงิน|\s*\(ชื่อบัญชี:|$)',
            detail_text,
            re.IGNORECASE
        )
        if edc_match:
            merchant_name = edc_match.group(1).strip()
            merchant_name = self._clean_merchant_name(merchant_name)
            return merchant_name if merchant_name else None
        
        return None
    
    def _clean_merchant_name(self, merchant_name: str) -> str:
        """Clean up merchant name by removing artifacts"""
        # Remove trailing channel indicators
        for channel in ['K PLUS', 'EDC/K SHOP/MYQR', 'Internet/Mobile GSB']:
            merchant_name = merchant_name.replace(channel, '').strip()
        
        # Remove common artifacts
        merchant_name = merchant_name.replace('  ', ' ').strip()
        
        return merchant_name
    
    def _validate_amount_balance(
        self, 
        prev_balance: float, 
        amount: float, 
        balance_after: float,
        transaction_type: str
    ) -> bool:
        """
        Validate that balance calculation is correct
        For debit (ชำระเงิน, โอนเงิน): prev_balance - amount ≈ balance_after
        For credit (รับโอนเงิน): prev_balance + amount ≈ balance_after
        
        Returns:
            True if validation passes (within tolerance of 0.02)
        """
        tolerance = 0.02  # Increased tolerance for floating point comparison
        
        if transaction_type in ['ชำระเงิน', 'โอนเงิน']:
            # Debit transaction
            expected_balance = prev_balance - amount
        elif transaction_type == 'รับโอนเงิน':
            # Credit transaction
            expected_balance = prev_balance + amount
        else:
            # Unknown type, can't validate
            return True
        
        diff = abs(expected_balance - balance_after)
        return diff <= tolerance



