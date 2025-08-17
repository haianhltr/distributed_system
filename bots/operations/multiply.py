"""Multiply operation plugin for bots."""

from operations.base import Operation


class MultiplyOperation(Operation):
    """Multiply two integers."""
    
    @property
    def name(self) -> str:
        return "multiply"
    
    def execute(self, a: int, b: int) -> int:
        """Multiply a and b."""
        return a * b