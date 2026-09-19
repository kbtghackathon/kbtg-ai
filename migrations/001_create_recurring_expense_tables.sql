-- Migration: Create Recurring Expense Detection Database Schema
-- Description: Creates tables for transaction storage, merchant categorization, 
--              recurring expense detection, and user category mappings
-- Requirements: 11.1-11.11, 32.1-32.10

-- ============================================================================
-- Table: users (assumed to exist, referenced by foreign keys)
-- ============================================================================
-- Note: This table should already exist in the system. If not, uncomment below:
-- CREATE TABLE IF NOT EXISTS users (
--   id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
--   email TEXT NOT NULL UNIQUE,
--   created_at TIMESTAMPTZ DEFAULT now(),
--   updated_at TIMESTAMPTZ DEFAULT now()
-- );

-- ============================================================================
-- Table: transactions
-- Purpose: Store all parsed bank statement transactions
-- Requirements: 11.1, 32.1-32.6
-- ============================================================================
CREATE TABLE transactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id),
  transaction_date DATE NOT NULL,
  transaction_time TIME,
  transaction_type VARCHAR(20) NOT NULL,
  amount NUMERIC(12,2) NOT NULL,
  balance_after NUMERIC(12,2),
  channel VARCHAR(50),
  ref_no VARCHAR(20),
  recipient_name TEXT,
  recipient_account_masked VARCHAR(20),
  merchant_name TEXT,
  recipient_key TEXT NOT NULL,
  is_promptpay BOOLEAN DEFAULT FALSE,
  raw_detail_text TEXT,
  source_statement_month DATE,
  created_at TIMESTAMPTZ DEFAULT now(),
  
  -- Constraint: Validate transaction type (Req 17.5, 32.4)
  CONSTRAINT valid_transaction_type CHECK (
    transaction_type IN ('ชำระเงิน', 'โอนเงิน', 'รับโอนเงิน', 'ยอดยกมา')
  ),
  
  -- Constraint: Amount must be non-negative (Req 21.8)
  CONSTRAINT positive_amount CHECK (amount >= 0)
);

-- Index: Optimize queries by user and recipient for pattern detection (Req 11.3)
CREATE INDEX idx_transactions_user_recipient ON transactions(user_id, recipient_key);

-- Index: Optimize queries by user and date for time-based analysis (Req 11.4)
CREATE INDEX idx_transactions_user_date ON transactions(user_id, transaction_date DESC);

-- Index: Optimize queries by statement month for re-upload scenarios (Req 12.1)
CREATE INDEX idx_transactions_statement_month ON transactions(user_id, source_statement_month);

-- Index: Optimize queries by transaction type for filtering
CREATE INDEX idx_transactions_type ON transactions(user_id, transaction_type);

-- ============================================================================
-- Table: merchant_category_dict
-- Purpose: Global merchant-to-category mapping dictionary
-- Requirements: 11.9, 32.7
-- ============================================================================
CREATE TABLE merchant_category_dict (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  keyword TEXT NOT NULL,
  match_type VARCHAR(10) DEFAULT 'substring',
  category VARCHAR(50) NOT NULL,
  category_label_th TEXT,
  priority INTEGER DEFAULT 100,
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  
  -- Constraint: Validate match type (Req 32.6)
  CONSTRAINT valid_match_type CHECK (
    match_type IN ('substring', 'exact', 'regex')
  ),
  
  -- Constraint: Keyword must not be empty (Req 4.2)
  CONSTRAINT non_empty_keyword CHECK (length(trim(keyword)) > 0),
  
  -- Constraint: Category must not be empty (Req 4.3)
  CONSTRAINT non_empty_category CHECK (length(trim(category)) > 0),
  
  -- Constraint: Unique keyword and match type combination (Req 32.7)
  CONSTRAINT unique_keyword UNIQUE (keyword, match_type)
);

-- Index: Optimize active keyword lookups (Req 16.5)
CREATE INDEX idx_merchant_dict_keyword ON merchant_category_dict(keyword) 
  WHERE is_active = TRUE;

-- Index: Optimize category-based queries
CREATE INDEX idx_merchant_dict_category ON merchant_category_dict(category) 
  WHERE is_active = TRUE;

-- Index: Optimize priority-based matching
CREATE INDEX idx_merchant_dict_priority ON merchant_category_dict(priority, is_active);

