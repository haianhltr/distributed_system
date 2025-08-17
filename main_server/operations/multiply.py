"""
Multiply operation plugin - multiplies two integers.
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))
from base import Operation


class MultiplyOperation(Operation):
    """Multiply two integers."""
    
    @property
    def name(self) -> str:
        return "multiply"
    
    @property
    def description(self) -> str:
        return "Multiply two integers (a * b)"
    
    def execute(self, a: int, b: int) -> int:
        """Multiply a and b."""
        return a * b