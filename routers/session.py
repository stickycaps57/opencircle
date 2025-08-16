from fastapi import APIRouter, HTTPException, Request, Response, Cookie
from fastapi.responses import JSONResponse
from pydantic import BaseModel, constr
from lib.database import Database
from sqlalchemy import insert, delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from datetime import datetime, timedelta, timezone
from lib.models import SessionModel
from utils.session_utils import (
    add_session,
    delete_session,
    update_session_last_activity,
)
import jwt
import os

router = APIRouter(
    prefix="/session",
    tags=["Session Management"],
)

db = Database()
table = db.tables
session = db.session

SESSION_DURATION_MINUTES = 60  # 1 hour session
SESSION_COOKIE_NAME = "session_token"
SESSION_COOKIE_PATH = "/"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = True  # Set to True in production (HTTPS)
SESSION_COOKIE_SAMESITE = "Lax"


@router.post("/", tags=["Create Session"])
async def create_session(data: SessionModel, request: Request, response: Response):
    try:
        account_uuid = str(data.account_uuid)
        session_token, expires_at = add_session(account_uuid, request)
        # Set session token in cookie
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_token,
            httponly=SESSION_COOKIE_HTTPONLY,
            secure=SESSION_COOKIE_SECURE,
            samesite=SESSION_COOKIE_SAMESITE,
            path=SESSION_COOKIE_PATH,
            expires=expires_at,
        )
        return {"message": "Session created", "expires_at": expires_at}
    except IntegrityError:
        raise HTTPException(status_code=400, detail="Could not create session")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", tags=["Get Session"])
async def get_session(session_token: str = Cookie(None)):
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")
    stmt = select(table["session"]).where(
        table["session"].c.session_token == session_token
    )
    result = session.execute(stmt).first()
    if not result:
        raise HTTPException(status_code=404, detail="Session not found")
    session_data = dict(result._mapping)
    # Check expiry
    expires_at = session_data["expires_at"]
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(tz=timezone.utc):
        delete_session(session_token)
        raise HTTPException(status_code=401, detail="Session expired")
    else:
        update_session_last_activity(session_token)
    return session_data


@router.delete("/", tags=["Delete Session"])
async def remove_session(response: Response, session_token: str = Cookie(None)):
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")
    try:
        data = jwt.decode(session_token, SECRET_KEY, algorithms=["HS256"])
        if "account_uuid" not in data:
            raise HTTPException(status_code=400, detail="Invalid session token")
        session_deleted = delete_session(session_token, data.get("account_uuid"))
        if session_deleted == 0:
            raise HTTPException(status_code=404, detail="Session not found")
        # Remove cookie
        response.delete_cookie(key=SESSION_COOKIE_NAME, path=SESSION_COOKIE_PATH)
        return {"message": "Session deleted (logged out)"}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except jwt.PyJWTError:
        raise HTTPException(status_code=400, detail="Invalid session token")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
