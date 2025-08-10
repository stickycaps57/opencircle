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
from utils.resource_utils import add_resource, delete_resource, get_resource
from lib.models import EventModel
from sqlalchemy import update, delete
from utils.address_utils import add_address, update_address
from utils.resource_utils import add_resource


router = APIRouter(
    prefix="/event",
    tags=["Event Management"],
)

db = Database()
table = db.tables
session = db.session


@router.post("/", tags=["Create Event"])
async def create_event(
    account_uuid: str = Form(...),
    title: str = Form(...),
    event_date: str = Form(...),
    country: str = Form(...),
    province: str = Form(...),
    city: str = Form(...),
    barangay: str = Form(...),
    house_building_number: str = Form(...),
    description: str = Form(...),
    is_autoaccept: bool = Form(...),
    image: Optional[UploadFile] = File(None),
):
    try:
        # Fetch organization id using account_uuid
        select_organization = (
            select(table["organization"].c.id)
            .select_from(
                table["organization"].join(
                    table["account"],
                    table["organization"].c.account_id == table["account"].c.id,
                )
            )
            .where(table["account"].c.uuid == account_uuid)
        )
        organization_id = session.execute(select_organization).scalar()
        if organization_id is None:
            raise HTTPException(status_code=404, detail="Organization not found")

        # Insert resource (image) if provided
        image_id = None
        if image:
            image_id = add_resource(image, account_uuid)

        # Insert address first
        address_id = add_address(
            country,
            province,
            city,
            barangay,
            house_building_number,
        )

        # Insert event using schema.sql columns
        stmt = insert(table["event"]).values(
            organization_id=organization_id,
            title=title,
            event_date=event_date,
            address_id=address_id,
            description=description,
            image=image_id,
            is_autoaccept=is_autoaccept,
        )
        result = session.execute(stmt)
        session.commit()
        event_id = result.inserted_primary_key[0]
        return {"event_id": event_id, "message": "Event created successfully"}
    except IntegrityError as e:
        session.rollback()
        raise HTTPException(status_code=400, detail="Integrity error: " + str(e))
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{event_id}", tags=["Delete Event"])
async def delete_event(
    event_id: int = Path(..., description="ID of the event to delete")
):
    try:
        # Check if event exists
        select_event = select(table["event"].c.id).where(
            table["event"].c.id == event_id
        )
        event_exists = session.execute(select_event).scalar()
        if not event_exists:
            raise HTTPException(status_code=404, detail="Event not found")

        # Delete the event
        stmt = delete(table["event"]).where(table["event"].c.id == event_id)
        session.execute(stmt)
        session.commit()
        return {"message": "Event deleted successfully"}
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/", tags=["Get Events"])
async def get_events(
    account_uuid: str = Query(..., description="Account UUID to check RSVP status")
):
    try:
        # Get account_id from uuid
        select_account = select(table["account"].c.id).where(
            table["account"].c.uuid == account_uuid
        )
        account_id = session.execute(select_account).scalar()
        if account_id is None:
            raise HTTPException(status_code=404, detail="Account not found")

        # Get all events
        select_events = select(table["event"]).order_by(
            table["event"].c.event_date.desc()
        )
        events_result = session.execute(select_events).fetchall()
        events = [dict(row._mapping) for row in events_result]

        # Get RSVP status for each event for this account
        for event in events:
            select_rsvp = select(table["rsvp"].c.status).where(
                (table["rsvp"].c.event_id == event["id"])
                & (table["rsvp"].c.attendee == account_id)
            )
            rsvp_result = session.execute(select_rsvp).scalar()
            event["rsvp_status"] = rsvp_result if rsvp_result else "none"

        return {"events": events}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{event_id}", tags=["Update Event"])
