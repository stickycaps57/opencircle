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
from lib.models import OrganizationModel

db = Database()
table = db.tables
session = db.session


def create_organization(organization: OrganizationModel):

    # additional checker for logo to identify if empty or not
    if organization.logo and organization.logo.filename and organization.logo.size > 0:
        resource_id = add_resource(organization.logo, organization.uuid)
    else:
        resource_id = None
        print(
            "No valid logo provided, skipping file upload and resource table data creation"
        )

    print(f"Resource ID: {resource_id}")

    stmt = insert(table["organization"]).values(
        account_id=organization.account_id,
        name=organization.name,
        logo=str(resource_id) if resource_id is not None else None,
        category=organization.category,
        description=organization.description,
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
