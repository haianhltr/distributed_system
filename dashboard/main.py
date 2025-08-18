import asyncio
import subprocess
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

import aiohttp
import uvicorn
from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import scaling modules
try:
    from k8s_scaler import get_k8s_scaler, is_k8s_available
    K8S_AVAILABLE = True
except ImportError:
    K8S_AVAILABLE = False
    logger.info("Kubernetes client not available - falling back to Docker Compose scaling")

app = FastAPI(title="Distributed System Dashboard", version="1.0.0")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security
security = HTTPBearer()

# Configuration
class Config:
    MAIN_SERVER_URL = os.environ.get("MAIN_SERVER_URL", "http://localhost:3001")
    ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "admin-secret-token")
    PORT = int(os.environ.get("PORT", 3002))

config = Config()

# Templates and static files
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Track running bot processes
bot_processes: Dict[str, subprocess.Popen] = {}

# Pydantic models
class JobPopulate(BaseModel):
    batchSize: int = 5
    operation: str = "sum"

class ScaleUp(BaseModel):
    count: int = 1

class BotAssignOperation(BaseModel):
    operation: Optional[str] = None

# Template filters
def format_number(num):
    """Format number with commas"""
    return f"{num:,}" if num else "0"

def get_status_badge(status):
    """Get CSS classes for status badges"""
    colors = {
        'pending': 'bg-gray-100 text-gray-800',
        'claimed': 'bg-yellow-100 text-yellow-800',
        'processing': 'bg-blue-100 text-blue-800',
        'succeeded': 'bg-green-100 text-green-800',
        'failed': 'bg-red-100 text-red-800',
        'idle': 'bg-green-100 text-green-800',
        'busy': 'bg-blue-100 text-blue-800',
        'down': 'bg-red-100 text-red-800'
    }
    return colors.get(status, 'bg-gray-100 text-gray-800')

def get_operation_badge(operation):
    """Get CSS classes for operation badges"""
    colors = {
        'sum': 'bg-blue-100 text-blue-800',
        'subtract': 'bg-purple-100 text-purple-800',
        'multiply': 'bg-green-100 text-green-800',
        'divide': 'bg-red-100 text-red-800'
    }
    return colors.get(operation, 'bg-gray-100 text-gray-800')

def format_datetime(dt_str):
    """Format datetime string to user-friendly format"""
    if not dt_str:
        return '-'
    try:
        # Parse the ISO datetime string
        from datetime import datetime
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        # Format as "Aug 16, 2:44 PM"
        return dt.strftime("%b %d, %I:%M %p")
    except:
        return dt_str

def format_task(job):
    """Format task description based on operation"""
    if not job:
        return '-'
    
    operation = job.get('operation', 'sum')
    a = job.get('a', 0)
    b = job.get('b', 0)
    
    operation_symbols = {
        'sum': '+',
        'subtract': '−',
        'multiply': '×',
        'divide': '÷'
    }
    
    symbol = operation_symbols.get(operation, '+')
    return f"{a} {symbol} {b}"

# Add filters to Jinja2 environment
templates.env.filters['format_number'] = format_number
templates.env.filters['get_status_badge'] = get_status_badge
templates.env.filters['get_operation_badge'] = get_operation_badge
templates.env.filters['format_datetime'] = format_datetime
templates.env.filters['format_task'] = format_task

# Admin authentication
async def verify_admin_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if credentials.credentials != config.ADMIN_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )
    return credentials.credentials

async def make_request(url: str, method: str = "GET", json_data: dict = None, headers: dict = None):
    """Make HTTP request to main server"""
    async with aiohttp.ClientSession() as session:
        if method.upper() == "GET":
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    raise HTTPException(status_code=response.status, detail=f"Request failed: {response.status}")
        elif method.upper() == "POST":
            async with session.post(url, json=json_data, headers=headers) as response:
                if response.status in [200, 201]:
                    return await response.json()
                else:
                    raise HTTPException(status_code=response.status, detail=f"Request failed: {response.status}")
        elif method.upper() == "DELETE":
            async with session.delete(url, headers=headers) as response:
                if response.status in [200, 204]:
                    return await response.json() if response.content_length else {}
                else:
                    raise HTTPException(status_code=response.status, detail=f"Request failed: {response.status}")

