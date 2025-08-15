"""Pydantic schemas for request/response validation."""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# Request schemas
class JobCreate(BaseModel):
    a: int = Field(..., ge=0, le=999, description="First operand")
    b: int = Field(..., ge=0, le=999, description="Second operand")


class JobClaim(BaseModel):
    bot_id: str = Field(..., min_length=1, description="Bot identifier")


class JobStart(BaseModel):
    bot_id: str = Field(..., min_length=1, description="Bot identifier")


class JobComplete(BaseModel):
    bot_id: str = Field(..., min_length=1, description="Bot identifier")
    sum: int = Field(..., description="Sum of a and b")
    duration_ms: int = Field(..., ge=0, description="Processing duration in milliseconds")


class JobFail(BaseModel):
    bot_id: str = Field(..., min_length=1, description="Bot identifier")
    error: str = Field(..., min_length=1, description="Error message")


class BotRegister(BaseModel):
    bot_id: str = Field(..., min_length=1, description="Bot identifier")


class BotHeartbeat(BaseModel):
    bot_id: str = Field(..., min_length=1, description="Bot identifier")


class JobPopulate(BaseModel):
    batchSize: int = Field(default=5, ge=1, le=100, description="Number of jobs to create")


class ScaleUp(BaseModel):
    count: int = Field(default=1, ge=1, le=10, description="Number of bots to scale up")


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, description="SQL query to execute")


# Response schemas
class JobResponse(BaseModel):
    id: str
    a: int
    b: int
    status: str
    claimed_by: Optional[str] = None
    created_at: datetime
    claimed_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    attempts: int = 0
    error: Optional[str] = None


class BotResponse(BaseModel):
    id: str
    status: str
    current_job_id: Optional[str] = None
    last_heartbeat_at: datetime
    created_at: datetime
    deleted_at: Optional[datetime] = None
    computed_status: Optional[str] = None
    lifecycle_status: Optional[str] = None
    processing_duration_seconds: Optional[float] = None
    processing_duration_formatted: Optional[str] = None
    heartbeat_age_formatted: Optional[str] = None
    deleted_age_formatted: Optional[str] = None


class MetricsResponse(BaseModel):
    timestamp: datetime
    jobs: Dict[str, Any]
    bots: Dict[str, Any]
    activity: Dict[str, Any]


class StatsResponse(BaseModel):
    bot_id: str
    period_hours: int
    total_jobs: int
    avg_duration_ms: float
    min_duration_ms: int
    max_duration_ms: int
    succeeded: int
    failed: int
    success_rate: float
    hourly_performance: List[Dict[str, Any]]
    recent_jobs: List[Dict[str, Any]]


class CleanupResponse(BaseModel):
    timestamp: str
    dry_run: bool
    database_cleanup: Optional[Dict[str, Any]] = None
    container_cleanup: Optional[Dict[str, Any]] = None