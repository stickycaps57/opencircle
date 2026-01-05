import os
import shutil
import uuid
from sqlalchemy import insert, delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from lib.database import Database
from utils.ftp_utils import ftp_manager
from fastapi import HTTPException

# FTP is now used instead of local storage
# UPLOAD_DIR = "uploads"  # Legacy - not used with FTP

db = Database()
table = db.tables


def add_resource(file, uploader_uuid):
    """
    Upload file to FTP and save resource info to database
    
    Args:
        file: UploadFile object
        uploader_uuid: UUID of the uploader
        
    Returns:
        int: Resource ID from database
    """
    session = db.session
    try:
        # Upload to FTP
        directory, filename, public_url = ftp_manager.upload_file(file, uploader_uuid)
        
        # Save resource info to database
        stmt = insert(table["resource"]).values(
            directory=directory,
            filename=filename
        )
        result = session.execute(stmt)
        session.commit()
        
        return result.inserted_primary_key[0]
        
    except Exception as e:
        session.rollback()
        raise Exception(f"Failed to add resource: {str(e)}")
    finally:
        session.close()


def delete_resource(resource_id, uploader_uuid):
    """
    Delete resource from FTP and database
    
    Args:
        resource_id: Resource ID from database
        uploader_uuid: UUID of the uploader (for authorization)
    """
    session = db.session
    try:
        # Get resource info from database
        resource_stmt = select(table["resource"]).where(table["resource"].c.id == resource_id)
        resource_result = session.execute(resource_stmt).first()
        
        if not resource_result:
            raise FileNotFoundError("Resource not found")
        
        resource = resource_result._mapping
        
        # Verify ownership (check if directory matches uploader_uuid)
        if resource["directory"] != uploader_uuid:
            raise PermissionError("Access denied to resource")
        
        # Delete from FTP
        ftp_manager.delete_file(resource["directory"], resource["filename"])
        
        # Delete from database
        delete_stmt = delete(table["resource"]).where(table["resource"].c.id == resource_id)
        result = session.execute(delete_stmt)
        session.commit()
        
        if result.rowcount == 0:
            raise FileNotFoundError("Resource not found in database")
            
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


def get_resource(resource_id):
    """
    Get resource information and public URL
    
    Args:
        resource_id: Resource ID from database
        
    Returns:
        dict: Resource information with public URL
    """
    session = db.session
    try:
        resource_stmt = select(table["resource"]).where(table["resource"].c.id == resource_id)
        resource_result = session.execute(resource_stmt).first()
        
        if not resource_result:
            raise FileNotFoundError("Resource not found")
        
        resource = resource_result._mapping
        
        # Generate public URL for FTP-hosted file
        public_url = ftp_manager.get_file_url(resource["directory"], resource["filename"])
        
        return {
            "id": resource["id"],
            "directory": resource["directory"],
            "filename": resource["filename"],
            "file_path": public_url,  # This is now the public URL
            "public_url": public_url
        }
        
    except Exception as e:
        raise e
    finally:
        session.close()


def _delete_resource_from_disk(file_path):
    if file_path and os.path.exists(file_path):
        os.remove(file_path)
    else:
        raise FileNotFoundError(status_code=404, detail="Resource not found on disk")