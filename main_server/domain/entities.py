"""Domain entities representing core business objects."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from enum import Enum
import uuid


class JobStatus(str, Enum):
    """Job lifecycle status."""
    PENDING = "pending"
    CLAIMED = "claimed"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class BotStatus(str, Enum):
    """Bot operational status."""
    IDLE = "idle"
    BUSY = "busy"
    DOWN = "down"


class BotHealthStatus(str, Enum):
    """Bot health status."""
    NORMAL = "normal"
    POTENTIALLY_STUCK = "potentially_stuck"
    UNHEALTHY = "unhealthy"


class Operation(str, Enum):
    """Supported mathematical operations."""
    SUM = "sum"
    SUBTRACT = "subtract"
    MULTIPLY = "multiply"
    DIVIDE = "divide"


@dataclass
class Job:
    """Domain entity representing a job."""
    id: str
    a: int
    b: int
    operation: Operation
    status: JobStatus
    created_at: datetime
    claimed_by: Optional[str] = None
    claimed_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    attempts: int = 0
    error: Optional[str] = None
    version: int = 1
    
    @classmethod
    def create(cls, a: int, b: int, operation: Operation) -> 'Job':
        """Create a new job."""
        return cls(
            id=str(uuid.uuid4()),
            a=a,
            b=b,
            operation=operation,
            status=JobStatus.PENDING,
            created_at=datetime.utcnow()
        )
    
    def can_be_claimed(self) -> bool:
        """Check if job can be claimed."""
        return self.status == JobStatus.PENDING
    
    def claim(self, bot_id: str) -> None:
        """Claim the job for a bot."""
        if not self.can_be_claimed():
            raise ValueError(f"Job {self.id} cannot be claimed in status {self.status}")
        self.status = JobStatus.CLAIMED
        self.claimed_by = bot_id
        self.claimed_at = datetime.utcnow()
    
    def start_processing(self) -> None:
        """Start processing the job."""
        if self.status != JobStatus.CLAIMED:
            raise ValueError(f"Job {self.id} must be claimed before processing")
        self.status = JobStatus.PROCESSING
        self.started_at = datetime.utcnow()
    
    def complete(self) -> None:
        """Mark job as completed."""
        if self.status != JobStatus.PROCESSING:
            raise ValueError(f"Job {self.id} must be processing to complete")
        self.status = JobStatus.SUCCEEDED
        self.finished_at = datetime.utcnow()
    
    def fail(self, error: str) -> None:
        """Mark job as failed."""
        if self.status != JobStatus.PROCESSING:
            raise ValueError(f"Job {self.id} must be processing to fail")
        self.status = JobStatus.FAILED
        self.finished_at = datetime.utcnow()
        self.error = error
        self.attempts += 1
    
    def reset_to_pending(self) -> None:
        """Reset job back to pending status."""
        self.status = JobStatus.PENDING
        self.claimed_by = None
        self.claimed_at = None
        self.started_at = None
        self.finished_at = None
    
    def get_processing_duration_ms(self) -> Optional[int]:
        """Get processing duration in milliseconds."""
        if self.started_at and self.finished_at:
            delta = self.finished_at - self.started_at
            return int(delta.total_seconds() * 1000)
        return None


@dataclass
class Bot:
    """Domain entity representing a bot."""
    id: str
    status: BotStatus
    assigned_operation: Optional[Operation] = None
    current_job_id: Optional[str] = None
    last_heartbeat_at: datetime = field(default_factory=datetime.utcnow)
    created_at: datetime = field(default_factory=datetime.utcnow)
    deleted_at: Optional[datetime] = None
    health_status: BotHealthStatus = BotHealthStatus.NORMAL
    stuck_job_id: Optional[str] = None
    health_checked_at: Optional[datetime] = None
    
    @classmethod
    def register(cls, bot_id: str) -> 'Bot':
        """Register a new bot."""
        return cls(
            id=bot_id,
            status=BotStatus.IDLE
        )
    
    def is_active(self) -> bool:
        """Check if bot is active."""
        return self.deleted_at is None
    
    def is_healthy(self, heartbeat_threshold_seconds: int = 120) -> bool:
        """Check if bot is healthy based on heartbeat."""
        if not self.is_active():
            return False
        time_since_heartbeat = (datetime.utcnow() - self.last_heartbeat_at).total_seconds()
        return time_since_heartbeat < heartbeat_threshold_seconds
    
    def update_heartbeat(self) -> None:
        """Update bot's heartbeat timestamp."""
        self.last_heartbeat_at = datetime.utcnow()
    
    def assign_job(self, job_id: str) -> None:
        """Assign a job to the bot."""
        if self.current_job_id:
            raise ValueError(f"Bot {self.id} already has job {self.current_job_id}")
        self.current_job_id = job_id
        self.status = BotStatus.BUSY
    
    def release_job(self) -> Optional[str]:
        """Release current job and return to idle."""
        job_id = self.current_job_id
        self.current_job_id = None
        self.status = BotStatus.IDLE
        return job_id
    
    def mark_deleted(self) -> None:
        """Soft delete the bot."""
        self.deleted_at = datetime.utcnow()
        self.status = BotStatus.DOWN
        self.current_job_id = None
    
    def can_claim_job(self) -> bool:
        """Check if bot can claim a new job."""
        return (
            self.is_active() and 
            self.is_healthy() and 
            self.current_job_id is None and
            self.assigned_operation is not None
        )


@dataclass
class Result:
    """Domain entity representing a job processing result."""
    id: str
    job_id: str
    a: int
    b: int
    operation: Operation
    result: int
    processed_by: str
    processed_at: datetime
    duration_ms: int
    status: str
    error: Optional[str] = None
    
    @classmethod
    def create_success(
        cls,
        job: Job,
        result: int,
        processed_by: str,
        duration_ms: int
    ) -> 'Result':
        """Create a successful result."""
        return cls(
            id=str(uuid.uuid4()),
            job_id=job.id,
            a=job.a,
            b=job.b,
            operation=job.operation,
            result=result,
            processed_by=processed_by,
            processed_at=datetime.utcnow(),
            duration_ms=duration_ms,
            status="succeeded"
        )
    
    @classmethod
    def create_failure(
        cls,
        job: Job,
        processed_by: str,
        error: str
    ) -> 'Result':
        """Create a failed result."""
        return cls(
            id=str(uuid.uuid4()),
            job_id=job.id,
            a=job.a,
            b=job.b,
            operation=job.operation,
            result=0,
            processed_by=processed_by,
            processed_at=datetime.utcnow(),
            duration_ms=0,
            status="failed",
            error=error
        )