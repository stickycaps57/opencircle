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
from sqlalchemy import insert, select, func
from typing import Optional
from utils.resource_utils import add_resource, delete_resource, get_resource, format_resource_for_response
from lib.models import PostModel
from sqlalchemy import update, delete
from fastapi import Cookie
from utils.session_utils import get_account_uuid_from_session
from utils.profanity_filter import moderate_text
from utils.notification_service import NotificationService
import json


router = APIRouter(
    prefix="/post",
    tags=["Post"],
)

db = Database()
table = db.tables
# session = db.session


@router.post("/", tags=["Create Post"])
async def create_post(
    description: str = Form(None),
    session_token: str = Cookie(None, alias="session_token"),
    images: Optional[list[UploadFile]] = File(None),
):
    session = db.session
    notification_service = NotificationService()

    try:
        if not session_token:
            raise HTTPException(status_code=401, detail="Authentication required")

        account_uuid = get_account_uuid_from_session(session_token)

        # Get account_id and role from account_uuid
        select_stmt = select(
            table["account"].c.id, 
            table["account"].c.role_id
        ).where(table["account"].c.uuid == account_uuid)
        account_result = session.execute(select_stmt).first()
        if account_result is None:
            raise HTTPException(status_code=404, detail="Account not found")
        
        account_data = account_result._mapping
        account_id = account_data["id"]
        role_id = account_data["role_id"]

        # Moderate description for profanity and toxicity
        if description:
            moderation_result = moderate_text(
                description, 
                toxicity_threshold=0.7, 
                auto_censor=True  # Set to False to reject instead of censoring
            )
            
            if not moderation_result["approved"]:
                raise HTTPException(
                    status_code=400, 
                    detail=moderation_result["reason"]
                )
            
            description = moderation_result["moderated_text"]

        # Handle multiple images: store resource IDs as a JSON array (list of ints)
        resource_ids = []
        if images:
            for image in images:
                if image.filename:  # Check if file was actually uploaded
                    resource_id = add_resource(image, account_uuid)
                    resource_ids.append(resource_id)

        # Store resource_ids as JSON string if not empty, else None
        images_field = json.dumps(resource_ids) if resource_ids else None

        stmt = insert(table["post"]).values(
            author=account_id,
            image=images_field,
            description=description,
        )
        result = session.execute(stmt)
        session.commit()
        
        # Get the post ID that was just created
        post_id = result.lastrowid

        # Check if this is an organization account and notify members
        if role_id == 2:  # Assuming role_id 2 is organization based on schema
            # Get organization details
            org_stmt = select(
                table["organization"].c.id,
                table["organization"].c.name
            ).where(table["organization"].c.account_id == account_id)
            org_result = session.execute(org_stmt).first()
            
            if org_result:
                org_data = org_result._mapping
                organization_id = org_data["id"]
                organization_name = org_data["name"]
                
                # Create a preview of the post description
                post_preview = description[:100] if description else "New post from organization"
                
                # Notify all organization members about the new post
                notification_service.notify_organization_members_new_post(
                    organization_id=organization_id,
                    post_id=post_id,
                    organization_name=organization_name,
                    post_preview=post_preview,
                )

        return {"message": "Post created successfully"}
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
        notification_service.close()


