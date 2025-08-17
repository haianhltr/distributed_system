# Multi-Operation MVP Implementation

## Overview

This document describes the implementation of the multi-operation system that enables the distributed job processing system to support multiple job operations (sum, subtract, multiply, divide) without hard-coding, with dynamic bot assignment and pluggable operation logic.

## 🎯 MVP Goals Achieved

✅ **Support multiple job operations** without hard-coding  
✅ **Assign each bot to a specific operation** dynamically via the dashboard  
✅ **Maintain per-operation job queues** so bots only claim matching jobs  
✅ **Load operation logic from plugins** in a dedicated folder  
✅ **Allow idle bots with no assignment** to pick up any operation's job (dynamic assignment)

## 🏗️ Architecture Changes

### Database Schema Updates

**Jobs Table:**
```sql
ALTER TABLE jobs ADD COLUMN operation TEXT NOT NULL DEFAULT 'sum';
ALTER TABLE jobs ADD COLUMN version INTEGER DEFAULT 1;
```

**Bots Table:**
```sql
ALTER TABLE bots ADD COLUMN assigned_operation TEXT; -- NULL = unassigned
```

**Results Table:**
```sql
ALTER TABLE results 
RENAME COLUMN sum TO result;
ALTER TABLE results ADD COLUMN operation TEXT NOT NULL;
```

**New Indexes:**
```sql
CREATE INDEX idx_jobs_operation_status_created 
ON jobs(operation, status, created_at) WHERE status = 'pending';

CREATE INDEX idx_bots_assigned_operation 
ON bots(assigned_operation) WHERE assigned_operation IS NOT NULL;
```

### Plugin System Architecture

**Main Server Operations:**
```
main_server/
├── operations/
│   ├── __init__.py
│   ├── base.py           # Operation interface
│   ├── sum.py           # Sum operation plugin
│   ├── subtract.py      # Subtract operation plugin
│   ├── multiply.py      # Multiply operation plugin
│   └── divide.py        # Divide operation plugin
└── plugin_loader.py     # Dynamic plugin loader
```

**Bot Operations (Mirror):**
```
bots/
├── operations/
│   ├── __init__.py
│   ├── base.py
│   ├── sum.py
│   ├── subtract.py
│   ├── multiply.py
│   └── divide.py
└── services/
    └── operation_service.py  # Bot-side operation execution
```

## 🔄 Dynamic Job Claiming Logic

The core innovation is the **atomic job claiming with dynamic assignment**:

```python
async def claim_job(claim_data: JobClaim):
    bot_id = claim_data.bot_id
    
    async with db_manager.get_connection() as conn:
        async with conn.transaction():
            # Get bot assignment status
            bot_info = await conn.fetchrow("""
                SELECT current_job_id, assigned_operation FROM bots 
                WHERE id = $1 AND deleted_at IS NULL
            """, bot_id)
            
            assigned_operation = bot_info['assigned_operation']
            
            if assigned_operation:
                # Bot has assigned operation - claim from that queue only
                claimed_job = await conn.fetchrow("""
                    UPDATE jobs SET status = 'claimed', claimed_by = $1, ...
                    WHERE id = (
                        SELECT id FROM jobs 
                        WHERE status = 'pending' AND operation = $2
                        ORDER BY created_at ASC 
                        FOR UPDATE SKIP LOCKED LIMIT 1
                    ) AND status = 'pending' AND operation = $2
                    RETURNING id, a, b, operation, ...
                """, bot_id, assigned_operation)
            else:
                # Bot unassigned - claim oldest job from any queue
                claimed_job = await conn.fetchrow("""
                    UPDATE jobs SET status = 'claimed', claimed_by = $1, ...
                    WHERE id = (
                        SELECT id FROM jobs 
                        WHERE status = 'pending' 
                        ORDER BY created_at ASC 
                        FOR UPDATE SKIP LOCKED LIMIT 1
                    ) AND status = 'pending'
                    RETURNING id, a, b, operation, ...
                """, bot_id)
                
                # Dynamically assign bot to the operation
                await conn.execute("""
                    UPDATE bots SET assigned_operation = $1 WHERE id = $2
                """, claimed_job['operation'], bot_id)
```

## 🚀 Key Features

### 1. Plugin-Based Operations

**Operation Interface:**
```python
class Operation(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        pass
    
    @abstractmethod
    def execute(self, a: int, b: int) -> int:
        pass
```

**Example Plugin (subtract.py):**
```python
class SubtractOperation(Operation):
    @property
    def name(self) -> str:
        return "subtract"
    
    def execute(self, a: int, b: int) -> int:
        return a - b
```

