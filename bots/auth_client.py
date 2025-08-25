"""Authentication client for bot operations."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
import aiohttp

from .exceptions import AuthenticationError, RateLimitError, BotClientError


logger = logging.getLogger(__name__)


class AuthClient:
    """Client for handling bot authentication with the server."""
    
    def __init__(self, config: Dict[str, any], session: aiohttp.ClientSession):
        """Initialize auth client.
        
        Args:
            config: Bot configuration containing:
                - bot_key: Unique bot identifier
                - bootstrap_secret: Secret for authentication
                - auth_endpoint: Server auth endpoint URL
                - token_refresh_skew_seconds: Seconds before expiry to refresh token
                - client_version: Client version for X-Client-Version header
            session: Aiohttp session for making requests
        """
        self.config = config
        self.session = session
        self.access_token: Optional[str] = None
        self.token_type: Optional[str] = None
        self.expires_at: Optional[datetime] = None
        self.client_version = config.get('client_version', '1.0.0')
        
        # Log config (but never the secret)
        logger.debug(f"Initialized auth client for bot_key: {config['bot_key']}")
    
    async def obtain_token(self) -> None:
        """Obtain access token from the server.
        
        Raises:
            AuthenticationError: If authentication fails (401/403)
            RateLimitError: If rate limited (429)
            BotClientError: For other errors (426, 503, etc.)
        """
        auth_data = {
            "bot_key": self.config["bot_key"],
            "bootstrap_secret": self.config["bootstrap_secret"]
        }
        
        headers = {
            "X-Client-Version": self.client_version,
            "Content-Type": "application/json"
        }
        
        logger.info(f"Obtaining access token for bot: {self.config['bot_key']}")
        
        try:
            async with self.session.post(
                self.config["auth_endpoint"],
                json=auth_data,
                headers=headers
            ) as response:
                
                if response.status == 200:
                    data = await response.json()
                    self._store_token(data)
                    logger.info("Successfully obtained access token")
                    
                elif response.status in (401, 403):
                    # Handle authentication/authorization errors
                    error_data = await response.json()
                    error_msg = error_data.get("message", "Authentication failed")
                    error_code = error_data.get("error_code", "UNAUTHENTICATED")
                    
                    logger.error(f"Authentication failed ({error_code}): {error_msg}")
                    raise AuthenticationError(f"{error_code}: {error_msg}")
                    
                elif response.status == 426:
                    # Client version too old
                    error_data = await response.json()
                    error_msg = error_data.get("message", "Client version too old")
                    logger.error(f"Client version error: {error_msg}")
                    raise BotClientError(f"OUTDATED_CLIENT: {error_msg}")
                    
                elif response.status == 429:
                    # Handle rate limiting
                    error_data = await response.json()
                    retry_after = response.headers.get("Retry-After", "60")
                    try:
                        retry_seconds = int(retry_after)
                    except ValueError:
                        retry_seconds = 60
                    
                    backoff_ms = error_data.get("backoff_ms", retry_seconds * 1000)
                    
                    logger.warning(f"Rate limited, retry after {retry_seconds} seconds")
                    
                    # Sleep and retry once if retryable
                    if error_data.get("retryable", True):
                        await asyncio.sleep(retry_seconds)
                        
                        # Retry the request
                        async with self.session.post(
                            self.config["auth_endpoint"],
                            json=auth_data,
                            headers=headers
                        ) as retry_response:
                            if retry_response.status == 200:
                                data = await retry_response.json()
                                self._store_token(data)
                                logger.info("Successfully obtained access token after retry")
                            else:
                                error_data = await retry_response.json()
                                raise RateLimitError(
                                    f"Still rate limited: {error_data.get('message', 'Unknown error')}",
                                    retry_after=retry_seconds
                                )
                    else:
                        raise RateLimitError(
                            error_data.get("message", "Rate limited"),
                            retry_after=retry_seconds
                        )
                        
                elif response.status == 503:
                    # Service unavailable
                    error_data = await response.json()
                    error_msg = error_data.get("message", "Service temporarily unavailable")
                    backoff_ms = error_data.get("backoff_ms", 5000)
                    
                    logger.warning(f"Service unavailable: {error_msg}")
                    raise BotClientError(f"TEMPORARY_UNAVAILABLE: {error_msg}")
                    
                else:
                    error_data = await response.json()
                    error_msg = error_data.get("message", "Unknown error")
                    error_code = error_data.get("error_code", "UNKNOWN")
                    raise BotClientError(f"Unexpected status {response.status} ({error_code}): {error_msg}")
                    
        except aiohttp.ClientError as e:
            logger.error(f"Network error obtaining token: {e}")
            raise BotClientError(f"Network error: {str(e)}")
    
    def _store_token(self, token_data: Dict[str, any]) -> None:
        """Store token data from server response."""
        self.access_token = token_data["access_token"]
        self.token_type = token_data.get("token_type", "Bearer")
        
        # Calculate expiry time with skew
        expires_in = token_data["expires_in"]
        skew = self.config.get("token_refresh_skew_seconds", 60)
        
        # Use issued_at if provided for more accurate timing
        if "issued_at" in token_data:
            try:
                # Parse ISO 8601 format from server
                issued_at_str = token_data["issued_at"].rstrip('Z')
                issued_at = datetime.fromisoformat(issued_at_str.replace('Z', ''))
                self.expires_at = issued_at + timedelta(seconds=expires_in - skew)
            except (ValueError, AttributeError):
                # Fall back to current time if parsing fails
                self.expires_at = datetime.utcnow() + timedelta(seconds=expires_in - skew)
        else:
            # Fallback to current time (backward compatibility)
            self.expires_at = datetime.utcnow() + timedelta(seconds=expires_in - skew)
        
        logger.debug(f"Token stored, expires at: {self.expires_at}")
    
    def get_auth_header(self) -> Dict[str, str]:
        """Build Authorization header for requests.
        
        Returns:
            Dict with Authorization header
        """
        if not self.access_token:
            raise ValueError("No access token available")
        
        return {
            "Authorization": f"{self.token_type} {self.access_token}"
        }
    
    def is_token_fresh(self) -> bool:
        """Check if token is still valid.
        
        Returns:
            True if token is valid, False if expired or not set
        """
        if not self.access_token or not self.expires_at:
            return False
        
        return datetime.utcnow() < self.expires_at
    
    async def ensure_fresh_token(self) -> None:
        """Ensure we have a fresh token, obtaining new one if needed."""
        if not self.is_token_fresh():
            logger.info("Token expired or not set, obtaining new token")
            await self.obtain_token()