# Health check
@app.get("/healthz")
async def health_check():
    return {"status": "healthy", "timestamp": "2025-08-12T00:00:00Z"}

# Main dashboard
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    try:
        # Make parallel requests to main server
        metrics_task = make_request(f"{config.MAIN_SERVER_URL}/metrics")
        bots_task = make_request(f"{config.MAIN_SERVER_URL}/bots?include_deleted=true")
        recent_jobs_task = make_request(f"{config.MAIN_SERVER_URL}/jobs?limit=10")
        
        # Fetch jobs by status to ensure we have examples of each type
        pending_jobs_task = make_request(f"{config.MAIN_SERVER_URL}/jobs?status=pending&limit=20")
        processing_jobs_task = make_request(f"{config.MAIN_SERVER_URL}/jobs?status=processing&limit=10")
        succeeded_jobs_task = make_request(f"{config.MAIN_SERVER_URL}/jobs?status=succeeded&limit=10")
        failed_jobs_task = make_request(f"{config.MAIN_SERVER_URL}/jobs?status=failed&limit=10")
        
        metrics, bots, recent_jobs, pending_jobs, processing_jobs, succeeded_jobs, failed_jobs = await asyncio.gather(
            metrics_task, bots_task, recent_jobs_task, pending_jobs_task, processing_jobs_task, succeeded_jobs_task, failed_jobs_task
        )
        
        # Combine all jobs for the dashboard (ensure all values are lists)
        pending_jobs = pending_jobs or []
        processing_jobs = processing_jobs or []
        succeeded_jobs = succeeded_jobs or []
        failed_jobs = failed_jobs or []
        recent_jobs = recent_jobs or []
        bots = bots or []
        all_jobs = pending_jobs + processing_jobs + succeeded_jobs + failed_jobs
        
        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "metrics": metrics,
            "bots": bots,
            "recentJobs": recent_jobs,
            "allJobs": all_jobs,
            "title": "Distributed System Dashboard"
        })
        
    except Exception as e:
        logger.error(f"Dashboard error: {e}")
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "Failed to load dashboard data",
            "message": str(e)
        })

# Bots list page
@app.get("/bots", response_class=HTMLResponse)
async def bots_page(request: Request):
    try:
        bots = await make_request(f"{config.MAIN_SERVER_URL}/bots")
        
        return templates.TemplateResponse("bots.html", {
            "request": request,
            "bots": bots,
            "title": "Bot Management"
        })
        
    except Exception as e:
        logger.error(f"Bots page error: {e}")
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "Failed to load bots data",
            "message": str(e)
        })

# Bot detail page
@app.get("/bots/{bot_id}", response_class=HTMLResponse)
async def bot_detail(request: Request, bot_id: str):
    try:
        bots_task = make_request(f"{config.MAIN_SERVER_URL}/bots?include_deleted=true")
        jobs_task = make_request(f"{config.MAIN_SERVER_URL}/jobs?limit=20")
        stats_task = make_request(f"{config.MAIN_SERVER_URL}/bots/{bot_id}/stats")
        
        bots, jobs, stats = await asyncio.gather(bots_task, jobs_task, stats_task)
        
        # Find the specific bot
        bot = next((b for b in bots if b["id"] == bot_id), None)
        if not bot:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "error": "Bot not found",
                "message": f"Bot {bot_id} does not exist"
            })
        
        # Get current jobs claimed by this bot
        current_jobs = [j for j in jobs if j.get("claimed_by") == bot_id]
        
        return templates.TemplateResponse("bot-detail.html", {
            "request": request,
            "bot": bot,
            "currentJobs": current_jobs,
            "stats": stats,
            "title": f"Bot {bot_id}"
        })
        
    except Exception as e:
        logger.error(f"Bot detail error: {e}")
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "Failed to load bot details",
            "message": str(e)
        })

