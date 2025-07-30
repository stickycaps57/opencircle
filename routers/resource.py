from fastapi import APIRouter, UploadFile, File, HTTPException, Path
from lib.database import Database
from sqlalchemy import insert, delete
from sqlalchemy.exc import IntegrityError
import shutil
import os
import uuid

router = APIRouter(
    prefix="/resource",
    tags=["resource"],
)

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

db = Database()
table = db.tables
session = db.session


@router.post("/upload", tags=["Upload resource"])
async def upload_photo(
    file: UploadFile = File(...),
    uploader_uuid: str = File(..., description="Uploader UUID"),
):
    # Generate a unique filename using uploader's UUID and a random UUID
    original_ext = os.path.splitext(file.filename)[1]
    unique_id = uuid.uuid4().hex
    new_filename = f"{uploader_uuid}_{unique_id}{original_ext}"

    file_location = os.path.join(UPLOAD_DIR, new_filename)
    try:
        with open(file_location, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        # Insert file record into the resource table
        stmt = insert(table["resource"]).values(
            directory=os.path.join(UPLOAD_DIR, new_filename)
        )
        result = session.execute(stmt)
        session.commit()
        resource_id = result.inserted_primary_key[0]
        return {
            "message": "Photo uploaded successfully",
            "resource_id": resource_id,
            "filename": new_filename,
        }
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=400, detail="Resource already exists")
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.delete("/{resource_id}", tags=["Delete resource"])
async def delete_photo(
    resource_id: int = Path(..., description="The ID of the resource to delete")
):
    # Get file path from DB
    resource = (
        session.query(table["resource"])
        .filter(table["resource"].c.id == resource_id)
        .first()
    )
    if not resource:
        session.close()
        raise HTTPException(status_code=404, detail="Resource not found")
    file_path = resource.path
    try:
        # Delete DB record
        stmt = delete(table["resource"]).where(table["resource"].c.id == resource_id)
        session.execute(stmt)
        session.commit()
        # Delete file from disk
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        return {"message": "Photo deleted successfully"}
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
