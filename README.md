# Distributed Job Processing System

A distributed system for processing computational jobs with multiple worker bots, built with **Python FastAPI** and PostgreSQL. Features automatic resource cleanup and comprehensive monitoring.

## Architecture

- **Main Server**: Generates jobs every 10 minutes and manages job/bot state
- **Bots**: Worker processes that claim and process one job at a time
- **Dashboard**: Web UI for monitoring and controlling the system
- **Datalake**: Append-only storage for all job results
- **State**: Centralized PostgreSQL database for job and bot coordination
- **Cleanup Service**: Automated resource management and orphaned data cleanup

## Technology Stack

- **Backend**: Python 3.11 + FastAPI
- **Database**: PostgreSQL with ACID transactions
- **Storage**: NDJSON files (date-partitioned)
- **Frontend**: Jinja2 templates + Tailwind CSS + Alpine.js
- **HTTP Client**: aiohttp for async operations
- **Deployment**: Docker Compose
- **Type Safety**: Pydantic models with validation
- **Monitoring**: Structured logging with cleanup tracking

## Quick Start

### 🚀 One-Command Start

**Development Mode (Recommended for local testing):**

**Windows:**
```batch
start-dev-python.bat
```

**Linux/Mac:**
```bash
./start-dev-python.sh
```

**Docker Mode (if Docker Desktop is working):**
```bash
docker-compose up --build -d
```

This starts the complete system:
- Main Server on port 3001
- Dashboard on port 3002  
- 3 bots automatically
- All with persistent data volumes

### 📊 Access Points

- **Dashboard:** http://localhost:3002
- **API:** http://localhost:3001
- **Health Check:** http://localhost:3001/healthz
- **Cleanup Management:** http://localhost:3002/cleanup

### 🛠️ Management Commands

```bash
# View logs
docker-compose logs -f

# Check status  
docker-compose ps

# Stop system
docker-compose down

# Stop and remove volumes
docker-compose down -v
```

### Development Mode (Optional)

For local development without Docker:

1. Install dependencies:
```bash
npm install
cd main_server && npm install
cd ../bots && npm install  
cd ../dashboard && npm install
```

2. Start services in separate terminals:
```bash
# Terminal 1: Main Server
cd main_server && npm run dev

# Terminal 2: Dashboard
cd dashboard && npm run dev

# Terminal 3: Bot
cd bots && npm run dev
```

## System Behavior

- **Job Creation**: Every 10 minutes, 5 new jobs are created (configurable)
- **Job Processing**: Each job takes exactly 5 minutes to process
- **Failure Rate**: 15% of jobs fail randomly (configurable)
- **One-at-a-Time**: Each bot processes only one job at a time
- **Atomic Claims**: Jobs are claimed atomically to prevent conflicts
- **Heartbeats**: Bots send heartbeats every 30 seconds
- **Downtime Detection**: Bots are marked down after 2 minutes without heartbeat

## API Endpoints

### Main Server (Port 3001)

#### Jobs
- `POST /jobs/populate` - Create new job batch (admin)
- `GET /jobs` - List jobs (with status filter)
- `GET /jobs/:id` - Get specific job
- `POST /jobs/claim` - Atomically claim a job
- `POST /jobs/:id/start` - Start processing
- `POST /jobs/:id/complete` - Mark job complete
- `POST /jobs/:id/fail` - Mark job failed

#### Bots
- `POST /bots/register` - Register new bot
- `POST /bots/heartbeat` - Send heartbeat
- `DELETE /bots/:id` - Delete bot (admin)
- `GET /bots` - List all bots

#### Metrics
- `GET /metrics/summary` - System overview
- `GET /datalake/stats` - Datalake statistics
- `GET /datalake/export/:date` - Export results for date

#### Cleanup (Admin)
- `GET /admin/cleanup/status` - Cleanup service status and history
- `POST /admin/cleanup` - Trigger cleanup (with dry_run parameter)
- `POST /admin/query` - Execute safe database queries

### Dashboard (Port 3002)

