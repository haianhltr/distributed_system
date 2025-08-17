"""Subtract operation plugin for bots."""

from operations.base import Operation


class SubtractOperation(Operation):
    """Subtract second integer from first."""
    
    @property
    def name(self) -> str:
        return "subtract"
    
    def execute(self, a: int, b: int) -> int:
        """Subtract b from a."""
        return a - b