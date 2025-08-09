from fastapi import (
    APIRouter,
    HTTPException,
    Path,
    UploadFile,
    File,
    Form,
    Request,
    Query,
)
from pydantic import BaseModel, constr
from lib.database import Database
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import insert, select
from typing import Optional
from utils.resource_utils import add_resource, delete_resource, get_resource
from lib.models import PostModel
from sqlalchemy import update, delete

router = APIRouter(
    prefix="/post",
    tags=["Post"],
)

db = Database()
table = db.tables
session = db.session


@router.post("/", tags=["Create Post"])
async def create_post(
    account_uuid: str = Form(...),
    account_id: int = Form(None),
    image: UploadFile = File(None),
    description: str = Form(None),
):
    resource_id = add_resource(image, account_uuid)
    if account_id is None:
        select_stmt = select(table["account"].c.id).where(
            table["account"].c.uuid == account_uuid
        )
        account_id = session.execute(select_stmt).scalar()

    stmt = insert(table["post"]).values(
        author=account_id,
        image=resource_id,
        description=description,
    )
    try:
        session.execute(stmt)
        session.commit()
        return {"message": "Post created successfully"}
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.get("/{account_uuid}", tags=["Get Posts"])
async def get_posts(
    account_uuid: str,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(5, ge=1, le=100, description="Posts per page"),
):
    try:
        select_stmt = select(table["account"].c.id).where(
            table["account"].c.uuid == account_uuid
        )
        account_id = session.execute(select_stmt).scalar()
        offset = (page - 1) * page_size
        post_stmt = (
            select(table["post"])
            .where(table["post"].c.author == account_id)
            .limit(page_size)
            .offset(offset)
        )
        result = session.execute(post_stmt).fetchall()
        if not result:
            raise HTTPException(
                status_code=404, detail="No posts found for this account"
            )

        posts = [dict(row._mapping) for row in result]
        return {
            "page": page,
            "page_size": page_size,
            "posts": posts,
            "count": len(posts),
        }
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{post_id}", tags=["Update Post"])
async def update_post(
    post_id: int = Path(..., description="The ID of the post to update"),
    description: str = Form(None),
    image: UploadFile = File(None),
    account_uuid: str = Form(...),
):
    try:
        # Get account_id from uuid
        select_stmt = select(table["account"].c.id).where(
            table["account"].c.uuid == account_uuid
        )
        account_id = session.execute(select_stmt).scalar()
        if account_id is None:
            raise HTTPException(status_code=404, detail="Account not found")

        # Prepare update values
        update_values = {}
        if description is not None:
            update_values["description"] = description
        if image is not None:
            resource_id = add_resource(image, account_uuid)
            update_values["image"] = resource_id

        if not update_values:
            raise HTTPException(status_code=400, detail="No update fields provided")

        # Update post only if author matches

        stmt = (
            update(table["post"])
            .where(table["post"].c.id == post_id)
            .where(table["post"].c.author == account_id)
            .values(**update_values)
        )
        result = session.execute(stmt)
        session.commit()
        if result.rowcount == 0:
            raise HTTPException(
                status_code=404, detail="Post not found or not owned by user"
            )
        return {"message": "Post updated successfully"}
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.delete("/{post_id}", tags=["Delete Post"])
async def delete_post(
    post_id: int = Path(..., description="The ID of the post to delete"),
    account_uuid: str = Form(...),
):
    try:
        # Get account_id from uuid
        select_stmt = select(table["account"].c.id).where(
            table["account"].c.uuid == account_uuid
        )
        account_id = session.execute(select_stmt).scalar()
        if account_id is None:
            raise HTTPException(status_code=404, detail="Account not found")

        # Check if post exists and is owned by user
        post_stmt = select(table["post"].c.image).where(
            table["post"].c.id == post_id, table["post"].c.author == account_id
        )
        post = session.execute(post_stmt).fetchone()
        if not post:
            raise HTTPException(
                status_code=404, detail="Post not found or not owned by user"
            )

        # Delete associated resource if exists
        resource_id = post.image
        if resource_id:
            delete_resource(resource_id, account_uuid)

        # Delete post
        stmt = delete(table["post"]).where(
            table["post"].c.id == post_id, table["post"].c.author == account_id
        )
        result = session.execute(stmt)
        session.commit()
        if result.rowcount == 0:
            raise HTTPException(
                status_code=404, detail="Post not found or not owned by user"
            )
        return {"message": "Post deleted successfully"}
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