-- ============================================================================
-- Table: recurring_expenses
-- Purpose: Store detected recurring expense patterns with idempotency support
-- Requirements: 11.5, 11.6, 11.7, 32.5, 32.9
-- ============================================================================
CREATE TABLE recurring_expenses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id),
  recipient_key TEXT NOT NULL,
  category VARCHAR(50),
  category_label_th TEXT,
  forecast_amount NUMERIC(12,2) NOT NULL,
  recurring_type VARCHAR(30) NOT NULL,
  frequency_type VARCHAR(20),  -- Deprecated: kept for backward compatibility
  n_months_present INTEGER,
  amount_cv NUMERIC(6,4),
  day_std NUMERIC(6,2),
  mean_amount NUMERIC(12,2),
  median_amount NUMERIC(12,2),
  cycle_days NUMERIC(6,2),
  confidence_score NUMERIC(4,3),
  is_active BOOLEAN DEFAULT TRUE,
  needs_user_label BOOLEAN DEFAULT FALSE,
  last_detected_date DATE,
  detection_run_id UUID,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  
  -- Constraint: Validate recurring type (Req 32.5)
  CONSTRAINT valid_recurring_type CHECK (
    recurring_type IN ('monthly_fixed', 'monthly_variable', 'periodic_non_monthly', 
                       'frequent_small_spend', 'not_recurring')
  ),
  
  -- Constraint: Forecast amount must be non-negative (Req 7.7)
  CONSTRAINT positive_forecast_amount CHECK (forecast_amount >= 0),
  
  -- Constraint: Confidence score must be between 0 and 1 (Req 24.1)
  CONSTRAINT valid_confidence_score CHECK (
    confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 1)
  ),
  
  -- Constraint: Amount CV (coefficient of variation) must be non-negative
  CONSTRAINT non_negative_cv CHECK (amount_cv IS NULL OR amount_cv >= 0),
  
  -- Constraint: Day std must be non-negative
  CONSTRAINT non_negative_day_std CHECK (day_std IS NULL OR day_std >= 0),
  
  -- Constraint: Category required unless needs_user_label is TRUE (Req 8.1)
  CONSTRAINT category_or_needs_label CHECK (
    category IS NOT NULL OR needs_user_label = TRUE
  )
);

-- Partial Unique Index: Enforce single active record per user+recipient (Req 11.6, 11.7, 12.5, 32.9)
-- This implements the single-record soft delete idempotency strategy
CREATE UNIQUE INDEX unique_user_recipient_active 
  ON recurring_expenses(user_id, recipient_key) 
  WHERE is_active = TRUE;

-- Index: Optimize queries for active recurring expenses (Req 11.5, 9.1)
CREATE INDEX idx_recurring_user_active ON recurring_expenses(user_id, is_active);

-- Index: Optimize queries for expenses needing user labels (Req 8.1)
CREATE INDEX idx_recurring_needs_label ON recurring_expenses(user_id, needs_user_label) 
  WHERE needs_user_label = TRUE;

-- Index: Optimize queries by detection run for auditing (Req 33.1)
CREATE INDEX idx_recurring_detection_run ON recurring_expenses(detection_run_id);

-- Index: Optimize queries by recipient key for updates
CREATE INDEX idx_recurring_recipient ON recurring_expenses(user_id, recipient_key);

-- ============================================================================
-- Table: user_category_mapping
-- Purpose: Store user-specific category labels for Group B transactions
-- Requirements: 11.10, 32.8
-- ============================================================================
CREATE TABLE user_category_mapping (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id),
  recipient_key TEXT NOT NULL,
  category VARCHAR(50) NOT NULL,
  category_label_th TEXT NOT NULL,
  labeled_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  
  -- Constraint: Category must not be empty
  CONSTRAINT non_empty_user_category CHECK (length(trim(category)) > 0),
  
  -- Constraint: Category label must not be empty
  CONSTRAINT non_empty_category_label CHECK (length(trim(category_label_th)) > 0),
  
  -- Constraint: Unique user and recipient combination (Req 8.10, 32.8)
  CONSTRAINT unique_user_recipient_mapping UNIQUE(user_id, recipient_key)
);

-- Index: Optimize lookups for user category overrides (Req 5.1, 8.8)
CREATE INDEX idx_user_mapping_user_recipient ON user_category_mapping(user_id, recipient_key);

-- Index: Optimize queries by category for reporting
CREATE INDEX idx_user_mapping_category ON user_category_mapping(user_id, category);

-- ============================================================================
-- Comments and Documentation
-- ============================================================================

COMMENT ON TABLE transactions IS 
  'Stores parsed bank statement transactions with normalized recipient keys for pattern detection';

COMMENT ON TABLE merchant_category_dict IS 
  'Global dictionary mapping merchant keywords to expense categories';

COMMENT ON TABLE recurring_expenses IS 
  'Detected recurring expense patterns with soft-delete idempotency (single active record per user+recipient)';

COMMENT ON TABLE user_category_mapping IS 
  'User-provided category labels for Group B transactions that override automatic categorization';

COMMENT ON COLUMN recurring_expenses.is_active IS 
  'Only one record per (user_id, recipient_key) can be active. Old records are deactivated for idempotency.';

COMMENT ON COLUMN recurring_expenses.needs_user_label IS 
  'TRUE when Group B transaction lacks category and requires user input for labeling';

COMMENT ON COLUMN recurring_expenses.detection_run_id IS 
  'UUID tracking which detection run created this record for auditing purposes';

COMMENT ON COLUMN transactions.recipient_key IS 
  'Normalized unique identifier for grouping transactions to same merchant/person';

COMMENT ON COLUMN transactions.source_statement_month IS 
  'Calendar month of the source bank statement PDF for re-upload handling';

-- ============================================================================
-- Migration Complete
-- ============================================================================
