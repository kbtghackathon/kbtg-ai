"""
Database Service Module

Provides database persistence operations with idempotency support for:
1. Transaction storage with parse success rate tracking
2. Recurring expense storage with single active record pattern (soft delete)
3. Statement re-upload comparison logic

Requirements: 11.1-11.11, 12.1-12.9, 16.8
"""

import logging
from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Dict
from uuid import UUID, uuid4
import psycopg2
from psycopg2 import pool
from psycopg2.extras import execute_values, RealDictCursor

from ..normalizer.transaction_normalizer import NormalizedTransaction
from ..detector.recurring_detection_engine import RecurringPattern

logger = logging.getLogger(__name__)


@dataclass
class StatementMetadata:
    """Metadata about a statement upload for idempotency tracking"""
    user_id: UUID
    statement_month: date
    total_records: int
    parsed_records: int
    parse_success_rate: float
    uploaded_at: date


@dataclass
class StatementMetadata:
    """Metadata about a statement upload for idempotency tracking"""
    user_id: UUID
    statement_month: date
    total_records: int
    parsed_records: int
    parse_success_rate: float
    uploaded_at: date


class ConnectionPool:
    """
    Database connection pool manager
    
    Implements connection pooling for concurrent user support.
    Requirements: 16.8
    """
    
    _instance = None
    _pool = None
    
    def __new__(cls):
        """Singleton pattern for connection pool"""
        if cls._instance is None:
            cls._instance = super(ConnectionPool, cls).__new__(cls)
        return cls._instance
    
    def initialize(
        self,
        connection_string: str,
        minconn: int = 1,
        maxconn: int = 20
    ):
        """
        Initialize connection pool
        
        Args:
            connection_string: PostgreSQL connection string
            minconn: Minimum number of connections in pool
            maxconn: Maximum number of connections in pool
            
        Requirements: 16.8
        """
        if self._pool is None:
            try:
                self._pool = psycopg2.pool.ThreadedConnectionPool(
                    minconn,
                    maxconn,
                    connection_string
                )
                logger.info(
                    f"Connection pool initialized: minconn={minconn}, maxconn={maxconn}"
                )
            except psycopg2.Error as e:
                logger.error(f"Failed to initialize connection pool: {str(e)}")
                raise
    
    def get_connection(self):
        """
        Get connection from pool
        
        Returns:
            Database connection
            
        Raises:
            PoolError: If pool is exhausted
        """
        if self._pool is None:
            raise RuntimeError("Connection pool not initialized")
        
        try:
            conn = self._pool.getconn()
            logger.debug("Connection retrieved from pool")
            return conn
        except psycopg2.pool.PoolError as e:
            logger.error(f"Failed to get connection from pool: {str(e)}")
            raise
    
    def return_connection(self, conn):
        """
        Return connection to pool
        
        Args:
            conn: Database connection to return
        """
        if self._pool is not None and conn is not None:
            self._pool.putconn(conn)
            logger.debug("Connection returned to pool")
    
    def close_all_connections(self):
        """Close all connections in pool"""
        if self._pool is not None:
            self._pool.closeall()
            logger.info("All connections in pool closed")
            self._pool = None


