"""Authentication API endpoints implementing A1 specification."""

import jwt
import bcrypt
import uuid
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
from fastapi import APIRouter, HTTPException, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import asyncpg

from main_server.repositories import create_unit_of_work, UnitOfWork

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/auth", tags=["auth"])

# JWT Configuration
JWT_ALGORITHM = "RS256"
JWT_ISSUER = "https://api.example.com"
JWT_AUDIENCE = "control-api"
TOKEN_TTL_SECONDS = 900  # 15 minutes
MIN_CLIENT_VERSION = "1.0.0"

# RSA Keys for JWT signing (in production, load from secure storage)
PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7VJTUt9Us8cKB
xdkxvDfFGUPTkYgPnANVYxD0n7+B6xmqduWuYvgx6wUOH1+nvjzgUu+8LYKbQQfX
5qPmnYjKBf5X3QdKsUJnN6pLDhWBasjwNANX1P6nRz4/29fcnKAf1n3HgQYgY7JZ
9iVoXJGVZu6H5hJhVjqhX/3Q7QKBgQDJv5XGZ9XcKpQp0vqxq8K/2vhT6z1gNSCl
3QXqUKjK8Y6lXr4P/x3dJT2Zz6Q7CzFhVz4X8cP4v5WrYo1m5dCJhWz1oG+J0fqs
M8pR+2Q0m8lNr3z6zT9C5vUjV7HxJxF9u5XvQx4K4NsQX2x3C9WqLQ5q7pJ1Y0Kn
6+tY8z7RtwIDAQABAoIBAH0rJ1KpLEOhQ0K/8z8Q3g9M0sT6X8Ot0xOCqFx5lF7j
JhKn8JQV6I1vxHgKjV4XZpx7A3C/h+CqYj1aX3h9Uo6w7IbJl3Y+QqE4zz7dWWFh
...
-----END PRIVATE KEY-----"""

PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAu1SU1L7VLPHCgcXZMbw3
xRlD05GID5wDVWMQ9J+/gesZqnblrmL4MesFDh9fp7484FLvvC2Cm0EH1+aj5p2I
ygX+V90HSrFCZzeqSw4VgWrI8DQDV9T+p0c+P9vX3JygH9Z9x4EGIGOyWfYlaFyR
lWbuh+YSYVbaoV/90O0hQIDAQAB
-----END PUBLIC KEY-----"""

KID = "auth-key-1"


class AuthTokenRequest(BaseModel):
    bot_key: str = Field(..., min_length=1, description="Unique bot identifier")
    bootstrap_secret: str = Field(..., min_length=8, description="Bootstrap secret for authentication")


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    issued_at: str


class AuthErrorResponse(BaseModel):
    error_code: str
    message: str
    retryable: bool = False
    backoff_ms: int = 0


async def get_unit_of_work() -> UnitOfWork:
    """Get unit of work - to be overridden in tests."""
    from main_server.api.dependencies import get_database
    db = await get_database()
    async with create_unit_of_work(db.pool) as uow:
        yield uow


def version_check(client_version: str) -> bool:
    """Check if client version meets minimum requirements."""
    try:
        # Simple semantic version comparison
        client_parts = [int(x) for x in client_version.split('.')]
        min_parts = [int(x) for x in MIN_CLIENT_VERSION.split('.')]
        
        for i, (client, min_ver) in enumerate(zip(client_parts, min_parts)):
            if client > min_ver:
                return True
            elif client < min_ver:
                return False
        
        return len(client_parts) >= len(min_parts)
    except (ValueError, AttributeError):
        return False


def constant_time_compare(a: str, b: str) -> bool:
    """Constant-time string comparison to prevent timing attacks."""
    if len(a) != len(b):
        return False
    
    result = 0
    for x, y in zip(a.encode(), b.encode()):
        result |= x ^ y
    return result == 0


async def check_auth_guard(uow: UnitOfWork, bot_key: str) -> Optional[int]:
    """Check if bot is locked due to failed attempts. Returns retry_after seconds if locked."""
    async with uow.db_pool.acquire() as conn:
        guard = await conn.fetchrow(
            "SELECT failed_attempts, locked_until FROM bot_auth_guard WHERE bot_key = $1",
            bot_key
        )
        
        if guard and guard['locked_until']:
            if datetime.utcnow() < guard['locked_until'].replace(tzinfo=None):
                # Still locked
                retry_after = int((guard['locked_until'].replace(tzinfo=None) - datetime.utcnow()).total_seconds())
                return max(retry_after, 1)
        
        return None


async def increment_failed_attempts(uow: UnitOfWork, bot_key: str):
    """Increment failed attempts and potentially lock the bot."""
    async with uow.db_pool.acquire() as conn:
        # Upsert failed attempt
        await conn.execute("""
            INSERT INTO bot_auth_guard (bot_key, failed_attempts, last_failed_at)
            VALUES ($1, 1, NOW())
            ON CONFLICT (bot_key) DO UPDATE SET
                failed_attempts = bot_auth_guard.failed_attempts + 1,
                last_failed_at = NOW(),
                locked_until = CASE 
                    WHEN bot_auth_guard.failed_attempts + 1 >= 5 
                    THEN NOW() + INTERVAL '15 minutes'
                    ELSE bot_auth_guard.locked_until
                END
        """, bot_key)


async def reset_auth_guard(uow: UnitOfWork, bot_key: str):
    """Reset failed attempts on successful auth."""
    async with uow.db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE bot_auth_guard SET failed_attempts = 0, locked_until = NULL WHERE bot_key = $1",
            bot_key
        )


