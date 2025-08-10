from fastapi import APIRouter, HTTPException, Form
from lib.database import Database
from sqlalchemy import insert, update, delete
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

router = APIRouter(
    prefix="/comment",
    tags=["Comment Management"],
)

db = Database()
table = db.tables
session = db.session


@router.post("/post", tags=["Add Comment to Post"])
async def add_comment_to_post(
    post_id: int = Form(...),
    account_uuid: str = Form(...),
    message: str = Form(...),
):
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
    account_uuid: str = Form(...),
    message: str = Form(...),
):
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
    account_uuid: str = Form(...),
    message: str = Form(...),
):
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
    account_uuid: str = Form(...),
):
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
async def get_comments_for_event(event_id: int, limit: int = 10):
    try:
        comments = (
            session.query(table["comment"])
            .filter(table["comment"].c.event_id == event_id)
            .order_by(table["comment"].c.created_date.desc())
            .limit(limit)
            .all()
        )
        result = [
            {
                "id": c.id,
                "author": c.author,
                "message": c.message,
                "created_date": getattr(c, "created_date", None),
                "last_modified_date": getattr(c, "last_modified_date", None),
            }
            for c in comments
        ]
        return {"comments": result}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    finally:
        session.close()


@router.get("/post/{post_id}", tags=["Get Comments for Post"])
async def get_comments_for_post(post_id: int, limit: int = 10):
    try:
        comments = (
            session.query(table["comment"])
            .filter(table["comment"].c.post_id == post_id)
            .order_by(table["comment"].c.created_date.desc())
            .limit(limit)
            .all()
        )
        result = [
            {
                "id": c.id,
                "author": c.author,
                "message": c.message,
                "created_date": getattr(c, "created_date", None),
                "last_modified_date": getattr(c, "last_modified_date", None),
            }
            for c in comments
        ]
        return {"comments": result}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    finally:
        session.close()
