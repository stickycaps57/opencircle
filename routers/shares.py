from fastapi import APIRouter, HTTPException, Form, Cookie, Query
from fastapi.responses import JSONResponse
from lib.database import Database
from sqlalchemy import insert, delete, select, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from utils.session_utils import get_account_uuid_from_session
from typing import Optional

router = APIRouter(
    prefix="/share",
    tags=["Shares Management"],
)
db = Database()
table = db.tables
session = db.session

@router.post("/", tags=["Share Content"])
async def share_content(
    content_id: int = Form(..., description="ID of the content to share (post or event)"),
    content_type: int = Form(..., description="Content type: 1 for post, 2 for event"),
    comment: Optional[str] = Form(None, description="Optional comment when sharing"),
    session_token: str = Cookie(None, alias="session_token"),
):
    try:
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
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=50, description="Items per page"),
    content_type: Optional[int] = Query(None, description="Filter by content type: 1 for posts, 2 for events"),
    session_token: str = Cookie(None, alias="session_token"),
):
    try:
        if not session_token:
            raise HTTPException(status_code=401, detail="Authentication required")

        # Get account_uuid from session
        account_uuid = get_account_uuid_from_session(session_token)

        offset = (page - 1) * limit

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
                post_query = select(
                    table["post"].c.id,
                    table["post"].c.description,
                    table["post"].c.created_date,
                    table["account"].c.uuid.label("author_uuid"),
                    table["account"].c.email.label("author_email")
                ).select_from(
                    table["post"].join(
                        table["account"],
                        table["post"].c.author == table["account"].c.id
                    )
                ).where(table["post"].c.id == share_data["content_id"])
                
                post_result = session.execute(post_query).fetchone()
                if post_result:
                    share_data["content_details"] = {
                        "type": "post",
                        "id": post_result.id,
                        "description": post_result.description,
                        "created_date": post_result.created_date,
                        "author_uuid": post_result.author_uuid,
                        "author_email": post_result.author_email
                    }

            elif share_data["content_type"] == 2:  # Event
                event_query = select(
                    table["event"].c.id,
                    table["event"].c.title,
                    table["event"].c.description,
                    table["event"].c.event_date,
                    table["event"].c.created_date,
                    table["organization"].c.name.label("organization_name")
                ).select_from(
                    table["event"].join(
                        table["organization"],
                        table["event"].c.organization_id == table["organization"].c.id
                    )
                ).where(table["event"].c.id == share_data["content_id"])
                
                event_result = session.execute(event_query).fetchone()
                if event_result:
                    share_data["content_details"] = {
                        "type": "event",
                        "id": event_result.id,
                        "title": event_result.title,
                        "description": event_result.description,
                        "event_date": event_result.event_date,
                        "created_date": event_result.created_date,
                        "organization_name": event_result.organization_name
                    }

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
        shares_query = select(
            table["shares"].c.id,
            table["shares"].c.comment,
            table["shares"].c.date_created,
            table["account"].c.uuid.label("sharer_uuid"),
            table["account"].c.email.label("sharer_email"),
            table["user"].c.first_name,
            table["user"].c.last_name
        ).select_from(
            table["shares"]
            .join(table["account"], table["shares"].c.account_uuid == table["account"].c.uuid)
            .outerjoin(table["user"], table["user"].c.account_id == table["account"].c.id)
        ).where(
            (table["shares"].c.content_id == content_id) &
            (table["shares"].c.content_type == content_type)
        ).order_by(
            table["shares"].c.date_created.desc()
        ).limit(limit).offset(offset)

        shares_result = session.execute(shares_query).fetchall()

        shares = []
        for share in shares_result:
            shares.append({
                "share_id": share.id,
                "comment": share.comment,
                "date_created": share.date_created,
                "sharer": {
                    "uuid": share.sharer_uuid,
                    "email": share.sharer_email,
                    "first_name": share.first_name,
                    "last_name": share.last_name
                }
            })

        content_name = "post" if content_type == 1 else "event"
        return {
            "content_type": content_name,
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