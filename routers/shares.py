from fastapi import APIRouter, HTTPException, Form, Cookie, Query
from fastapi.responses import JSONResponse
from lib.database import Database
from sqlalchemy import insert, delete, select, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from utils.session_utils import get_account_uuid_from_session
from typing import Optional
import json

router = APIRouter(
    prefix="/share",
    tags=["Shares Management"],
)
db = Database()
table = db.tables
# session = db.session

@router.post("/", tags=["Share Content"])
async def share_content(
    content_id: int = Form(..., description="ID of the content to share (post or event)"),
    content_type: int = Form(..., description="Content type: 1 for post, 2 for event"),
    comment: Optional[str] = Form(None, description="Optional comment when sharing"),
    session_token: str = Cookie(None, alias="session_token"),
):
    try:

        session = db.session

        if not session_token:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Validate content_type
        if content_type not in [1, 2]:
            raise HTTPException(status_code=400, detail="Content type must be 1 (post) or 2 (event)")

        # Get account_uuid from session
        account_uuid = get_account_uuid_from_session(session_token)

        # Validate that the content exists
        if content_type == 1:  # Post
            post_exists = session.execute(
                select(table["post"].c.id).where(table["post"].c.id == content_id)
            ).scalar()
            if not post_exists:
                raise HTTPException(status_code=404, detail="Post not found")
        elif content_type == 2:  # Event
            event_exists = session.execute(
                select(table["event"].c.id).where(table["event"].c.id == content_id)
            ).scalar()
            if not event_exists:
                raise HTTPException(status_code=404, detail="Event not found")

        # Check if already shared by this user
        existing_share = session.execute(
            select(table["shares"].c.id).where(
                (table["shares"].c.account_uuid == account_uuid) &
                (table["shares"].c.content_id == content_id) &
                (table["shares"].c.content_type == content_type)
            )
        ).scalar()
        if existing_share:
            raise HTTPException(status_code=409, detail="Content already shared by this user")

        # Insert share
        stmt = insert(table["shares"]).values(
            account_uuid=account_uuid,
            content_id=content_id,
            content_type=content_type,
            comment=comment
        )
        result = session.execute(stmt)
        session.commit()
        share_id = result.inserted_primary_key[0]

        content_name = "post" if content_type == 1 else "event"
        return {
            "share_id": share_id,
            "message": f"{content_name.capitalize()} shared successfully"
        }

    except IntegrityError as e:
        session.rollback()
        raise HTTPException(status_code=400, detail="Integrity error: " + str(e))
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.delete("/{share_id}", tags=["Delete Share"])
async def delete_share(
    share_id: int,
    session_token: str = Cookie(None, alias="session_token"),
):
    try:

        session = db.session

        if not session_token:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Get account_uuid from session
        account_uuid = get_account_uuid_from_session(session_token)

        # Check if share exists and belongs to this user
        existing_share = session.execute(
            select(table["shares"]).where(
                (table["shares"].c.id == share_id) &
                (table["shares"].c.account_uuid == account_uuid)
            )
        ).fetchone()

        if not existing_share:
            raise HTTPException(
                status_code=404,
                detail="Share not found or you don't have permission to delete it"
            )

        # Delete the share
        stmt = delete(table["shares"]).where(table["shares"].c.id == share_id)
        session.execute(stmt)
        session.commit()

        return {"message": "Share deleted successfully"}

    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.get("/user", tags=["Get User Shares"])
