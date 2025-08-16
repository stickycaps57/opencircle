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


@router.get("/all", tags=["Get All Posts with Comments"])
async def get_all_posts(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Posts per page"),
):
    try:
        offset = (page - 1) * page_size
        post_stmt = (
            select(
                table["post"].c.id,
                table["post"].c.author,
                table["post"].c.image,
                table["post"].c.description,
                table["post"].c.created_date,
                table["account"].c.uuid.label("author_uuid"),
                table["account"].c.email.label("author_email"),
                table["user"].c.first_name.label("author_first_name"),
                table["user"].c.last_name.label("author_last_name"),
                table["user"].c.bio.label("author_bio"),
                table["user"].c.profile_picture.label("author_profile_picture"),
                table["resource"].c.directory.label("image_directory"),
                table["resource"].c.filename.label("image_filename"),
            )
            .select_from(
                table["post"]
                .join(table["account"], table["post"].c.author == table["account"].c.id)
                .outerjoin(
                    table["user"], table["user"].c.account_id == table["account"].c.id
                )
                .outerjoin(
                    table["resource"], table["post"].c.image == table["resource"].c.id
                )
            )
            .order_by(table["post"].c.created_date.desc())
            .limit(page_size)
            .offset(offset)
        )
        result = session.execute(post_stmt).fetchall()
        posts = []
        for row in result:
            data = row._mapping
            post_id = data["id"]

            # Fetch top 3 latest comments for this post, joined with user details
            comment_stmt = (
                select(
                    table["comment"].c.id.label("comment_id"),
                    table["comment"].c.message,
                    table["comment"].c.created_date,
                    table["account"].c.id.label("account_id"),
                    table["account"].c.uuid,
                    table["account"].c.email,
                    table["user"].c.first_name,
                    table["user"].c.last_name,
                    table["user"].c.bio,
                    table["user"].c.profile_picture,
                )
                .select_from(
                    table["comment"]
                    .join(
                        table["account"],
                        table["comment"].c.author == table["account"].c.id,
                    )
                    .outerjoin(
                        table["user"],
                        table["user"].c.account_id == table["account"].c.id,
                    )
                )
                .where(table["comment"].c.post_id == post_id)
                .order_by(table["comment"].c.created_date.desc())
                .limit(3)
            )
            comments_result = session.execute(comment_stmt).fetchall()
            comments = []
            for comment in comments_result:
                cdata = comment._mapping
                comments.append(
                    {
                        "comment_id": cdata["comment_id"],
                        "message": cdata["message"],
                        "created_date": cdata["created_date"],
                        "account": {
                            "id": cdata["account_id"],
                            "uuid": cdata["uuid"],
                            "email": cdata["email"],
                        },
                        "user": {
                            "first_name": cdata["first_name"],
                            "last_name": cdata["last_name"],
                            "bio": cdata["bio"],
                            "profile_picture": cdata["profile_picture"],
                        },
                    }
                )

            posts.append(
                {
                    "id": data["id"],
                    "author_id": data["author"],
                    "author_uuid": data["author_uuid"],
                    "author_email": data["author_email"],
                    "author_first_name": data["author_first_name"],
                    "author_last_name": data["author_last_name"],
                    "author_bio": data["author_bio"],
                    "author_profile_picture": data["author_profile_picture"],
                    "image": (
                        {
                            "id": data["image"],
                            "directory": data["image_directory"],
                            "filename": data["image_filename"],
                        }
                        if data["image"]
                        else None
                    ),
                    "description": data["description"],
                    "created_date": data["created_date"],
                    "latest_comments": comments,
                }
            )
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
            .order_by(table["post"].c.created_date.desc())
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


@router.get("/{account_uuid}/with_comments", tags=["Get Posts With Comments"])
async def get_posts_with_comments(
    account_uuid: str,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(5, ge=1, le=100, description="Posts per page"),
):
    try:
        # Get account_id from uuid
        select_stmt = select(table["account"].c.id).where(
            table["account"].c.uuid == account_uuid
        )
        account_id = session.execute(select_stmt).scalar()
        if account_id is None:
            raise HTTPException(status_code=404, detail="Account not found")

        offset = (page - 1) * page_size

        # Fetch posts
        post_stmt = (
            select(table["post"])
            .where(table["post"].c.author == account_id)
            .order_by(table["post"].c.created_date.desc())
            .limit(page_size)
            .offset(offset)
        )
        posts_result = session.execute(post_stmt).fetchall()
        if not posts_result:
            raise HTTPException(
                status_code=404, detail="No posts found for this account"
            )

        posts = []
        for row in posts_result:
            post_dict = dict(row._mapping)
            post_id = post_dict["id"]

            # Fetch top 3 latest comments for this post, joined with user details
            comment_stmt = (
                select(
                    table["comment"].c.id.label("comment_id"),
                    table["comment"].c.message,
                    table["comment"].c.created_date,
                    table["account"].c.id.label("account_id"),
                    table["account"].c.uuid,
                    table["account"].c.email,
                    table["user"].c.first_name,
                    table["user"].c.last_name,
                    table["user"].c.bio,
                    table["user"].c.profile_picture,
                )
                .select_from(
                    table["comment"]
                    .join(
                        table["account"],
                        table["comment"].c.author == table["account"].c.id,
                    )
                    .outerjoin(
                        table["user"],
                        table["user"].c.account_id == table["account"].c.id,
                    )
                )
                .where(table["comment"].c.post_id == post_id)
                .order_by(table["comment"].c.created_date.desc())
                .limit(3)
            )
            comments_result = session.execute(comment_stmt).fetchall()
            comments = []
            for comment in comments_result:
                data = comment._mapping
                comments.append(
                    {
                        "comment_id": data["comment_id"],
                        "message": data["message"],
                        "created_date": data["created_date"],
                        "account": {
                            "id": data["account_id"],
                            "uuid": data["uuid"],
                            "email": data["email"],
                        },
                        "user": {
                            "first_name": data["first_name"],
                            "last_name": data["last_name"],
                            "bio": data["bio"],
                            "profile_picture": data["profile_picture"],
                        },
                    }
                )
            post_dict["comments"] = comments
            posts.append(post_dict)

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
