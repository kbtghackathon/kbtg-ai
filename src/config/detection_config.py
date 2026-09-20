"""
Detection configuration data class

This module defines all recurring detection thresholds as required by
Requirements 13.1-13.13.
"""

from dataclasses import dataclass
from typing import Dict, Any
import json
from pathlib import Path


@dataclass
class DetectionConfig:
    """
    Configuration for recurring detection thresholds.
    
    All thresholds must be loaded from configuration files, not hardcoded
    in the detection logic (Requirement 13.21).
    
    Attributes:
        # Rule 1: Frequent small spend exclusion
        frequent_spend_transactions_per_month: Average transactions per month threshold
        frequent_spend_mean_amount_threshold: Mean amount threshold for exclusion
        
        # Rule 2: Monthly fixed bill
        monthly_fixed_min_months: Minimum months present required
        monthly_fixed_day_std_max: Maximum day standard deviation
        monthly_fixed_amount_cv_max: Maximum coefficient of variation for amounts
        
        # Rule 3: Monthly variable bill
        monthly_variable_min_months: Minimum months present required
        monthly_variable_day_std_max: Maximum day standard deviation
        monthly_variable_amount_cv_max: Maximum coefficient of variation
        
        # Rule 4: Periodic non-monthly
        periodic_min_transactions: Minimum number of transactions
        periodic_gap_std_max: Maximum standard deviation of transaction gaps
        periodic_gap_min_days: Minimum average gap in days
        
        # Confidence scoring
        confidence_data_completeness_weight: Weight for data completeness factor
        confidence_pattern_consistency_weight: Weight for pattern consistency factor
    """
    
    # Rule 1: Frequent small spend exclusion (Requirements 13.2, 13.3)
    frequent_spend_transactions_per_month: float = 3.0
    frequent_spend_mean_amount_threshold: float = 200.0
    
    # Rule 2: Monthly fixed bill (Requirements 13.4, 13.5, 13.6)
    monthly_fixed_min_months: int = 4
    monthly_fixed_day_std_max: float = 3.0
    monthly_fixed_amount_cv_max: float = 0.10
    
    # Rule 3: Monthly variable bill (Requirements 13.7, 13.8, 13.9)
    monthly_variable_min_months: int = 4
    monthly_variable_day_std_max: float = 5.0
    monthly_variable_amount_cv_max: float = 0.30
    
    # Rule 4: Periodic non-monthly (Requirements 13.10, 13.11, 13.12)
    periodic_min_transactions: int = 3
    periodic_gap_std_max: float = 15.0
    periodic_gap_min_days: float = 45.0
    
    # Confidence scoring (Requirement 13.13)
    confidence_data_completeness_weight: float = 0.4
    confidence_pattern_consistency_weight: float = 0.6
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "DetectionConfig":
        """
        Load configuration from dictionary.
        
        Args:
            config_dict: Dictionary containing configuration values
            
        Returns:
            DetectionConfig instance with values from dictionary
        """
        return cls(**config_dict)
    
    @classmethod
    def from_json_file(cls, file_path: Path) -> "DetectionConfig":
        """
        Load configuration from JSON file.
        
        Args:
            file_path: Path to JSON configuration file
            
        Returns:
            DetectionConfig instance loaded from file
            
        Raises:
            FileNotFoundError: If configuration file does not exist
            json.JSONDecodeError: If file contains invalid JSON
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            config_dict = json.load(f)
        return cls.from_dict(config_dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Export configuration to dictionary.
        
        Returns:
            Dictionary representation of configuration
        """
        return {
            "frequent_spend_transactions_per_month": self.frequent_spend_transactions_per_month,
            "frequent_spend_mean_amount_threshold": self.frequent_spend_mean_amount_threshold,
            "monthly_fixed_min_months": self.monthly_fixed_min_months,
            "monthly_fixed_day_std_max": self.monthly_fixed_day_std_max,
            "monthly_fixed_amount_cv_max": self.monthly_fixed_amount_cv_max,
            "monthly_variable_min_months": self.monthly_variable_min_months,
            "monthly_variable_day_std_max": self.monthly_variable_day_std_max,
            "monthly_variable_amount_cv_max": self.monthly_variable_amount_cv_max,
            "periodic_min_transactions": self.periodic_min_transactions,
            "periodic_gap_std_max": self.periodic_gap_std_max,
            "periodic_gap_min_days": self.periodic_gap_min_days,
            "confidence_data_completeness_weight": self.confidence_data_completeness_weight,
            "confidence_pattern_consistency_weight": self.confidence_pattern_consistency_weight,
        }
    
    def to_json_file(self, file_path: Path) -> None:
        """
        Save configuration to JSON file.
        
        Args:
            file_path: Path where JSON file should be saved
        """
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
