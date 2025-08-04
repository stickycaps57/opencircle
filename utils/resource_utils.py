import os
import shutil
import uuid
from sqlalchemy import insert, delete
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from lib.database import Database

# put in a yaml file or secret or OS env variable
UPLOAD_DIR = "uploads"


db = Database()
table = db.tables
session = db.session


def add_resource(file, uploader_uuid):
    upload_dir = UPLOAD_DIR
    modified_filename = _create_filename(uploader_uuid, file)

    _copy_resource_to_disk(modified_filename, file)
    resource_pk = _save_resource_info_into_database(upload_dir, modified_filename)

    return resource_pk


def _create_filename(uploader_uuid, file):
    original_ext = os.path.splitext(file.filename)[1]
    unique_id = uuid.uuid4().hex
    new_filename = f"{uploader_uuid}_{unique_id}{original_ext}"

    return new_filename


def _copy_resource_to_disk(modified_filename, file):
    try:
        file_location = os.path.join(UPLOAD_DIR, modified_filename)
        with open(file_location, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except (IOError, OSError) as e:
        raise IOError(f"Error saving resource: {str(e)}")


def _save_resource_info_into_database(upload_dir, modified_filename):
    try:
        stmt = insert(table["resource"]).values(
            directory=upload_dir, filename=modified_filename
        )
        result = session.execute(stmt)
        session.commit()
        return result.inserted_primary_key[0]
    except IntegrityError:
        session.rollback()
        raise IntegrityError("Resource already exists")
    except Exception as e:
        session.rollback()
        raise SQLAlchemyError(f"Error uploading resource: {str(e)}")
    finally:
        session.close()


def get_resource(resource_id):
    resource = _get_resource_by_id(resource_id)

    if not resource:
        session.close()
        raise FileNotFoundError(detail="Resource not found")
    else:
        file_path = os.path.join(resource.directory, resource.filename)
        if not os.path.exists(file_path):
            session.close()
            raise FileNotFoundError(detail="Resource file not found")

        return {
            "id": resource.id,
            "file_path": file_path,
        }


def _get_resource_by_id(resource_id):
    return (
        session.query(table["resource"])
        .filter(table["resource"].c.id == resource_id)
        .first()
    )


def delete_resource(resource_id, uuid):
    resource = _get_resource_by_id(resource_id)

    if not resource:
        session.close()
        raise FileNotFoundError(status_code=404, detail="Resource not found")
    elif _check_access_to_resource(resource, uuid):
        try:
            file_path = os.path.join(resource.directory, resource.filename)
            _delete_resource_from_disk(file_path)
            _delete_resource_from_database(resource_id)
        except (IOError, OSError) as e:
            raise IOError(f"Error deleting resource: {str(e)}")
    else:
        raise PermissionError("Access denied to resource")


def _check_access_to_resource(resource, uuid):
    if resource.filename.startswith(f"{uuid}_"):
        return True
    else:
        return False


def _delete_resource_from_database(resource_id):
    stmt = delete(table["resource"]).where(table["resource"].c.id == resource_id)
    try:
        result = session.execute(stmt)
        session.commit()
        if result.rowcount == 0:
            raise FileNotFoundError("Resource not found in database")
        return True
    except Exception as e:
        session.rollback()
        raise SQLAlchemyError(f"Database error during resource deletion: {str(e)}")
    finally:
        session.close()


def _delete_resource_from_disk(file_path):
    if file_path and os.path.exists(file_path):
        os.remove(file_path)
    else:
        raise FileNotFoundError(status_code=404, detail="Resource not found on disk")
