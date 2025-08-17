"""
Divide operation plugin - divides first integer by second (integer division).
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))
from base import Operation


class DivideOperation(Operation):
    """Divide first integer by second (integer division)."""
    
    @property
    def name(self) -> str:
        return "divide"
    
    @property
    def description(self) -> str:
        return "Divide first integer by second using integer division (a // b)"
    
    def validate_inputs(self, a: int, b: int) -> None:
        """Validate that we're not dividing by zero."""
        if b == 0:
            raise ValueError("Division by zero is not allowed")
    
    def execute(self, a: int, b: int) -> int:
        """Divide a by b using integer division."""
        self.validate_inputs(a, b)
        return a // b