"""
Sum operation plugin - adds two integers.

This is the default operation for backward compatibility.
"""

import sys
import os
sys.path.append(os.path.dirname(__file__))
from base import Operation


class SumOperation(Operation):
    """Add two integers together."""
    
    @property
    def name(self) -> str:
        return "sum"
    
    @property
    def description(self) -> str:
        return "Add two integers (a + b)"
    
    def execute(self, a: int, b: int) -> int:
        """Add two integers."""
        return a + b