# Jobs list page
@app.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request, status: str = "", limit: int = 50, offset: int = 0, sort: str = "default"):
    try:
        url = f"{config.MAIN_SERVER_URL}/jobs?limit={limit}&offset={offset}"
        if status:
            url += f"&status={status}"
        
        jobs = await make_request(url)
        
        # Apply custom sorting based on sort parameter
        if sort == "default":
            # Default: DO NOT re-sort! The backend already sorted correctly
            # Backend sorts: ALL pending first across all pages, then finished
            pass  # Keep the backend's sorting order
        elif sort == "created_desc":
            # Sort by created time (newest first)
            jobs.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        elif sort == "created_asc":
            # Sort by created time (oldest first)
            jobs.sort(key=lambda x: x.get('created_at', ''))
        elif sort == "status":
            # Sort by status
            status_order = {'pending': 0, 'claimed': 1, 'processing': 2, 'succeeded': 3, 'failed': 4}
            jobs.sort(key=lambda x: status_order.get(x['status'], 5))
        
        return templates.TemplateResponse("jobs.html", {
            "request": request,
            "jobs": jobs,
            "currentStatus": status,
            "currentSort": sort,
            "title": "Job Management",
            "pagination": {
                "limit": limit,
                "offset": offset,
                "hasNext": len(jobs) == limit,
                "hasPrev": offset > 0
            }
        })
        
    except Exception as e:
        logger.error(f"Jobs page error: {e}")
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "Failed to load jobs data",
            "message": str(e)
        })

# Job detail page
@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: str):
    try:
        job = await make_request(f"{config.MAIN_SERVER_URL}/jobs/{job_id}")
        
        return templates.TemplateResponse("job-detail.html", {
            "request": request,
            "job": job,
            "title": f"Job {job_id}"
        })
        
    except HTTPException as e:
        if e.status_code == 404:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "error": "Job not found",
                "message": f"Job {job_id} does not exist"
            })
        raise
    except Exception as e:
        logger.error(f"Job detail error: {e}")
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "Failed to load job details",
            "message": str(e)
        })

# Smart scaling endpoint - detects environment and uses appropriate method
@app.post("/scale/up")
async def scale_up(scale_data: ScaleUp):
    """
    Scale up bots using the most appropriate method for the current environment:
    1. Kubernetes (production) - if available
    2. Docker Compose (development/staging)
    3. Direct subprocess (local development - legacy)
    """
    try:
        count = scale_data.count
        
        # Method 1: Try Kubernetes scaling (production)
        if K8S_AVAILABLE and is_k8s_available():
            logger.info(f"Using Kubernetes scaling to add {count} bots")
            scaler = get_k8s_scaler()
            result = await scaler.scale_up(count)
            result["method"] = "kubernetes"
            return result
        
        # Method 2: Docker Compose scaling (development/staging)
        # Check if we're running in a containerized environment
        if os.path.exists("/.dockerenv"):
            # We're running inside a container, try Docker Compose scaling
            logger.info(f"Using Docker Compose scaling to add {count} bots (containerized)")
            return await _scale_up_docker_compose_containerized(count)
        else:
            # We're running on host, check for compose file
            project_root = Path(__file__).parent.parent
            compose_file = project_root / "docker-compose.yml"
            
            if compose_file.exists():
                logger.info(f"Using Docker Compose scaling to add {count} bots")
                return await _scale_up_docker_compose(count, compose_file, project_root)
        
        # Method 3: Direct subprocess (local development - legacy)
        logger.info(f"Using direct subprocess scaling to add {count} bots")
        return await _scale_up_subprocess(count)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Scale up error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to scale up bots: {str(e)}")

