from fastapi import APIRouter, HTTPException, Form
from lib.database import Database
from sqlalchemy import insert, update, delete
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from fastapi import Request
from utils.session_utils import get_account_uuid_from_session


router = APIRouter(
    prefix="/rsvp",
    tags=["RSVP Management"],
)

db = Database()
table = db.tables
session = db.session


@router.post("/", tags=["Create RSVP"])
async def create_rsvp(
    event_id: int = Form(...),
    request: Request = None,
):
    # Get session_token from cookie
    session_token = request.cookies.get("session_token")
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")

    # Use utility function to get account_uuid from session
    account_uuid = get_account_uuid_from_session(session_token)

    event = session.query(table["event"]).filter_by(id=event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    status = "pending"

    account = session.query(table["account"]).filter_by(uuid=account_uuid).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    account_id = account.id

    stmt = insert(table["rsvp"]).values(
        event_id=event_id, attendee=account_id, status=status
    )
    try:
        session.execute(stmt)
        session.commit()
        return {"message": "RSVP created successfully"}
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="RSVP already exists for this account and event"
        )
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/event/{event_id}", tags=["Get RSVPs for Event"])
async def get_rsvps_for_event(
    event_id: int,
):
    try:
        # Fetch all RSVP records for the given event_id, joining account, user, and resource tables
        rsvp_stmt = (
            session.query(
                table["rsvp"].c.id.label("rsvp_id"),
                table["rsvp"].c.event_id,
                table["rsvp"].c.attendee,
                table["rsvp"].c.status,
                table["rsvp"].c.created_date,
                table["rsvp"].c.last_modified_date,
                table["account"].c.uuid.label("account_uuid"),
                table["account"].c.email,
                table["user"].c.id.label("user_id"),
                table["user"].c.first_name,
                table["user"].c.last_name,
                table["user"].c.bio,
                table["resource"].c.directory.label("profile_picture_directory"),
                table["resource"].c.filename.label("profile_picture_filename"),
                table["resource"].c.id.label("profile_picture_id"),
            )
            .join(table["account"], table["rsvp"].c.attendee == table["account"].c.id)
            .outerjoin(
                table["user"], table["user"].c.account_id == table["account"].c.id
            )
            .outerjoin(
                table["resource"],
                table["user"].c.profile_picture == table["resource"].c.id,
            )
            .filter(table["rsvp"].c.event_id == event_id)
            .all()
        )
        if not rsvp_stmt:
            raise HTTPException(status_code=404, detail="No RSVPs found for this event")

        # Convert results to list of dicts
        rsvps = []
        for row in rsvp_stmt:
            data = row._mapping
            rsvps.append(
                {
                    "id": data["rsvp_id"],
                    "event_id": data["event_id"],
                    "attendee": data["attendee"],
                    "status": data["status"],
                    "created_date": data["created_date"],
                    "last_modified_date": data["last_modified_date"],
                    "account_uuid": data["account_uuid"],
                    "user_id": data["user_id"],
                    "first_name": data["first_name"],
                    "last_name": data["last_name"],
                    "email": data["email"],
                    "bio": data["bio"],
                    "profile_picture": (
                        {
                            "id": data["profile_picture_id"],
                            "directory": data["profile_picture_directory"],
                            "filename": data["profile_picture_filename"],
                        }
                        if data["profile_picture_id"]
                        else None
                    ),
                }
            )
        return {"event_id": event_id, "rsvps": rsvps}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.get("/attendees/{event_id}", tags=["Get Attendees of an Event"])
async def get_attendees_for_event(
    event_id: int,
):
    try:
        # Fetch all RSVP records for the given event_id
        rsvp_stmt = (
            session.query(
                table["account"].c.uuid,
                table["user"].c.id,
                table["user"].c.first_name,
                table["user"].c.last_name,
                table["account"].c.email,
                table["resource"].c.directory.label("profile_picture_directory"),
                table["resource"].c.filename.label("profile_picture_filename"),
                table["resource"].c.id.label("profile_picture_id"),
            )
            .select_from(table["rsvp"])
            .join(table["account"], table["rsvp"].c.attendee == table["account"].c.id)
            .outerjoin(
                table["user"], table["account"].c.id == table["user"].c.account_id
            )
            .outerjoin(
                table["resource"],
                table["user"].c.profile_picture == table["resource"].c.id,
            )
            .filter(
                table["rsvp"].c.event_id == event_id, table["rsvp"].c.status == "joined"
            )
            .all()
        )
        if not rsvp_stmt:
            raise HTTPException(
                status_code=404, detail="No attendees found for this event"
            )

        # Convert results to list of dicts
        rsvps = []
        for row in rsvp_stmt:
            data = row._mapping
            rsvps.append(
                {
                    "account_uuid": data["uuid"],
                    "user_id": data["id"],
                    "first_name": data["first_name"],
                    "last_name": data["last_name"],
                    "email": data["email"],
                    "profile_picture": (
                        {
                            "id": data["profile_picture_id"],
                            "directory": data["profile_picture_directory"],
                            "filename": data["profile_picture_filename"],
                        }
                        if data["profile_picture_id"]
                        else None
                    ),
                }
            )
        return {"event_id": event_id, "attendees": rsvps}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.put("/status/{rsvp_id}", tags=["Update RSVP Status"])
