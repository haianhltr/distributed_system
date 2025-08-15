"""Simple test runner for bot tests."""

import sys
import importlib
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def run_test_module(module_name):
    """Run a specific test module."""
    try:
        print(f"\n=== Running {module_name} ===")
        module = importlib.import_module(f"tests.{module_name}")
        
        # Find and run test functions
        test_functions = [
            getattr(module, name) for name in dir(module) 
            if name.startswith('test_') and callable(getattr(module, name))
        ]
        
        if not test_functions:
            print(f"No test functions found in {module_name}")
            return False
        
        passed = 0
        failed = 0
        
        for test_func in test_functions:
            try:
                print(f"Running {test_func.__name__}...")
                test_func()
                print(f"  PASSED: {test_func.__name__}")
                passed += 1
            except Exception as e:
                print(f"  FAILED: {test_func.__name__} - {e}")
                failed += 1
        
        print(f"\nResults for {module_name}: {passed} passed, {failed} failed")
        return failed == 0
        
    except Exception as e:
        print(f"ERROR: Failed to run {module_name}: {e}")
        return False


def main():
    """Run all tests."""
    test_modules = [
        "test_config",
        # Add more test modules here as they're created
    ]
    
    print("Starting bot test suite...")
    
    total_passed = 0
    total_failed = 0
    
    for module in test_modules:
        success = run_test_module(module)
        if success:
            total_passed += 1
        else:
            total_failed += 1
    
    print(f"\n{'='*50}")
    print(f"TEST SUITE SUMMARY")
    print(f"{'='*50}")
    print(f"Modules passed: {total_passed}")
    print(f"Modules failed: {total_failed}")
    print(f"Overall result: {'PASS' if total_failed == 0 else 'FAIL'}")
    
    return total_failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)