async def _scale_up_docker_compose(count: int, compose_file: Path, project_root: Path) -> Dict[str, Any]:
    """Scale up using Docker Compose"""
    spawned_count = 0
    failed_services = []
    timestamp = int(asyncio.get_event_loop().time())
    
    for i in range(count):
        service_name = f"bot-dynamic-{timestamp}-{i}"
        
        try:
            process = await asyncio.create_subprocess_exec(
                "docker", "compose", "-f", str(compose_file), "run", "-d", 
                "--name", service_name,
                "-e", f"BOT_ID={service_name}",
                "-e", f"MAIN_SERVER_URL=http://main-server:3001",
                "-e", "HEARTBEAT_INTERVAL_MS=30000",
                "-e", "PROCESSING_DURATION_MS=300000",
                "-e", "FAILURE_RATE=0.15",
                "bot-1",  # Use bot-1 as template
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(project_root)
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                container_id = stdout.decode().strip()
                bot_processes[service_name] = {
                    "container_id": container_id,
                    "type": "docker"
                }
                logger.info(f"Spawned bot container: {service_name} ({container_id[:12]})")
                spawned_count += 1
            else:
                error_msg = stderr.decode() if stderr else "Docker run failed"
                failed_services.append(f"{service_name}: {error_msg}")
                logger.error(f"Failed to spawn bot {service_name}: {error_msg}")
            
        except Exception as e:
            failed_services.append(f"{service_name}: {str(e)}")
            logger.error(f"Failed to spawn bot {service_name}: {e}")
    
    result = {
        "status": "success" if spawned_count > 0 else "failed",
        "spawned": spawned_count,
        "method": "docker-compose"
    }
    if failed_services:
        result["failed"] = failed_services
        result["status"] = "partial" if spawned_count > 0 else "failed"
    
    if spawned_count == 0:
        raise HTTPException(status_code=500, detail=f"Failed to spawn any bots. Errors: {failed_services}")
    
    return result

async def _scale_up_docker_compose_containerized(count: int) -> Dict[str, Any]:
    """Scale up using Docker commands when running inside a container"""
    spawned_count = 0
    failed_services = []
    timestamp = int(asyncio.get_event_loop().time())
    
    for i in range(count):
        service_name = f"bot-dynamic-{timestamp}-{i}"
        
        try:
            # Use docker run directly since we can't access docker-compose.yml from inside container
            process = await asyncio.create_subprocess_exec(
                "docker", "run", "-d", 
                "--name", service_name,
                "--network", "distributed-system",  # Use the same network as other services
                "-e", f"BOT_ID={service_name}",
                "-e", "MAIN_SERVER_URL=http://main-server:3001",
                "-e", "HEARTBEAT_INTERVAL_MS=30000",
                "-e", "PROCESSING_DURATION_MS=300000",
                "-e", "FAILURE_RATE=0.15",
                "distributed-system-test-bot-1",  # Use the same image as bot-1
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                container_id = stdout.decode().strip()
                bot_processes[service_name] = {
                    "container_id": container_id,
                    "type": "docker"
                }
                logger.info(f"Spawned bot container: {service_name} ({container_id[:12]})")
                spawned_count += 1
            else:
                error_msg = stderr.decode() if stderr else "Docker run failed"
                failed_services.append(f"{service_name}: {error_msg}")
                logger.error(f"Failed to spawn bot {service_name}: {error_msg}")
            
        except Exception as e:
            failed_services.append(f"{service_name}: {str(e)}")
            logger.error(f"Failed to spawn bot {service_name}: {e}")
    
    result = {
        "status": "success" if spawned_count > 0 else "failed",
        "spawned": spawned_count,
        "method": "docker-containerized"
    }
    if failed_services:
        result["failed"] = failed_services
        result["status"] = "partial" if spawned_count > 0 else "failed"
    
    if spawned_count == 0:
        raise HTTPException(status_code=500, detail=f"Failed to spawn any bots. Errors: {failed_services}")
    
    return result

async def _scale_up_subprocess(count: int) -> Dict[str, Any]:
    """Scale up using direct subprocess (legacy method)"""
    bots_dir = Path(__file__).parent.parent / "bots"
    bot_script = bots_dir / "bot.py"
    
    if not bots_dir.exists():
        raise HTTPException(status_code=500, detail=f"Bots directory not found: {bots_dir}")
    if not bot_script.exists():
        raise HTTPException(status_code=500, detail=f"Bot script not found: {bot_script}")
    
    spawned_count = 0
    failed_bots = []
    timestamp = int(asyncio.get_event_loop().time())
    
    for i in range(count):
        bot_id = f"bot-subprocess-{timestamp}-{i}"
        
        try:
            process = subprocess.Popen([
                sys.executable, str(bot_script)
            ], 
            cwd=str(bots_dir),
            env={
                **os.environ,
                "MAIN_SERVER_URL": config.MAIN_SERVER_URL,
                "BOT_ID": bot_id
            },
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
            )
            
            await asyncio.sleep(0.1)
            if process.poll() is None:
                bot_processes[bot_id] = process
                logger.info(f"Spawned bot subprocess: {bot_id}")
                spawned_count += 1
            else:
                stdout, stderr = process.communicate()
                error_msg = stderr.decode() if stderr else "Process exited immediately"
                failed_bots.append(f"{bot_id}: {error_msg}")
                logger.error(f"Bot {bot_id} failed to start: {error_msg}")
            
        except Exception as e:
            failed_bots.append(f"{bot_id}: {str(e)}")
            logger.error(f"Failed to spawn bot {bot_id}: {e}")
    
    result = {
        "status": "success" if spawned_count > 0 else "failed",
        "spawned": spawned_count,
        "method": "subprocess"
    }
    if failed_bots:
        result["failed"] = failed_bots
        result["status"] = "partial" if spawned_count > 0 else "failed"
    
    if spawned_count == 0:
        raise HTTPException(status_code=500, detail=f"Failed to spawn any bots. Errors: {failed_bots}")
    
    return result

# Delete specific bot
@app.delete("/bots/{bot_id}")
async def delete_bot(bot_id: str):
    try:
        # Delete bot from main server
        headers = {"Authorization": f"Bearer {config.ADMIN_TOKEN}"}
        await make_request(f"{config.MAIN_SERVER_URL}/bots/{bot_id}", "DELETE", headers=headers)
        
        # Try to kill local process/container if it exists
        if bot_id in bot_processes:
            bot_info = bot_processes[bot_id]
            
            if isinstance(bot_info, dict) and bot_info.get("type") == "docker":
                # Handle Docker container
                container_id = bot_info["container_id"]
                try:
                    process = await asyncio.create_subprocess_exec(
                        "docker", "stop", container_id,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await process.communicate()
                    
                    # Remove the container
                    process = await asyncio.create_subprocess_exec(
                        "docker", "rm", container_id,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await process.communicate()
                    
                    logger.info(f"Stopped and removed Docker container: {bot_id} ({container_id[:12]})")
                except Exception as e:
                    logger.error(f"Failed to stop Docker container {container_id}: {e}")
            else:
                # Handle subprocess (legacy)
                process = bot_info
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                logger.info(f"Terminated local bot process: {bot_id}")
            
            del bot_processes[bot_id]
        
        return {"status": "deleted"}
        
    except Exception as e:
        logger.error(f"Delete bot error: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete bot")

# Bot management endpoints
@app.post("/bots/cleanup")
async def cleanup_bots():
    try:
        headers = {"Authorization": f"Bearer {config.ADMIN_TOKEN}"}
        result = await make_request(
            f"{config.MAIN_SERVER_URL}/bots/cleanup",
            "POST",
            None,
            headers
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Cleanup bots error: {e}")
        raise HTTPException(status_code=500, detail="Failed to cleanup bots")

@app.post("/bots/reset")
async def reset_bots():
    try:
        headers = {"Authorization": f"Bearer {config.ADMIN_TOKEN}"}
        result = await make_request(
            f"{config.MAIN_SERVER_URL}/bots/reset",
            "POST",
            None,
            headers
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Reset bots error: {e}")
        raise HTTPException(status_code=500, detail="Failed to reset bots")

# Operations endpoints
@app.get("/api/operations")
async def get_operations():
    try:
        result = await make_request(f"{config.MAIN_SERVER_URL}/operations", "GET")
        return result
    except Exception as e:
        logger.error(f"Get operations error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get operations")

# Bot operation assignment
class BotOperationAssignment(BaseModel):
    operation: Optional[str] = None

@app.post("/api/bots/{bot_id}/assign-operation")
async def assign_bot_operation(bot_id: str, assignment: BotOperationAssignment):
    try:
        headers = {"Authorization": f"Bearer {config.ADMIN_TOKEN}"}
        result = await make_request(
            f"{config.MAIN_SERVER_URL}/bots/{bot_id}/assign-operation",
            "POST",
            {"operation": assignment.operation},
            headers
        )
        return result
    except Exception as e:
        logger.error(f"Assign operation error: {e}")
        raise HTTPException(status_code=500, detail="Failed to assign operation")

# Manually populate jobs
@app.post("/jobs/populate")
async def populate_jobs(job_data: JobPopulate):
    try:
        headers = {"Authorization": f"Bearer {config.ADMIN_TOKEN}"}
        result = await make_request(
            f"{config.MAIN_SERVER_URL}/jobs/populate",
            "POST",
            {"batchSize": job_data.batchSize, "operation": job_data.operation},
            headers
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Populate jobs error: {e}")
        raise HTTPException(status_code=500, detail="Failed to populate jobs")

# Operations endpoint
@app.get("/api/operations")
async def get_operations():
    """Get available operations from main server"""
    try:
        operations = await make_request(f"{config.MAIN_SERVER_URL}/operations")
        return operations
    except Exception as e:
        logger.error(f"Failed to get operations: {e}")
        raise HTTPException(status_code=500, detail="Failed to get operations")

# Bot operation assignment endpoint
@app.post("/api/bots/{bot_id}/assign-operation")
async def assign_bot_operation(bot_id: str, assignment_data: BotAssignOperation):
    """Assign or unassign an operation to a bot"""
    try:
        headers = {"Authorization": f"Bearer {config.ADMIN_TOKEN}"}
        result = await make_request(
            f"{config.MAIN_SERVER_URL}/bots/{bot_id}/assign-operation",
            "POST",
            {"operation": assignment_data.operation},
            headers
        )
        return result
    except Exception as e:
        logger.error(f"Failed to assign operation to bot {bot_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to assign operation")

# API endpoint for real-time data
@app.get("/api/metrics")
async def get_metrics():
    try:
        metrics_task = make_request(f"{config.MAIN_SERVER_URL}/metrics")
        bots_task = make_request(f"{config.MAIN_SERVER_URL}/bots?include_deleted=true")
        
        metrics, bots = await asyncio.gather(metrics_task, bots_task)
        
        return {
            "metrics": metrics,
            "bots": bots,
            "timestamp": "2025-08-12T00:00:00Z"
        }
        
    except Exception as e:
        logger.error(f"API metrics error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch metrics")

# Infrastructure status endpoint
@app.get("/api/infrastructure")
async def get_infrastructure_status():
    """Get current infrastructure and scaling capabilities"""
    try:
        # Determine available scaling methods
        scaling_methods = []
        active_method = None
        
        # Check Kubernetes
        if K8S_AVAILABLE and is_k8s_available():
            try:
                scaler = get_k8s_scaler()
                deployment_status = await scaler.get_deployment_status()
                hpa_status = await scaler.get_hpa_status()
                
                scaling_methods.append({
                    "type": "kubernetes",
                    "available": True,
                    "active": True,
                    "deployment": deployment_status,
                    "hpa": hpa_status
                })
                active_method = "kubernetes"
            except Exception as e:
                scaling_methods.append({
                    "type": "kubernetes",
                    "available": False,
                    "error": str(e)
                })
        
        # Check Docker Compose
        compose_file = Path(__file__).parent.parent / "docker-compose.yml"
        if compose_file.exists():
            scaling_methods.append({
                "type": "docker-compose",
                "available": True,
                "active": active_method != "kubernetes",
                "compose_file": str(compose_file)
            })
            if not active_method:
                active_method = "docker-compose"
        
        # Subprocess is always available as fallback
        scaling_methods.append({
            "type": "subprocess",
            "available": True,
            "active": active_method is None,
            "note": "Legacy local development method"
        })
        
        if not active_method:
            active_method = "subprocess"
        
        return {
            "active_scaling_method": active_method,
            "scaling_methods": scaling_methods,
            "locally_managed_containers": len([
                k for k, v in bot_processes.items() 
                if isinstance(v, dict) and v.get("type") == "docker"
            ]),
            "locally_managed_processes": len([
                k for k, v in bot_processes.items() 
                if not isinstance(v, dict)
            ])
        }
        
    except Exception as e:
        logger.error(f"Infrastructure status error: {e}")
        raise HTTPException(status_code=500, detail="Failed to get infrastructure status")

def cleanup_processes():
    """Clean up bot processes on shutdown"""
    logger.info("Shutting down dashboard, cleaning up bot processes...")
    for bot_id, bot_info in bot_processes.items():
        if isinstance(bot_info, dict) and bot_info.get("type") == "docker":
            # Handle Docker container
            container_id = bot_info["container_id"]
            try:
                subprocess.run(["docker", "stop", container_id], timeout=10)
                subprocess.run(["docker", "rm", container_id], timeout=5)
                logger.info(f"Cleaned up Docker container: {bot_id} ({container_id[:12]})")
            except Exception as e:
                logger.error(f"Failed to cleanup Docker container {container_id}: {e}")
        else:
            # Handle subprocess (legacy)
            process = bot_info
            logger.info(f"Terminating bot process: {bot_id}")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

# Cleanup management endpoints
@app.get("/cleanup", response_class=HTMLResponse)
async def cleanup_page(request: Request):
    """Cleanup management page"""
    return templates.TemplateResponse("cleanup.html", {"request": request})

@app.get("/api/cleanup/status")
async def get_cleanup_status():
    """Get cleanup service status from main server"""
    try:
        status = await make_request(f"{config.MAIN_SERVER_URL}/admin/cleanup/status")
        return status
    except Exception as e:
        logger.error(f"Failed to get cleanup status: {e}")
        raise HTTPException(status_code=500, detail="Failed to get cleanup status")

@app.get("/api/cleanup/orphaned")
async def get_orphaned_resources():
    """Check for orphaned resources"""
    try:
        # Get deleted bots from database
        deleted_bots_query = """
            SELECT id, deleted_at, 
                   EXTRACT(EPOCH FROM (NOW() - deleted_at))/86400 as days_ago 
            FROM bots 
            WHERE deleted_at IS NOT NULL 
            ORDER BY deleted_at DESC 
            LIMIT 20
        """
        
        # Get stopped containers
        docker_cmd = ["docker", "ps", "-a", "--filter", "name=bot-", "--filter", "status=exited", "--format", "{{.Names}}:{{.Status}}"]
        
        try:
            # Query database through main server
            db_response = await make_request(
                f"{config.MAIN_SERVER_URL}/admin/query",
                method="POST",
                json_data={"query": deleted_bots_query},
                headers={"Authorization": f"Bearer {config.ADMIN_TOKEN}"}
            )
            deleted_bots = db_response.get("results", [])
        except:
            deleted_bots = []
        
        try:
            # Check Docker containers
            process = await asyncio.create_subprocess_exec(
                *docker_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            stopped_containers = []
            if process.returncode == 0:
                for line in stdout.decode().strip().split('\n'):
                    if line:
                        parts = line.split(':', 1)
                        if len(parts) == 2:
                            stopped_containers.append({
                                "name": parts[0],
                                "status": parts[1]
                            })
        except:
            stopped_containers = []
        
        return {
            "deleted_bots": deleted_bots,
            "stopped_containers": stopped_containers
        }
        
    except Exception as e:
        logger.error(f"Failed to check orphaned resources: {e}")
        raise HTTPException(status_code=500, detail="Failed to check orphaned resources")

@app.post("/api/cleanup/run")
async def run_cleanup(dry_run: bool = True):
    """Trigger cleanup operation"""
    try:
        # Call main server cleanup endpoint
        url = f"{config.MAIN_SERVER_URL}/admin/cleanup?dry_run={dry_run}"
        headers = {"Authorization": f"Bearer {config.ADMIN_TOKEN}"}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    raise HTTPException(status_code=response.status, detail=f"Cleanup failed: {error_text}")
                    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cleanup operation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Cleanup operation failed: {str(e)}")

@app.post("/api/bots/{bot_id}/reset")
async def reset_bot_via_dashboard(bot_id: str):
    """Reset bot state via dashboard"""
    try:
        # Call main server reset endpoint
        url = f"{config.MAIN_SERVER_URL}/bots/{bot_id}/reset"
        headers = {"Authorization": f"Bearer {config.ADMIN_TOKEN}"}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers) as response:
                if response.status == 200:
                    result = await response.json()
                    # Add additional context for dashboard
                    if result.get('released_job_id'):
                        result['message'] = f"Bot {bot_id} reset successfully. Job {result['released_job_id']} has been released back to pending."
                    else:
                        result['message'] = f"Bot {bot_id} reset successfully. No active jobs were found."
                    return result
                else:
                    error_text = await response.text()
                    raise HTTPException(status_code=response.status, detail=f"Reset failed: {error_text}")
                    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bot reset operation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Bot reset failed: {str(e)}")

# New job release and bot restart endpoints for manual intervention
@app.post("/api/jobs/{job_id}/release")
async def release_job_via_dashboard(job_id: str):
    """Release a stuck job back to pending state"""
    try:
        # Call main server job release endpoint
        url = f"{config.MAIN_SERVER_URL}/jobs/{job_id}/release"
        headers = {"Authorization": f"Bearer {config.ADMIN_TOKEN}"}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    raise HTTPException(status_code=response.status, detail=f"Job release failed: {error_text}")
                    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Job release operation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Job release failed: {str(e)}")

@app.post("/api/bots/{bot_id}/restart")
async def restart_bot_via_dashboard(bot_id: str):
    """Mark a bot for restart and release any current job"""
    try:
        # Call main server bot restart endpoint
        url = f"{config.MAIN_SERVER_URL}/bots/{bot_id}/restart"
        headers = {"Authorization": f"Bearer {config.ADMIN_TOKEN}"}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    raise HTTPException(status_code=response.status, detail=f"Bot restart failed: {error_text}")
                    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bot restart operation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Bot restart failed: {str(e)}")

@app.get("/api/admin/stuck-jobs")
async def get_stuck_jobs_summary():
    """Get summary of potentially stuck jobs"""
    try:
        # Call main server stuck jobs endpoint
        url = f"{config.MAIN_SERVER_URL}/admin/stuck-jobs"
        headers = {"Authorization": f"Bearer {config.ADMIN_TOKEN}"}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    raise HTTPException(status_code=response.status, detail=f"Failed to get stuck jobs: {error_text}")
                    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get stuck jobs operation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get stuck jobs: {str(e)}")

@app.post("/api/clear-all-data")
async def clear_all_data():
    """Complete system reset - clear all jobs, results, and reset bots"""
    try:
        deleted_jobs = 0
        reset_bots = 0
        cleared_files = 0
        errors = []
        
        logger.info("Starting complete system clear operation")
        
        # Clear all jobs
        try:
            url = f"{config.MAIN_SERVER_URL}/admin/clear-all-data"
            headers = {"Authorization": f"Bearer {config.ADMIN_TOKEN}"}
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers) as response:
                    if response.status == 200:
                        result = await response.json()
                        deleted_jobs = result.get('deleted_jobs', 0)
                        reset_bots = result.get('reset_bots', 0)
                        cleared_files = result.get('cleared_files', 0)
                    else:
                        error_text = await response.text()
                        errors.append(f"Clear all data failed: {error_text}")
                        
        except Exception as e:
            errors.append(f"Clear all data error: {str(e)}")
        
        return {
            "status": "completed",
            "deleted_jobs": deleted_jobs,
            "reset_bots": reset_bots,
            "cleared_files": cleared_files,
            "errors": errors
        }
        
    except Exception as e:
        logger.error(f"Clear all data operation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Clear all data failed: {str(e)}")

@app.post("/api/admin/cleanup-inconsistent-states")
async def cleanup_inconsistent_states_via_dashboard():
    """Clean up inconsistent bot-job states via dashboard"""
    try:
        # Call main server cleanup endpoint
        url = f"{config.MAIN_SERVER_URL}/admin/cleanup-inconsistent-states"
        headers = {"Authorization": f"Bearer {config.ADMIN_TOKEN}"}
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    error_text = await response.text()
                    raise HTTPException(status_code=response.status, detail=f"Cleanup failed: {error_text}")
                    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cleanup inconsistent states operation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")

@app.on_event("shutdown")
async def shutdown_event():
    cleanup_processes()

if __name__ == "__main__":
    import signal
    
    def signal_handler(signum, frame):
        cleanup_processes()
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=config.PORT,
        reload=True
    )