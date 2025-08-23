"""Authentication API endpoints."""

import jwt
from datetime import datetime, timedelta
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthRequest(BaseModel):
    bot_key: str = Field(..., min_length=1, description="Bot key identifier")
    bootstrap_secret: str = Field(..., min_length=1, description="Bootstrap secret")


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int


@router.post("/token", response_model=AuthResponse)
async def get_token(auth_request: AuthRequest):
    """Get JWT token for bot authentication."""
    
    # Simple validation - in production, verify against database
    if auth_request.bootstrap_secret != "test_bootstrap_secret":
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Generate JWT token
    now = datetime.utcnow()
    expires_in = 900  # 15 minutes
    
    payload = {
        "aud": "bots",
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
        "scope": "register",
        "bot_key": auth_request.bot_key,
        "iat": int(now.timestamp())
    }
    
    # In production, use a proper secret from environment/config
    secret_key = "your-secret-key"
    access_token = jwt.encode(payload, secret_key, algorithm="HS256")
    
    return AuthResponse(
        access_token=access_token,
        expires_in=expires_in
    )