### 2. Dynamic Plugin Loading

The system automatically discovers and loads operations from the `operations/` folder at startup:

```python
# Scans operations/ directory
operation_files = operations_dir.glob("*.py")

# Loads each plugin dynamically
for operation_file in operation_files:
    operation_instance = load_operation_module(operation_file)
    operations[operation_name] = operation_instance
```

### 3. Bot Assignment Modes

**Assigned Bots:**
- Have `assigned_operation` set (e.g., "multiply")
- Can only claim jobs with matching operation
- Provides operation specialization

**Unassigned Bots:**
- Have `assigned_operation = NULL`
- Can claim any pending job (FIFO across all operations)
- Automatically get assigned to the operation of the first job they claim
- Provides dynamic load balancing

### 4. Race-Condition-Free Implementation

Uses PostgreSQL's `FOR UPDATE SKIP LOCKED` to ensure atomic job claiming:
- Multiple bots can't claim the same job
- No deadlocks between concurrent claim attempts
- Operation-specific queues maintained atomically

## 📊 API Endpoints

### New Endpoints

**Operations Management:**
- `GET /operations` - List available operations
- `POST /bots/{bot_id}/assign-operation` - Assign/unassign bot operation

**Enhanced Endpoints:**
- `POST /jobs/populate` - Now accepts `operation` parameter
- `POST /jobs/claim` - Now supports dynamic assignment logic
- `GET /bots` - Now includes `assigned_operation` field

### Dashboard Integration

**New Dashboard Features:**
- Operation selector when creating jobs
- Bot assignment dropdown on bot detail pages
- Operation badges and color coding
- "Unassigned" mode support

## 🧪 Testing

### Test Coverage

**Multi-Operation Test Script:** `testing/test_multi_operations.py`
- Tests all operation plugins work correctly
- Verifies dynamic assignment for unassigned bots
- Confirms assigned bots respect operation constraints
- Validates operation execution correctness

**Quick MVP Test:** `scripts/test_mvp.py`
- Rapid validation of core MVP features
- Suitable for CI/CD integration

### Test Scenarios

1. **Plugin Discovery:** Drop `modulo.py` into `operations/` → system loads it automatically
2. **Assigned Bot Constraint:** Bot assigned to "multiply" only claims multiply jobs
3. **Dynamic Assignment:** Unassigned bot claims first available job, gets assigned to that operation
4. **Backward Compatibility:** Default "sum" operation still works without changes
5. **Mixed Workloads:** Multiple operations running concurrently with different bot assignments

## 📈 Benefits

### For Operations Teams
- **Zero-downtime operation addition** - drop plugin file, restart service
- **Flexible bot allocation** - assign bots to specific operations or let them auto-balance
- **Clear observability** - see which bots are working on which operations

### For Developers
- **Plugin architecture** - operations are isolated and testable
- **Type safety** - strong typing with Pydantic models
- **Race-condition free** - atomic database operations prevent conflicts

### For System Performance
- **Efficient querying** - operation-specific indexes optimize job lookups
- **Load balancing** - unassigned bots automatically balance across operations
- **Scalability** - each operation can scale independently

## 🔧 Deployment

### Rollout Steps

1. **Database Migration:**
   ```bash
   psql -d distributed_system -f scripts/migration_001_add_operations.sql
   ```

2. **Deploy Main Server:**
   - Operations loaded automatically from `main_server/operations/`
   - Existing jobs default to "sum" operation

3. **Deploy Bots:**
   - Bot operations loaded from `bots/operations/`
   - Existing bots remain unassigned (can claim any job)

4. **Dashboard Update:**
   - New operation management UI
   - Bot assignment controls

### Configuration

**Environment Variables:**
- No new configuration required
- All operations discovered automatically
- Bot assignments managed via API/dashboard

## 🎯 Success Criteria Met

✅ **Can drop subtract.py into operations/ without core code changes**  
✅ **Bot with assigned operation processes only that type**  
✅ **Bot with no assigned operation picks first available job from any queue, adopts its operation**  
✅ **Dashboard shows bot's current assignment (even if auto-assigned)**  
✅ **Default sum-only flow still works without disruption**  
✅ **Atomic claim logic still race-free**  

## 🚀 Future Enhancements

- **Multi-operation bots** - bots that can handle multiple operations
- **Priority queues** - some operations prioritized over others
- **Dynamic plugin reload** - hot-swap operations without restart
- **Operation-specific configuration** - different failure rates, timeouts per operation
- **Advanced scheduling** - smart assignment based on bot performance history

This implementation successfully delivers the MVP requirements while maintaining the robust, production-ready architecture of the original system.