import os
import shutil
import uuid
import base64
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


def format_resource_for_response(resource_id, directory=None, filename=None):
    """
    Format resource information for API responses with the actual image data
    
    Args:
        resource_id: Resource ID from database
        directory: Optional directory (if already known)
        filename: Optional filename (if already known)
        
    Returns:
        dict: Formatted resource information with base64-encoded image data
    """
    if resource_id is None:
        return None
    
    try:
        # If directory and filename are not provided, get them from database
        if directory is None or filename is None:
            session = db.session
            try:
                resource_stmt = select(table["resource"]).where(table["resource"].c.id == resource_id)
                resource_result = session.execute(resource_stmt).first()
                
                if not resource_result:
                    return None
                
                resource = resource_result._mapping
                directory = resource["directory"]
                filename = resource["filename"]
            finally:
                session.close()
        
        # Download file content from FTP
        file_content = ftp_manager.download_file(directory, filename)
        
        if file_content is None:
            return None
        
        # Convert to base64 for frontend use
        base64_content = base64.b64encode(file_content).decode('utf-8')
        
        # Determine content type based on file extension
        extension = filename.lower().split('.')[-1] if '.' in filename else ''
        content_type_map = {
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'gif': 'image/gif',
            'bmp': 'image/bmp',
            'webp': 'image/webp',
            'svg': 'image/svg+xml',
        }
        content_type = content_type_map.get(extension, 'image/jpeg')
        
        # Return data URL format for direct use in frontend
        data_url = f"data:{content_type};base64,{base64_content}"
        
        return {
            "id": resource_id,
            "directory": directory,
            "filename": filename,
            "image": data_url  # This contains the actual image data
        }
        
    except Exception as e:
        # If there's any error downloading or processing, return None
        return None


def get_resource_url(resource_id):
    """
    Generate the API endpoint URL for a resource that serves the actual file content
    
    Args:
        resource_id: Resource ID from database
        
    Returns:
        str: API endpoint URL that serves the file content
    """
    if resource_id is None:
        return None
    return f"/resource/{resource_id}"


def get_resource_with_url(resource_id):
    """
    Get resource information with API endpoint URL instead of FTP URL
    
    Args:
        resource_id: Resource ID from database
        
    Returns:
        dict: Resource information with API endpoint URL
    """
    session = db.session
    try:
        resource_stmt = select(table["resource"]).where(table["resource"].c.id == resource_id)
        resource_result = session.execute(resource_stmt).first()
        
        if not resource_result:
            raise FileNotFoundError("Resource not found")
        
        resource = resource_result._mapping
        
        # Generate API endpoint URL instead of FTP URL
        resource_url = get_resource_url(resource_id)
        
        return {
            "id": resource["id"],
            "directory": resource["directory"],
            "filename": resource["filename"],
            "file_path": resource_url,  # This is now the API endpoint URL
            "public_url": resource_url  # This is now the API endpoint URL
        }
        
    except Exception as e:
        raise e
    finally:
        session.close()


def get_resource_file_content(resource_id):
    """
    Get resource file content as bytes
    
    Args:
        resource_id: Resource ID from database
        
    Returns:
        tuple: (file_content_bytes, filename, content_type)
    """
    session = db.session
    try:
        resource_stmt = select(table["resource"]).where(table["resource"].c.id == resource_id)
        resource_result = session.execute(resource_stmt).first()
        
        if not resource_result:
            raise FileNotFoundError("Resource not found")
        
        resource = resource_result._mapping
        
        # Download file content from FTP
        file_content = ftp_manager.download_file(resource["directory"], resource["filename"])
        
        if file_content is None:
            raise FileNotFoundError("File not found on FTP server")
        
        # Determine content type based on file extension
        filename = resource["filename"]
        extension = filename.lower().split('.')[-1] if '.' in filename else ''
        
        content_type_map = {
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'gif': 'image/gif',
            'bmp': 'image/bmp',
            'webp': 'image/webp',
            'svg': 'image/svg+xml',
            'pdf': 'application/pdf',
            'txt': 'text/plain',
            'csv': 'text/csv',
            'json': 'application/json',
            'xml': 'application/xml',
        }
        
        content_type = content_type_map.get(extension, 'application/octet-stream')
        
        return file_content, filename, content_type
        
    except Exception as e:
        raise e
    finally:
        session.close()


def _delete_resource_from_disk(file_path):
    if file_path and os.path.exists(file_path):
        os.remove(file_path)
    else:
        raise FileNotFoundError(status_code=404, detail="Resource not found on disk")
