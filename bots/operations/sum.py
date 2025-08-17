"""Sum operation plugin for bots."""

from operations.base import Operation


class SumOperation(Operation):
    """Add two integers together."""
    
    @property
    def name(self) -> str:
        return "sum"
    
    def execute(self, a: int, b: int) -> int:
        """Add two integers."""
        return a + b