import os
import shutil
import uuid
from sqlalchemy import insert, delete, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from lib.database import Database
from pydantic import BaseModel, constr
from typing import Optional
from utils.resource_utils import add_resource, delete_resource, get_resource
from fastapi import APIRouter, UploadFile, File, HTTPException, Path, Query
from lib.models import SessionModel
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, constr
from lib.database import Database
from sqlalchemy import insert, delete, select
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timedelta, timezone
import jwt

db = Database()
table = db.tables
session = db.session

SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "fallback-unsafe-key")
SESSION_DURATION_MINUTES = 60  # 1 hour session


def add_session(account_uuid: str, request: Request):
    now = datetime.now(tz=timezone.utc)
    expires_at_date_time = now + timedelta(minutes=SESSION_DURATION_MINUTES)
    ip_address = request.client.host
    user_agent = request.headers.get("user-agent", "")
    payload = {
        "account_uuid": account_uuid,
        "exp": expires_at_date_time,
        "iat": now,
    }

    session_token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")

    stmt = insert(table["session"]).values(
        account_uuid=account_uuid,
        session_token=session_token,
        created_at=now,
        expires_at=expires_at_date_time,
        ip_address=ip_address,
        user_agent=user_agent,
        last_activity=now,
    )
    try:
        session.execute(stmt)
        session.commit()
        return {"session_token": session_token, "expires_at": expires_at_date_time}
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=400, detail="Could not create session")
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


def delete_session(session_token: str):
    try:
        stmt = delete(table["session"]).where(
            table["session"].c.session_token == session_token
        )
        result = session.execute(stmt)
        session.commit()
        return result.rowcount
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


def update_session_last_activity(session_token: str):
    try:
        stmt = (
            update(table["session"])
            .where(table["session"].c.session_token == session_token)
            .values(last_activity=datetime.now(tz=timezone.utc))
        )
        result = session.execute(stmt)
        session.commit()
        return result.rowcount
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
