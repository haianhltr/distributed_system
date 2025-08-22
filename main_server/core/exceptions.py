"""Custom exceptions for the application."""

from typing import Optional, Any, Dict
from fastapi import HTTPException, status


class ServiceError(Exception):
    """Base exception for service layer errors."""
    
    def __init__(self, message: str, code: Optional[str] = None, details: Optional[Any] = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for API responses."""
        result = {"message": self.message}
        if self.code:
            result["code"] = self.code
        if self.details:
            result["details"] = self.details
        return result


class ValidationError(ServiceError):
    """Raised when data validation fails."""
    def __init__(self, message: str, field: Optional[str] = None, details: Optional[Any] = None):
        super().__init__(message, code="VALIDATION_ERROR", details=details)
        self.field = field


class NotFoundError(ServiceError):
    """Raised when a requested resource is not found."""
    def __init__(self, resource: str, resource_id: str):
        message = f"{resource} with ID {resource_id} not found"
        super().__init__(message, code="NOT_FOUND")
        self.resource = resource
        self.resource_id = resource_id


class ConflictError(ServiceError):
    """Raised when a resource conflict occurs."""
    def __init__(self, message: str, resource: Optional[str] = None):
        super().__init__(message, code="CONFLICT")
        self.resource = resource


class AuthenticationError(ServiceError):
    """Raised when authentication fails."""
    def __init__(self, message: str = "Invalid authentication credentials"):
        super().__init__(message, code="AUTHENTICATION_FAILED")


class AuthorizationError(ServiceError):
    """Raised when authorization fails."""
    def __init__(self, message: str = "Insufficient permissions"):
        super().__init__(message, code="AUTHORIZATION_FAILED")


class DatabaseError(ServiceError):
    """Raised when database operations fail."""
    def __init__(self, message: str, operation: Optional[str] = None):
        super().__init__(message, code="DATABASE_ERROR")
        self.operation = operation


class ExternalServiceError(ServiceError):
    """Raised when external service calls fail."""
    def __init__(self, service: str, message: str):
        super().__init__(message, code="EXTERNAL_SERVICE_ERROR")
        self.service = service


class BusinessRuleViolation(ServiceError):
    """Raised when business rules are violated."""
    def __init__(self, message: str, rule: Optional[str] = None):
        super().__init__(message, code="BUSINESS_RULE_VIOLATION")
        self.rule = rule


class ResourceExhausted(ServiceError):
    """Raised when a resource limit is reached."""
    def __init__(self, resource: str, limit: Optional[int] = None):
        message = f"{resource} limit reached"
        if limit:
            message += f" (limit: {limit})"
        super().__init__(message, code="RESOURCE_EXHAUSTED")
        self.resource = resource
        self.limit = limit


def service_error_handler(error: ServiceError) -> HTTPException:
    """Convert service errors to HTTP exceptions."""
    status_map = {
        ValidationError: status.HTTP_400_BAD_REQUEST,
        NotFoundError: status.HTTP_404_NOT_FOUND,
        ConflictError: status.HTTP_409_CONFLICT,
        AuthenticationError: status.HTTP_401_UNAUTHORIZED,
        AuthorizationError: status.HTTP_403_FORBIDDEN,
        BusinessRuleViolation: status.HTTP_422_UNPROCESSABLE_ENTITY,
        ResourceExhausted: status.HTTP_429_TOO_MANY_REQUESTS,
        DatabaseError: status.HTTP_500_INTERNAL_SERVER_ERROR,
        ExternalServiceError: status.HTTP_502_BAD_GATEWAY,
    }
    
    status_code = status_map.get(type(error), status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    return HTTPException(
        status_code=status_code,
        detail=error.to_dict()
    )