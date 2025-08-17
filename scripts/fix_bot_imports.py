#!/usr/bin/env python3
"""Fix relative imports in bot code to work with Docker container structure."""

import os
import re

# Root directory for bots
BOTS_DIR = "bots"

# Files to fix
files_to_fix = [
    "bots/services/health_service.py",
    "bots/services/http_client.py", 
    "bots/services/operation_service.py",
    "bots/utils/circuit_breaker.py",
    "bots/utils/retry.py"
]

# Replacement patterns
replacements = [
    (r"from \.\.", "from "),  # Remove relative parent imports
    (r"from \.", "from "),     # Remove relative current imports
]

def fix_imports(file_path):
    """Fix imports in a single file."""
    print(f"Fixing imports in {file_path}")
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    original_content = content
    
    for pattern, replacement in replacements:
        content = re.sub(pattern, replacement, content)
    
    if content != original_content:
        with open(file_path, 'w') as f:
            f.write(content)
        print(f"  ✓ Fixed imports in {file_path}")
    else:
        print(f"  - No changes needed in {file_path}")

if __name__ == "__main__":
    for file_path in files_to_fix:
        if os.path.exists(file_path):
            fix_imports(file_path)
        else:
            print(f"  ✗ File not found: {file_path}")
    
    print("\nImport fixing complete!")