async def update_rsvp_status(
    rsvp_id: int,
    request: Request = None,
    status: str = Form(...),
):
    try:
        # Get session_token from cookie
        session_token = request.cookies.get("session_token")
        if not session_token:
            raise HTTPException(status_code=401, detail="Session token missing")

        # Use utility function to get account_uuid from session
        account_uuid = get_account_uuid_from_session(session_token)

        # Get account_id from uuid
        account = session.query(table["account"]).filter_by(uuid=account_uuid).first()
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        account_id = account.id

        # Get RSVP and related event
        rsvp = session.query(table["rsvp"]).filter_by(id=rsvp_id).first()
        if not rsvp:
            raise HTTPException(status_code=404, detail="RSVP not found")
        event = session.query(table["event"]).filter_by(id=rsvp.event_id).first()
        if not event:
            raise HTTPException(status_code=404, detail="Event not found for RSVP")

        # Only allow update if the account is the Organization who owns the event
        org = (
            session.query(table["organization"])
            .filter_by(account_id=account_id)
            .first()
        )
        if not org or getattr(org, "id", None) != getattr(
            event, "organization_id", None
        ):
            raise HTTPException(
                status_code=403,
                detail="Only the event organizer can update RSVP status",
            )

        stmt = (
            update(table["rsvp"])
            .where(table["rsvp"].c.id == rsvp_id)
            .values(status=status)
        )
        result = session.execute(stmt)
        session.commit()
        if result.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="RSVP not found or not owned by the Organization",
            )
        return {"message": "RSVP status updated successfully"}
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.delete("/{rsvp_id}", tags=["Delete RSVP"])
async def delete_rsvp(
    rsvp_id: int,
    request: Request = None,
):
    try:
        # Get session_token from cookie
        session_token = request.cookies.get("session_token")
        if not session_token:
            raise HTTPException(status_code=401, detail="Session token missing")

        # Use utility function to get account_uuid from session
        account_uuid = get_account_uuid_from_session(session_token)

        # Get RSVP and related event
        rsvp = session.query(table["rsvp"]).filter_by(id=rsvp_id).first()
        if not rsvp:
            raise HTTPException(status_code=404, detail="RSVP not found")
        event = session.query(table["event"]).filter_by(id=rsvp.event_id).first()
        if not event:
            raise HTTPException(status_code=404, detail="Event not found for RSVP")

        account = session.query(table["account"]).filter_by(uuid=account_uuid).first()
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")

        is_rsvp_creator = rsvp.attendee == account.id
        is_event_organizer = False
        if not is_rsvp_creator:
            org = (
                session.query(table["organization"])
                .filter_by(account_id=account.id)
                .first()
            )
            if org and org.id == event.organization_id:
                is_event_organizer = True

        if not (is_rsvp_creator or is_event_organizer):
            raise HTTPException(
                status_code=403,
                detail="Only the RSVP creator or event organizer can delete this RSVP",
            )

        stmt = delete(table["rsvp"]).where(table["rsvp"].c.id == rsvp_id)
        session.execute(stmt)
        session.commit()
        return {"message": "RSVP deleted successfully"}

    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.post("/statuses", tags=["Get RSVP Statuses for Accounts"])
async def get_rsvp_statuses_for_accounts(
    event_id: int = Form(...),
    account_uuids: list[str] = Form(...),
):
    try:
        # Get account IDs from UUIDs
        accounts = (
            session.query(table["account"].c.id, table["account"].c.uuid)
            .filter(table["account"].c.uuid.in_(account_uuids))
            .all()
        )
        uuid_to_id = {row._mapping["uuid"]: row._mapping["id"] for row in accounts}
        if not uuid_to_id:
            raise HTTPException(
                status_code=404, detail="No accounts found for given UUIDs"
            )

        # Query RSVP statuses for these accounts and event
        rsvps = (
            session.query(
                table["rsvp"].c.attendee,
                table["rsvp"].c.status,
                table["account"].c.uuid,
            )
            .join(table["account"], table["rsvp"].c.attendee == table["account"].c.id)
            .filter(
                table["rsvp"].c.event_id == event_id,
                table["account"].c.uuid.in_(account_uuids),
            )
            .all()
        )

        # Map results by account_uuid
        status_map = {row._mapping["uuid"]: row._mapping["status"] for row in rsvps}

        # Return status for each requested account_uuid (None if not found)
        result = [
            {"account_uuid": uuid, "status": status_map.get(uuid)}
            for uuid in account_uuids
        ]
        return {"event_id": event_id, "statuses": result}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
