from fastapi import APIRouter, HTTPException, Form
from lib.database import Database
from sqlalchemy import insert, update, delete, func
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from fastapi import Cookie
from utils.session_utils import get_account_uuid_from_session

router = APIRouter(
    prefix="/comment",
    tags=["Comment Management"],
)

db = Database()
table = db.tables
# session = db.session


@router.post("/post", tags=["Add Comment to Post"])
async def add_comment_to_post(
    post_id: int = Form(...),
    message: str = Form(...),
    session_token: str = Cookie(...),
):
    session = db.session
    # Get account_uuid from session_token
    account_uuid = get_account_uuid_from_session(session_token)
    if not account_uuid:
        raise HTTPException(status_code=401, detail="Invalid session token")

    # Get account_id from uuid
    account = session.query(table["account"]).filter_by(uuid=account_uuid).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    account_id = account.id

    stmt = insert(table["comment"]).values(
        post_id=post_id, event_id=None, author=account_id, message=message
    )
    try:
        session.execute(stmt)
        session.commit()
        return {"message": "Comment added successfully"}
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Comment could not be added")
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.post("/event", tags=["Add Comment to Event"])
async def add_comment_to_event(
    event_id: int = Form(...),
    message: str = Form(...),
    session_token: str = Cookie(...),
):
    session = db.session
    # Get account_uuid from session_token
    account_uuid = get_account_uuid_from_session(session_token)
    if not account_uuid:
        raise HTTPException(status_code=401, detail="Invalid session token")

    # Get account_id from uuid
    account = session.query(table["account"]).filter_by(uuid=account_uuid).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    account_id = account.id

    stmt = insert(table["comment"]).values(
        event_id=event_id, post_id=None, author=account_id, message=message
    )
    try:
        session.execute(stmt)
        session.commit()
        return {"message": "Comment added successfully"}
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=409, detail="Comment could not be added")
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.put("/{comment_id}", tags=["Update Comment"])
async def update_comment(
    comment_id: int,
    message: str = Form(...),
    session_token: str = Cookie(...),
):
    session = db.session
    # Get account_uuid from session_token
    account_uuid = get_account_uuid_from_session(session_token)
    if not account_uuid:
        raise HTTPException(status_code=401, detail="Invalid session token")

    # Get account_id from uuid
    account = session.query(table["account"]).filter_by(uuid=account_uuid).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    account_id = account.id

    # Only allow update if the account is the author
    stmt = (
        update(table["comment"])
        .where(table["comment"].c.id == comment_id)
        .where(table["comment"].c.author == account_id)
        .values(message=message)
    )
    try:
        result = session.execute(stmt)
        session.commit()
        if result.rowcount == 0:
            raise HTTPException(
                status_code=404, detail="Comment not found or not owned by user"
            )
        return {"message": "Comment updated successfully"}
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.delete("/{comment_id}", tags=["Delete Comment"])
async def delete_comment(
    comment_id: int,
    session_token: str = Cookie(...),
):
    session = db.session
    # Get account_uuid from session_token
    account_uuid = get_account_uuid_from_session(session_token)
    if not account_uuid:
        raise HTTPException(status_code=401, detail="Invalid session token")

    # Get account_id from uuid
    account = session.query(table["account"]).filter_by(uuid=account_uuid).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    account_id = account.id

    # Only allow delete if the account is the author
    stmt = (
        delete(table["comment"])
        .where(table["comment"].c.id == comment_id)
        .where(table["comment"].c.author == account_id)
    )
    try:
        result = session.execute(stmt)
        session.commit()
        if result.rowcount == 0:
            raise HTTPException(
                status_code=404, detail="Comment not found or not owned by user"
            )
        return {"message": "Comment deleted successfully"}
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.get("/event/{event_id}", tags=["Get Comments for Event"])
async def get_comments_for_event(event_id: int, limit: int = 10, offset: int = 0):
    session = db.session
    try:
        org_logo = table["resource"].alias("org_logo")
        # Join role table to get role name
        query = (
            session.query(
                table["comment"].c.id,
                table["comment"].c.author,
                table["comment"].c.message,
                table["comment"].c.created_date,
                table["comment"].c.last_modified_date,
                table["account"].c.uuid.label("account_uuid"),
                table["account"].c.email.label("account_email"),
                table["account"].c.role_id.label("account_role_id"),
                table["role"].c.name.label("role_name"),
                table["user"].c.first_name.label("user_first_name"),
                table["user"].c.last_name.label("user_last_name"),
                table["user"].c.bio.label("user_bio"),
                table["resource"].c.directory.label("profile_picture_directory"),
                table["resource"].c.filename.label("profile_picture_filename"),
                table["resource"].c.id.label("profile_picture_id"),
                table["organization"].c.name.label("organization_name"),
                table["organization"].c.description.label("organization_description"),
                org_logo.c.directory.label("organization_logo_directory"),
                org_logo.c.filename.label("organization_logo_filename"),
                org_logo.c.id.label("organization_logo_id"),
            )
            .join(table["account"], table["comment"].c.author == table["account"].c.id)
            .join(table["role"], table["account"].c.role_id == table["role"].c.id)
            .outerjoin(
                table["user"],
                table["user"].c.account_id == table["account"].c.id,
            )
            .outerjoin(
                table["resource"],
                table["user"].c.profile_picture == table["resource"].c.id,
            )
            .outerjoin(
                table["organization"],
                table["organization"].c.account_id == table["account"].c.id,
            )
            .outerjoin(
                org_logo,
                table["organization"].c.logo == org_logo.c.id,
            )
            .filter(table["comment"].c.event_id == event_id)
            .order_by(table["comment"].c.created_date.desc())
        )
        total = query.count()
        comments = query.offset(offset).limit(limit).all()
        result = []
        for c in comments:
            role_name = getattr(c, "role_name", None)
            if role_name == "organization":
                profile = {
                    "organization_name": getattr(c, "organization_name", None),
                    "organization_description": getattr(
                        c, "organization_description", None
                    ),
                    "organization_logo": (
                        {
                            "id": getattr(c, "organization_logo_id", None),
                            "directory": getattr(
                                c, "organization_logo_directory", None
                            ),
                            "filename": getattr(c, "organization_logo_filename", None),
                        }
                        if getattr(c, "organization_logo_id", None)
                        else None
                    ),
                }
            else:
                profile = {
                    "user_first_name": getattr(c, "user_first_name", None),
                    "user_last_name": getattr(c, "user_last_name", None),
                    "user_bio": getattr(c, "user_bio", None),
                    "profile_picture": (
                        {
                            "id": getattr(c, "profile_picture_id", None),
                            "directory": getattr(c, "profile_picture_directory", None),
                            "filename": getattr(c, "profile_picture_filename", None),
                        }
                        if getattr(c, "profile_picture_id", None)
                        else None
                    ),
                }
            result.append(
                {
                    "id": c.id,
                    "author": c.author,
                    "message": c.message,
                    "created_date": c.created_date,
                    "last_modified_date": c.last_modified_date,
                    "account_uuid": getattr(c, "account_uuid", None),
                    "account_email": getattr(c, "account_email", None),
                    "role": role_name,
                    **profile,
                }
            )
        return {"comments": result, "total": total, "limit": limit, "offset": offset}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    finally:
        session.close()


