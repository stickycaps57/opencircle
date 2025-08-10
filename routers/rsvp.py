from fastapi import APIRouter, HTTPException, Form
from lib.database import Database
from sqlalchemy import insert, update, delete
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

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
    account_uuid: str = Form(...),
):

    event = session.query(table["event"]).filter_by(id=event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    if getattr(event, "auto_accept", 0) == 1:
        status = "joined"
    else:
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
        # Fetch all RSVP records for the given event_id
        rsvp_stmt = session.query(table["rsvp"]).filter_by(event_id=event_id).all()
        if not rsvp_stmt:
            raise HTTPException(status_code=404, detail="No RSVPs found for this event")

        # Convert results to list of dicts
        rsvps = []
        for rsvp in rsvp_stmt:
            rsvps.append(
                {
                    "id": rsvp.id,
                    "event_id": rsvp.event_id,
                    "attendee": rsvp.attendee,
                    "status": rsvp.status,
                    "created_date": rsvp.created_date,
                    "last_modified_date": rsvp.last_modified_date,
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
            session.query(table["rsvp"], table["account"], table["user"])
            .join(table["account"], table["rsvp"].c.attendee == table["account"].c.id)
            .join(table["user"], table["account"].c.id == table["user"].c.account_id)
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
                    "account_uuid": data[table["account"].c.uuid],
                    "user_id": data[table["user"].c.id],
                    "first_name": data[table["user"].c.first_name],
                    "last_name": data[table["user"].c.last_name],
                    "email": data[table["account"].c.email],
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
    account_uuid: str = Form(...),
    status: str = Form(...),
):
    # Get account_id from uuid
    account = session.query(table["account"]).filter_by(uuid=account_uuid).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    account_id = account.id

    # Only allow update if the account is the Organization who owns the event
    # and the account is linked to the organization_id under the Event table
    event = (
        session.query(table["event"])
        .join(table["rsvp"], table["event"].c.id == table["rsvp"].c.event_id)
        .filter(table["rsvp"].c.id == rsvp_id)
        .first()
    )
    if not event:
        raise HTTPException(status_code=404, detail="Event not found for RSVP")
    # Check if account is linked to the event's organization
    org = session.query(table["organization"]).filter_by(account_id=account_id).first()

    if not org or getattr(org, "id", None) != getattr(event, "organization_id", None):
        raise HTTPException(
            status_code=403, detail="Account not linked to event's organization"
        )
    stmt = (
        update(table["rsvp"]).where(table["rsvp"].c.id == rsvp_id).values(status=status)
    )
    try:
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
    account_uuid: str = Form(...),
):
    try:
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
