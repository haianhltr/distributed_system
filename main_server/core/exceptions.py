"""Custom exceptions for the application."""

from typing import Optional, Any


class ServiceError(Exception):
    """Base exception for service layer errors."""
    
    def __init__(self, message: str, code: Optional[str] = None, details: Optional[Any] = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details


class ValidationError(ServiceError):
    """Raised when data validation fails."""
    pass


class NotFoundError(ServiceError):
    """Raised when a requested resource is not found."""
    pass


class ConflictError(ServiceError):
    """Raised when a resource conflict occurs."""
    pass


class AuthenticationError(ServiceError):
    """Raised when authentication fails."""
    pass


class DatabaseError(ServiceError):
    """Raised when database operations fail."""
    pass


class ExternalServiceError(ServiceError):
    """Raised when external service calls fail."""
    pass