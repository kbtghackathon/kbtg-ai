"""
Categorization Module

This module categorizes transactions using merchant dictionary (Group A)
and pattern-based detection (Group B).
"""

from .categorization_module import (
    CategorizedTransaction,
    CategoryGroup,
    CategorizationModule
)

__all__ = [
    'CategorizedTransaction',
    'CategoryGroup',
    'CategorizationModule'
]
