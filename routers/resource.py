from fastapi import APIRouter, UploadFile, File, HTTPException, Path, Query
from utils.resource_utils import add_resource, delete_resource, get_resource
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from fastapi.responses import FileResponse, RedirectResponse
from utils.ftp_utils import ftp_manager

router = APIRouter(
    prefix="/resource",
    tags=["resource"],
)


@router.post("/upload", tags=["Upload photo"])
async def upload_photo(
    file: UploadFile = File(...),
    uploader_uuid: str = File(..., description="Uploader UUID"),
):
    try:
        resource_id = add_resource(file, uploader_uuid)

        return {
            "message": "Photo uploaded successfully",
            "resource_id": resource_id,
        }

    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail="File not found")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail="Permission denied")
    except IntegrityError as e:
        raise HTTPException(status_code=409, detail="Integrity error: " + str(e.orig))
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{resource_id}", tags=["Delete photo"])
async def delete_photo(
    resource_id: int = Path(..., description="The ID of the resource to delete"),
    uploader_uuid: str = Query(..., description="Uploader UUID"),
):
    try:
        delete_resource(resource_id, uploader_uuid)
        return {"message": "Photo deleted successfully"}

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Resource not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Access denied to resource")
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except IOError as e:
        raise HTTPException(status_code=500, detail="IO error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{resource_id}", tags=["Get photo by ID"])
async def get_photo(
    resource_id: int = Path(..., description="The ID of the resource to retrieve"),
):
    try:
        resource = get_resource(resource_id)
        # Redirect to the public FTP URL instead of serving the file directly
        return RedirectResponse(url=resource["public_url"])
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Resource not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/info/{resource_id}", tags=["Get photo information by ID"])
async def get_photo(
    resource_id: int = Path(..., description="The ID of the resource to retrieve"),
):
    try:
        return get_resource(resource_id)

    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Resource not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
