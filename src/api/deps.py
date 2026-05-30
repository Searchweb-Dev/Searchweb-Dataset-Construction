"""FastAPI 의존성."""

from fastapi import HTTPException, Header
from src.core.config import get_api_key


def verify_api_key(x_api_key: str = Header(...)) -> str:
    """API Key 검증."""
    valid_api_key = get_api_key()
    if not x_api_key or x_api_key != valid_api_key:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return x_api_key
