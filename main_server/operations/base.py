"""
Base interface for all job operations.

All operation plugins must implement the Operation interface.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Union


class Operation(ABC):
    """Base class for all job operations."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Return the operation name (must match filename without .py)."""
        pass
    
    @property
    @abstractmethod
    def description(self) -> str:
        """Return a human-readable description of the operation."""
        pass
    
    @property
    def min_inputs(self) -> int:
        """Minimum number of inputs required (default 2 for a, b)."""
        return 2
    
    @property
    def max_inputs(self) -> int:
        """Maximum number of inputs supported (default 2 for a, b)."""
        return 2
    
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
    
    def get_metadata(self) -> Dict[str, Any]:
        """
        Return operation metadata for API exposure.
        
        Returns:
            Dictionary containing operation information
        """
        return {
            "name": self.name,
            "description": self.description,
            "min_inputs": self.min_inputs,
            "max_inputs": self.max_inputs
        }


class GenericOperation(Operation):
    """
    Enhanced operation interface supporting flexible input/output via JSONB.
    
    This extends the base Operation interface to support the new generic
    operation framework while maintaining backward compatibility.
    """
    
    @property
    def input_schema(self) -> Dict[str, Any]:
        """
        JSON Schema for input validation.
        
        Returns:
            JSON Schema dictionary for validating input_data
        """
        # Default schema for backward compatibility (a, b integers)
        return {
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"}
            },
            "required": ["a", "b"],
            "additionalProperties": False
        }
    
    @property
    def output_schema(self) -> Dict[str, Any]:
        """
        JSON Schema for output validation.
        
        Returns:
            JSON Schema dictionary describing expected output format
        """
        # Default schema for backward compatibility (result integer)
        return {
            "type": "object",
            "properties": {
                "result": {"type": "integer"}
            },
            "required": ["result"],
            "additionalProperties": True
        }
    
    @property
    def resource_requirements(self) -> Dict[str, Any]:
        """
        Resource requirements for this operation.
        
        Returns:
            Dictionary with memory_mb, cpu_cores, timeout_seconds, etc.
        """
        return {
            "memory_mb": 100,
            "cpu_cores": 1,
            "timeout_seconds": 30,
            "network_required": False
        }
    
    async def execute_generic(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute operation with flexible input/output using JSONB.
        
        This method should be overridden by operations that want to use
        the new generic interface. For backward compatibility, this default
        implementation calls the legacy execute() method.
        
        Args:
            input_data: Dictionary containing operation inputs
            
        Returns:
            Dictionary containing operation outputs
            
        Raises:
            ValueError: If input_data is invalid
            ArithmeticError: If operation fails
        """
        # Backward compatibility: extract a, b from input_data and call legacy execute
        try:
            a = input_data.get("a")
            b = input_data.get("b")
            
            if a is None or b is None:
                raise ValueError("Missing required inputs 'a' and 'b'")
            
            # Call legacy execute method
            result = self.execute(int(a), int(b))
            
            return {"result": result}
            
        except Exception as e:
            raise ValueError(f"Operation execution failed: {str(e)}")
    
    def validate_input_data(self, input_data: Dict[str, Any]) -> None:
        """
        Validate input data against the input schema.
        
        Args:
            input_data: Dictionary to validate
            
        Raises:
            ValueError: If input_data doesn't match schema
        """
        # Basic validation - could be enhanced with jsonschema library
        schema = self.input_schema
        
        if schema.get("type") == "object":
            required_fields = schema.get("required", [])
            properties = schema.get("properties", {})
            
            # Check required fields
            for field in required_fields:
                if field not in input_data:
                    raise ValueError(f"Missing required field: {field}")
            
            # Basic type checking
            for field, field_schema in properties.items():
                if field in input_data:
                    value = input_data[field]
                    expected_type = field_schema.get("type")
                    
                    if expected_type == "integer" and not isinstance(value, int):
                        raise ValueError(f"Field '{field}' must be an integer")
                    elif expected_type == "string" and not isinstance(value, str):
                        raise ValueError(f"Field '{field}' must be a string")
                    elif expected_type == "number" and not isinstance(value, (int, float)):
                        raise ValueError(f"Field '{field}' must be a number")
    
    def get_enhanced_metadata(self) -> Dict[str, Any]:
        """
        Return enhanced metadata including schemas and resource requirements.
        
        Returns:
            Dictionary containing enhanced operation information
        """
        metadata = self.get_metadata()
        metadata.update({
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "resource_requirements": self.resource_requirements,
            "supports_generic": True
        })
        return metadata