async def get_user_shares(
    account_uuid: str,
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=50, description="Items per page"),
    content_type: Optional[int] = Query(None, description="Filter by content type: 1 for posts, 2 for events"),
    
    # session_token: str = Cookie(None, alias="session_token"),
):

    try:

        session = db.session

        # if not session_token:
        #     raise HTTPException(status_code=401, detail="Authentication required")

        # # Get account_uuid from session
        # account_uuid = get_account_uuid_from_session(session_token)

       
        offset = (page - 1) * limit
        select_account_id = select(table["account"].c.id).where(
            table["account"].c.uuid == account_uuid
        )
        account_id = session.execute(select_account_id).scalar()

        # Build base query
        base_query = select(table["shares"]).where(
            table["shares"].c.account_uuid == account_uuid
        )

        # Add content type filter if provided
        if content_type is not None:
            if content_type not in [1, 2]:
                raise HTTPException(status_code=400, detail="Content type must be 1 (post) or 2 (event)")
            base_query = base_query.where(table["shares"].c.content_type == content_type)

        # Get total count
        count_query = select(func.count()).select_from(base_query.alias())
        total_count = session.execute(count_query).scalar()

        # Get shares with pagination
        shares_query = base_query.order_by(
            table["shares"].c.date_created.desc()
        ).limit(limit).offset(offset)

        shares_result = session.execute(shares_query).fetchall()

        shares = []
        for share in shares_result:
            share_data = dict(share._mapping)
            
            # Get content details based on content_type
            if share_data["content_type"] == 1:  # Post
                profile_resource = table["resource"].alias("profile_resource")
                org_logo_resource = table["resource"].alias("org_logo_resource")
                post_query = (
                    select(
                        table["post"].c.id,
                        table["post"].c.description,
                        table["post"].c.created_date,
                        table["post"].c.image,
                        table["account"].c.uuid.label("author_uuid"),
                        table["account"].c.email.label("author_email"),
                        table["user"].c.id.label("user_id"),
                        table["user"].c.first_name.label("author_first_name"),
                        table["user"].c.last_name.label("author_last_name"),
                        profile_resource.c.directory.label("profile_picture_directory"),
                        profile_resource.c.filename.label("profile_picture_filename"),
                        profile_resource.c.id.label("profile_picture_id"),
                        table["organization"].c.name.label("author_organization_name"),
                        org_logo_resource.c.directory.label("organization_logo_directory"),
                        org_logo_resource.c.filename.label("organization_logo_filename"),
                        org_logo_resource.c.id.label("organization_logo_id"),
                    )
                    .select_from(
                        table["post"]
                        .join(
                            table["account"],
                            table["post"].c.author == table["account"].c.id,
                        )
                        .outerjoin(
                            table["user"],
                            table["user"].c.account_id == table["account"].c.id,
                        )
                        .outerjoin(
                            profile_resource,
                            table["user"].c.profile_picture == profile_resource.c.id,
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
                    .where(table["post"].c.id == share_data["content_id"])
                )
                
                post_result = session.execute(post_query).fetchone()
                if post_result:
                    images = []
                    if post_result.image:
                        try:
                            resource_ids = json.loads(post_result.image)
                            for res_id in resource_ids:
                                res_stmt = select(
                                    table["resource"].c.id,
                                    table["resource"].c.directory,
                                    table["resource"].c.filename,
                                ).where(table["resource"].c.id == res_id)
                                res_result = session.execute(res_stmt).first()
                                if res_result:
                                    res_data = res_result._mapping
                                    images.append(
                                        {
                                            "id": res_data["id"],
                                            "directory": res_data["directory"],
                                            "filename": res_data["filename"],
                                        }
                                    )
                        except (json.JSONDecodeError, TypeError):
                            pass

                    share_data["content_details"] = {
                        "type": "post",
                        "id": post_result.id,
                         "user_id": post_result.user_id,
                        "description": post_result.description,
                        "created_date": post_result.created_date,
                        "author_uuid": post_result.author_uuid,
                        "author_email": post_result.author_email,
                        "author_first_name": post_result.author_first_name,
                        "author_last_name": post_result.author_last_name,
                        "author_organization_name": post_result.author_organization_name,
                        "images": images,
                        "profile_picture": (
                            {
                                "id": post_result.profile_picture_id,
                                "directory": post_result.profile_picture_directory,
                                "filename": post_result.profile_picture_filename,
                            }
                            if post_result.profile_picture_id
                            else None
                        ),
                        "logo": (
                            {
                                "id": post_result.organization_logo_id,
                                "directory": post_result.organization_logo_directory,
                                "filename": post_result.organization_logo_filename,
                            }
                            if post_result.organization_logo_id
                            else None
                        ),
                    }

            elif share_data["content_type"] == 2:  # Event
                event_query = (
                    select(
                        table["event"].c.id,
                        table["event"].c.organization_id,
                        table["event"].c.title,
                        table["event"].c.description,
                        table["event"].c.event_date,
                        table["event"].c.created_date,
                        table["event"].c.image,
                        table["resource"].c.directory.label("image_directory"),
                        table["resource"].c.filename.label("image_filename"),
                        table["address"].c.province.label("address_province"),
                        table["address"].c.city.label("address_city"),
                        table["address"].c.barangay.label("address_barangay"),
                        table["organization"].c.name.label("organization_name"),
                    )
                    .select_from(
                        table["event"]
                        .outerjoin(
                            table["resource"], table["event"].c.image == table["resource"].c.id
                        )
                        .outerjoin(
                            table["address"], table["event"].c.address_id == table["address"].c.id
                        )
                        .join(
                            table["organization"],
                            table["event"].c.organization_id == table["organization"].c.id,
                        )
                    )
                    .where(table["event"].c.id == share_data["content_id"])
                )
                
                event_result = session.execute(event_query).fetchone()
                if event_result:
                    share_data["content_details"] = {
                        "type": "event",
                        "id": event_result.id,
                        "title": event_result.title,
                        "description": event_result.description,
                        "event_date": event_result.event_date,
                        "created_date": event_result.created_date,
                        "organization_name": event_result.organization_name,
                        "organization_id": event_result.organization_id,
                        "image": (
                            {
                                "id": event_result.image,
                                "directory": event_result.image_directory,
                                "filename": event_result.image_filename,
                            }
                            if event_result.image
                            else None
                        ),
                        "address": {
                            "province": event_result.address_province,
                            "city": event_result.address_city,
                            "barangay": event_result.address_barangay,
                        },
                    }
                    if account_id:
                        user_id_stmt = select(table["user"].c.id).where(
                            table["user"].c.account_id == account_id
                        )
                        user_id = session.execute(user_id_stmt).scalar()
                        org_id = event_result.organization_id
                        membership_status = None
                        print("data", user_id, org_id)
                        if user_id and org_id:
                            membership_stmt = select(table["membership"].c.status).where(
                                (table["membership"].c.organization_id == org_id)
                                & (table["membership"].c.user_id == user_id)
                            )
                            membership_status = session.execute(membership_stmt).scalar()
                        print("membership status", membership_status)
                        share_data["content_details"]["user_membership_status_with_organizer"] = membership_status
                    
                    # Get RSVP status of the sharer for this event if they are a user
                    if account_id:
                        rsvp_status_stmt = select(table["rsvp"].c.status).where(
                            (table["rsvp"].c.event_id == share_data["content_id"]) &
                            (table["rsvp"].c.attendee == account_id)
                        )
                        rsvp_status = session.execute(rsvp_status_stmt).scalar()
                        share_data["content_details"]["sharer_rsvp_status"] = rsvp_status

            shares.append(share_data)

        return {
            "shares": shares,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_count,
                "pages": (total_count + limit - 1) // limit
            }
        }

    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.get("/content/{content_type}/{content_id}", tags=["Get Shares for Content"])
async def get_shares_for_content(
    content_type: int,
    content_id: int,
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=50, description="Items per page"),
):
    try:

        session = db.session

        # Validate content_type
        if content_type not in [1, 2]:
            raise HTTPException(status_code=400, detail="Content type must be 1 (post) or 2 (event)")

        # Validate that the content exists
        if content_type == 1:  # Post
            post_exists = session.execute(
                select(table["post"].c.id).where(table["post"].c.id == content_id)
            ).scalar()
            if not post_exists:
                raise HTTPException(status_code=404, detail="Post not found")
        elif content_type == 2:  # Event
            event_exists = session.execute(
                select(table["event"].c.id).where(table["event"].c.id == content_id)
            ).scalar()
            if not event_exists:
                raise HTTPException(status_code=404, detail="Event not found")

        offset = (page - 1) * limit

        # Get total count of shares for this content
        count_query = select(func.count()).select_from(table["shares"]).where(
            (table["shares"].c.content_id == content_id) &
            (table["shares"].c.content_type == content_type)
        )
        total_count = session.execute(count_query).scalar()

        # Get shares with user details
        org_logo_resource = table["resource"].alias("org_logo_resource")
        profile_picture_resource = table["resource"].alias("profile_picture_resource")
        shares_query = select(
            table["shares"].c.id,
            table["shares"].c.comment,
            table["shares"].c.date_created,
            table["account"].c.uuid.label("sharer_uuid"),
            table["account"].c.email.label("sharer_email"),
            table["user"].c.id.label("sharer_id"),
            table["user"].c.first_name,
            table["user"].c.last_name,
            table["organization"].c.id.label("organization_id"),
            table["organization"].c.name.label("organization_name"),
            org_logo_resource.c.directory.label("organization_logo_directory"),
            org_logo_resource.c.filename.label("organization_logo_filename"),
            profile_picture_resource.c.directory.label("profile_picture_directory"),
            profile_picture_resource.c.filename.label("profile_picture_filename")
        ).select_from(
            table["shares"]
            .join(table["account"], table["shares"].c.account_uuid == table["account"].c.uuid)
            .outerjoin(table["user"], table["user"].c.account_id == table["account"].c.id)
            .outerjoin(profile_picture_resource, table["user"].c.profile_picture == profile_picture_resource.c.id)
            .outerjoin(table["organization"], table["organization"].c.account_id == table["account"].c.id)
            .outerjoin(org_logo_resource, table["organization"].c.logo == org_logo_resource.c.id)
        ).where(
            (table["shares"].c.content_id == content_id) &
            (table["shares"].c.content_type == content_type)
        ).order_by(
            table["shares"].c.date_created.desc()
        ).limit(limit).offset(offset)

        shares_result = session.execute(shares_query).fetchall()

        shares = []
        for share in shares_result:
            share_data = {
                "share_id": share.id,
                "comment": share.comment,
                "date_created": share.date_created,
                "sharer": {
                    "id": share.sharer_id,
                    "organization_id": share.organization_id,
                    "uuid": share.sharer_uuid,
                    "email": share.sharer_email,
                    "first_name": share.first_name,
                    "last_name": share.last_name,
                    "organization_name": share.organization_name,
                    "profile_picture": {
                        "directory": share.profile_picture_directory,
                        "filename": share.profile_picture_filename
                    } if share.profile_picture_directory else None,
                    "logo": {
                        "directory": share.organization_logo_directory,
                        "filename": share.organization_logo_filename
                    } if share.organization_logo_directory else None
                }
            }
            
            # If this is an event share, get the RSVP status of the sharer
            if content_type == 2 and share.sharer_id:  # Event and sharer is a user
                # Get account_id from sharer_id
                sharer_account_stmt = select(table["user"].c.account_id).where(
                    table["user"].c.id == share.sharer_id
                )
                sharer_account_id = session.execute(sharer_account_stmt).scalar()
                
                if sharer_account_id:
                    rsvp_status_stmt = select(table["rsvp"].c.status).where(
                        (table["rsvp"].c.event_id == content_id) &
                        (table["rsvp"].c.attendee == sharer_account_id)
                    )
                    rsvp_status = session.execute(rsvp_status_stmt).scalar()
                    share_data["sharer"]["rsvp_status"] = rsvp_status
            
            shares.append(share_data)

        return {
            "content_type": content_type,
            "content_id": content_id,
            "shares": shares,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_count,
                "pages": (total_count + limit - 1) // limit
            }
        }

    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()

