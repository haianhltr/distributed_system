"""Apply the bot health status migration to fix job release bug."""

import asyncio
import sys
import os
from pathlib import Path

import asyncpg


async def apply_migration():
    """Apply the bot health status migration."""
    db_url = os.getenv("DATABASE_URL", 'postgresql://ds_user:ds_password@localhost:5432/distributed_system')
    
    print("Connecting to database...")
    
    try:
        # Read the migration SQL file
        migration_file = Path(__file__).parent / "migration_002_add_bot_health_status.sql"
        if not migration_file.exists():
            print(f"Error: Migration file not found at {migration_file}")
            return False
            
        with open(migration_file, 'r') as f:
            migration_sql = f.read()
        
        # Connect to database
        conn = await asyncpg.connect(db_url)
        
        print("Applying migration 002: Fix bot health status constraint...")
        
        # Execute migration
        await conn.execute(migration_sql)
        
        # Verify the constraint was updated
        result = await conn.fetchrow("""
            SELECT conname, pg_get_constraintdef(oid) as definition
            FROM pg_constraint
            WHERE conname = 'bots_health_status_check'
            AND conrelid = 'bots'::regclass
        """)
        
        if result:
            print(f"[OK] Constraint updated: {result['definition']}")
        else:
            print("[ERROR] Constraint not found - this might indicate an error")
            
        # Check migration log
        migration_logged = await conn.fetchrow("""
            SELECT * FROM migration_log 
            WHERE migration_name = '002_fix_bot_health_status'
        """)
        
        if migration_logged:
            print(f"[OK] Migration recorded in log at {migration_logged['applied_at']}")
        
        print("\n[SUCCESS] Migration 002 applied successfully!")
        print("The job release bug should now be fixed.")
        
        await conn.close()
        return True
        
    except Exception as e:
        print(f'\n[ERROR] Migration failed: {e}')
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(apply_migration())
    sys.exit(0 if success else 1)