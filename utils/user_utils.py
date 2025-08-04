import os
import shutil
import uuid
from sqlalchemy import insert, delete
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from lib.database import Database
from pydantic import BaseModel, constr
from typing import Optional
from utils.resource_utils import add_resource, delete_resource, get_resource
from fastapi import APIRouter, UploadFile, File, HTTPException, Path, Query
from lib.models import UserModel

db = Database()
table = db.tables
session = db.session


def create_user(user: UserModel):
    resource_id = add_resource(user.profile_picture, user.uuid)
    print(f"Resource ID: {resource_id}")

    stmt = insert(table["user"]).values(
        account_id=user.account_id,
        first_name=user.first_name,
        last_name=user.last_name,
        bio=user.bio,
        profile_picture=str(resource_id) if resource_id is not None else None,
    )
    try:
        session.execute(stmt)
        session.commit()
        return {"message": "User created successfully"}
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=400, detail="User already exists or invalid account_id"
        )
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