@router.post("/token", responses={
    200: {"model": AuthTokenResponse},
    401: {"model": AuthErrorResponse, "description": "Unauthenticated"},
    403: {"model": AuthErrorResponse, "description": "Forbidden (bot revoked)"},
    426: {"model": AuthErrorResponse, "description": "Client too old"},
    429: {"model": AuthErrorResponse, "description": "Rate limited"},
    503: {"model": AuthErrorResponse, "description": "Temporarily unavailable"}
})
async def issue_token(
    auth_request: AuthTokenRequest,
    request: Request,
    x_client_version: str = Header(..., alias="X-Client-Version"),
    uow: UnitOfWork = Depends(get_unit_of_work)
):
    """Issue JWT access token for bot authentication (A1 specification)."""
    
    bot_key = auth_request.bot_key
    
    try:
        # 1. Check client version
        if not version_check(x_client_version):
            logger.warning(f"Outdated client version: {x_client_version} for bot: {bot_key}")
            return JSONResponse(
                status_code=426,
                content=AuthErrorResponse(
                    error_code="OUTDATED_CLIENT",
                    message=f"Client version {x_client_version} is too old. Minimum: {MIN_CLIENT_VERSION}",
                    retryable=False
                ).dict()
            )
        
        # 2. Check auth guard (rate limiting)
        retry_after = await check_auth_guard(uow, bot_key)
        if retry_after:
            logger.warning(f"Bot {bot_key} is rate limited, retry after {retry_after}s")
            response = JSONResponse(
                status_code=429,
                content=AuthErrorResponse(
                    error_code="RATE_LIMITED",
                    message=f"Too many failed attempts. Retry after {retry_after} seconds.",
                    retryable=True,
                    backoff_ms=retry_after * 1000
                ).dict()
            )
            response.headers["Retry-After"] = str(retry_after)
            return response
        
        # 3. Lookup bot in auth_bots table
        async with uow.db_pool.acquire() as conn:
            bot = await conn.fetchrow(
                "SELECT bot_key, bootstrap_secret_hash, is_enabled FROM auth_bots WHERE bot_key = $1",
                bot_key
            )
        
        # 4. Handle unknown bot (return 401 without revealing existence)
        if not bot:
            logger.warning(f"Unknown bot key attempted auth: {bot_key}")
            await increment_failed_attempts(uow, bot_key)
            return JSONResponse(
                status_code=401,
                content=AuthErrorResponse(
                    error_code="UNAUTHENTICATED",
                    message="Invalid credentials",
                    retryable=False
                ).dict()
            )
        
        # 5. Check if bot is enabled
        if not bot['is_enabled']:
            logger.warning(f"Disabled bot attempted auth: {bot_key}")
            return JSONResponse(
                status_code=403,
                content=AuthErrorResponse(
                    error_code="FORBIDDEN",
                    message="Bot access has been revoked",
                    retryable=False
                ).dict()
            )
        
        # 6. Verify bootstrap secret with constant-time comparison
        stored_hash = bot['bootstrap_secret_hash'].tobytes()
        provided_secret_bytes = auth_request.bootstrap_secret.encode('utf-8')
        
        if not bcrypt.checkpw(provided_secret_bytes, stored_hash):
            logger.warning(f"Invalid secret for bot: {bot_key}")
            await increment_failed_attempts(uow, bot_key)
            return JSONResponse(
                status_code=401,
                content=AuthErrorResponse(
                    error_code="UNAUTHENTICATED",
                    message="Invalid credentials",
                    retryable=False
                ).dict()
            )
        
        # 7. Success - Generate JWT token
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=TOKEN_TTL_SECONDS)
        jti = str(uuid.uuid4())
        
        payload = {
            "iss": JWT_ISSUER,
            "sub": bot_key,
            "aud": JWT_AUDIENCE,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
            "jti": jti,
            "scope": "register:write heartbeat:send claim:read report:write"
        }
        
        # Sign with RS256
        token = jwt.encode(
            payload, 
            PRIVATE_KEY, 
            algorithm=JWT_ALGORITHM,
            headers={"kid": KID}
        )
        
        # Reset auth guard on successful authentication
        await reset_auth_guard(uow, bot_key)
        
        # Log successful authentication (without sensitive data)
        client_ip = request.client.host if request.client else "unknown"
        logger.info(f"Token issued", extra={
            "event": "auth_token.issue",
            "bot_key": bot_key,
            "result": "success",
            "status": 200,
            "ip_hash": hash(client_ip) % 10000,  # Hash IP for privacy
            "kid": KID,
            "jti": jti
        })
        
        return AuthTokenResponse(
            access_token=token,
            token_type="Bearer",
            expires_in=TOKEN_TTL_SECONDS,
            issued_at=now.isoformat() + "Z"
        )
        
    except Exception as e:
        logger.error(f"Internal error during token issuance for bot {bot_key}: {str(e)}")
        return JSONResponse(
            status_code=503,
            content=AuthErrorResponse(
                error_code="TEMPORARY_UNAVAILABLE",
                message="Service temporarily unavailable",
                retryable=True,
                backoff_ms=5000
            ).dict()
        )


@router.get("/.well-known/jwks")
async def get_jwks():
    """JWKS endpoint for JWT verification."""
    # In production, this would return the actual public key
    return {
        "keys": [
            {
                "kty": "RSA",
                "kid": KID,
                "use": "sig",
                "alg": "RS256",
                "n": "u1SU1L7VLPHCgcXZMbw3xRlD05GID5wDVWMQ9J-_gesZqnblrmL4MesFDh9fp7484FLvvC2Cm0EH1-aj5p2IygX-V90HSrFCZzeqSw4VgWrI8DQDV9T-p0c-P9vX3JygH9Z9x4EGIGOyWfYlaFyRlWbuh-YSYVbaoV_90O0hQIDAQAB",
                "e": "AQAB"
            }
        ]
    }