@router.get("/post/{post_id}", tags=["Get Comments for Post"])
async def get_comments_for_post(post_id: int, limit: int = 10, offset: int = 0):
    session = db.session
    try:
        org_logo = table["resource"].alias("org_logo")
        query = (
            session.query(
                table["comment"].c.id,
                table["comment"].c.author,
                table["comment"].c.message,
                table["comment"].c.created_date,
                table["comment"].c.last_modified_date,
                table["account"].c.uuid.label("account_uuid"),
                table["account"].c.email.label("account_email"),
                table["account"].c.role_id.label("account_role_id"),
                table["role"].c.name.label("role_name"),
                table["user"].c.first_name.label("user_first_name"),
                table["user"].c.last_name.label("user_last_name"),
                table["user"].c.bio.label("user_bio"),
                table["resource"].c.directory.label("profile_picture_directory"),
                table["resource"].c.filename.label("profile_picture_filename"),
                table["resource"].c.id.label("profile_picture_id"),
                table["organization"].c.name.label("organization_name"),
                table["organization"].c.description.label("organization_description"),
                org_logo.c.directory.label("organization_logo_directory"),
                org_logo.c.filename.label("organization_logo_filename"),
                org_logo.c.id.label("organization_logo_id"),
            )
            .join(table["account"], table["comment"].c.author == table["account"].c.id)
            .join(table["role"], table["account"].c.role_id == table["role"].c.id)
            .outerjoin(
                table["user"],
                table["user"].c.account_id == table["account"].c.id,
            )
            .outerjoin(
                table["resource"],
                table["user"].c.profile_picture == table["resource"].c.id,
            )
            .outerjoin(
                table["organization"],
                table["organization"].c.account_id == table["account"].c.id,
            )
            .outerjoin(
                org_logo,
                table["organization"].c.logo == org_logo.c.id,
            )
            .filter(table["comment"].c.post_id == post_id)
            .order_by(table["comment"].c.created_date.desc())
        )
        total = query.count()
        comments = query.offset(offset).limit(limit).all()
        result = []
        for c in comments:
            role_name = getattr(c, "role_name", None)
            if role_name == "organization":
                profile = {
                    "organization_name": getattr(c, "organization_name", None),
                    "organization_description": getattr(
                        c, "organization_description", None
                    ),
                    "organization_logo": (
                        {
                            "id": getattr(c, "organization_logo_id", None),
                            "directory": getattr(
                                c, "organization_logo_directory", None
                            ),
                            "filename": getattr(c, "organization_logo_filename", None),
                        }
                        if getattr(c, "organization_logo_id", None)
                        else None
                    ),
                }
            else:
                profile = {
                    "user_first_name": getattr(c, "user_first_name", None),
                    "user_last_name": getattr(c, "user_last_name", None),
                    "user_bio": getattr(c, "user_bio", None),
                    "profile_picture": (
                        {
                            "id": getattr(c, "profile_picture_id", None),
                            "directory": getattr(c, "profile_picture_directory", None),
                            "filename": getattr(c, "profile_picture_filename", None),
                        }
                        if getattr(c, "profile_picture_id", None)
                        else None
                    ),
                }
            result.append(
                {
                    "id": c.id,
                    "author": c.author,
                    "message": c.message,
                    "created_date": c.created_date,
                    "last_modified_date": c.last_modified_date,
                    "account_uuid": getattr(c, "account_uuid", None),
                    "account_email": getattr(c, "account_email", None),
                    "role": role_name,
                    **profile,
                }
            )
        return {"comments": result, "total": total, "limit": limit, "offset": offset}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    finally:
        session.close()
