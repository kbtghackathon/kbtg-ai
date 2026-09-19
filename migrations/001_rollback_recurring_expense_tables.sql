-- Rollback Migration: Drop Recurring Expense Detection Database Schema
-- Description: Removes all tables created in 001_create_recurring_expense_tables.sql
-- WARNING: This will permanently delete all recurring expense detection data

-- ============================================================================
-- Drop tables in reverse order (respecting foreign key dependencies)
-- ============================================================================

-- Drop user_category_mapping (no dependencies)
DROP TABLE IF EXISTS user_category_mapping CASCADE;

-- Drop recurring_expenses (references users)
DROP TABLE IF EXISTS recurring_expenses CASCADE;

-- Drop merchant_category_dict (no dependencies)
DROP TABLE IF EXISTS merchant_category_dict CASCADE;

-- Drop transactions (references users)
DROP TABLE IF EXISTS transactions CASCADE;

-- Note: users table is not dropped as it's owned by another system component

-- ============================================================================
-- Rollback Complete
-- ============================================================================