@router.get("/all", tags=["Get All Posts with Comments"])
async def get_all_posts(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(10, ge=1, le=100, description="Posts per page"),
):
    session = db.session
    try:
        offset = (page - 1) * page_size
        profile_resource = table["resource"].alias("profile_resource")
        org_logo_resource = table["resource"].alias("org_logo_resource")

        post_stmt = (
            select(
                table["post"].c.id,
                table["post"].c.author,
                table["post"].c.image,
                table["post"].c.description,
                table["post"].c.created_date,
                table["account"].c.uuid.label("author_uuid"),
                table["account"].c.email.label("author_email"),
                table["organization"].c.name.label("organization_name"),
                table["organization"].c.id.label("organization_id"),
                org_logo_resource.c.directory.label("organization_logo_directory"),
                org_logo_resource.c.filename.label("organization_logo_filename"),
                org_logo_resource.c.id.label("organization_logo_id"),
                table["user"].c.first_name.label("author_first_name"),
                table["user"].c.last_name.label("author_last_name"),
                table["user"].c.bio.label("author_bio"),
                table["user"].c.profile_picture.label("author_profile_picture"),
                profile_resource.c.directory.label("author_profile_picture_directory"),
                profile_resource.c.filename.label("author_profile_picture_filename"),
                profile_resource.c.id.label("author_profile_picture_id"),
            )
            .select_from(
                table["post"]
                .join(table["account"], table["post"].c.author == table["account"].c.id)
                .outerjoin(
                    table["user"], table["user"].c.account_id == table["account"].c.id
                )
                .outerjoin(
                    table["organization"], table["organization"].c.account_id == table["account"].c.id
                )
                .outerjoin(
                    org_logo_resource,
                    table["organization"].c.logo == org_logo_resource.c.id,
                )
                .outerjoin(
                    profile_resource,
                    table["user"].c.profile_picture == profile_resource.c.id,
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

            # Parse image JSON to get resource IDs and fetch resource details
            images = []
            if data["image"]:
                try:
                    resource_ids = json.loads(data["image"])
                    for res_id in resource_ids:
                        res_stmt = select(
                            table["resource"].c.id,
                            table["resource"].c.directory,
                            table["resource"].c.filename,
                        ).where(table["resource"].c.id == res_id)
                        res_result = session.execute(res_stmt).first()
                        if res_result:
                            res_data = res_result._mapping
                            images.append(format_resource_for_response(
                                res_data["id"],
                                res_data["directory"],
                                res_data["filename"]
                            ))
                except (json.JSONDecodeError, TypeError):
                    pass

            # Get total comments count for this post
            total_comments_stmt = (
                select(func.count())
                .select_from(table["comment"])
                .where(table["comment"].c.post_id == post_id)
            )
            total_comments = session.execute(total_comments_stmt).scalar()

            # Fetch top 3 latest comments...
            comment_resource = table["resource"].alias("comment_resource")
            comment_stmt = (
                select(
                    table["comment"].c.id.label("comment_id"),
                    table["comment"].c.message,
                    table["comment"].c.created_date,
                    table["account"].c.id.label("account_id"),
                    table["account"].c.uuid,
                    table["account"].c.email,
                    table["account"].c.role_id,
                    table["role"].c.name.label("role_name"),
                    table["user"].c.first_name,
                    table["user"].c.last_name,
                    table["user"].c.bio,
                    table["user"].c.profile_picture,
                    comment_resource.c.directory.label("profile_picture_directory"),
                    comment_resource.c.filename.label("profile_picture_filename"),
                    comment_resource.c.id.label("profile_picture_id"),
                    table["organization"].c.name.label("organization_name"),
                    table["organization"].c.description.label(
                        "organization_description"
                    ),
                    table["organization"].c.logo.label("organization_logo"),
                    org_logo_resource.c.directory.label("organization_logo_directory"),
                    org_logo_resource.c.filename.label("organization_logo_filename"),
                    org_logo_resource.c.id.label("organization_logo_id"),
                )
                .select_from(
                    table["comment"]
                    .join(
                        table["account"],
                        table["comment"].c.author == table["account"].c.id,
                    )
                    .join(
                        table["role"],
                        table["account"].c.role_id == table["role"].c.id,
                    )
                    .outerjoin(
                        table["user"],
                        table["user"].c.account_id == table["account"].c.id,
                    )
                    .outerjoin(
                        comment_resource,
                        table["user"].c.profile_picture == comment_resource.c.id,
                    )
                    .outerjoin(
                        table["organization"],
                        table["organization"].c.account_id == table["account"].c.id,
                    )
                    .outerjoin(
                        org_logo_resource,
                        table["organization"].c.logo == org_logo_resource.c.id,
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
                if cdata["role_name"] == "organization":
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
                            "organization": {
                                "name": cdata["organization_name"],
                                "description": cdata["organization_description"],
                                "logo": format_resource_for_response(
                                    cdata["organization_logo_id"],
                                    cdata["organization_logo_directory"],
                                    cdata["organization_logo_filename"]
                                ),
                            },
                        }
                    )
                else:
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
                                "profile_picture": format_resource_for_response(
                                    cdata["profile_picture_id"],
                                    cdata["profile_picture_directory"],
                                    cdata["profile_picture_filename"]
                                ),
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
                    "author_organization_name": data["organization_name"],
                    "author_organization_id": data["organization_id"],
                    "author_profile_picture": format_resource_for_response(
                        data["author_profile_picture_id"],
                        data["author_profile_picture_directory"],
                        data["author_profile_picture_filename"]
                    ),
                    "author_logo": format_resource_for_response(
                        data["organization_logo_id"],
                        data["organization_logo_directory"],
                        data["organization_logo_filename"]
                    ),
                    "images": images,
                    "description": data["description"],
                    "created_date": data["created_date"],
                    "latest_comments": comments,
                    "total_comments": total_comments,
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
    finally:
        session.close()


@router.get("/{account_uuid}", tags=["Get Posts of User or Organization"])
async def get_posts(
    account_uuid: str,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(5, ge=1, le=100, description="Posts per page"),
):
    session = db.session
    try:
        # Get account details
        account_stmt = select(table["account"]).where(
            table["account"].c.uuid == account_uuid
        )
        account_result = session.execute(account_stmt).first()
        if not account_result:
            raise HTTPException(status_code=404, detail="Account not found")
        account = account_result._mapping
        account_id = account["id"]
        role_id = account["role_id"]

        # Get role name
        role_stmt = select(table["role"].c.name).where(table["role"].c.id == role_id)
        role_result = session.execute(role_stmt).scalar()
        is_user = role_result == "user"
        is_org = role_result == "organization"

        offset = (page - 1) * page_size
        post_stmt = (
            select(
                table["post"].c.id,
                table["post"].c.author,
                table["post"].c.image,
                table["post"].c.description,
                table["post"].c.created_date,
                table["post"].c.last_modified_date,
            )
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

        # Get author details based on role
        author_details = None
        if is_user:
            user_stmt = (
                select(
                    table["user"].c.id,
                    table["user"].c.first_name,
                    table["user"].c.last_name,
                    table["user"].c.bio,
                    table["user"].c.profile_picture,
                    table["resource"].c.directory.label("profile_picture_directory"),
                    table["resource"].c.filename.label("profile_picture_filename"),
                )
                .select_from(
                    table["user"].outerjoin(
                        table["resource"],
                        table["user"].c.profile_picture == table["resource"].c.id,
                    )
                )
                .where(table["user"].c.account_id == account_id)
            )
            user_result = session.execute(user_stmt).first()
            if user_result:
                user = user_result._mapping
                author_details = {
                    "type": "user",
                    "id": user["id"],
                    "first_name": user["first_name"],
                    "last_name": user["last_name"],
                    "bio": user["bio"],
                    "profile_picture": format_resource_for_response(
                        user["profile_picture"],
                        user["profile_picture_directory"],
                        user["profile_picture_filename"]
                    ),
                }
        elif is_org:
            org_stmt = (
                select(
                    table["organization"].c.id,
                    table["organization"].c.name,
                    table["organization"].c.logo,
                    table["organization"].c.category,
                    table["organization"].c.description,
                    table["resource"].c.directory.label("logo_directory"),
                    table["resource"].c.filename.label("logo_filename"),
                )
                .select_from(
                    table["organization"].outerjoin(
                        table["resource"],
                        table["organization"].c.logo == table["resource"].c.id,
                    )
                )
                .where(table["organization"].c.account_id == account_id)
            )
            org_result = session.execute(org_stmt).first()
            if org_result:
                org = org_result._mapping
                author_details = {
                    "type": "organization",
                    "id": org["id"],
                    "name": org["name"],
                    "category": org["category"],
                    "description": org["description"],
                    "logo": format_resource_for_response(
                        org["logo"],
                        org["logo_directory"],
                        org["logo_filename"]
                    ),
                }

        posts = []
        for row in result:
            data = row._mapping

            # Parse image JSON to get resource IDs and fetch resource details
            images = []
            if data["image"]:
                try:
                    resource_ids = json.loads(data["image"])
                    for res_id in resource_ids:
                        res_stmt = select(
                            table["resource"].c.id,
                            table["resource"].c.directory,
                            table["resource"].c.filename,
                        ).where(table["resource"].c.id == res_id)
                        res_result = session.execute(res_stmt).first()
                        if res_result:
                            res_data = res_result._mapping
                            images.append(format_resource_for_response(
                                res_data["id"],
                                res_data["directory"],
                                res_data["filename"]
                            ))
                except (json.JSONDecodeError, TypeError):
                    pass

            posts.append(
                {
                    "id": data["id"],
                    "author_id": data["author"],
                    "images": images,
                    "description": data["description"],
                    "created_date": data["created_date"],
                    "last_modified_date": data["last_modified_date"],
                }
            )
        return {
            "page": page,
            "page_size": page_size,
            "author": author_details,
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
    session = db.session
    try:
        # Get account_id from uuid
        select_stmt = select(table["account"].c.id).where(
            table["account"].c.uuid == account_uuid
        )
        account_id = session.execute(select_stmt).scalar()
        if account_id is None:
            raise HTTPException(status_code=404, detail="Account not found")

        offset = (page - 1) * page_size

        # Get total count of posts for this account
        total_count_stmt = select(func.count(table["post"].c.id)).where(
            table["post"].c.author == account_id
        )
        total_count = session.execute(total_count_stmt).scalar() or 0

        # Alias for profile picture resource
        profile_resource = table["resource"].alias("profile_resource")
        org_logo_resource = table["resource"].alias("org_logo_resource")

        # Fetch posts with author details (no image join since we parse JSON)
        post_stmt = (
            select(
                table["post"].c.id,
                table["post"].c.author,
                table["post"].c.image,
                table["post"].c.description,
                table["post"].c.created_date,
                table["post"].c.last_modified_date,
                table["account"].c.uuid.label("author_uuid"),
                table["account"].c.email.label("author_email"),
                table["organization"].c.name.label("organization_name"),
                org_logo_resource.c.directory.label("organization_logo_directory"),
                org_logo_resource.c.filename.label("organization_logo_filename"),
                org_logo_resource.c.id.label("organization_logo_id"),
                table["user"].c.first_name.label("author_first_name"),
                table["user"].c.last_name.label("author_last_name"),
                table["user"].c.bio.label("author_bio"),
                table["user"].c.profile_picture.label("author_profile_picture"),
                profile_resource.c.directory.label("author_profile_picture_directory"),
                profile_resource.c.filename.label("author_profile_picture_filename"),
                profile_resource.c.id.label("author_profile_picture_id"),
            )
            .select_from(
                table["post"]
                .join(table["account"], table["post"].c.author == table["account"].c.id)
                .outerjoin(
                    table["user"], table["user"].c.account_id == table["account"].c.id
                )
                .outerjoin(
                    table["organization"], table["organization"].c.account_id == table["account"].c.id
                )
                .outerjoin(
                    org_logo_resource,
                    table["organization"].c.logo == org_logo_resource.c.id,
                )
                .outerjoin(
                    profile_resource,
                    table["user"].c.profile_picture == profile_resource.c.id,
                )
            )
            .where(table["post"].c.author == account_id)
            .order_by(table["post"].c.created_date.desc())
            .limit(page_size)
            .offset(offset)
        )
        posts_result = session.execute(post_stmt).fetchall()
        if not posts_result:
            return {
                "page": page,
                "page_size": page_size,
                "posts": [],
                "total": total_count,
            }

        posts = []
        for row in posts_result:
            post_dict = dict(row._mapping)
            post_id = post_dict["id"]

            # Parse image JSON to get resource IDs and fetch resource details
            images = []
            if post_dict["image"]:
                try:
                    resource_ids = json.loads(post_dict["image"])
                    for res_id in resource_ids:
                        res_stmt = select(
                            table["resource"].c.id,
                            table["resource"].c.directory,
                            table["resource"].c.filename,
                        ).where(table["resource"].c.id == res_id)
                        res_result = session.execute(res_stmt).first()
                        if res_result:
                            res_data = res_result._mapping
                            images.append(format_resource_for_response(
                                res_data["id"],
                                res_data["directory"],
                                res_data["filename"]
                            ))

                except (json.JSONDecodeError, TypeError):
                    pass

            # Fetch total comments for this post
            comment_count_stmt = select(func.count(table["comment"].c.id)).where(
                table["comment"].c.post_id == post_id
            )
            total_comments = session.execute(comment_count_stmt).scalar() or 0

            # Fetch top 3 latest comments for this post, joined with user/org details and profile picture/logo resource
            comment_resource = table["resource"].alias("comment_resource")
            comment_stmt = (
                select(
                    table["comment"].c.id.label("comment_id"),
                    table["comment"].c.message,
                    table["comment"].c.created_date,
                    table["account"].c.id.label("account_id"),
                    table["account"].c.uuid,
                    table["account"].c.email,
                    table["account"].c.role_id,
                    table["role"].c.name.label("role_name"),
                    table["user"].c.first_name,
                    table["user"].c.last_name,
                    table["user"].c.bio,
                    table["user"].c.profile_picture,
                    comment_resource.c.directory.label("profile_picture_directory"),
                    comment_resource.c.filename.label("profile_picture_filename"),
                    comment_resource.c.id.label("profile_picture_id"),
                    table["organization"].c.name.label("organization_name"),
                    table["organization"].c.description.label(
                        "organization_description"
                    ),
                    table["organization"].c.logo.label("organization_logo"),
                    org_logo_resource.c.directory.label("organization_logo_directory"),
                    org_logo_resource.c.filename.label("organization_logo_filename"),
                    org_logo_resource.c.id.label("organization_logo_id"),
                )
                .select_from(
                    table["comment"]
                    .join(
                        table["account"],
                        table["comment"].c.author == table["account"].c.id,
                    )
                    .join(
                        table["role"],
                        table["account"].c.role_id == table["role"].c.id,
                    )
                    .outerjoin(
                        table["user"],
                        table["user"].c.account_id == table["account"].c.id,
                    )
                    .outerjoin(
                        comment_resource,
                        table["user"].c.profile_picture == comment_resource.c.id,
                    )
                    .outerjoin(
                        table["organization"],
                        table["organization"].c.account_id == table["account"].c.id,
                    )
                    .outerjoin(
                        org_logo_resource,
                        table["organization"].c.logo == org_logo_resource.c.id,
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
                if data["role_name"] == "organization":
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
                            "organization": {
                                "name": data["organization_name"],
                                "description": data["organization_description"],
                                "logo": format_resource_for_response(
                                    data["organization_logo_id"],
                                    data["organization_logo_directory"],
                                    data["organization_logo_filename"]
                                ),
                            },
                        }
                    )
                else:
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
                                "profile_picture": format_resource_for_response(
                                    data["profile_picture_id"],
                                    data["profile_picture_directory"],
                                    data["profile_picture_filename"]
                                ),
                            },
                        }
                    )

            # Add total comments count to post
            post_dict["total_comments"] = total_comments
            post_dict["comments"] = comments
            # Add images array instead of single image
            post_dict["images"] = images
            # Add author details to post, including joined profile picture resource
            post_dict["author"] = {
                "id": post_dict["author"],
                "uuid": post_dict["author_uuid"],
                "email": post_dict["author_email"],
                "first_name": post_dict["author_first_name"],
                "last_name": post_dict["author_last_name"],
                "bio": post_dict["author_bio"],
                "organization_name": post_dict["organization_name"],
                "profile_picture": format_resource_for_response(
                    post_dict["author_profile_picture_id"],
                    post_dict["author_profile_picture_directory"],
                    post_dict["author_profile_picture_filename"]
                ),
                "logo": format_resource_for_response(
                    post_dict["organization_logo_id"],
                    post_dict["organization_logo_directory"],
                    post_dict["organization_logo_filename"]
                ),
            }
            # Remove raw resource and author fields from top-level
            post_dict.pop("image", None)
            post_dict.pop("author_uuid", None)
            post_dict.pop("author_email", None)
            post_dict.pop("author_first_name", None)
            post_dict.pop("author_last_name", None)
            post_dict.pop("author_bio", None)
            post_dict.pop("organization_name", None)
            post_dict.pop("organization_logo_id", None)
            post_dict.pop("organization_logo_directory", None)
            post_dict.pop("organization_logo_filename", None)
            post_dict.pop("author_profile_picture", None)
            post_dict.pop("author_profile_picture_id", None)
            post_dict.pop("author_profile_picture_directory", None)
            post_dict.pop("author_profile_picture_filename", None)
            posts.append(post_dict)

        return {
            "page": page,
            "page_size": page_size,
            "posts": posts,
            "total": total_count,
        }
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{post_id}", tags=["Update Post"])
async def update_post(
    post_id: int = Path(..., description="The ID of the post to update"),
    description: str = Form(None),
    images: Optional[list[UploadFile]] = File(None),
    session_token: str = Cookie(None, alias="session_token"),
):
    session = db.session
    try:
        if not session_token:
            raise HTTPException(status_code=401, detail="Authentication required")

        account_uuid = get_account_uuid_from_session(session_token)

        # Get account_id from account_uuid
        account_stmt = select(table["account"].c.id).where(
            table["account"].c.uuid == account_uuid
        )
        account_row = session.execute(account_stmt).first()
        if not account_row:
            raise HTTPException(status_code=404, detail="Account not found")
        account_id = account_row._mapping["id"]

        # Check if post is owned by user and get existing images
        post_stmt = select(table["post"].c.author, table["post"].c.image).where(
            table["post"].c.id == post_id
        )
        post = session.execute(post_stmt).fetchone()
        if not post or post.author != account_id:
            raise HTTPException(
                status_code=403, detail="You are not the author of this post"
            )

        # Prepare update values
        update_values = {}
        if description is not None:
            # Ensure description is a string
            description_str = str(description)
            # Moderate description for profanity and toxicity
            moderation_result = moderate_text(
                description_str, 
                toxicity_threshold=0.7, 
                auto_censor=True  # Set to False to reject instead of censoring
            )
            
            if not moderation_result["approved"]:
                raise HTTPException(
                    status_code=400, 
                    detail=moderation_result["reason"]
                )
            
            update_values["description"] = moderation_result["moderated_text"]
        
        if images is not None:
            # Delete existing images
            existing_images = post.image
            if existing_images:
                try:
                    existing_resource_ids = json.loads(existing_images)
                    for resource_id in existing_resource_ids:
                        delete_resource(resource_id, account_uuid)
                except (json.JSONDecodeError, TypeError):
                    pass
            
            # Upload new images
            resource_ids = []
            for image in images:
                if image.filename:  # Check if file was actually uploaded
                    resource_id = add_resource(image, account_uuid)
                    resource_ids.append(resource_id)
            
            # Store resource_ids as JSON string if not empty, else None
            update_values["image"] = json.dumps(resource_ids) if resource_ids else None
        else:
            existing_images = post.image
            if existing_images:
                try:
                    existing_resource_ids = json.loads(existing_images)
                    for resource_id in existing_resource_ids:
                        delete_resource(resource_id, account_uuid)
                except (json.JSONDecodeError, TypeError):
                    pass
            update_values["image"] = None

        if not update_values:
            raise HTTPException(status_code=400, detail="No update fields provided")

        # Update post
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
    session_token: str = Cookie(None, alias="session_token"),
):
    session = db.session
    try:
        if not session_token:
            raise HTTPException(status_code=401, detail="Authentication required")

        account_uuid = get_account_uuid_from_session(session_token)

        # Get account_id from account_uuid
        account_stmt = select(table["account"].c.id).where(
            table["account"].c.uuid == account_uuid
        )
        account_id = session.execute(account_stmt).scalar()

        if account_id is None:
            raise HTTPException(status_code=404, detail="Account not found")

        # Check if post exists and is owned by user
        post_stmt = select(table["post"].c.image, table["post"].c.author).where(
            table["post"].c.id == post_id
        )
        post = session.execute(post_stmt).fetchone()
        if not post or post.author != account_id:
            raise HTTPException(
                status_code=404, detail="Post not found or not owned by user"
            )

        # Delete associated resources if exists (multiple images)
        images_field = post.image
        if images_field:
            try:
                resource_ids = json.loads(images_field)
                for resource_id in resource_ids:
                    delete_resource(resource_id, account_uuid)
            except (json.JSONDecodeError, TypeError):
                # Handle case where it might be a single resource_id (legacy data)
                pass

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


@router.get("/single/{post_id}", tags=["Get Single Post"])
async def get_single_post(
    post_id: int = Path(..., description="The ID of the post to fetch"),
):
    session = db.session
    try:
        # Join post with account (author), user/org, and resource (profile picture)
        profile_resource = table["resource"].alias("profile_resource")
        post_stmt = (
            select(
                table["post"].c.id,
                table["post"].c.description,
                table["post"].c.created_date,
                table["post"].c.last_modified_date,
                table["post"].c.image,
                table["post"].c.author,
                table["account"].c.uuid.label("author_uuid"),
                table["account"].c.email.label("author_email"),
                table["user"].c.first_name.label("author_first_name"),
                table["user"].c.last_name.label("author_last_name"),
                table["user"].c.bio.label("author_bio"),
                table["user"].c.profile_picture.label("author_profile_picture"),
                profile_resource.c.directory.label("author_profile_picture_directory"),
                profile_resource.c.filename.label("author_profile_picture_filename"),
                profile_resource.c.id.label("author_profile_picture_id"),
            )
            .select_from(
                table["post"]
                .join(table["account"], table["post"].c.author == table["account"].c.id)
                .outerjoin(
                    table["user"], table["user"].c.account_id == table["account"].c.id
                )
                .outerjoin(
                    profile_resource,
                    table["user"].c.profile_picture == profile_resource.c.id,
                )
            )
            .where(table["post"].c.id == post_id)
        )
        result = session.execute(post_stmt).first()
        if not result:
            raise HTTPException(status_code=404, detail="Post not found")
        data = result._mapping

        # Parse image JSON to get resource IDs and fetch resource details
        images = []
        if data["image"]:
            try:
                resource_ids = json.loads(data["image"])
                for res_id in resource_ids:
                    res_stmt = select(
                        table["resource"].c.id,
                        table["resource"].c.directory,
                        table["resource"].c.filename,
                    ).where(table["resource"].c.id == res_id)
                    res_result = session.execute(res_stmt).first()
                    if res_result:
                        res_data = res_result._mapping
                        images.append(format_resource_for_response(
                            res_data["id"],
                            res_data["directory"],
                            res_data["filename"]
                        ))
            except (json.JSONDecodeError, TypeError):
                pass

        post = {
            "id": data["id"],
            "description": data["description"],
            "created_date": data["created_date"],
            "last_modified_date": data["last_modified_date"],
            "author": {
                "id": data["author"],
                "uuid": data["author_uuid"],
                "email": data["author_email"],
                "first_name": data["author_first_name"],
                "last_name": data["author_last_name"],
                "bio": data["author_bio"],
                "profile_picture": format_resource_for_response(
                    data["author_profile_picture_id"],
                    data["author_profile_picture_directory"],
                    data["author_profile_picture_filename"]
                ),
            },
            "images": images,
        }
        return post
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
