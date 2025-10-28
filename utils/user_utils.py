import os
import shutil
import uuid
from sqlalchemy import insert, delete
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from lib.database import Database, SessionLocal
from pydantic import BaseModel, constr
from typing import Optional
from utils.resource_utils import add_resource, delete_resource, get_resource
from fastapi import APIRouter, UploadFile, File, HTTPException, Path, Query
from lib.models import UserModel

db = Database()
table = db.tables
session = db.session


def create_user(user: UserModel):
    # Create a new database session to avoid conflicts
    local_session = SessionLocal()
    
    try:
        # additional checker for profile_picture to identify if empty or not
        if (
            user.profile_picture
            and user.profile_picture.filename
            and user.profile_picture.size > 0
        ):
            resource_id = add_resource(user.profile_picture, user.uuid)
        else:
            resource_id = None
            print(
                "No valid profile picture provided, skipping file upload and resource table data creation"
            )

        stmt = insert(table["user"]).values(
            account_id=user.account_id,
            first_name=user.first_name,
            last_name=user.last_name,
            bio=user.bio,
            profile_picture=str(resource_id) if resource_id is not None else None,
        )
        
        local_session.execute(stmt)
        local_session.commit()
        return {"message": "User created successfully"}
        
    except IntegrityError:
        local_session.rollback()
        raise HTTPException(
            status_code=400, detail="User already exists or invalid account_id"
        )
    except Exception as e:
        local_session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        local_session.close()
