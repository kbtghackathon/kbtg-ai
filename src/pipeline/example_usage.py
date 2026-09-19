"""
Example usage of the main processing pipeline.

This script demonstrates how to use the process_recurring_expense_detection
function with proper configuration and logging.
"""

import os
from pathlib import Path
from uuid import UUID
import logging

from .main_pipeline import (
    process_recurring_expense_detection,
    configure_structured_logging,
    PipelineResult
)
from ..config.detection_config import DetectionConfig
from ..config.forecast_config import ForecastConfig
from ..config.user_labeling_config import UserLabelingConfig


def run_pipeline_example():
    """
    Example of running the recurring expense detection pipeline.
    
    This demonstrates:
    1. Configuration loading
    2. Structured logging setup
    3. Pipeline execution
    4. Result handling
    """
    
    # ============================================================
    # 1. Configure Structured Logging
    # ============================================================
    configure_structured_logging(log_level="INFO")
    logger = logging.getLogger(__name__)
    
    # ============================================================
    # 2. Load Configuration
    # ============================================================
    # Option A: Use default configurations
    detection_config = DetectionConfig()
    forecast_config = ForecastConfig()
    user_labeling_config = UserLabelingConfig()
    
    # Option B: Load from JSON files (if they exist)
    config_dir = Path(__file__).parent.parent.parent / "config"
    
    if (config_dir / "detection_config.json").exists():
        detection_config = DetectionConfig.from_json_file(
            config_dir / "detection_config.json"
        )
        logger.info("Loaded detection config from file")
    
    if (config_dir / "forecast_config.json").exists():
        forecast_config = ForecastConfig.from_json_file(
            config_dir / "forecast_config.json"
        )
        logger.info("Loaded forecast config from file")
    
    if (config_dir / "user_labeling_config.json").exists():
        user_labeling_config = UserLabelingConfig.from_json_file(
            config_dir / "user_labeling_config.json"
        )
        logger.info("Loaded user labeling config from file")
    
    # ============================================================
    # 3. Prepare Input Data
    # ============================================================
    # Example: 6 months of PDF statements
    pdf_directory = Path("./sample_statements")  # Replace with actual path
    pdf_files = sorted(pdf_directory.glob("statement_*.pdf"))
    
    if not pdf_files:
        logger.error(f"No PDF files found in {pdf_directory}")
        return
    
    # Limit to 6 months
    pdf_files = pdf_files[:6]
    
    # User information
    user_id = UUID("12345678-1234-5678-1234-567812345678")  # Replace with actual user_id
    current_salary = 25000.0  # Replace with actual salary
    
    # Database connection string
    db_connection_string = os.getenv(
        "DATABASE_URL",
        "postgresql://user:password@localhost:5432/recurring_expenses"
    )
    
    # ============================================================
    # 4. Run Pipeline
    # ============================================================
    logger.info("Starting pipeline execution")
    
    result: PipelineResult = process_recurring_expense_detection(
        pdf_files=pdf_files,
        user_id=user_id,
        current_salary=current_salary,
        db_connection_string=db_connection_string,
        detection_config=detection_config,
        forecast_config=forecast_config,
        user_labeling_config=user_labeling_config
    )
    
    # ============================================================
    # 5. Handle Results
    # ============================================================
    if result.success:
        logger.info("Pipeline completed successfully!")
        
        summary = result.summary
        
        print("\n" + "="*60)
        print("RECURRING EXPENSE SUMMARY")
        print("="*60)
        print(f"Salary This Month: ฿{summary.salary_this_month:,.2f}")
        print(f"Total Recurring Expenses: ฿{summary.total_recurring:,.2f}")
        print(f"Remaining After Reserve: ฿{summary.remaining_after_reserve:,.2f}")
        print(f"\nData Months Available: {summary.data_months_available}")
        
        if summary.data_completeness_warning:
            print(f"⚠️  Warning: {summary.data_completeness_warning}")
        
        print(f"\nRecurring Expenses Breakdown:")
        print("-" * 60)
        
        for expense in summary.recurring_expenses:
            print(
                f"  {expense.category_label_th:30s} "
                f"฿{expense.amount:>10,.2f} "
                f"(confidence: {expense.confidence:.2%})"
            )
        
        if summary.pending_user_labels:
            print(f"\n⚠️  {len(summary.pending_user_labels)} expenses need user labeling")
        
        print("\n" + "="*60)
        print(f"Execution Time: {result.execution_time_seconds:.2f} seconds")
        print(f"Transactions Parsed: {result.total_transactions_parsed}")
        print(f"Parse Success Rate: {result.parse_success_rate:.2%}")
        print(f"Patterns Detected: {result.total_patterns_detected}")
        print("="*60)
        
        if result.warnings:
            print(f"\n⚠️  Warnings ({len(result.warnings)}):")
            for warning in result.warnings:
                print(f"  - {warning}")
    
    else:
        logger.error("Pipeline failed!")
        print("\n" + "="*60)
        print("PIPELINE EXECUTION FAILED")
        print("="*60)
        print(f"Error: {result.error_message}")
        
        if result.warnings:
            print(f"\nWarnings ({len(result.warnings)}):")
            for warning in result.warnings:
                print(f"  - {warning}")
        
        print("="*60)


if __name__ == "__main__":
    run_pipeline_example()
