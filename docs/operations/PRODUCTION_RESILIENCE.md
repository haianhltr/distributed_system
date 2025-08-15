# Production Resilience & Design Improvements

## Current Design Flaws

### 1. **Bot State Recovery Issues** 🚨

**Problem**: Bots can restart with stale job assignments, causing "phantom claims"

**Current Behavior**:
```sql
-- Bot shows idle but has stale job assignment
SELECT id, status, current_job_id FROM bots 
WHERE status = 'idle' AND current_job_id IS NOT NULL;
```

**Production Impact**:
- Jobs stuck in "claimed" state indefinitely
- Bots appear available but can't claim new work
- Requires manual database intervention

### 2. **Inadequate Health Checks** 🚨

**Problem**: Health checks only verify HTTP connectivity, not job processing capability

**Current Implementation**:
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:3001/healthz"]
```

**Missing Validations**:
- Database connectivity
- Job claiming capability
- Background task health
- Resource availability

### 3. **Startup Race Conditions** 🚨

**Problem**: No proper service dependency management

**Issues**:
- Bots start before main server is ready
- No connection retry with exponential backoff
- Hard failures on network issues
- No graceful degradation

### 4. **Single Points of Failure** 🚨

**Architecture Issues**:
- Single main server instance
- Single database instance
- No load balancing
- No failover mechanisms

### 5. **No Circuit Breaker Pattern** 🚨

**Problem**: Services retry indefinitely without intelligent failure handling

**Missing Features**:
- Connection circuit breakers
- Adaptive retry strategies
- Failure threshold detection
- Automatic recovery testing

## Production Solutions

### 1. **Self-Healing Bot Recovery** ✅

```python
# Add to bot startup
async def recover_from_stale_state(self):
    """Recover from stale job assignments on startup"""
    try:
        # Check if we have a stale job assignment
        response = await self.session.get(f"{self.server_url}/bots/{self.id}")
        if response.status == 200:
            bot_data = await response.json()
            if bot_data.get('current_job_id') and bot_data.get('status') == 'idle':
                # Clear stale assignment
                await self.session.post(f"{self.server_url}/bots/{self.id}/reset")
                logger.info(f"Recovered from stale job assignment: {bot_data['current_job_id']}")
    except Exception as e:
        logger.warning(f"State recovery failed: {e}")
```

### 2. **Comprehensive Health Checks** ✅

```python
# Enhanced health check endpoint
@app.get("/healthz")
async def health_check():
    checks = {
        "database": await check_database_connection(),
        "job_processing": await check_job_claim_capability(),
        "cleanup_service": await check_cleanup_service(),
        "resource_usage": await check_resource_limits()
    }
    
    all_healthy = all(checks.values())
    status_code = 200 if all_healthy else 503
    
    return Response(
        content=json.dumps({
            "status": "healthy" if all_healthy else "unhealthy",
            "checks": checks,
            "timestamp": datetime.utcnow().isoformat()
        }),
        status_code=status_code,
        media_type="application/json"
    )
```

### 3. **Smart Retry & Circuit Breaker** ✅

```python
class ResilientHttpClient:
    def __init__(self):
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30,
            expected_exception=aiohttp.ClientError
        )
        self.retry_config = ExponentialBackoff(
            initial_delay=1.0,
            max_delay=60.0,
            multiplier=2.0,
            max_attempts=10
        )
    
    async def request_with_resilience(self, method, url, **kwargs):
        """HTTP request with circuit breaker and retry logic"""
        for attempt in range(self.retry_config.max_attempts):
            if not self.circuit_breaker.can_execute():
                raise CircuitBreakerOpen("Service unavailable")
            
            try:
                async with self.session.request(method, url, **kwargs) as response:
                    if response.status < 500:
                        self.circuit_breaker.record_success()
                        return response
                    raise aiohttp.ClientResponseError(
                        request_info=response.request_info,
                        history=response.history,
                        status=response.status
                    )
            except Exception as e:
                self.circuit_breaker.record_failure()
                if attempt < self.retry_config.max_attempts - 1:
                    delay = self.retry_config.get_delay(attempt)
                    logger.warning(f"Request failed, retrying in {delay}s: {e}")
                    await asyncio.sleep(delay)
                else:
                    raise
```

### 4. **High Availability Architecture** ✅

```yaml
# Production docker-compose with HA
version: '3.8'
services:
  # Multiple main server instances
  main-server-1:
    build: ...
    deploy:
      replicas: 3
  
  # Load balancer
  nginx:
    image: nginx:alpine
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
    ports:
      - "80:80"
    depends_on:
      - main-server-1
  
  # PostgreSQL with replication
  postgres-primary:
    image: postgres:16-alpine
    environment:
      - POSTGRES_REPLICATION_MODE=master
  
  postgres-replica:
    image: postgres:16-alpine
    environment:
      - POSTGRES_REPLICATION_MODE=slave
    depends_on:
      - postgres-primary
  
  # Redis for shared state
  redis:
    image: redis:alpine
    deploy:
      replicas: 3
```

### 5. **Kubernetes Production Deployment** ✅

```yaml
# k8s/main-server-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: main-server
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    spec:
      containers:
      - name: main-server
        image: distributed-system-main-server:latest
        ports:
        - containerPort: 3001
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: db-credentials
              key: url
        livenessProbe:
          httpGet:
            path: /healthz
            port: 3001
          initialDelaySeconds: 30
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3
        readinessProbe:
          httpGet:
            path: /ready
            port: 3001
          initialDelaySeconds: 5
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 2
        resources:
          requests:
            memory: "256Mi"
            cpu: "250m"
          limits:
            memory: "512Mi"
            cpu: "500m"

