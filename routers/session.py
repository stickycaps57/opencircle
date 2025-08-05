from fastapi import APIRouter, HTTPException, Request
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


@router.post("/", tags=["Create Session"])
async def create_session(data: SessionModel, request: Request):
    try:
        account_uuid = str(data.account_uuid)
        return add_session(account_uuid, request)
    except IntegrityError:
        raise HTTPException(status_code=400, detail="Could not create session")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{session_token}", tags=["Get Session"])
async def get_session(session_token: str):
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
        # Optionally, delete expired session here
        delete_session(session_token)
        raise HTTPException(status_code=401, detail="Session expired")
    else:
        # Update last activity timestamp
        update_session_last_activity(session_token)

    return session_data


@router.delete("/{session_token}", tags=["Delete Session"])
async def remove_session(session_token: str):
    try:
        data = jwt.decode(session_token, SECRET_KEY, algorithms=["HS256"])
        if "account_uuid" not in data:
            raise HTTPException(status_code=400, detail="Invalid session token")
        else:
            session_deleted = delete_session(session_token, data.get("account_uuid"))
            if session_deleted == 0:
                raise HTTPException(status_code=404, detail="Session not found")
            return {"message": "Session deleted (logged out)"}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=str(e))