- `/` - Main overview
- `/bots` - Bot management
- `/bots/:id` - Bot details
- `/jobs` - Job listing
- `/jobs/:id` - Job details
- `/cleanup` - Resource cleanup management

## Configuration

Environment variables (see `docker-compose.yml`):

**Core System:**
- `POPULATE_INTERVAL_MS` - Job creation interval (default: 10 minutes)
- `BATCH_SIZE` - Jobs per batch (default: 5)
- `PROCESSING_DURATION_MS` - Job processing time (default: 5 minutes)
- `FAILURE_RATE` - Random failure rate (default: 0.15)
- `HEARTBEAT_INTERVAL_MS` - Bot heartbeat interval (default: 30 seconds)
- `ADMIN_TOKEN` - Admin API token (default: admin-secret-token)

**Cleanup System:**
- `BOT_RETENTION_DAYS` - Days to keep deleted bot records (default: 7)
- `CLEANUP_INTERVAL_HOURS` - Hours between cleanup runs (default: 6)
- `CONTAINER_CLEANUP_ENABLED` - Enable Docker container cleanup (default: true)
- `CLEANUP_DRY_RUN` - Run in preview mode only (default: false)

## Data Storage

### Database (PostgreSQL)
- **Jobs table**: job state and metadata with atomic claiming
- **Bots table**: bot registration, heartbeats, and soft deletes
- **Results table**: completed job results with performance metrics

### Datalake (NDJSON files)
- Append-only job results
- Partitioned by date (YYYY-MM-DD)
- Location: `datalake/data/results-YYYY-MM-DD.ndjson`

## Scaling

### Add More Bots

**Development:**
```bash
BOT_ID=my-bot-3 npm run dev
```

**Dashboard:**
Use "Add Bot" button or scale up controls

**Docker:**
```bash
docker-compose up -d --scale bot-1=5
```

### Configuration Tuning

- Reduce `PROCESSING_DURATION_MS` for faster throughput
- Increase `BATCH_SIZE` for more jobs per interval
- Adjust `FAILURE_RATE` for testing resilience

## Monitoring

- **Dashboard Overview**: Real-time job/bot counts and throughput
- **Bot Status**: Heartbeat monitoring and downtime detection
- **Job Tracking**: Status transitions and processing history
- **Datalake Stats**: Success rates and performance metrics
- **Cleanup Management**: Automated resource cleanup with history tracking
- **Orphaned Resources**: Detection and removal of stale data

## Resource Management

### Cleanup System

The system includes automated cleanup to prevent resource accumulation:

- **Database Cleanup**: Removes bot records older than retention period
- **Container Cleanup**: Removes stopped/orphaned Docker containers  
- **Orphaned Results**: Cleans up results referencing deleted bots
- **Scheduled Execution**: Runs automatically every 6 hours
- **Web Interface**: Manual control via dashboard at `/cleanup`
- **History Tracking**: Maintains log of all cleanup operations

### Manual Cleanup

```bash
# Monitor cleanup operations
./scripts/monitor-cleanup.sh

# Trigger cleanup (dry run)
curl -X POST http://localhost:3001/admin/cleanup?dry_run=true \
  -H "Authorization: Bearer admin-secret-token"

# Execute cleanup
curl -X POST http://localhost:3001/admin/cleanup?dry_run=false \
  -H "Authorization: Bearer admin-secret-token"
```

## Production Considerations

- ✅ **PostgreSQL**: Production-ready database with ACID transactions
- ✅ **Resource Cleanup**: Automated cleanup prevents data accumulation
- ✅ **Monitoring**: Comprehensive dashboard and API metrics
- **TODO**: Add proper authentication/authorization beyond admin token
- **TODO**: Implement log aggregation and alerting
- **TODO**: Add automated scaling based on queue depth
- **TODO**: Set up Prometheus/Grafana monitoring stack

## Development

```bash
# Run tests
npm test

# Start all services
npm run dev:all

# Check system health
curl http://localhost:3001/healthz
curl http://localhost:3000/healthz
```