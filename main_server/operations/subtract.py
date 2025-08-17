"""
Subtract operation plugin - subtracts second integer from first.
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))
from base import Operation


class SubtractOperation(Operation):
    """Subtract second integer from first."""
    
    @property
    def name(self) -> str:
        return "subtract"
    
    @property
    def description(self) -> str:
        return "Subtract second integer from first (a - b)"
    
    def execute(self, a: int, b: int) -> int:
        """Subtract b from a."""
        return a - b