class DatabaseService:
    """
    Database persistence service with idempotency support
    
    Implements:
    - Task 13.1: Parse success rate tracking
    - Task 13.2: Statement re-upload comparison logic
    - Task 13.3: Recurring expenses idempotency with soft delete
    - Task 16.4: Connection pooling for concurrent users
    """
    
    def __init__(self, connection_string: str = None, use_pool: bool = True):
        """
        Initialize database service
        
        Args:
            connection_string: PostgreSQL connection string (required if use_pool=True)
            use_pool: Whether to use connection pooling (default: True)
            
        Requirements: 16.8
        """
        self.connection_string = connection_string
        self.use_pool = use_pool
        self._connection = None
        self._pool = ConnectionPool()
        
        if use_pool and connection_string:
            # Initialize pool if not already initialized
            if self._pool._pool is None:
                self._pool.initialize(connection_string)
    
    def connect(self):
        """
        Establish database connection
        
        Uses connection pool if enabled, otherwise creates direct connection.
        Requirements: 16.8
        """
        if self.use_pool:
            # Get connection from pool
            if self._connection is None or self._connection.closed:
                self._connection = self._pool.get_connection()
                logger.debug("Database connection acquired from pool")
        else:
            # Direct connection (backward compatibility)
            if self._connection is None or self._connection.closed:
                self._connection = psycopg2.connect(self.connection_string)
                logger.info("Direct database connection established")
    
    def close(self):
        """
        Close database connection
        
        Returns connection to pool if pooling is enabled.
        Requirements: 16.8
        """
        if self._connection and not self._connection.closed:
            if self.use_pool:
                self._pool.return_connection(self._connection)
                logger.debug("Database connection returned to pool")
            else:
                self._connection.close()
                logger.info("Direct database connection closed")
            self._connection = None
    
    def __enter__(self):
        """Context manager entry"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        if exc_type:
            self._connection.rollback()
            logger.error(f"Transaction rolled back due to error: {exc_val}")
        self.close()
    
    # ========================================================================
    # Task 13.1: Parse Success Rate Tracking
    # Requirements: 12.1, 39.5
    # ========================================================================
    
    def calculate_parse_success_rate(
        self,
        total_records: int,
        parsed_records: int
    ) -> float:
        """
        Calculate parse success rate
        
        Args:
            total_records: Total number of records in statement
            parsed_records: Number of successfully parsed records
            
        Returns:
            Parse success rate as decimal (0.0 to 1.0)
            
        Validates: Requirements 12.1, 39.5
        """
        if total_records == 0:
            return 0.0
        return parsed_records / total_records
    
    def get_existing_statement_metadata(
        self,
        user_id: UUID,
        statement_month: date
    ) -> Optional[StatementMetadata]:
        """
        Get metadata for existing statement upload
        
        Args:
            user_id: User ID
            statement_month: Statement month to check
            
        Returns:
            StatementMetadata if exists, None otherwise
            
        Validates: Requirements 12.1, 12.10
        """
        self.connect()
        
        query = """
        SELECT 
            COUNT(*) as total_records,
            MIN(created_at) as uploaded_at
        FROM transactions
        WHERE user_id = %s AND source_statement_month = %s
        """
        
        with self._connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, (str(user_id), statement_month))
            result = cursor.fetchone()
            
            if result and result['total_records'] > 0:
                # For existing data, we consider all records as parsed
                # (we don't track unparsed records in the database)
                total = result['total_records']
                return StatementMetadata(
                    user_id=user_id,
                    statement_month=statement_month,
                    total_records=total,
                    parsed_records=total,
                    parse_success_rate=1.0,  # Existing data assumed fully parsed
                    uploaded_at=result['uploaded_at'] if isinstance(result['uploaded_at'], date) else result['uploaded_at'].date()
                )
            
            return None
    
    # ========================================================================
    # Task 13.2: Statement Re-upload Comparison Logic
    # Requirements: 12.1, 12.2, 12.3
    # ========================================================================
    
    def should_replace_existing_statement(
        self,
        existing_metadata: StatementMetadata,
        new_parse_success_rate: float
    ) -> bool:
        """
        Determine if new upload should replace existing statement data
        
        Logic:
        - If new parse_success_rate >= existing rate: Replace (True)
        - If new parse_success_rate < existing rate: Warn, require confirmation (False)
        
        Args:
            existing_metadata: Metadata of existing statement
            new_parse_success_rate: Parse success rate of new upload
            
        Returns:
            True if should replace automatically, False if needs user confirmation
            
        Validates: Requirements 12.1, 12.2, 12.3
        """
        should_replace = new_parse_success_rate >= existing_metadata.parse_success_rate
        
        if should_replace:
            logger.info(
                f"New upload has equal or better parse rate "
                f"(new: {new_parse_success_rate:.2%}, existing: {existing_metadata.parse_success_rate:.2%}). "
                f"Will replace existing data."
            )
        else:
            logger.warning(
                f"New upload has LOWER parse rate "
                f"(new: {new_parse_success_rate:.2%}, existing: {existing_metadata.parse_success_rate:.2%}). "
                f"User confirmation required before replacing data."
            )
        
        return should_replace
    
    def delete_transactions_for_statement_month(
        self,
        user_id: UUID,
        statement_month: date
    ) -> int:
        """
        Delete all transactions for a specific statement month
        
        Used during re-upload to replace existing data
        
        Args:
            user_id: User ID
            statement_month: Statement month to delete
            
        Returns:
            Number of transactions deleted
            
        Validates: Requirements 12.2
        """
        self.connect()
        
        delete_query = """
        DELETE FROM transactions
        WHERE user_id = %s AND source_statement_month = %s
        """
        
        with self._connection.cursor() as cursor:
            cursor.execute(delete_query, (str(user_id), statement_month))
            deleted_count = cursor.rowcount
            self._connection.commit()
            
            logger.info(
                f"Deleted {deleted_count} transactions for user {user_id}, "
                f"statement month {statement_month}"
            )
            
            return deleted_count
    
    # ========================================================================
    # Transaction Persistence
    # Requirements: 3.8, 11.1
    # ========================================================================
    
    def insert_transactions(
        self,
        transactions: List[NormalizedTransaction]
    ) -> int:
        """
        Insert normalized transactions into database
        
        Args:
            transactions: List of normalized transactions
            
        Returns:
            Number of transactions inserted
            
        Validates: Requirements 3.8, 11.1
        """
        if not transactions:
            return 0
        
        self.connect()
        
        insert_query = """
        INSERT INTO transactions (
            user_id, transaction_date, transaction_time, transaction_type,
            amount, balance_after, channel, ref_no, recipient_name,
            recipient_account_masked, merchant_name, recipient_key,
            is_promptpay, raw_detail_text, source_statement_month
        ) VALUES %s
        """
        
        # Prepare data tuples
        data_tuples = []
        for tx in transactions:
            raw = tx.raw_transaction
            data_tuples.append((
                str(tx.user_id),
                raw.transaction_date,
                raw.transaction_time,
                raw.transaction_type,
                raw.amount,
                raw.balance_after,
                raw.channel,
                raw.ref_no,
                raw.recipient_name,
                raw.recipient_account_masked,
                raw.merchant_name,
                tx.recipient_key,
                raw.is_promptpay,
                raw.raw_detail_text,
                raw.source_statement_month
            ))
        
        with self._connection.cursor() as cursor:
            execute_values(cursor, insert_query, data_tuples)
            self._connection.commit()
            inserted_count = len(data_tuples)
            
            logger.info(f"Inserted {inserted_count} transactions")
            
            return inserted_count
    
    # ========================================================================
    # Task 13.3: Recurring Expenses Idempotency (Single Active Record Pattern)
    # Requirements: 12.4, 12.5, 12.6, 12.7
    # ========================================================================
    
    def find_active_recurring_expense(
        self,
        user_id: UUID,
        recipient_key: str
    ) -> Optional[Dict]:
        """
        Find active recurring expense record for user and recipient
        
        Args:
            user_id: User ID
            recipient_key: Recipient key
            
        Returns:
            Dict with expense data if exists, None otherwise
            
        Validates: Requirements 12.4
        """
        self.connect()
        
        query = """
        SELECT id, category, forecast_amount, recurring_type, confidence_score
        FROM recurring_expenses
        WHERE user_id = %s AND recipient_key = %s AND is_active = TRUE
        """
        
        with self._connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, (str(user_id), recipient_key))
            result = cursor.fetchone()
            
            if result:
                return dict(result)
            return None
    
    def deactivate_recurring_expense(
        self,
        expense_id: UUID
    ) -> bool:
        """
        Deactivate an existing recurring expense record (soft delete)
        
        This is part of the idempotency strategy: when re-detecting patterns,
        we deactivate the old record and insert a new active one.
        
        Args:
            expense_id: ID of expense to deactivate
            
        Returns:
            True if deactivated successfully
            
        Validates: Requirements 12.5
        """
        self.connect()
        
        update_query = """
        UPDATE recurring_expenses
        SET is_active = FALSE, updated_at = now()
        WHERE id = %s
        """
        
        with self._connection.cursor() as cursor:
            cursor.execute(update_query, (str(expense_id),))
            self._connection.commit()
            
            logger.debug(f"Deactivated recurring expense {expense_id}")
            
            return cursor.rowcount > 0
    
    def insert_recurring_expense(
        self,
        pattern: RecurringPattern,
        user_id: UUID,
        detection_run_id: UUID,
        forecast_amount: float = None
    ) -> UUID:
        """
        Insert new active recurring expense record
        
        Args:
            pattern: Detected recurring pattern
            user_id: User ID
            detection_run_id: Unique ID for this detection run
            forecast_amount: Forecasted amount (if None, uses mean_amount)
            
        Returns:
            UUID of inserted record
            
        Validates: Requirements 12.6, 33.1
        """
        self.connect()
        
        # Use forecast_amount if provided, otherwise fallback to mean_amount
        amount = forecast_amount if forecast_amount is not None else pattern.mean_amount
        
        insert_query = """
        INSERT INTO recurring_expenses (
            user_id, recipient_key, category, category_label_th,
            forecast_amount, recurring_type, n_months_present,
            amount_cv, day_std, mean_amount, median_amount,
            cycle_days, confidence_score, is_active,
            needs_user_label, last_detected_date, detection_run_id
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        ) RETURNING id
        """
        
        with self._connection.cursor() as cursor:
            cursor.execute(insert_query, (
                str(user_id),
                pattern.recipient_key,
                pattern.category,
                pattern.category_label_th,
                amount,
                pattern.recurring_type.value,
                pattern.n_months_present,
                pattern.amount_cv,
                pattern.day_std,
                pattern.mean_amount,
                pattern.median_amount,
                pattern.cycle_days,
                pattern.confidence_score,
                True,  # is_active
                pattern.needs_user_label,
                date.today(),
                str(detection_run_id)
            ))
            
            expense_id = cursor.fetchone()[0]
            self._connection.commit()
            
            logger.debug(
                f"Inserted recurring expense {expense_id} for "
                f"user {user_id}, recipient {pattern.recipient_key}"
            )
            
            return UUID(expense_id)
    
    def save_recurring_expense_idempotent(
        self,
        pattern: RecurringPattern,
        user_id: UUID,
        detection_run_id: UUID,
        forecast_amount: float = None
    ) -> UUID:
        """
        Save recurring expense with idempotency guarantee
        
        Strategy:
        1. Check if active record exists for (user_id, recipient_key)
        2. If exists: deactivate it (set is_active=FALSE)
        3. Insert new active record
        
        This ensures only one active record exists per (user_id, recipient_key)
        while maintaining history of inactive records.
        
        Args:
            pattern: Detected recurring pattern
            user_id: User ID
            detection_run_id: Unique ID for this detection run
            forecast_amount: Forecasted amount (if None, uses mean_amount)
            
        Returns:
            UUID of the new active record
            
        Validates: Requirements 12.4, 12.5, 12.6, 12.7
        """
        # Check for existing active record
        existing = self.find_active_recurring_expense(user_id, pattern.recipient_key)
        
        if existing:
            # Deactivate existing record
            self.deactivate_recurring_expense(UUID(existing['id']))
            logger.info(
                f"Deactivated existing recurring expense for "
                f"user {user_id}, recipient {pattern.recipient_key}"
            )
        
        # Insert new active record
        expense_id = self.insert_recurring_expense(
            pattern, user_id, detection_run_id, forecast_amount
        )
        
        amount_to_log = forecast_amount if forecast_amount is not None else pattern.mean_amount
        logger.info(
            f"Saved recurring expense idempotently: "
            f"user={user_id}, recipient={pattern.recipient_key}, "
            f"type={pattern.recurring_type.value}, "
            f"forecast={amount_to_log}"
        )
        
        return expense_id
    
    def get_active_recurring_expenses(
        self,
        user_id: UUID
    ) -> List[Dict]:
        """
        Get all active recurring expenses for a user
        
        Args:
            user_id: User ID
            
        Returns:
            List of active recurring expense records
            
        Validates: Requirements 9.1, 11.5
        """
        self.connect()
        
        query = """
        SELECT 
            id, recipient_key, category, category_label_th,
            forecast_amount, recurring_type, n_months_present,
            amount_cv, day_std, mean_amount, median_amount,
            cycle_days, confidence_score, needs_user_label
        FROM recurring_expenses
        WHERE user_id = %s AND is_active = TRUE
        ORDER BY forecast_amount DESC
        """
        
        with self._connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, (str(user_id),))
            results = cursor.fetchall()
            
            return [dict(row) for row in results]
    
    def count_active_recurring_expenses_for_recipient(
        self,
        user_id: UUID,
        recipient_key: str
    ) -> int:
        """
        Count active recurring expenses for a specific recipient
        
        Should always return 0 or 1 due to partial unique index constraint.
        Used for validation in property tests.
        
        Args:
            user_id: User ID
            recipient_key: Recipient key
            
        Returns:
            Count of active records (should be 0 or 1)
            
        Validates: Requirements 11.6, 11.7, 12.5 (Property 29)
        """
        self.connect()
        
        query = """
        SELECT COUNT(*) as count
        FROM recurring_expenses
        WHERE user_id = %s AND recipient_key = %s AND is_active = TRUE
        """
        
        with self._connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, (str(user_id), recipient_key))
            result = cursor.fetchone()
            
            return result['count'] if result else 0
