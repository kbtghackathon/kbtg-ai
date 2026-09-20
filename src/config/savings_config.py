"""
Savings recommendation configuration data class.

Follows the shape of DetectionConfig and ForecastConfig, with one deliberate
omission: there is no `from_json_file` and no `config/savings_config.json`.

The existing JSON files in `config/` are not actually loaded anywhere -- the
pipeline always constructs the dataclass defaults -- so shipping another one
would suggest a knob that does nothing. The defaults below are the real
configuration until someone wires loading up for all of them at once.
"""

from dataclasses import dataclass, field
from typing import Any, Dict


# Fractions of the monthly surplus proposed at each aggressiveness level.
# These mirror the levels the app offers the user (SAFE / BALANCED / BOLD) and
# must stay in step with domain.Aggressiveness.Ratio() on the Go side, because
# the Go rule engine is the fallback when this service cannot answer and the
# two should not disagree about what "balanced" means.
DEFAULT_AGGRESSIVENESS_RATIOS: Dict[str, float] = {
    "SAFE": 0.15,
    "BALANCED": 0.30,
    "BOLD": 0.50,
}


@dataclass
class SavingsConfig:
    """
    Configuration for the savings recommendation.

    Attributes:
        aggressiveness_ratios: share of the surplus proposed per level
        default_aggressiveness: level used when the caller sends an unknown one
        max_analysis_months: months of statement that count as complete data
        min_income_months: months of observed income needed to override the
                           declared salary
        months_quality_floor: quality multiplier at zero months of statement
        parse_quality_floor: quality multiplier at a zero parse success rate
        min_data_quality: hard floor on the combined multiplier
    """

    aggressiveness_ratios: Dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_AGGRESSIVENESS_RATIOS)
    )
    default_aggressiveness: str = "BALANCED"

    # Data-quality scoring. The floors are what stop a thin statement from
    # proposing an amount so small the feature looks broken to the user who
    # just uploaded it: one month of real statement is weak evidence, but it
    # is still evidence.
    max_analysis_months: int = 6
    # Months of observed income needed before it may override what the user
    # declared. One payday is not a pattern -- a statement window that happens
    # to catch a single credit, or to cut across paydays, would otherwise
    # rewrite someone's salary off one observation.
    min_income_months: int = 2
    months_quality_floor: float = 0.75
    parse_quality_floor: float = 0.70
    min_data_quality: float = 0.60

    def ratio_for(self, aggressiveness: str) -> float:
        """
        Share of the surplus to propose at this level.

        An unrecognised level falls back to the default rather than to zero: a
        bad value in the caller's settings should make the recommendation
        ordinary, not silently switch saving off.
        """
        key = (aggressiveness or "").strip().upper()

        return self.aggressiveness_ratios.get(
            key,
            self.aggressiveness_ratios.get(self.default_aggressiveness, 0.30),
        )

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "SavingsConfig":
        """Load configuration from a dictionary."""
        return cls(**config_dict)

    def to_dict(self) -> Dict[str, Any]:
        """Export configuration to a dictionary."""
        return {
            "aggressiveness_ratios": dict(self.aggressiveness_ratios),
            "default_aggressiveness": self.default_aggressiveness,
            "max_analysis_months": self.max_analysis_months,
            "min_income_months": self.min_income_months,
            "months_quality_floor": self.months_quality_floor,
            "parse_quality_floor": self.parse_quality_floor,
            "min_data_quality": self.min_data_quality,
        }
