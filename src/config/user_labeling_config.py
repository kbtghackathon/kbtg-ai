"""
User labeling configuration data class

This module defines all user labeling suggestion heuristic thresholds as required by
Requirements 13.15-13.21.
"""

from dataclasses import dataclass
from typing import Dict, Any
import json
from pathlib import Path


@dataclass
class UserLabelingConfig:
    """
    Configuration for user labeling suggestion heuristics.
    
    All category suggestion thresholds must be loaded from configuration files,
    not hardcoded in the suggestion logic (Requirement 13.21).
    
    Attributes:
        rent_amount_threshold: Amounts above this suggest rent or loan payment
        utility_amount_min: Lower bound for utility bill suggestion
        utility_amount_max: Upper bound for utility bill suggestion
        loan_amount_threshold: Regular loan payment threshold
        family_support_amount_threshold: Family support payment threshold
    """
    
    # Category suggestion thresholds (Requirements 13.15-13.20)
    rent_amount_threshold: float = 3000.0          # Amounts above this suggest rent
    utility_amount_min: float = 500.0              # Utility bill amount range lower bound
    utility_amount_max: float = 1000.0             # Utility bill amount range upper bound
    loan_amount_threshold: float = 2000.0          # Regular loan payments
    family_support_amount_threshold: float = 1500.0 # Family support payments
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "UserLabelingConfig":
        """
        Load configuration from dictionary.
        
        Args:
            config_dict: Dictionary containing configuration values
            
        Returns:
            UserLabelingConfig instance with values from dictionary
        """
        return cls(**config_dict)
    
    @classmethod
    def from_json_file(cls, file_path: Path) -> "UserLabelingConfig":
        """
        Load configuration from JSON file.
        
        Args:
            file_path: Path to JSON configuration file
            
        Returns:
            UserLabelingConfig instance loaded from file
            
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
            "rent_amount_threshold": self.rent_amount_threshold,
            "utility_amount_min": self.utility_amount_min,
            "utility_amount_max": self.utility_amount_max,
            "loan_amount_threshold": self.loan_amount_threshold,
            "family_support_amount_threshold": self.family_support_amount_threshold,
        }
    
    def to_json_file(self, file_path: Path) -> None:
        """
        Save configuration to JSON file.
        
        Args:
            file_path: Path where JSON file should be saved
        """
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
