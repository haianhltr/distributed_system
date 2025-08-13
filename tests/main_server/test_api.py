import pytest
import json
from unittest.mock import patch


@pytest.mark.asyncio
class TestHealthCheck:
    """Test health check endpoint"""
    
    async def test_health_check(self, async_client):
        """Test health check returns success"""
        response = await async_client.get("/healthz")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data


@pytest.mark.asyncio
class TestMetrics:
    """Test metrics endpoint"""
    
    async def test_metrics_endpoint(self, async_client):
        """Test metrics endpoint returns Prometheus format"""
        response = await async_client.get("/metrics")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; version=0.0.4; charset=utf-8"
        
        content = response.text
        assert "jobs_created_total" in content
        assert "jobs_pending_total" in content
        assert "bots_active_total" in content


@pytest.mark.asyncio
class TestJobEndpoints:
    """Test job-related endpoints"""
    
    async def test_populate_jobs_requires_auth(self, async_client):
        """Test job population requires admin token"""
        response = await async_client.post("/jobs/populate", 
            json={"batchSize": 5}
        )
        assert response.status_code == 401
    
    async def test_populate_jobs_with_auth(self, async_client, admin_headers, db_connection):
        """Test job population with valid auth"""
        response = await async_client.post("/jobs/populate",
            json={"batchSize": 3},
            headers=admin_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["created"] == 3
        assert len(data["jobs"]) == 3
        
        # Verify jobs were created in database
        count = await db_connection.fetchval("SELECT COUNT(*) FROM jobs")
        assert count == 3
    
    async def test_get_jobs(self, async_client, sample_job):
        """Test getting job list"""
        response = await async_client.get("/jobs")
        assert response.status_code == 200
        
        jobs = response.json()
        assert len(jobs) == 1
        assert jobs[0]["id"] == sample_job["id"]
        assert jobs[0]["a"] == sample_job["a"]
        assert jobs[0]["b"] == sample_job["b"]
    
    async def test_get_jobs_with_status_filter(self, async_client, sample_job):
        """Test getting jobs with status filter"""
        response = await async_client.get("/jobs?status=pending")
        assert response.status_code == 200
        
        jobs = response.json()
        assert len(jobs) == 1
        assert jobs[0]["status"] == "pending"
        
        response = await async_client.get("/jobs?status=completed")
        assert response.status_code == 200
        
        jobs = response.json()
        assert len(jobs) == 0
    
    async def test_get_jobs_with_pagination(self, async_client, db_connection):
        """Test job pagination"""
        # Create multiple jobs
        for i in range(5):
            await db_connection.execute("""
                INSERT INTO jobs (id, a, b, status, created_at)
                VALUES ($1, $2, $3, 'pending', CURRENT_TIMESTAMP)
            """, f"job-{i}", i, i*2)
        
        # Test first page
        response = await async_client.get("/jobs?limit=2&offset=0")
        assert response.status_code == 200
        jobs = response.json()
        assert len(jobs) == 2
        
        # Test second page  
        response = await async_client.get("/jobs?limit=2&offset=2")
        assert response.status_code == 200
        jobs = response.json()
        assert len(jobs) == 2
    
    async def test_get_single_job(self, async_client, sample_job):
        """Test getting a single job"""
        response = await async_client.get(f"/jobs/{sample_job['id']}")
        assert response.status_code == 200
        
        job = response.json()
        assert job["id"] == sample_job["id"]
        assert job["a"] == sample_job["a"]
        assert job["b"] == sample_job["b"]
    
    async def test_get_nonexistent_job(self, async_client):
        """Test getting a nonexistent job returns 404"""
        response = await async_client.get("/jobs/nonexistent")
        assert response.status_code == 404


@pytest.mark.asyncio
class TestJobWorkflow:
    """Test complete job workflow"""
    
    async def test_job_claim_cycle(self, async_client, sample_job, sample_bot):
        """Test claiming and processing a job"""
        job_id = sample_job["id"]
        bot_id = sample_bot["id"]
        
        # Claim job
        response = await async_client.post(f"/jobs/claim",
            json={"bot_id": bot_id}
        )
        assert response.status_code == 200
        claimed_job = response.json()
        assert claimed_job["id"] == job_id
        assert claimed_job["status"] == "claimed"
        
        # Start job
        response = await async_client.post(f"/jobs/{job_id}/start",
            json={"bot_id": bot_id}
        )
        assert response.status_code == 200
        
        # Complete job
        expected_sum = sample_job["a"] + sample_job["b"]
        response = await async_client.post(f"/jobs/{job_id}/complete",
            json={
                "bot_id": bot_id,
                "sum": expected_sum,
                "duration_ms": 1000
            }
        )
        assert response.status_code == 200
    
    async def test_job_failure_cycle(self, async_client, sample_job, sample_bot):
        """Test job failure workflow"""
        job_id = sample_job["id"]
        bot_id = sample_bot["id"]
        
        # Claim and start job
        await async_client.post(f"/jobs/claim", json={"bot_id": bot_id})
        await async_client.post(f"/jobs/{job_id}/start", json={"bot_id": bot_id})
        
        # Fail job
        response = await async_client.post(f"/jobs/{job_id}/fail",
            json={
                "bot_id": bot_id,
                "error": "Test error message"
            }
        )
        assert response.status_code == 200


@pytest.mark.asyncio  
class TestBotEndpoints:
    """Test bot-related endpoints"""
    
    async def test_bot_registration(self, async_client):
        """Test bot registration"""
        response = await async_client.post("/bots/register",
            json={"bot_id": "new-test-bot"}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["bot_id"] == "new-test-bot"
        assert data["status"] == "registered"
    
    async def test_duplicate_bot_registration(self, async_client, sample_bot):
        """Test duplicate bot registration"""
        response = await async_client.post("/bots/register",
            json={"bot_id": sample_bot["id"]}
        )
        assert response.status_code == 200  # Should update existing bot
    
    async def test_get_bots(self, async_client, sample_bot):
        """Test getting bot list"""
        response = await async_client.get("/bots")
        assert response.status_code == 200
        
        bots = response.json()
        assert len(bots) >= 1
        
        bot_ids = [bot["id"] for bot in bots]
        assert sample_bot["id"] in bot_ids
    
    async def test_bot_heartbeat(self, async_client, sample_bot):
        """Test bot heartbeat"""
        response = await async_client.post("/bots/heartbeat",
            json={"bot_id": sample_bot["id"]}
        )
        assert response.status_code == 200
        
        data = response.json()
        assert data["bot_id"] == sample_bot["id"]
        assert data["status"] == "heartbeat_received"
    
    async def test_delete_bot_requires_auth(self, async_client, sample_bot):
        """Test bot deletion requires admin token"""
        response = await async_client.delete(f"/bots/{sample_bot['id']}")
        assert response.status_code == 401
    
    async def test_delete_bot_with_auth(self, async_client, admin_headers, sample_bot, db_connection):
        """Test bot deletion with admin auth"""
        response = await async_client.delete(f"/bots/{sample_bot['id']}",
            headers=admin_headers
        )
        assert response.status_code == 200
        
        # Verify bot is marked as deleted
        result = await db_connection.fetchval("""
            SELECT deleted_at FROM bots WHERE id = $1
        """, sample_bot["id"])
        assert result is not None


@pytest.mark.asyncio
class TestMetricsSummary:
    """Test metrics summary endpoint"""
    
    async def test_metrics_summary(self, async_client, sample_job, sample_bot):
        """Test metrics summary endpoint"""
        response = await async_client.get("/metrics/summary")
        assert response.status_code == 200
        
        data = response.json()
        assert "jobs" in data
        assert "bots" in data
        assert "throughput" in data
        
        # Should have at least one pending job
        assert data["jobs"]["pending"] >= 1
        
        # Should have at least one bot
        assert data["bots"]["total"] >= 1


@pytest.mark.asyncio
class TestErrorHandling:
    """Test API error handling"""
    
    async def test_invalid_json(self, async_client, admin_headers):
        """Test invalid JSON handling"""
        response = await async_client.post("/jobs/populate",
            content="invalid json",
            headers={**admin_headers, "Content-Type": "application/json"}
        )
        assert response.status_code == 422
    
    async def test_missing_required_fields(self, async_client, admin_headers):
        """Test missing required fields"""
        response = await async_client.post("/jobs/populate",
            json={},  # Missing batchSize
            headers=admin_headers
        )
        assert response.status_code == 422
    
    async def test_invalid_job_id(self, async_client):
        """Test invalid job ID handling"""
        response = await async_client.get("/jobs/invalid-job-id-that-does-not-exist")
        assert response.status_code == 404