async def update_event(
    event_id: int = Path(..., description="ID of the event to update"),
    account_uuid: str = Form(...),
    title: Optional[str] = Form(None),
    event_date: Optional[str] = Form(None),
    country: Optional[str] = Form(None),
    province: Optional[str] = Form(None),
    city: Optional[str] = Form(None),
    barangay: Optional[str] = Form(None),
    house_building_number: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    is_autoaccept: Optional[bool] = Form(None),
    image: Optional[UploadFile] = File(None),
):
    try:
        # Get account_id from account_uuid
        select_account = select(table["account"].c.id).where(
            table["account"].c.uuid == account_uuid
        )
        account_id = session.execute(select_account).scalar()
        if account_id is None:
            raise HTTPException(status_code=404, detail="Account not found")

        # Check if event exists and is owned by this account
        select_event = (
            select(table["event"], table["organization"])
            .select_from(
                table["event"].join(
                    table["organization"],
                    table["event"].c.organization_id == table["organization"].c.id,
                )
            )
            .where(table["event"].c.id == event_id)
            .where(table["organization"].c.account_id == account_id)
        )
        event = session.execute(select_event).fetchone()
        if not event:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to update this event",
            )

        update_data = {}

        if title is not None:
            update_data["title"] = title
        if event_date is not None:
            update_data["event_date"] = event_date
        if description is not None:
            update_data["description"] = description
        if is_autoaccept is not None:
            update_data["is_autoaccept"] = is_autoaccept

        # Update address if any address field is provided
        address_fields = [country, province, city, barangay, house_building_number]
        if any(field is not None for field in address_fields):
            address_id = event._mapping["address_id"]
            update_address(
                address_id,
                country=country,
                province=province,
                city=city,
                barangay=barangay,
                house_building_number=house_building_number,
            )

        # Update image if provided
        if image:
            image_id = add_resource(image, account_id)
            update_data["image"] = image_id

        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")

        stmt = (
            update(table["event"])
            .where(table["event"].c.id == event_id)
            .values(**update_data)
        )
        session.execute(stmt)
        session.commit()
        return {"message": "Event updated successfully"}
    except IntegrityError as e:
        session.rollback()
        raise HTTPException(status_code=400, detail="Integrity error: " + str(e))
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{event_id}/rsvps", tags=["Get RSVPs for Event"])
async def get_event_rsvps(
    event_id: int = Path(..., description="ID of the event to get RSVPs for")
):
    try:
        # Check if event exists
        select_event = select(table["event"].c.id).where(
            table["event"].c.id == event_id
        )
        event_exists = session.execute(select_event).scalar()
        if not event_exists:
            raise HTTPException(status_code=404, detail="Event not found")

        stmt = (
            select(
                table["rsvp"].c.id.label("rsvp_id"),
                table["rsvp"].c.status,
                table["account"].c.id.label("account_id"),
                table["account"].c.uuid,
                table["account"].c.email,
                table["user"].c.first_name,
                table["user"].c.last_name,
                table["user"].c.bio,
                table["user"].c.profile_picture,
            )
            .select_from(
                table["rsvp"]
                .join(
                    table["account"], table["rsvp"].c.attendee == table["account"].c.id
                )
                .outerjoin(
                    table["user"], table["user"].c.account_id == table["account"].c.id
                )
            )
            .where(table["rsvp"].c.event_id == event_id)
        )
        rsvps_result = session.execute(stmt).fetchall()
        rsvps = [dict(row._mapping) for row in rsvps_result]

        return {"event_id": event_id, "rsvps": rsvps}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/organizer/active", tags=["Get Active Events by Organizer"])
