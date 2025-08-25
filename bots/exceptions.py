"""Bot client exceptions."""


class BotClientError(Exception):
    """Base exception for bot client errors."""
    pass


class AuthenticationError(BotClientError):
    """Authentication failed error."""
    pass


class RateLimitError(BotClientError):
    """Rate limit exceeded error."""
    
    def __init__(self, message: str, retry_after: int = None):
        super().__init__(message)
        self.retry_after = retry_after