@router.get("/all_with_comments", tags=["Get All Shares With Comments"])
async def get_all_shares_with_comments(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=50, description="Items per page"),
    content_type: Optional[int] = Query(None, description="Filter by content type: 1 for posts, 2 for events"),
    session_token: str = Cookie(None, alias="session_token"),
):
    """
    Get all shared content (posts and events) with comments for news feed
    """
    session = db.session
    try:
        offset = (page - 1) * limit
        user_id = None
        if session_token:
            try:
                account_uuid = get_account_uuid_from_session(session_token)
                select_account = select(table["account"].c.id).where(
                    table["account"].c.uuid == account_uuid
                )
                account_id = session.execute(select_account).scalar()
                select_user = select(table["user"].c.id).where(
                    table["user"].c.account_id == account_id
                )
                user_id = session.execute(select_user).scalar()
            except Exception:
                user_id = None

        # Build base query for shares
        base_query = select(table["shares"])

        # Add content type filter if provided
        if content_type is not None:
            if content_type not in [1, 2]:
                raise HTTPException(status_code=400, detail="Content type must be 1 (post) or 2 (event)")
            base_query = base_query.where(table["shares"].c.content_type == content_type)

        # Get total count
        count_query = select(func.count()).select_from(base_query.alias())
        total_count = session.execute(count_query).scalar()

        # Get shares with pagination
        shares_query = base_query.order_by(
            table["shares"].c.date_created.desc()
        ).limit(limit).offset(offset)

        shares_result = session.execute(shares_query).fetchall()

        shares_with_content = []
        
        for share in shares_result:
            share_data = dict(share._mapping)
            
            # Get sharer details
            org_logo_resource = table["resource"].alias("org_logo_resource")
            profile_picture_resource = table["resource"].alias("profile_picture_resource")
            sharer_query = select(
                table["account"].c.uuid,
                table["account"].c.email,
                table["user"].c.id.label("sharer_id"),
                table["user"].c.first_name,
                table["user"].c.last_name,
                table["user"].c.profile_picture,
                profile_picture_resource.c.directory.label("profile_picture_directory"),
                profile_picture_resource.c.filename.label("profile_picture_filename"),
                table["organization"].c.name.label("organization_name"),
                table["organization"].c.id.label("organization_id"),
                org_logo_resource.c.directory.label("organization_logo_directory"),
                org_logo_resource.c.filename.label("organization_logo_filename")
            ).select_from(
                table["account"]
                .outerjoin(table["user"], table["user"].c.account_id == table["account"].c.id)
                .outerjoin(table["organization"], table["organization"].c.account_id == table["account"].c.id)
                .outerjoin(profile_picture_resource, table["user"].c.profile_picture == profile_picture_resource.c.id)
                .outerjoin(org_logo_resource, table["organization"].c.logo == org_logo_resource.c.id)
            ).where(table["account"].c.uuid == share_data["account_uuid"])
            
            sharer_result = session.execute(sharer_query).first()
            
            content_details = None
            comments = []
            
            if share_data["content_type"] == 1:  # Post
                # Get post details with author info
                org_logo_resource = table["resource"].alias("org_logo_resource")
                post_query = select(
                    table["post"].c.id,
                    table["post"].c.description,
                    table["post"].c.image,
                    table["post"].c.created_date,
                    table["account"].c.uuid.label("author_uuid"),
                    table["account"].c.email.label("author_email"),
                    table["user"].c.first_name.label("author_first_name"),
                    table["user"].c.last_name.label("author_last_name"),
                    table["user"].c.profile_picture.label("author_profile_picture"),
                    table["resource"].c.directory.label("author_profile_directory"),
                    table["resource"].c.filename.label("author_profile_filename"),
                    table["organization"].c.id.label("author_organization_id"),
                    table["organization"].c.name.label("author_organization_name"),
                    org_logo_resource.c.directory.label("author_organization_logo_directory"),
                    org_logo_resource.c.filename.label("author_organization_logo_filename")
                ).select_from(
                    table["post"]
                    .join(table["account"], table["post"].c.author == table["account"].c.id)
                    .outerjoin(table["user"], table["user"].c.account_id == table["account"].c.id)
                    .outerjoin(table["resource"], table["user"].c.profile_picture == table["resource"].c.id)
                    .outerjoin(table["organization"], table["organization"].c.account_id == table["account"].c.id)
                    .outerjoin(org_logo_resource, table["organization"].c.logo == org_logo_resource.c.id)
                ).where(table["post"].c.id == share_data["content_id"])
                
                post_result = session.execute(post_query).first()
                if post_result:
                    # Parse images from JSON
                    images = []
                    if post_result.image:
                        try:
                            resource_ids = json.loads(post_result.image)
                            for resource_id in resource_ids:
                                image_query = select(table["resource"]).where(table["resource"].c.id == resource_id)
                                image_result = session.execute(image_query).first()
                                if image_result:
                                    images.append({
                                        "id": image_result.id,
                                        "directory": image_result.directory,
                                        "filename": image_result.filename
                                    })
                        except (json.JSONDecodeError, TypeError):
                            pass
                    
                    content_details = {
                        "type": "post",
                        "id": post_result.id,
                        "description": post_result.description,
                        "images": images,
                        "created_date": post_result.created_date,
                        "author": {
                            "uuid": post_result.author_uuid,
                            "email": post_result.author_email,
                            "first_name": post_result.author_first_name,
                            "last_name": post_result.author_last_name,
                            "organization_id": post_result.author_organization_id,
                            "organization_name": post_result.author_organization_name,
                            "profile_picture": {
                                "directory": post_result.author_profile_directory,
                                "filename": post_result.author_profile_filename
                            } if post_result.author_profile_directory else None,
                            "organization_logo": {
                                "directory": post_result.author_organization_logo_directory,
                                "filename": post_result.author_organization_logo_filename
                            } if post_result.author_organization_logo_directory else None,
                        }
                    }
                    
                    # Get post comments (top 5 latest)
                    comments_query = select(
                        table["comment"].c.id,
                        table["comment"].c.message,
                        table["comment"].c.created_date,
                        table["account"].c.uuid.label("commenter_uuid"),
                        table["account"].c.email.label("commenter_email"),
                        table["user"].c.first_name.label("commenter_first_name"),
                        table["user"].c.last_name.label("commenter_last_name")
                    ).select_from(
                        table["comment"]
                        .join(table["account"], table["comment"].c.author == table["account"].c.id)
                        .outerjoin(table["user"], table["user"].c.account_id == table["account"].c.id)
                    ).where(
                        table["comment"].c.post_id == share_data["content_id"]
                    ).order_by(table["comment"].c.created_date.desc()).limit(5)
                    
                    comments_result = session.execute(comments_query).fetchall()
                    comments = [{
                        "id": comment.id,
                        "message": comment.message,
                        "created_date": comment.created_date,
                        "author": {
                            "uuid": comment.commenter_uuid,
                            "email": comment.commenter_email,
                            "first_name": comment.commenter_first_name,
                            "last_name": comment.commenter_last_name
                        }
                    } for comment in comments_result]

            elif share_data["content_type"] == 2:  # Event
                # Get event details with organization info
                org_logo_resource = table["resource"].alias("org_logo_resource")
                event_query = select(
                    table["event"].c.id,
                    table["event"].c.organization_id,
                    table["event"].c.title,
                    table["event"].c.description,
                    table["event"].c.event_date,
                    table["event"].c.image,
                    table["event"].c.created_date,
                    table["organization"].c.name.label("organization_name"),
                    table["organization"].c.category.label("organization_category"),
                    org_logo_resource.c.directory.label("organization_logo_directory"),
                    org_logo_resource.c.filename.label("organization_logo_filename"),
                    table["address"].c.country,
                    table["address"].c.province,
                    table["address"].c.city,
                    table["address"].c.barangay,
                    table["address"].c.house_building_number,
                    table["resource"].c.directory.label("event_image_directory"),
                    table["resource"].c.filename.label("event_image_filename")
                ).select_from(
                    table["event"]
                    .join(table["organization"], table["event"].c.organization_id == table["organization"].c.id)
                    .outerjoin(org_logo_resource, table["organization"].c.logo == org_logo_resource.c.id)
                    .outerjoin(table["address"], table["event"].c.address_id == table["address"].c.id)
                    .outerjoin(table["resource"], table["event"].c.image == table["resource"].c.id)
                ).where(table["event"].c.id == share_data["content_id"])
                
                event_result = session.execute(event_query).first()
                if event_result:
                    content_details = {
                        "type": "event",
                        "id": event_result.id,
                        "organization_id": event_result.organization_id,
                        "title": event_result.title,
                        "description": event_result.description,
                        "event_date": event_result.event_date,
                        "created_date": event_result.created_date,
                        "image": (
                            {
                                "directory": event_result.event_image_directory,
                                "filename": event_result.event_image_filename,
                            }
                            if event_result.event_image_directory
                            else None
                        ),
                        "organization": {
                            "name": event_result.organization_name,
                            "category": event_result.organization_category,
                            "logo": (
                                {
                                    "directory": event_result.organization_logo_directory,
                                    "filename": event_result.organization_logo_filename,
                                }
                                if event_result.organization_logo_directory
                                else None
                            ),
                            "address": {
                                "province": event_result.province,
                                "city": event_result.city,
                                "barangay": event_result.barangay,
                            },
                        },
                    }
                    if user_id and event_result.organization_id:
                        membership_status = session.execute(
                            select(table["membership"].c.status).where(
                                (table["membership"].c.organization_id == event_result.organization_id)
                                & (table["membership"].c.user_id == user_id)
                            )
                        ).scalar()
                        content_details["organization"]["user_membership_status_with_organizer"] = membership_status
                    
                    # Get event comments (top 5 latest)
                    comments_query = select(
                        table["comment"].c.id,
                        table["comment"].c.message,
                        table["comment"].c.created_date,
                        table["account"].c.uuid.label("commenter_uuid"),
                        table["account"].c.email.label("commenter_email"),
                        table["user"].c.first_name.label("commenter_first_name"),
                        table["user"].c.last_name.label("commenter_last_name")
                    ).select_from(
                        table["comment"]
                        .join(table["account"], table["comment"].c.author == table["account"].c.id)
                        .outerjoin(table["user"], table["user"].c.account_id == table["account"].c.id)
                    ).where(
                        table["comment"].c.event_id == share_data["content_id"]
                    ).order_by(table["comment"].c.created_date.desc()).limit(5)
                    
                    comments_result = session.execute(comments_query).fetchall()
                    comments = [{
                        "id": comment.id,
                        "message": comment.message,
                        "created_date": comment.created_date,
                        "author": {
                            "uuid": comment.commenter_uuid,
                            "email": comment.commenter_email,
                            "first_name": comment.commenter_first_name,
                            "last_name": comment.commenter_last_name
                        }
                    } for comment in comments_result]

            # Only add to results if we have content details
            if content_details and sharer_result:
                sharer_data = {
                    "id": sharer_result.sharer_id,
                    "organization_id": sharer_result.organization_id,
                    "uuid": sharer_result.uuid,
                    "email": sharer_result.email,
                    "first_name": sharer_result.first_name,
                    "last_name": sharer_result.last_name,
                    "organization_name": sharer_result.organization_name,
                    "profile_picture": {
                        "directory": sharer_result.profile_picture_directory,
                        "filename": sharer_result.profile_picture_filename
                    } if sharer_result.profile_picture_directory else None,
                    "logo": {
                        "directory": sharer_result.organization_logo_directory,
                        "filename": sharer_result.organization_logo_filename
                    } if sharer_result.organization_logo_directory else None
                }
                
                # If this is an event share and the sharer is a user, get their RSVP status
                if share_data["content_type"] == 2 and sharer_result.sharer_id:
                    # Get account_id from sharer_id
                    sharer_account_stmt = select(table["user"].c.account_id).where(
                        table["user"].c.id == sharer_result.sharer_id
                    )
                    sharer_account_id = session.execute(sharer_account_stmt).scalar()
                    
                    if sharer_account_id:
                        rsvp_status_stmt = select(table["rsvp"].c.status).where(
                            (table["rsvp"].c.event_id == share_data["content_id"]) &
                            (table["rsvp"].c.attendee == sharer_account_id)
                        )
                        rsvp_status = session.execute(rsvp_status_stmt).scalar()
                        sharer_data["rsvp_status"] = rsvp_status

                shares_with_content.append({
                    "share_id": share_data["id"],
                    "share_comment": share_data["comment"],
                    "share_date": share_data["date_created"],
                    "sharer": sharer_data,
                    "content": content_details,
                    "comments": comments,
                    "comments_count": len(comments)
                })

        return {
            "shares": shares_with_content,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_count,
                "pages": (total_count + limit - 1) // limit
            }
        }

    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