async def get_active_events_by_organizer(
    account_uuid: str = Query(..., description="Account UUID of the organizer")
):
    try:
        # Get organization id from account_uuid
        select_organization = (
            select(table["organization"].c.id)
            .select_from(
                table["organization"].join(
                    table["account"],
                    table["organization"].c.account_id == table["account"].c.id,
                )
            )
            .where(table["account"].c.uuid == account_uuid)
        )
        organization_id = session.execute(select_organization).scalar()
        if organization_id is None:
            raise HTTPException(status_code=404, detail="Organization not found")

        # Get all active events for this organization (with joined RSVPs)
        select_events = (
            select(
                table["event"],
                table["rsvp"].c.id.label("rsvp_id"),
                table["rsvp"].c.status.label("rsvp_status"),
                table["account"].c.id.label("account_id"),
                table["account"].c.uuid,
                table["account"].c.email,
                table["user"].c.first_name,
                table["user"].c.last_name,
                table["user"].c.bio,
                table["user"].c.profile_picture,
            )
            .select_from(
                table["event"]
                .outerjoin(
                    table["rsvp"],
                    (table["event"].c.id == table["rsvp"].c.event_id)
                    & (table["rsvp"].c.status == "joined"),
                )
                .outerjoin(
                    table["account"],
                    table["rsvp"].c.attendee == table["account"].c.id,
                )
                .outerjoin(
                    table["user"],
                    table["user"].c.account_id == table["account"].c.id,
                )
            )
            .where(
                (table["event"].c.organization_id == organization_id)
                & (table["event"].c.event_date >= func.current_date())
                & (table["event"].c.status == "active")
            )
            .order_by(table["event"].c.event_date.asc())
        )
        events_result = session.execute(select_events).fetchall()

        # Group members by event
        events_dict = {}
        for row in events_result:
            event_id = row._mapping["id"]
            if event_id not in events_dict:
                # Copy event columns except member info
                event_data = {
                    k: v
                    for k, v in row._mapping.items()
                    if k
                    not in [
                        "rsvp_id",
                        "rsvp_status",
                        "account_id",
                        "uuid",
                        "email",
                        "first_name",
                        "last_name",
                        "bio",
                        "profile_picture",
                    ]
                }
                event_data["members"] = []
                event_data["pending_rsvps"] = []
                events_dict[event_id] = event_data

            # Add member info if RSVP exists and is joined
            if row._mapping["rsvp_id"]:
                member = {
                    "rsvp_id": row._mapping["rsvp_id"],
                    "rsvp_status": row._mapping["rsvp_status"],
                    "account": {
                        "id": row._mapping["account_id"],
                        "uuid": row._mapping["uuid"],
                        "email": row._mapping["email"],
                    },
                    "user": {
                        "first_name": row._mapping["first_name"],
                        "last_name": row._mapping["last_name"],
                        "bio": row._mapping["bio"],
                        "profile_picture": row._mapping["profile_picture"],
                    },
                }
                events_dict[event_id]["members"].append(member)

        # Fetch pending RSVPs for each event and add to pending_rsvps
        for event_id in events_dict.keys():
            # Pending RSVPs
            pending_stmt = (
                select(
                    table["rsvp"].c.id.label("rsvp_id"),
                    table["rsvp"].c.status.label("rsvp_status"),
                    table["account"].c.id.label("account_id"),
                    table["account"].c.uuid,
                    table["account"].c.email,
                    table["user"].c.first_name,
                    table["user"].c.last_name,
                    table["user"].c.bio,
                    table["user"].c.profile_picture,
                )
                .select_from(
                    table["rsvp"]
                    .join(
                        table["account"],
                        table["rsvp"].c.attendee == table["account"].c.id,
                    )
                    .outerjoin(
                        table["user"],
                        table["user"].c.account_id == table["account"].c.id,
                    )
                )
                .where(
                    (table["rsvp"].c.event_id == event_id)
                    & (table["rsvp"].c.status == "pending")
                )
            )
            pending_result = session.execute(pending_stmt).fetchall()
            pending_rsvps = []
            for row in pending_result:
                pending_rsvps.append(
                    {
                        "rsvp_id": row._mapping["rsvp_id"],
                        "rsvp_status": row._mapping["rsvp_status"],
                        "account": {
                            "id": row._mapping["account_id"],
                            "uuid": row._mapping["uuid"],
                            "email": row._mapping["email"],
                        },
                        "user": {
                            "first_name": row._mapping["first_name"],
                            "last_name": row._mapping["last_name"],
                            "bio": row._mapping["bio"],
                            "profile_picture": row._mapping["profile_picture"],
                        },
                    }
                )
            events_dict[event_id]["pending_rsvps"] = pending_rsvps

            # Limited comments: top 2 latest for this event
            comments_stmt = (
                select(
                    table["comment"].c.id.label("comment_id"),
                    table["comment"].c.message,
                    table["comment"].c.created_date,
                    table["account"].c.id.label("account_id"),
                    table["account"].c.uuid,
                    table["account"].c.email,
                    table["user"].c.first_name,
                    table["user"].c.last_name,
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
                .where(table["comment"].c.event_id == event_id)
                .order_by(table["comment"].c.created_date.desc())
                .limit(2)
            )
            comments_result = session.execute(comments_stmt).fetchall()
            limited_comments = []
            for row in comments_result:
                limited_comments.append(
                    {
                        "comment_id": row._mapping["comment_id"],
                        "message": row._mapping["message"],
                        "created_date": row._mapping["created_date"],
                        "account": {
                            "id": row._mapping["account_id"],
                            "uuid": row._mapping["uuid"],
                            "email": row._mapping["email"],
                        },
                        "user": {
                            "first_name": row._mapping["first_name"],
                            "last_name": row._mapping["last_name"],
                        },
                    }
                )
            events_dict[event_id]["limited_comments"] = limited_comments

        return {"active_events": list(events_dict.values())}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/organizer/past", tags=["Get Past Events by Organizer"])
async def get_past_events_by_organizer(
    account_uuid: str = Query(..., description="Account UUID of the organizer")
):
    try:
        # Get organization id from account_uuid
        select_organization = (
            select(table["organization"].c.id)
            .select_from(
                table["organization"].join(
                    table["account"],
                    table["organization"].c.account_id == table["account"].c.id,
                )
            )
            .where(table["account"].c.uuid == account_uuid)
        )
        organization_id = session.execute(select_organization).scalar()
        if organization_id is None:
            raise HTTPException(status_code=404, detail="Organization not found")

        # Get all past events for this organization (with joined RSVPs)
        select_events = (
            select(
                table["event"],
                table["rsvp"].c.id.label("rsvp_id"),
                table["rsvp"].c.status.label("rsvp_status"),
                table["account"].c.id.label("account_id"),
                table["account"].c.uuid,
                table["account"].c.email,
                table["user"].c.first_name,
                table["user"].c.last_name,
                table["user"].c.bio,
                table["user"].c.profile_picture,
            )
            .select_from(
                table["event"]
                .outerjoin(
                    table["rsvp"],
                    (table["event"].c.id == table["rsvp"].c.event_id)
                    & (table["rsvp"].c.status == "joined"),
                )
                .outerjoin(
                    table["account"],
                    table["rsvp"].c.attendee == table["account"].c.id,
                )
                .outerjoin(
                    table["user"],
                    table["user"].c.account_id == table["account"].c.id,
                )
            )
            .where(
                (table["event"].c.organization_id == organization_id)
                & (table["event"].c.event_date < func.current_date())
                & (table["event"].c.status == "active")
            )
            .order_by(table["event"].c.event_date.desc())
        )
        events_result = session.execute(select_events).fetchall()

        # Group members by event
        events_dict = {}
        for row in events_result:
            event_id = row._mapping["id"]
            if event_id not in events_dict:
                # Copy event columns except member info
                event_data = {
                    k: v
                    for k, v in row._mapping.items()
                    if k
                    not in [
                        "rsvp_id",
                        "rsvp_status",
                        "account_id",
                        "uuid",
                        "email",
                        "first_name",
                        "last_name",
                        "bio",
                        "profile_picture",
                    ]
                }
                event_data["members"] = []
                events_dict[event_id] = event_data

            # Add member info if RSVP exists and is joined
            if row._mapping["rsvp_id"]:
                member = {
                    "rsvp_id": row._mapping["rsvp_id"],
                    "rsvp_status": row._mapping["rsvp_status"],
                    "account": {
                        "id": row._mapping["account_id"],
                        "uuid": row._mapping["uuid"],
                        "email": row._mapping["email"],
                    },
                    "user": {
                        "first_name": row._mapping["first_name"],
                        "last_name": row._mapping["last_name"],
                        "bio": row._mapping["bio"],
                        "profile_picture": row._mapping["profile_picture"],
                    },
                }
                events_dict[event_id]["members"].append(member)

        # Limited comments: top 2 latest for each event
        for event_id in events_dict.keys():
            comments_stmt = (
                select(
                    table["comment"].c.id.label("comment_id"),
                    table["comment"].c.message,
                    table["comment"].c.created_date,
                    table["account"].c.id.label("account_id"),
                    table["account"].c.uuid,
                    table["account"].c.email,
                    table["user"].c.first_name,
                    table["user"].c.last_name,
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
                .where(table["comment"].c.event_id == event_id)
                .order_by(table["comment"].c.created_date.desc())
                .limit(2)
            )
            comments_result = session.execute(comments_stmt).fetchall()
            limited_comments = []
            for row in comments_result:
                limited_comments.append(
                    {
                        "comment_id": row._mapping["comment_id"],
                        "message": row._mapping["message"],
                        "created_date": row._mapping["created_date"],
                        "account": {
                            "id": row._mapping["account_id"],
                            "uuid": row._mapping["uuid"],
                            "email": row._mapping["email"],
                        },
                        "user": {
                            "first_name": row._mapping["first_name"],
                            "last_name": row._mapping["last_name"],
                        },
                    }
                )
            events_dict[event_id]["limited_comments"] = limited_comments

        return {"past_events": list(events_dict.values())}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/organizer/by_month_year", tags=["Get Events by Month and Year"])
async def get_events_by_month_year(
    account_uuid: str = Query(..., description="Account UUID of the organizer"),
    month: int = Query(..., ge=1, le=12, description="Month (1-12)"),
    year: int = Query(..., ge=1900, description="Year (e.g., 2024)"),
):
    try:
        # Get organization id from account_uuid
        select_organization = (
            select(table["organization"].c.id)
            .select_from(
                table["organization"].join(
                    table["account"],
                    table["organization"].c.account_id == table["account"].c.id,
                )
            )
            .where(table["account"].c.uuid == account_uuid)
        )
        organization_id = session.execute(select_organization).scalar()
        if organization_id is None:
            raise HTTPException(status_code=404, detail="Organization not found")

        # Helper for filtering by month/year
        def month_year_filter(col):
            return (
                func.extract("month", col) == month,
                func.extract("year", col) == year,
            )

        # Past events: before today
        past_stmt = (
            select(table["event"])
            .where(
                (table["event"].c.organization_id == organization_id)
                & (table["event"].c.event_date < func.current_date())
                & (table["event"].c.status == "active")
                & month_year_filter(table["event"].c.event_date)[0]
                & month_year_filter(table["event"].c.event_date)[1]
            )
            .order_by(table["event"].c.event_date.desc())
        )
        past_events = [
            dict(row._mapping) for row in session.execute(past_stmt).fetchall()
        ]

        # Upcoming events: after today
        upcoming_stmt = (
            select(table["event"])
            .where(
                (table["event"].c.organization_id == organization_id)
                & (table["event"].c.event_date > func.current_date())
                & (table["event"].c.status == "active")
                & month_year_filter(table["event"].c.event_date)[0]
                & month_year_filter(table["event"].c.event_date)[1]
            )
            .order_by(table["event"].c.event_date.asc())
        )
        upcoming_events = [
            dict(row._mapping) for row in session.execute(upcoming_stmt).fetchall()
        ]

        # Active events: today or future, status active
        active_stmt = (
            select(table["event"])
            .where(
                (table["event"].c.organization_id == organization_id)
                & (table["event"].c.event_date >= func.current_date())
                & (table["event"].c.status == "active")
                & month_year_filter(table["event"].c.event_date)[0]
                & month_year_filter(table["event"].c.event_date)[1]
            )
            .order_by(table["event"].c.event_date.asc())
        )
        active_events = [
            dict(row._mapping) for row in session.execute(active_stmt).fetchall()
        ]

        return {
            "past_events": past_events,
            "upcoming_events": upcoming_events,
            "active_events": active_events,
        }
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
