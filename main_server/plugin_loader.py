"""
Plugin loader for dynamically loading operation modules.

Scans the operations/ directory and loads all valid operation plugins.
"""

import os
import sys
import importlib
import importlib.util
from pathlib import Path
from typing import Dict, List, Type, Any
import logging

from operations.base import Operation

logger = logging.getLogger(__name__)


class PluginLoader:
    """Dynamically loads and manages operation plugins."""
    
    def __init__(self, operations_dir: str = "operations"):
        self.operations_dir = Path(operations_dir)
        self.operations: Dict[str, Operation] = {}
        self._loaded = False
    
    def load_operations(self) -> Dict[str, Operation]:
        """
        Load all operation plugins from the operations directory.
        
        Returns:
            Dictionary mapping operation names to operation instances
        """
        if self._loaded:
            return self.operations
        
        logger.info(f"Loading operations from {self.operations_dir}")
        
        if not self.operations_dir.exists():
            logger.warning(f"Operations directory {self.operations_dir} does not exist")
            return {}
        
        # Find all Python files in operations directory (excluding __init__.py and base.py)
        operation_files = [
            f for f in self.operations_dir.glob("*.py") 
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
    
    def _load_operation_module(self, file_path: Path, operation_name: str) -> Operation:
        """
        Load a single operation module and instantiate the operation class.
        
        Args:
            file_path: Path to the operation Python file
            operation_name: Expected name of the operation
            
        Returns:
            Operation instance or None if loading failed
        """
        try:
            # Add the operations directory to Python path temporarily
            operations_dir = str(file_path.parent)
            if operations_dir not in sys.path:
                sys.path.insert(0, operations_dir)
            
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
                try:
                    if (isinstance(attr, type) and 
                        hasattr(attr, '__mro__') and
                        any(base.__name__ == 'Operation' for base in attr.__mro__) and 
                        attr.__name__ != 'Operation'):
                        operation_class = attr
                        break
                except:
                    continue
            
            if not operation_class:
                logger.error(f"No Operation class found in {file_path}")
                # Debug: show what classes we found
                classes = [attr for attr in dir(module) if isinstance(getattr(module, attr, None), type)]
                logger.error(f"Classes found: {classes}")
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
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
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
    
    def get_operation_names(self) -> List[str]:
        """
        Get list of all available operation names.
        
        Returns:
            List of operation names
        """
        if not self._loaded:
            self.load_operations()
        
        return list(self.operations.keys())
    
    def get_operations_metadata(self) -> List[Dict[str, Any]]:
        """
        Get metadata for all loaded operations.
        
        Returns:
            List of operation metadata dictionaries
        """
        if not self._loaded:
            self.load_operations()
        
        return [op.get_metadata() for op in self.operations.values()]
    
    def reload_operations(self) -> Dict[str, Operation]:
        """
        Reload all operations (useful for development).
        
        Returns:
            Dictionary mapping operation names to operation instances
        """
        self.operations.clear()
        self._loaded = False
        return self.load_operations()


# Global plugin loader instance
plugin_loader = PluginLoader()