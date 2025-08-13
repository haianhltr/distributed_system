# Distributed Job Processing System

A distributed system for processing computational jobs with multiple worker bots, built with **Python FastAPI** and SQLite.

## Architecture

- **Main Server**: Generates jobs every 10 minutes and manages job/bot state
- **Bots**: Worker processes that claim and process one job at a time
- **Dashboard**: Web UI for monitoring and controlling the system
- **Datalake**: Append-only storage for all job results
- **State**: Centralized database for job and bot coordination

## Technology Stack

- **Backend**: Python 3.11 + FastAPI
- **Database**: SQLite with ACID transactions
- **Storage**: NDJSON files (date-partitioned)
- **Frontend**: Jinja2 templates + Tailwind CSS
- **HTTP Client**: aiohttp for async operations
- **Deployment**: Docker Compose
- **Type Safety**: Pydantic models with validation

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

### Dashboard (Port 3000)

- `/` - Main overview
- `/bots` - Bot management
- `/bots/:id` - Bot details
- `/jobs` - Job listing
- `/jobs/:id` - Job details

## Configuration

Environment variables (see `ops/.env.example`):

- `POPULATE_INTERVAL_MS` - Job creation interval (default: 10 minutes)
- `BATCH_SIZE` - Jobs per batch (default: 5)
- `PROCESSING_DURATION_MS` - Job processing time (default: 5 minutes)
- `FAILURE_RATE` - Random failure rate (default: 0.15)
- `HEARTBEAT_INTERVAL_MS` - Bot heartbeat interval (default: 30 seconds)
- `ADMIN_TOKEN` - Admin API token (default: admin-secret-token)

## Data Storage

### Database (SQLite)
- Jobs table: job state and metadata
- Bots table: bot registration and heartbeats  
- Results table: completed job results

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

## Production Considerations

- Replace SQLite with PostgreSQL for multi-instance deployment
- Add proper authentication/authorization
- Implement log aggregation and monitoring
- Add automated scaling based on queue depth
- Set up data retention policies for datalake
- Add health checks and alerting

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