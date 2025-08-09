from fastapi import APIRouter, HTTPException, Form
from lib.database import Database
from sqlalchemy import insert
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
    finally:
        session.close()


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
async def get_rsvps_for_event(
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
