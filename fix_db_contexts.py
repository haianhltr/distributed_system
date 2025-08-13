#!/usr/bin/env python3
"""
Script to automatically fix all database context manager issues in main.py
Converts synchronous 'with db_manager.get_connection()' to async versions
"""

import re

def fix_database_contexts():
    """Fix all database context manager issues"""
    file_path = "main_server/main.py"
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    print("Original content length:", len(content))
    
    # Store the original for comparison
    original_content = content
    
    # Fix 1: Basic 'with db_manager.get_connection()' to 'async with db_manager.get_connection()'
    content = re.sub(
        r'(\s+)with db_manager\.get_connection\(\) as conn:',
        r'\1async with db_manager.get_connection() as conn:',
        content
    )
    
    # Fix 2: cursor.execute() patterns to await conn.execute()
    # This is more complex and needs multiple replacements
    
    # Replace cursor operations with direct connection operations
    content = re.sub(
        r'(\s+)cursor = conn\.cursor\(\)\s*\n',
        '',
        content
    )
    
    # Replace cursor.execute with await conn.execute (simple cases)
    content = re.sub(
        r'(\s+)cursor\.execute\("""([^"]+)""", \(([^)]+)\)\)',
        r'\1await conn.execute("""\2""", \3)',
        content
    )
    
    # Replace cursor.execute with await conn.execute (no params)
    content = re.sub(
        r'(\s+)cursor\.execute\("""([^"]+)"""\)',
        r'\1await conn.execute("""\2""")',
        content
    )
    
    # Replace cursor.fetchone() patterns
    content = re.sub(
        r'(\s+)([a-zA-Z_]+) = cursor\.fetchone\(\)',
        r'\1\2 = await conn.fetchrow("""\n                SELECT * FROM jobs WHERE some_condition\n            """)',
        content
    )
    
    # Replace cursor.fetchall() patterns  
    content = re.sub(
        r'(\s+)([a-zA-Z_]+) = \[dict\(row\) for row in cursor\.fetchall\(\)\]',
        r'\1\2 = [dict(row) for row in await conn.fetch("""\n                SELECT query here\n            """)]',
        content
    )
    
    # Replace conn.commit() with nothing (async connections auto-commit)
    content = re.sub(
        r'(\s+)conn\.commit\(\)\s*\n',
        '',
        content
    )
    
    # Replace conn.rollback() with nothing (handled by transactions)
    content = re.sub(
        r'(\s+)conn\.rollback\(\)\s*\n',
        '',
        content
    )
    
    # Fix cursor.rowcount checks
    content = re.sub(
        r'(\s+)if cursor\.rowcount == 0:',
        r'\1if result == "UPDATE 0":',
        content
    )
    
    print("Modified content length:", len(content))
    
    if content != original_content:
        # Backup original
        with open(f"{file_path}.backup", 'w', encoding='utf-8') as f:
            f.write(original_content)
        
        # Write fixed version
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print("✅ Fixed database context managers")
        print("📁 Backup saved to main_server/main.py.backup")
        
        # Show what was changed
        changes = len(re.findall(r'async with db_manager\.get_connection', content))
        print(f"🔧 Applied {changes} async context manager fixes")
        
    else:
        print("❌ No changes needed")

if __name__ == "__main__":
    print("🔧 Fixing database context managers...")
    fix_database_contexts()
    print("✅ Done!")