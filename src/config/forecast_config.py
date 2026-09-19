"""
Forecast configuration data class

This module defines all forecasting parameters as required by Requirement 13.14.
"""

from dataclasses import dataclass
from typing import Dict, Any
import json
from pathlib import Path


@dataclass
class ForecastConfig:
    """
    Configuration for amount forecasting.
    
    All forecasting parameters must be loaded from configuration files
    (Requirement 13.14, 13.21).
    
    Attributes:
        recency_decay_factor: Exponential decay factor for recency weighting
                             in weighted moving average (0 < factor < 1)
        days_per_month: Standard month length for pro-rating periodic expenses
    """
    
    # Weighted moving average parameters
    recency_decay_factor: float = 0.8  # Exponential decay for recency weighting
    
    # Pro-rating parameters
    days_per_month: float = 30.0       # Standard month length for pro-rating
    
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "ForecastConfig":
        """
        Load configuration from dictionary.
        
        Args:
            config_dict: Dictionary containing configuration values
            
        Returns:
            ForecastConfig instance with values from dictionary
        """
        return cls(**config_dict)
    
    @classmethod
    def from_json_file(cls, file_path: Path) -> "ForecastConfig":
        """
        Load configuration from JSON file.
        
        Args:
            file_path: Path to JSON configuration file
            
        Returns:
            ForecastConfig instance loaded from file
            
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
            "recency_decay_factor": self.recency_decay_factor,
            "days_per_month": self.days_per_month,
        }
    
    def to_json_file(self, file_path: Path) -> None:
        """
        Save configuration to JSON file.
        
        Args:
            file_path: Path where JSON file should be saved
        """
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