---
apiVersion: v1
kind: Service
metadata:
  name: main-server-service
spec:
  selector:
    app: main-server
  ports:
  - port: 80
    targetPort: 3001
  type: LoadBalancer

---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: main-server-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: main-server
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

## Operational Improvements

### 1. **Observability Stack** 📊

```yaml
# Monitoring with Prometheus + Grafana
services:
  prometheus:
    image: prom/prometheus
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    ports:
      - "9090:9090"
  
  grafana:
    image: grafana/grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    ports:
      - "3000:3000"
    volumes:
      - grafana-storage:/var/lib/grafana

  # Metrics collection
  node-exporter:
    image: prom/node-exporter
    ports:
      - "9100:9100"
```

### 2. **Centralized Logging** 📝

```python
# Structured logging with correlation IDs
import structlog
import uuid

logger = structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer() if DEBUG else structlog.processors.JSONRenderer()
    ]
)

# Add correlation ID to all requests
@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    correlation_id = str(uuid.uuid4())
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
    
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response
```

### 3. **Automated Recovery Procedures** 🔄

```python
# Self-healing job recovery
async def recover_orphaned_jobs():
    """Recover jobs claimed by dead bots"""
    cutoff = datetime.utcnow() - timedelta(minutes=5)
    
    async with db.get_connection() as conn:
        # Find jobs claimed by bots that haven't sent heartbeat
        orphaned_jobs = await conn.fetch("""
            SELECT j.id, j.claimed_by 
            FROM jobs j
            JOIN bots b ON j.claimed_by = b.id
            WHERE j.status = 'claimed' 
            AND b.last_heartbeat_at < $1
        """, cutoff)
        
        for job in orphaned_jobs:
            await conn.execute("""
                UPDATE jobs 
                SET status = 'pending', claimed_by = NULL, claimed_at = NULL
                WHERE id = $1
            """, job['id'])
            
            logger.info("Recovered orphaned job", job_id=job['id'], 
                       bot_id=job['claimed_by'])

# Run recovery every minute
asyncio.create_task(periodic_task(recover_orphaned_jobs, interval=60))
```

### 4. **Database Resilience** 🗄️

```python
# Connection pool with failover
class ResilientDatabaseManager:
    def __init__(self, primary_url: str, replica_urls: List[str]):
        self.primary_url = primary_url
        self.replica_urls = replica_urls
        self.primary_pool = None
        self.replica_pools = []
        self.circuit_breaker = CircuitBreaker()
    
    async def get_connection(self, read_only: bool = False):
        """Get connection with automatic failover"""
        if read_only and self.replica_pools:
            # Try replicas for read operations
            for pool in self.replica_pools:
                try:
                    return await pool.acquire()
                except Exception:
                    continue
        
        # Fallback to primary
        if self.circuit_breaker.can_execute():
            try:
                conn = await self.primary_pool.acquire()
                self.circuit_breaker.record_success()
                return conn
            except Exception as e:
                self.circuit_breaker.record_failure()
                raise DatabaseUnavailable("Primary database unavailable") from e
        
        raise DatabaseUnavailable("All database connections failed")
```

## Disaster Recovery Procedures

### 1. **Service Recovery Runbook** 📋

```bash
#!/bin/bash
# recovery-runbook.sh

echo "=== Distributed System Recovery ==="

# Step 1: Check system status
kubectl get pods -l app=main-server
kubectl get pods -l app=bot-worker

# Step 2: Recover orphaned jobs
kubectl exec deployment/main-server -- python -c "
from recovery import recover_orphaned_jobs
import asyncio
asyncio.run(recover_orphaned_jobs())
"

# Step 3: Scale up if needed
kubectl scale deployment/main-server --replicas=5
kubectl scale deployment/bot-worker --replicas=20

# Step 4: Verify health
for i in {1..10}; do
    curl -f http://main-server-service/healthz || echo "Health check failed"
    sleep 5
done

echo "Recovery complete"
```

### 2. **Automated Alerts** 🚨

```yaml
# Alertmanager rules
groups:
- name: distributed-system
  rules:
  - alert: MainServerDown
    expr: up{job="main-server"} == 0
    for: 30s
    labels:
      severity: critical
    annotations:
      summary: "Main server is down"
      
  - alert: OrphanedJobs
    expr: orphaned_jobs_total > 10
    for: 2m
    labels:
      severity: warning
    annotations:
      summary: "High number of orphaned jobs detected"
      
  - alert: BotFailureRate
    expr: bot_failure_rate > 0.5
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "Bot failure rate is high"
```

## Production Readiness Checklist

### Infrastructure ✅
- [ ] Load balancer configuration
- [ ] Database replication setup
- [ ] Redis cluster for shared state
- [ ] Container registry
- [ ] Kubernetes cluster
- [ ] Monitoring stack (Prometheus/Grafana)
- [ ] Centralized logging (ELK stack)
- [ ] Backup procedures

### Application ✅
- [ ] Health check endpoints
- [ ] Circuit breaker implementation
- [ ] Retry logic with exponential backoff
- [ ] Graceful shutdown handling
- [ ] Resource limits and requests
- [ ] Security hardening
- [ ] Performance testing
- [ ] Load testing

### Operations ✅
- [ ] Deployment automation
- [ ] Rollback procedures
- [ ] Disaster recovery runbooks
- [ ] Monitoring dashboards
- [ ] Alert configurations
- [ ] On-call procedures
- [ ] Incident response plan
- [ ] Capacity planning

This production-ready architecture would handle the bot restart scenario automatically through self-healing mechanisms, proper health checks, and automated recovery procedures.