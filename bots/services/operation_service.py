"""
Operation service for loading and executing job operations.
"""

import importlib
import importlib.util
from pathlib import Path
from typing import Dict, Optional
import logging

from ..operations.base import Operation

logger = logging.getLogger(__name__)


class OperationService:
    """Service for loading and executing operations."""
    
    def __init__(self):
        self.operations: Dict[str, Operation] = {}
        self._loaded = False
        self._operations_dir = Path(__file__).parent.parent / "operations"
    
    def load_operations(self) -> Dict[str, Operation]:
        """Load all operation plugins."""
        if self._loaded:
            return self.operations
        
        logger.info(f"Loading operations from {self._operations_dir}")
        
        if not self._operations_dir.exists():
            logger.warning(f"Operations directory {self._operations_dir} does not exist")
            return {}
        
        # Find all Python files in operations directory (excluding __init__.py and base.py)
        operation_files = [
            f for f in self._operations_dir.glob("*.py") 
            if f.name not in ["__init__.py", "base.py"]
        ]
        
        for operation_file in operation_files:
            try:
                operation_name = operation_file.stem
                operation_instance = self._load_operation_module(operation_file, operation_name)
                
                if operation_instance:
                    self.operations[operation_name] = operation_instance
                    logger.info(f"Loaded operation: {operation_name}")
                
            except Exception as e:
                logger.error(f"Failed to load operation from {operation_file}: {e}")
                continue
        
        self._loaded = True
        logger.info(f"Loaded {len(self.operations)} operations: {list(self.operations.keys())}")
        return self.operations
    
    def _load_operation_module(self, file_path: Path, operation_name: str) -> Optional[Operation]:
        """Load a single operation module and instantiate the operation class."""
        try:
            # Load module from file
            spec = importlib.util.spec_from_file_location(operation_name, file_path)
            if not spec or not spec.loader:
                logger.error(f"Could not load spec for {operation_name}")
                return None
            
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Look for Operation class in the module
            operation_class = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and 
                    issubclass(attr, Operation) and 
                    attr != Operation):
                    operation_class = attr
                    break
            
            if not operation_class:
                logger.error(f"No Operation class found in {file_path}")
                return None
            
            # Instantiate the operation
            operation_instance = operation_class()
            
            # Verify the operation name matches the filename
            if operation_instance.name != operation_name:
                logger.warning(
                    f"Operation name mismatch: file={operation_name}, "
                    f"class.name={operation_instance.name}"
                )
            
            return operation_instance
            
        except Exception as e:
            logger.error(f"Error loading operation module {file_path}: {e}")
            return None
    
    def get_operation(self, name: str) -> Operation:
        """
        Get operation by name.
        
        Args:
            name: Operation name
            
        Returns:
            Operation instance
            
        Raises:
            KeyError: If operation not found
        """
        if not self._loaded:
            self.load_operations()
        
        if name not in self.operations:
            raise KeyError(f"Operation '{name}' not found. Available: {list(self.operations.keys())}")
        
        return self.operations[name]
    
    def execute_operation(self, operation_name: str, a: int, b: int) -> int:
        """
        Execute an operation with given inputs.
        
        Args:
            operation_name: Name of the operation to execute
            a: First operand
            b: Second operand
            
        Returns:
            Result of the operation
            
        Raises:
            KeyError: If operation not found
            ValueError: If inputs are invalid
            ArithmeticError: If operation results in mathematical error
        """
        operation = self.get_operation(operation_name)
        return operation.execute(a, b)