● Complete Architecture Review: Distributed Job Processing System

  System Overview

  This is a production-ready distributed job processing system with 4 core 
  components coordinating through a PostgreSQL database to execute computational
  tasks across multiple worker nodes.

  1. Main Server (main_server/main.py) - Control Plane

  Core Responsibilities

  - Job Lifecycle Management: Creates, tracks, and coordinates job execution
  - Bot Registration & Heartbeat Monitoring: Maintains worker pool health
  - Atomic Job Distribution: Ensures exactly-once job assignment
  - Results Collection: Dual-path storage (database + datalake)

  Key Architectural Patterns

  # Atomic job claiming with database transactions
  async with conn.transaction():
      # Check bot availability
      # Find pending job
      # Atomically assign job to bot
      # Update both job and bot states

  API Surface (FastAPI-based)

  - Job Operations: /jobs/claim, /jobs/{id}/start, /jobs/{id}/complete,
  /jobs/{id}/fail
  - Bot Operations: /bots/register, /bots/heartbeat, /bots/{id}
  - Admin Operations: /jobs/populate, /bots/cleanup, /bots/reset
  - Observability: /metrics, /healthz

  Background Processes

  - Auto Job Population: Every 10 minutes (configurable)
  - Dead Bot Detection: 2-minute heartbeat timeout
  - Connection Pool Management: 5-20 PostgreSQL connections

  2. Worker Bots (bots/bot.py) - Execution Layer

  State Machine Architecture

  INITIALIZING → REGISTERING → HEALTH_CHECK → READY → PROCESSING
       ↓              ↓             ↓           ↑         ↓
     ERROR ←──────────────────────────────────────────────┘

  Resilience Patterns

  - Circuit Breakers: Separate breakers for registration, heartbeats, job
  claiming
  - Exponential Backoff: Configurable retry with jitter
  - Health Monitoring: Multi-layer health checks (registration, connectivity,
  database)
  - Graceful Degradation: State-aware error recovery

  Job Processing Flow

  1. Claim Phase: Atomic job acquisition via POST /jobs/claim
  2. Start Phase: Job status transition via POST /jobs/{id}/start
  3. Processing: Configurable duration (default 5 minutes)
  4. Completion: Success/failure reporting with metrics

  Configuration Management

  BOT_ID=bot-unique-id
  MAIN_SERVER_URL=http://main-server:3001
  HEARTBEAT_INTERVAL_MS=30000
  PROCESSING_DURATION_MS=300000
  FAILURE_RATE=0.15  # Simulated failure rate

  3. Database Layer (database.py) - State Management

  Schema Design

  -- Core job coordination
  CREATE TABLE jobs (
      id TEXT PRIMARY KEY,                    -- UUID-based job IDs
      a INTEGER, b INTEGER,                   -- Task parameters
      status TEXT CHECK (status IN (...)),   -- Lifecycle state
      claimed_by TEXT,                        -- Bot assignment
      -- Comprehensive timestamp tracking
      created_at, claimed_at, started_at, finished_at TIMESTAMP,
      attempts INTEGER DEFAULT 0,            -- Retry tracking
      error TEXT                             -- Failure diagnostics
  );

  -- Bot pool management
  CREATE TABLE bots (
      id TEXT PRIMARY KEY,
      status TEXT CHECK (status IN ('idle', 'busy', 'down')),
      current_job_id TEXT,                   -- One-to-one job assignment
      last_heartbeat_at TIMESTAMP,           -- Liveness detection
      created_at, deleted_at TIMESTAMP       -- Soft delete pattern
  );

  -- Analytics and audit trail
  CREATE TABLE results (
      id TEXT PRIMARY KEY,
      job_id TEXT NOT NULL,                  -- Links to jobs table
      a, b, sum INTEGER,                     -- Denormalized task data
      processed_by TEXT,                     -- Bot attribution
      processed_at TIMESTAMP,               -- Completion time
      duration_ms INTEGER,                   -- Performance tracking
      status TEXT, error TEXT               -- Result validation
  );

  Performance Optimizations

  - Strategic Indexing: Status-based queries, time-series analysis, bot
  assignments
  - Unique Constraints: UNIQUE(current_job_id) WHERE current_job_id IS NOT NULL       
  prevents double-assignment
  - Connection Pooling: Async connection pool (5-20 connections, 60s timeout)

  4. Dashboard (dashboard/main.py) - Observability & Control

  Multi-Environment Scaling

  The dashboard intelligently detects deployment environment and uses appropriate     
   scaling:

  1. Kubernetes Production: Uses K8s API for HPA-based scaling
  2. Docker Compose Development: Container-based bot spawning
  3. Local Development: Direct subprocess management

  # Smart scaling detection
  if K8S_AVAILABLE and is_k8s_available():
      # Production Kubernetes scaling
  elif os.path.exists("/.dockerenv"):
      # Containerized environment
  elif compose_file.exists():
      # Docker Compose host
  else:
      # Local subprocess fallback

  Real-time Monitoring

  - System Metrics: Job counts by status, bot health, throughput analysis
  - Bot Management: Individual bot performance, health checks, scaling controls       
  - Job Operations: Status filtering, lifecycle tracking, failure analysis
  - Infrastructure Status: Scaling method detection, capacity planning

  Web Interface Architecture

  - Backend: FastAPI with async request handling
  - Frontend: Jinja2 templates + Tailwind CSS
  - Real-time Updates: 10-second polling, status badge system
  - Analytics: Chart.js for performance visualization

  5. Data Flow Architecture

  Job Processing Pipeline

  Job Creation → Database (pending) → Bot Claim (atomic) → Processing → Results →     
   Datalake
       ↓              ↓                    ↓                ↓          ↓
  ↓
  Dashboard ← Job Tracking ← Bot Assignment ← Status Updates ← Metrics ←
  Analytics

  Coordination Patterns

  - Database-Centric: All coordination flows through PostgreSQL ACID transactions     
  - Event-Driven: Status changes trigger downstream actions
  - Heartbeat-Based: 30-second liveness detection with 2-minute timeout
  - Atomic Operations: Race condition prevention through transaction isolation        

  Data Storage Strategy

  Operational Data → PostgreSQL (ACID, real-time queries)
       ↓
  Analytics Data → NDJSON Datalake (append-only, time-partitioned)
       ↓
  Results-YYYY-MM-DD.ndjson (daily partitions, streaming compatible)

  6. Failure Modes & Recovery

  Network Partitions

  - Circuit Breakers: Prevent cascade failures
  - Retry Logic: Exponential backoff with configurable limits
  - Health Checks: Multi-layer verification (registration, connectivity,
  database)

  Bot Failures

  - Heartbeat Monitoring: 2-minute timeout detection
  - Job Recovery: Orphaned jobs returned to pending state
  - Graceful Shutdown: Clean termination with job failure reporting

  System Recovery

  - Admin Operations: Bot cleanup, state reset, job population
  - Soft Deletes: Non-destructive bot removal
  - Connection Resilience: Automatic pool recreation on database reconnection

  7. Production Considerations

  Scalability

  - Horizontal Bot Scaling: Environment-aware deployment (K8s, Docker,
  subprocess)
  - Database Connection Pooling: Configurable pool sizing
  - Time-Partitioned Storage: Daily datalake partitions for performance

  Observability

  - Structured Logging: JSON-formatted logs with correlation IDs
  - Metrics Endpoints: Prometheus-compatible metrics
  - Health Checks: Comprehensive system health monitoring
  - Performance Tracking: Duration analysis, success rates, throughput metrics        

  Security

  - Bearer Token Auth: Admin operation protection
  - CORS Configuration: Cross-origin request handling
  - Input Validation: Pydantic model validation
  - Error Boundary: Graceful error handling with user feedback

  This architecture demonstrates enterprise-grade distributed system patterns
  with comprehensive failure handling, observability, and operational controls        
  suitable for production workloads.