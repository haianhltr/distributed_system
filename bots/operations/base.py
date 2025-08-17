"""
Base interface for bot operation plugins.
"""

from abc import ABC, abstractmethod


class Operation(ABC):
    """Base class for all job operations."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Return the operation name."""
        pass
    
    @abstractmethod
    def execute(self, a: int, b: int) -> int:
        """
        Execute the operation on two integers.
        
        Args:
            a: First operand
            b: Second operand
            
        Returns:
            Result of the operation
            
        Raises:
            ValueError: If operation cannot be performed with given inputs
            ArithmeticError: If operation results in mathematical error
        """
        pass
    
    def validate_inputs(self, a: int, b: int) -> None:
        """
        Validate inputs before execution (override if needed).
        
        Args:
            a: First operand
            b: Second operand
            
        Raises:
            ValueError: If inputs are invalid for this operation
        """
        pass