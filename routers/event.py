from fastapi import (
    APIRouter,
    HTTPException,
    Path,
    UploadFile,
    File,
    Form,
    Request,
    Query,
    Cookie,
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
from utils.session_utils import get_account_uuid_from_session
from utils.profanity_filter import moderate_text


router = APIRouter(
    prefix="/event",
    tags=["Event Management"],
)

db = Database()
table = db.tables
# session = db.session


def address_dict(row):
    return {
        "id": row.get("address_id"),
        "country": row.get("address_country"),
        "province": row.get("address_province"),
        "city": row.get("address_city"),
        "barangay": row.get("address_barangay"),
        "house_building_number": row.get("address_house_building_number"),
        "country_code": row.get("address_country_code"),
        "province_code": row.get("address_province_code"),
        "city_code": row.get("address_city_code"),
        "barangay_code": row.get("address_barangay_code"),
    }


@router.post("/", tags=["Create Event"])
async def create_event(
    title: str = Form(...),
    event_date: str = Form(...),
    country: str = Form(...),
    province: str = Form(...),
    city: str = Form(...),
    barangay: str = Form(...),
    house_building_number: str = Form(...),
    country_code: str = Form(...),
    province_code: str = Form(...),
    city_code: str = Form(...),
    barangay_code: str = Form(...),
    description: str = Form(...),
    image: Optional[UploadFile] = File(None),
    session_token: str = Cookie(None, alias="session_token"),
):
    session = db.session
    try:
        if not session_token:
            raise HTTPException(status_code=401, detail="Authentication required")

        account_uuid = get_account_uuid_from_session(session_token)

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

        # Moderate title for profanity and toxicity
        if title:
            title_str = str(title)
            title_moderation = moderate_text(
                title_str,
                toxicity_threshold=0.7,
                auto_censor=True
            )
            
            if not title_moderation["approved"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Title {title_moderation['reason']}"
                )
            
            title = title_moderation["moderated_text"]

        # Moderate description for profanity and toxicity
        if description:
            description_str = str(description)
            description_moderation = moderate_text(
                description_str,
                toxicity_threshold=0.7,
                auto_censor=True
            )
            
            if not description_moderation["approved"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Description {description_moderation['reason']}"
                )
            
            description = description_moderation["moderated_text"]
            
        # Insert resource (image) if provided
        image_id = None
        if image:
            image_id = add_resource(image, account_uuid)

        # Insert address first, now with codes
        address_id = add_address(
            country,
            province,
            city,
            barangay,
            house_building_number,
            country_code,
            province_code,
            city_code,
            barangay_code,
        )

        # Insert event using schema.sql columns
        stmt = insert(table["event"]).values(
            organization_id=organization_id,
            title=title,
            event_date=event_date,
            address_id=address_id,
            description=description,
            image=image_id,
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
    event_id: int = Path(..., description="ID of the event to delete"),
    session_token: str = Cookie(None, alias="session_token"),
):
    session = db.session
    try:
        if not session_token:
            raise HTTPException(status_code=401, detail="Authentication required")

        account_uuid = get_account_uuid_from_session(session_token)

        # Get organization id using account_uuid
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

        # Check if event exists and is owned by this organization
        select_event = select(table["event"].c.id).where(
            (table["event"].c.id == event_id)
            & (table["event"].c.organization_id == organization_id)
        )
        event_exists = session.execute(select_event).scalar()
        if not event_exists:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to delete this event or event not found",
            )

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


@router.get("/", tags=["Get all Events and Show RSVP Status of User Per Event"])
async def get_events(
    account_uuid: str = Query(..., description="Account UUID to check RSVP status")
):
    session = db.session
    try:
        # Get account_id from uuid
        select_account = select(table["account"].c.id).where(
            table["account"].c.uuid == account_uuid
        )
        account_id = session.execute(select_account).scalar()
        if account_id is None:
            raise HTTPException(status_code=404, detail="Account not found")

        # Get all events, join image to resource, address to address, and organization to organization_id
        select_events = (
            select(
                table["event"].c.id,
                table["event"].c.organization_id,
                table["event"].c.title,
                table["event"].c.event_date,
                table["event"].c.address_id,
                table["event"].c.description,
                table["event"].c.image,
                table["event"].c.created_date,
                table["event"].c.last_modified_date,
                table["resource"].c.directory.label("image_directory"),
                table["resource"].c.filename.label("image_filename"),
                table["address"].c.country.label("address_country"),
                table["address"].c.province.label("address_province"),
                table["address"].c.city.label("address_city"),
                table["address"].c.barangay.label("address_barangay"),
                table["address"].c.house_building_number.label(
                    "address_house_building_number"
                ),
                table["address"].c.country_code.label("address_country_code"),
                table["address"].c.province_code.label("address_province_code"),
                table["address"].c.city_code.label("address_city_code"),
                table["address"].c.barangay_code.label("address_barangay_code"),
                table["organization"].c.name.label("organization_name"),
                table["organization"].c.description.label("organization_description"),
                table["organization"].c.logo.label("organization_logo"),
                table["organization"].c.category.label("organization_category"),
            )
            .select_from(
                table["event"]
                .outerjoin(
                    table["resource"], table["event"].c.image == table["resource"].c.id
                )
                .outerjoin(
                    table["address"],
                    table["event"].c.address_id == table["address"].c.id,
                )
                .outerjoin(
                    table["organization"],
                    table["event"].c.organization_id == table["organization"].c.id,
                )
            )
            .order_by(table["event"].c.event_date.desc())
        )
        events_result = session.execute(select_events).fetchall()
        events = []
        for row in events_result:
            event = dict(row._mapping)
            event["image"] = (
                {
                    "id": event["image"],
                    "directory": event["image_directory"],
                    "filename": event["image_filename"],
                }
                if event["image"]
                else None
            )
            event.pop("image_directory", None)
            event.pop("image_filename", None)

            # Use the new address_dict function to expose all address fields
            event["address"] = address_dict(event)
            event.pop("address_country", None)
            event.pop("address_province", None)
            event.pop("address_city", None)
            event.pop("address_barangay", None)
            event.pop("address_house_building_number", None)
            event.pop("address_country_code", None)
            event.pop("address_province_code", None)
            event.pop("address_city_code", None)
            event.pop("address_barangay_code", None)

            event["organization"] = {
                "id": event["organization_id"],
                "name": event["organization_name"],
                "description": event["organization_description"],
                "logo": event["organization_logo"],
                "category": event["organization_category"],
            }
            event.pop("organization_name", None)
            event.pop("organization_description", None)
            event.pop("organization_logo", None)
            event.pop("organization_category", None)

            # Get RSVP status for each event for this account
            select_rsvp = select(table["rsvp"].c.status).where(
                (table["rsvp"].c.event_id == event["id"])
                & (table["rsvp"].c.attendee == account_id)
            )
            rsvp_result = session.execute(select_rsvp).scalar()
            event["rsvp_status"] = rsvp_result if rsvp_result else "none"

            events.append(event)

        return {"events": events}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{event_id}", tags=["Update Event"])
async def update_event(
    event_id: int = Path(..., description="ID of the event to update"),
    title: Optional[str] = Form(None),
    event_date: Optional[str] = Form(None),
    country: Optional[str] = Form(None),
    province: Optional[str] = Form(None),
    city: Optional[str] = Form(None),
    barangay: Optional[str] = Form(None),
    house_building_number: Optional[str] = Form(None),
    country_code: Optional[str] = Form(None),
    province_code: Optional[str] = Form(None),
    city_code: Optional[str] = Form(None),
    barangay_code: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None),
    session_token: str = Cookie(None, alias="session_token"),
):
    session = db.session
    try:
        if not session_token:
            raise HTTPException(status_code=401, detail="Authentication required")

        account_uuid = get_account_uuid_from_session(session_token)

        # Get organization id using account_uuid
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

        # Check if event exists and is owned by this organization
        select_event = (
            select(table["event"], table["organization"])
            .select_from(
                table["event"].join(
                    table["organization"],
                    table["event"].c.organization_id == table["organization"].c.id,
                )
            )
            .where(table["event"].c.id == event_id)
            .where(table["organization"].c.id == organization_id)
        )
        event = session.execute(select_event).fetchone()
        if not event:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission to update this event",
            )

        update_data = {}

        if title is not None:
            # Moderate title for profanity and toxicity
            title_str = str(title)
            title_moderation = moderate_text(
                title_str,
                toxicity_threshold=0.7,
                auto_censor=True
            )
            
            if not title_moderation["approved"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Title {title_moderation['reason']}"
                )
            
            update_data["title"] = title_moderation["moderated_text"]

        if event_date is not None:
            update_data["event_date"] = event_date

        if description is not None:
            # Moderate description for profanity and toxicity
            description_str = str(description)
            description_moderation = moderate_text(
                description_str,
                toxicity_threshold=0.7,
                auto_censor=True
            )
            
            if not description_moderation["approved"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Description {description_moderation['reason']}"
                )
            
            update_data["description"] = description_moderation["moderated_text"]

        # Update address if any address field is provided
        address_fields = [
            country,
            province,
            city,
            barangay,
            house_building_number,
            country_code,
            province_code,
            city_code,
            barangay_code,
        ]
        if any(field is not None for field in address_fields):
            address_id = event._mapping["address_id"]
            update_address(
                address_id,
                country=country,
                province=province,
                city=city,
                barangay=barangay,
                house_building_number=house_building_number,
                country_code=country_code,
                province_code=province_code,
                city_code=city_code,
                barangay_code=barangay_code,
            )

        # Update image if provided
        if image:
            image_id = add_resource(image, organization_id)
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
    session = db.session
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
                table["resource"].c.directory.label("profile_picture_directory"),
                table["resource"].c.filename.label("profile_picture_filename"),
            )
            .select_from(
                table["rsvp"]
                .join(
                    table["account"], table["rsvp"].c.attendee == table["account"].c.id
                )
                .outerjoin(
                    table["user"], table["user"].c.account_id == table["account"].c.id
                )
                .outerjoin(
                    table["resource"],
                    table["user"].c.profile_picture == table["resource"].c.id,
                )
            )
            .where(table["rsvp"].c.event_id == event_id)
        )
        rsvps_result = session.execute(stmt).fetchall()
        rsvps = []
        for row in rsvps_result:
            rsvp = dict(row._mapping)
            # Group profile_picture details if present
            if rsvp["profile_picture"]:
                rsvp["profile_picture"] = {
                    "id": rsvp["profile_picture"],
                    "directory": rsvp["profile_picture_directory"],
                    "filename": rsvp["profile_picture_filename"],
                }
            else:
                rsvp["profile_picture"] = None
            rsvp.pop("profile_picture_directory", None)
            rsvp.pop("profile_picture_filename", None)
            rsvps.append(rsvp)

        return {"event_id": event_id, "rsvps": rsvps}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



# modified original function to include pagination and frequency total for events, event's members & requests
@router.get("/organizer/active", tags=["Get Active Events by Organizer"])
async def get_active_events_by_organizer(
    account_uuid: str = Query(..., description="Account UUID of the organizer"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(5, ge=1, le=100, description="Events per page"),
    session_token: Optional[str] = Cookie(None, alias="session_token"),
):
    session = db.session
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

        offset = (page - 1) * page_size

        total_count_stmt = select(func.count(table["event"].c.id)).where(
            (table["event"].c.organization_id == organization_id)
            & (table["event"].c.event_date >= func.current_date())
        )
        total_count = session.execute(total_count_stmt).scalar() or 0

        organization_resource = table["resource"].alias("organization_resource")

        # If session_token is provided, get account_id and user_id
        account_id = None
        user_id = None
        if session_token:
            try:
                account_uuid_user = get_account_uuid_from_session(session_token)
                select_account = select(table["account"].c.id).where(
                    table["account"].c.uuid == account_uuid_user
                )
                account_id = session.execute(select_account).scalar()
                select_user = select(table["user"].c.id).where(
                    table["user"].c.account_id == account_id
                )
                user_id = session.execute(select_user).scalar()
            except Exception:
                account_id = None
                user_id = None

        select_events = (
            select(
                table["event"].c.id,
                table["event"].c.organization_id,
                table["organization"].c.account_id.label("organization_account_id"),
                table["organization"].c.name.label("organization_name"),
                table["organization"].c.logo.label("organization_logo_id"),
                organization_resource.c.directory.label("organization_logo_directory"),
                organization_resource.c.filename.label("organization_logo_filename"),
                table["event"].c.title,
                table["event"].c.event_date,
                table["event"].c.address_id,
                table["event"].c.description,
                table["event"].c.image,
                table["event"].c.created_date,
                table["event"].c.last_modified_date,
                table["resource"].c.directory.label("image_directory"),
                table["resource"].c.filename.label("image_filename"),
                table["address"].c.country.label("address_country"),
                table["address"].c.province.label("address_province"),
                table["address"].c.city.label("address_city"),
                table["address"].c.barangay.label("address_barangay"),
                table["address"].c.house_building_number.label(
                    "address_house_building_number"
                ),
                table["address"].c.country_code.label("address_country_code"),
                table["address"].c.province_code.label("address_province_code"),
                table["address"].c.city_code.label("address_city_code"),
                table["address"].c.barangay_code.label("address_barangay_code"),
            )
            .select_from(
                table["event"]
                .outerjoin(
                    table["organization"],
                    table["event"].c.organization_id == table["organization"].c.id,
                )
                .outerjoin(
                    organization_resource,
                    table["organization"].c.logo == organization_resource.c.id,
                )
                .outerjoin(
                    table["resource"], table["event"].c.image == table["resource"].c.id
                )
                .outerjoin(
                    table["address"],
                    table["event"].c.address_id == table["address"].c.id,
                )
            )
            .where(
                (table["event"].c.organization_id == organization_id)
                & (table["event"].c.event_date >= func.current_date())
            )
            .order_by(table["event"].c.event_date.asc())
            .limit(page_size)
            .offset(offset)
        )
        events_result = session.execute(select_events).fetchall()

        events = []
        for row in events_result:
            event_data = dict(row._mapping)
            event_id = event_data["id"]

            event_data["image"] = (
                {
                    "id": event_data["image"],
                    "directory": event_data["image_directory"],
                    "filename": event_data["image_filename"],
                }
                if event_data["image"]
                else None
            )
            event_data.pop("image_directory", None)
            event_data.pop("image_filename", None)

            event_data["address"] = {
                "id": event_data["address_id"],
                "country": event_data["address_country"],
                "province": event_data["address_province"],
                "city": event_data["address_city"],
                "barangay": event_data["address_barangay"],
                "house_building_number": event_data["address_house_building_number"],
                "country_code": event_data["address_country_code"],
                "province_code": event_data["address_province_code"],
                "city_code": event_data["address_city_code"],
                "barangay_code": event_data["address_barangay_code"],
            }
            event_data.pop("address_country", None)
            event_data.pop("address_province", None)
            event_data.pop("address_city", None)
            event_data.pop("address_barangay", None)
            event_data.pop("address_house_building_number", None)
            event_data.pop("address_country_code", None)
            event_data.pop("address_province_code", None)
            event_data.pop("address_city_code", None)
            event_data.pop("address_barangay_code", None)

            event_data["organization"] = {
                "id": event_data["organization_id"],
                "account_id": event_data["organization_account_id"],
                "name": event_data["organization_name"],
                "logo": (
                    {
                        "id": event_data["organization_logo_id"],
                        "directory": event_data["organization_logo_directory"],
                        "filename": event_data["organization_logo_filename"],
                    }
                    if event_data["organization_logo_id"]
                    else None
                ),
            }
            event_data.pop("organization_account_uuid", None)
            event_data.pop("organization_account_email", None)
            event_data.pop("organization_name", None)
            event_data.pop("organization_description", None)
            event_data.pop("organization_category", None)
            event_data.pop("organization_logo_id", None)
            event_data.pop("organization_logo_directory", None)
            event_data.pop("organization_logo_filename", None)

            members_count_stmt = select(func.count(table["rsvp"].c.id)).where(
                (table["rsvp"].c.event_id == event_id)
                & (table["rsvp"].c.status == "joined")
            )
            total_members = session.execute(members_count_stmt).scalar() or 0

            pending_count_stmt = select(func.count(table["rsvp"].c.id)).where(
                (table["rsvp"].c.event_id == event_id)
                & (table["rsvp"].c.status == "pending")
            )
            total_pending_rsvps = session.execute(pending_count_stmt).scalar() or 0

            # Membership check: Get authenticated user's membership status in this event's organization
            membership_status = None
            if user_id and event_data["organization_id"]:
                membership_stmt = select(table["membership"].c.status).where(
                    (
                        table["membership"].c.organization_id
                        == event_data["organization_id"]
                    )
                    & (table["membership"].c.user_id == user_id)
                )
                membership_status = session.execute(membership_stmt).scalar()
            event_data["user_membership_status_with_organizer"] = membership_status

            # If authenticated user, fetch RSVP status for this event
            if account_id:
                rsvp_stmt = select(table["rsvp"].c.id, table["rsvp"].c.status).where(
                    (table["rsvp"].c.event_id == event_id)
                    & (table["rsvp"].c.attendee == account_id)
                )
                rsvp_result = session.execute(rsvp_stmt).fetchone()
                if rsvp_result:
                    event_data["user_rsvp"] = {
                        "rsvp_id": rsvp_result.id,
                        "status": rsvp_result.status,
                    }
                else:
                    event_data["user_rsvp"] = None

            # Fetch joined RSVPs for this event (limit to recent 3)
            joined_stmt = (
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
                    table["resource"].c.directory.label("profile_picture_directory"),
                    table["resource"].c.filename.label("profile_picture_filename"),
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
                    .outerjoin(
                        table["resource"],
                        table["user"].c.profile_picture == table["resource"].c.id,
                    )
                )
                .where(
                    (table["rsvp"].c.event_id == event_id)
                    & (table["rsvp"].c.status == "joined")
                )
                .limit(3)
            )
            joined_result = session.execute(joined_stmt).fetchall()
            members = []
            for row_member in joined_result:
                profile_picture = None
                if row_member._mapping["profile_picture"]:
                    profile_picture = {
                        "id": row_member._mapping["profile_picture"],
                        "directory": row_member._mapping["profile_picture_directory"],
                        "filename": row_member._mapping["profile_picture_filename"],
                    }
                members.append(
                    {
                        "rsvp_id": row_member._mapping["rsvp_id"],
                        "rsvp_status": row_member._mapping["rsvp_status"],
                        "account": {
                            "id": row_member._mapping["account_id"],
                            "uuid": row_member._mapping["uuid"],
                            "email": row_member._mapping["email"],
                        },
                        "user": {
                            "first_name": row_member._mapping["first_name"],
                            "last_name": row_member._mapping["last_name"],
                            "bio": row_member._mapping["bio"],
                            "profile_picture": profile_picture,
                        },
                    }
                )

            # Pending RSVPs (limit to recent 3)
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
                    table["resource"].c.directory.label("profile_picture_directory"),
                    table["resource"].c.filename.label("profile_picture_filename"),
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
                    .outerjoin(
                        table["resource"],
                        table["user"].c.profile_picture == table["resource"].c.id,
                    )
                )
                .where(
                    (table["rsvp"].c.event_id == event_id)
                    & (table["rsvp"].c.status == "pending")
                )
                .limit(3)
            )
            pending_result = session.execute(pending_stmt).fetchall()
            pending_rsvps = []
            for row_pending in pending_result:
                profile_picture = None
                if row_pending._mapping["profile_picture"]:
                    profile_picture = {
                        "id": row_pending._mapping["profile_picture"],
                        "directory": row_pending._mapping["profile_picture_directory"],
                        "filename": row_pending._mapping["profile_picture_filename"],
                    }
                pending_rsvps.append(
                    {
                        "rsvp_id": row_pending._mapping["rsvp_id"],
                        "rsvp_status": row_pending._mapping["rsvp_status"],
                        "account": {
                            "id": row_pending._mapping["account_id"],
                            "uuid": row_pending._mapping["uuid"],
                            "email": row_pending._mapping["email"],
                        },
                        "user": {
                            "first_name": row_pending._mapping["first_name"],
                            "last_name": row_pending._mapping["last_name"],
                            "bio": row_pending._mapping["bio"],
                            "profile_picture": profile_picture,
                        },
                    }
                )

            comment_profile_resource = table["resource"].alias(
                "comment_profile_resource"
            )
            comment_logo_resource = table["resource"].alias("comment_logo_resource")

            comment_count_stmt = select(func.count(table["comment"].c.id)).where(
                table["comment"].c.event_id == event_id
            )
            total_comments = session.execute(comment_count_stmt).scalar() or 0

            comments_stmt = (
                select(
                    table["comment"].c.id.label("comment_id"),
                    table["comment"].c.message,
                    table["comment"].c.created_date,
                    table["account"].c.id.label("account_id"),
                    table["account"].c.uuid,
                    table["account"].c.email,
                    table["role"].c.name.label("role_name"),
                    table["user"].c.first_name.label("user_first_name"),
                    table["user"].c.last_name.label("user_last_name"),
                    table["user"].c.profile_picture.label("profile_picture_id"),
                    comment_profile_resource.c.directory.label(
                        "profile_picture_directory"
                    ),
                    comment_profile_resource.c.filename.label(
                        "profile_picture_filename"
                    ),
                    table["organization"].c.name.label("organization_name"),
                    table["organization"].c.category.label("organization_category"),
                    table["organization"].c.logo.label("organization_logo_id"),
                    comment_logo_resource.c.directory.label(
                        "organization_logo_directory"
                    ),
                    comment_logo_resource.c.filename.label(
                        "organization_logo_filename"
                    ),
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
                        comment_profile_resource,
                        table["user"].c.profile_picture
                        == comment_profile_resource.c.id,
                    )
                    .outerjoin(
                        table["organization"],
                        table["organization"].c.account_id == table["account"].c.id,
                    )
                    .outerjoin(
                        comment_logo_resource,
                        table["organization"].c.logo == comment_logo_resource.c.id,
                    )
                )
                .where(table["comment"].c.event_id == event_id)
                .order_by(table["comment"].c.created_date.desc())
                .limit(3)
            )

            comments_result = session.execute(comments_stmt).fetchall()
            limited_comments = []
            for row_comment in comments_result:
                data = row_comment._mapping
                role_name = data.get("role_name")
                comment_obj = {
                    "comment_id": data["comment_id"],
                    "message": data["message"],
                    "created_date": data["created_date"],
                    "account": {
                        "id": data["account_id"],
                        "uuid": data["account_uuid"],
                        "email": data["account_email"],
                    },
                    "role": role_name,
                }
                if role_name == "organization":
                    comment_obj["organization"] = {
                        "name": data["organization_name"],
                        "category": data["organization_category"],
                        "logo": (
                            {
                                "id": data["organization_logo_id"],
                                "directory": data["organization_logo_directory"],
                                "filename": data["organization_logo_filename"],
                            }
                            if data["organization_logo_id"]
                            else None
                        ),
                    }
                else:
                    comment_obj["user"] = {
                        "first_name": data["user_first_name"],
                        "last_name": data["user_last_name"],
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
                limited_comments.append(comment_obj)

            event_data["total_comments"] = total_comments
            event_data["total_members"] = total_members
            event_data["total_pending_rsvps"] = total_pending_rsvps
            event_data["members"] = members
            event_data["pending_rsvps"] = pending_rsvps
            event_data["limited_comments"] = limited_comments

            events.append(event_data)

        return {
            "page": page,
            "page_size": page_size,
            "active_events": events,
            "total": total_count,
        }

    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/organizer/past", tags=["Get Past Events by Organizer"])
async def get_past_events_by_organizer(
    account_uuid: str = Query(..., description="Account UUID of the organizer"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(5, ge=1, le=100, description="Events per page"),
    session_token: Optional[str] = Cookie(None, alias="session_token"),
):
    session = db.session
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

        # Pagination: get total count
        total_count_stmt = select(func.count(table["event"].c.id)).where(
            (table["event"].c.organization_id == organization_id)
            & (table["event"].c.event_date < func.current_date())
        )
        total_count = session.execute(total_count_stmt).scalar() or 0
        offset = (page - 1) * page_size

        organization_resource = table["resource"].alias("organization_resource")

        # If session_token is provided, get account_id and user_id
        account_id = None
        user_id = None
        if session_token:
            try:
                account_uuid_user = get_account_uuid_from_session(session_token)
                select_account = select(table["account"].c.id).where(
                    table["account"].c.uuid == account_uuid_user
                )
                account_id = session.execute(select_account).scalar()
                select_user = select(table["user"].c.id).where(
                    table["user"].c.account_id == account_id
                )
                user_id = session.execute(select_user).scalar()
            except Exception:
                account_id = None
                user_id = None

        # Get paginated past events for this organization (with joined RSVPs, address, resource)
        select_events = (
            select(
                table["event"].c.id,
                table["event"].c.organization_id,
                table["organization"].c.account_id.label("organization_account_id"),
                table["organization"].c.name.label("organization_name"),
                table["organization"].c.logo.label("organization_logo_id"),
                organization_resource.c.directory.label("organization_logo_directory"),
                organization_resource.c.filename.label("organization_logo_filename"),
                table["event"].c.title,
                table["event"].c.event_date,
                table["event"].c.address_id,
                table["event"].c.description,
                table["event"].c.image,
                table["event"].c.created_date,
                table["event"].c.last_modified_date,
                table["resource"].c.directory.label("image_directory"),
                table["resource"].c.filename.label("image_filename"),
                table["address"].c.country.label("address_country"),
                table["address"].c.province.label("address_province"),
                table["address"].c.city.label("address_city"),
                table["address"].c.barangay.label("address_barangay"),
                table["address"].c.house_building_number.label(
                    "address_house_building_number"
                ),
                table["address"].c.country_code.label("address_country_code"),
                table["address"].c.province_code.label("address_province_code"),
                table["address"].c.city_code.label("address_city_code"),
                table["address"].c.barangay_code.label("address_barangay_code"),
            )
            .select_from(
                table["event"]
                .outerjoin(
                    table["organization"],
                    table["event"].c.organization_id == table["organization"].c.id,
                )
                .outerjoin(
                    organization_resource,
                    table["organization"].c.logo == organization_resource.c.id,
                )
                .outerjoin(
                    table["resource"], table["event"].c.image == table["resource"].c.id
                )
                .outerjoin(
                    table["address"],
                    table["event"].c.address_id == table["address"].c.id,
                )
            )
            .where(
                (table["event"].c.organization_id == organization_id)
                & (table["event"].c.event_date < func.current_date())
            )
            .order_by(table["event"].c.event_date.desc())
            .limit(page_size)
            .offset(offset)
        )
        events_result = session.execute(select_events).fetchall()

        events_list = []
        for row in events_result:
            event_id = row._mapping["id"]
            event_data = dict(row._mapping)
            event_data["image"] = (
                {
                    "id": event_data["image"],
                    "directory": event_data["image_directory"],
                    "filename": event_data["image_filename"],
                }
                if event_data["image"]
                else None
            )
            event_data.pop("image_directory", None)
            event_data.pop("image_filename", None)
            event_data["address"] = {
                "id": event_data["address_id"],
                "country": event_data["address_country"],
                "province": event_data["address_province"],
                "city": event_data["address_city"],
                "barangay": event_data["address_barangay"],
                "house_building_number": event_data["address_house_building_number"],
                "country_code": event_data["address_country_code"],
                "province_code": event_data["address_province_code"],
                "city_code": event_data["address_city_code"],
                "barangay_code": event_data["address_barangay_code"],
            }
            event_data.pop("address_country", None)
            event_data.pop("address_province", None)
            event_data.pop("address_city", None)
            event_data.pop("address_barangay", None)
            event_data.pop("address_house_building_number", None)
            event_data.pop("address_country_code", None)
            event_data.pop("address_province_code", None)
            event_data.pop("address_city_code", None)
            event_data.pop("address_barangay_code", None)

            event_data["organization"] = {
                "id": event_data["organization_id"],
                "account_id": event_data["organization_account_id"],
                "name": event_data["organization_name"],
                "logo": (
                    {
                        "id": event_data["organization_logo_id"],
                        "directory": event_data["organization_logo_directory"],
                        "filename": event_data["organization_logo_filename"],
                    }
                    if event_data["organization_logo_id"]
                    else None
                ),
            }
            event_data.pop("organization_account_uuid", None)
            event_data.pop("organization_account_email", None)
            event_data.pop("organization_name", None)
            event_data.pop("organization_description", None)
            event_data.pop("organization_category", None)
            event_data.pop("organization_logo_id", None)
            event_data.pop("organization_logo_directory", None)
            event_data.pop("organization_logo_filename", None)

            members_count_stmt = select(func.count(table["rsvp"].c.id)).where(
                (table["rsvp"].c.event_id == event_id)
                & (table["rsvp"].c.status == "joined")
            )
            total_members = session.execute(members_count_stmt).scalar() or 0

            pending_count_stmt = select(func.count(table["rsvp"].c.id)).where(
                (table["rsvp"].c.event_id == event_id)
                & (table["rsvp"].c.status == "pending")
            )
            total_pending_rsvps = session.execute(pending_count_stmt).scalar() or 0

            # Membership check: Get authenticated user's membership status in this event's organization
            membership_status = None
            if user_id and event_data["organization_id"]:
                membership_stmt = select(table["membership"].c.status).where(
                    (
                        table["membership"].c.organization_id
                        == event_data["organization_id"]
                    )
                    & (table["membership"].c.user_id == user_id)
                )
                membership_status = session.execute(membership_stmt).scalar()
            event_data["user_membership_status_with_organizer"] = membership_status

            # If authenticated user, fetch RSVP status for this event
            if account_id:
                rsvp_stmt = select(table["rsvp"].c.id, table["rsvp"].c.status).where(
                    (table["rsvp"].c.event_id == event_id)
                    & (table["rsvp"].c.attendee == account_id)
                )
                rsvp_result = session.execute(rsvp_stmt).fetchone()
                if rsvp_result:
                    event_data["user_rsvp"] = {
                        "rsvp_id": rsvp_result.id,
                        "status": rsvp_result.status,
                    }
                else:
                    event_data["user_rsvp"] = None

            # Fetch joined RSVPs for this event (limit to recent 3)
            joined_stmt = (
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
                    table["resource"].c.directory.label("profile_picture_directory"),
                    table["resource"].c.filename.label("profile_picture_filename"),
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
                    .outerjoin(
                        table["resource"],
                        table["user"].c.profile_picture == table["resource"].c.id,
                    )
                )
                .where(
                    (table["rsvp"].c.event_id == event_id)
                    & (table["rsvp"].c.status == "joined")
                )
                .limit(3)
            )
            joined_result = session.execute(joined_stmt).fetchall()
            members = []
            for row_member in joined_result:
                profile_picture = None
                if row_member._mapping["profile_picture"]:
                    profile_picture = {
                        "id": row_member._mapping["profile_picture"],
                        "directory": row_member._mapping["profile_picture_directory"],
                        "filename": row_member._mapping["profile_picture_filename"],
                    }
                members.append(
                    {
                        "rsvp_id": row_member._mapping["rsvp_id"],
                        "rsvp_status": row_member._mapping["rsvp_status"],
                        "account": {
                            "id": row_member._mapping["account_id"],
                            "uuid": row_member._mapping["uuid"],
                            "email": row_member._mapping["email"],
                        },
                        "user": {
                            "first_name": row_member._mapping["first_name"],
                            "last_name": row_member._mapping["last_name"],
                            "bio": row_member._mapping["bio"],
                            "profile_picture": profile_picture,
                        },
                    }
                )

            # Pending RSVPs (limit to recent 3)
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
                    table["resource"].c.directory.label("profile_picture_directory"),
                    table["resource"].c.filename.label("profile_picture_filename"),
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
                    .outerjoin(
                        table["resource"],
                        table["user"].c.profile_picture == table["resource"].c.id,
                    )
                )
                .where(
                    (table["rsvp"].c.event_id == event_id)
                    & (table["rsvp"].c.status == "pending")
                )
                .limit(3)
            )
            pending_result = session.execute(pending_stmt).fetchall()
            pending_rsvps = []
            for row_pending in pending_result:
                profile_picture = None
                if row_pending._mapping["profile_picture"]:
                    profile_picture = {
                        "id": row_pending._mapping["profile_picture"],
                        "directory": row_pending._mapping["profile_picture_directory"],
                        "filename": row_pending._mapping["profile_picture_filename"],
                    }
                pending_rsvps.append(
                    {
                        "rsvp_id": row_pending._mapping["rsvp_id"],
                        "rsvp_status": row_pending._mapping["rsvp_status"],
                        "account": {
                            "id": row_pending._mapping["account_id"],
                            "uuid": row_pending._mapping["uuid"],
                            "email": row_pending._mapping["email"],
                        },
                        "user": {
                            "first_name": row_pending._mapping["first_name"],
                            "last_name": row_pending._mapping["last_name"],
                            "bio": row_pending._mapping["bio"],
                            "profile_picture": profile_picture,
                        },
                    }
                )

            comment_profile_resource = table["resource"].alias(
                "comment_profile_resource"
            )
            comment_logo_resource = table["resource"].alias("comment_logo_resource")

            comment_count_stmt = select(func.count(table["comment"].c.id)).where(
                table["comment"].c.event_id == event_id
            )
            total_comments = session.execute(comment_count_stmt).scalar() or 0

            comments_stmt = (
                select(
                    table["comment"].c.id.label("comment_id"),
                    table["comment"].c.message,
                    table["comment"].c.created_date,
                    table["account"].c.id.label("account_id"),
                    table["account"].c.uuid,
                    table["account"].c.email,
                    table["role"].c.name.label("role_name"),
                    table["user"].c.first_name.label("user_first_name"),
                    table["user"].c.last_name.label("user_last_name"),
                    table["user"].c.profile_picture.label("profile_picture_id"),
                    comment_profile_resource.c.directory.label(
                        "profile_picture_directory"
                    ),
                    comment_profile_resource.c.filename.label(
                        "profile_picture_filename"
                    ),
                    table["organization"].c.name.label("organization_name"),
                    table["organization"].c.category.label("organization_category"),
                    table["organization"].c.logo.label("organization_logo_id"),
                    comment_logo_resource.c.directory.label(
                        "organization_logo_directory"
                    ),
                    comment_logo_resource.c.filename.label(
                        "organization_logo_filename"
                    ),
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
                        comment_profile_resource,
                        table["user"].c.profile_picture
                        == comment_profile_resource.c.id,
                    )
                    .outerjoin(
                        table["organization"],
                        table["organization"].c.account_id == table["account"].c.id,
                    )
                    .outerjoin(
                        comment_logo_resource,
                        table["organization"].c.logo == comment_logo_resource.c.id,
                    )
                )
                .where(table["comment"].c.event_id == event_id)
                .order_by(table["comment"].c.created_date.desc())
                .limit(3)
            )

            comments_result = session.execute(comments_stmt).fetchall()
            limited_comments = []
            for row_comment in comments_result:
                data = row_comment._mapping
                role_name = data.get("role_name")
                comment_obj = {
                    "comment_id": data["comment_id"],
                    "message": data["message"],
                    "created_date": data["created_date"],
                    "account": {
                        "id": data["account_id"],
                        "uuid": data["account_uuid"],
                        "email": data["account_email"],
                    },
                    "role": role_name,
                }
                if role_name == "organization":
                    comment_obj["organization"] = {
                        "name": data["organization_name"],
                        "category": data["organization_category"],
                        "logo": (
                            {
                                "id": data["organization_logo_id"],
                                "directory": data["organization_logo_directory"],
                                "filename": data["organization_logo_filename"],
                            }
                            if data["organization_logo_id"]
                            else None
                        ),
                    }
                else:
                    comment_obj["user"] = {
                        "first_name": data["user_first_name"],
                        "last_name": data["user_last_name"],
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
                limited_comments.append(comment_obj)

            event_data["total_comments"] = total_comments
            event_data["total_members"] = total_members
            event_data["total_pending_rsvps"] = total_pending_rsvps
            event_data["members"] = members
            event_data["pending_rsvps"] = pending_rsvps
            event_data["limited_comments"] = limited_comments

            events_list.append(event_data)

        return {
            "page": page,
            "page_size": page_size,
            "past_events": events_list,
            "total": total_count,
        }
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
    session = db.session
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
            # raise HTTPException(status_code=404, detail="Organization not found")
            return {
                "past_events": [],
                "active_events": [],
            }

        def month_year_filter(col):
            return (
                func.extract("month", col) == month,
                func.extract("year", col) == year,
            )

        # Past events: before today
        logo_resource = table["resource"].alias("logo_resource")
        past_stmt = (
            select(
                table["event"],
                table["address"].c.country.label("address_country"),
                table["address"].c.province.label("address_province"),
                table["address"].c.city.label("address_city"),
                table["address"].c.barangay.label("address_barangay"),
                table["address"].c.house_building_number.label(
                    "address_house_building_number"
                ),
                table["address"].c.country_code.label("address_country_code"),
                table["address"].c.province_code.label("address_province_code"),
                table["address"].c.city_code.label("address_city_code"),
                table["address"].c.barangay_code.label("address_barangay_code"),
                table["resource"].c.directory.label("image_directory"),
                table["resource"].c.filename.label("image_filename"),
                table["organization"].c.name.label("organization_name"),
                table["organization"].c.description.label("organization_description"),
                table["organization"].c.logo.label("organization_logo"),
                table["organization"].c.category.label("organization_category"),
                logo_resource.c.directory.label("logo_directory"),
                logo_resource.c.filename.label("logo_filename"),
            )
            .select_from(
                table["event"]
                .join(
                    table["organization"],
                    table["event"].c.organization_id == table["organization"].c.id,
                )
                .outerjoin(
                    table["address"],
                    table["event"].c.address_id == table["address"].c.id,
                )
                .outerjoin(
                    table["resource"], table["event"].c.image == table["resource"].c.id
                )
                .outerjoin(
                    logo_resource, table["organization"].c.logo == logo_resource.c.id
                )
            )
            .where(
                (table["event"].c.organization_id == organization_id)
                & (table["event"].c.event_date < func.current_date())
                & month_year_filter(table["event"].c.event_date)[0]
                & month_year_filter(table["event"].c.event_date)[1]
            )
            .order_by(table["event"].c.event_date.desc())
        )
        past_events_result = session.execute(past_stmt).fetchall()
        past_events = []
        for row in past_events_result:
            event = dict(row._mapping)
            event_id = event["id"]
            event["image"] = (
                {
                    "id": event["image"],
                    "directory": event["image_directory"],
                    "filename": event["image_filename"],
                }
                if event["image"]
                else None
            )
            event.pop("image_directory", None)
            event.pop("image_filename", None)
            event["address"] = {
                "id": event["address_id"],
                "country": event["address_country"],
                "province": event["address_province"],
                "city": event["address_city"],
                "barangay": event["address_barangay"],
                "house_building_number": event["address_house_building_number"],
                "country_code": event["address_country_code"],
                "province_code": event["address_province_code"],
                "city_code": event["address_city_code"],
                "barangay_code": event["address_barangay_code"],
            }
            event.pop("address_country", None)
            event.pop("address_province", None)
            event.pop("address_city", None)
            event.pop("address_barangay", None)
            event.pop("address_house_building_number", None)
            event.pop("address_country_code", None)
            event.pop("address_province_code", None)
            event.pop("address_city_code", None)
            event.pop("address_barangay_code", None)

            # Add organization object
            event["organization"] = {
                "id": event["organization_id"],
                "name": event["organization_name"],
                "description": event["organization_description"],
                "logo": (
                    {
                        "id": event["organization_logo"],
                        "directory": event.get("logo_directory"),
                        "filename": event.get("logo_filename"),
                    }
                    if event.get("organization_logo")
                    else None
                ),
                "category": event["organization_category"],
            }
            event.pop("organization_name", None)
            event.pop("organization_description", None)
            event.pop("organization_logo", None)
            event.pop("organization_category", None)
            event.pop("logo_directory", None)
            event.pop("logo_filename", None)

            # Fetch RSVPs for this event, join user and profile picture
            profile_resource = table["resource"].alias("profile_resource")
            rsvp_stmt = (
                select(
                    table["rsvp"].c.id.label("rsvp_id"),
                    table["rsvp"].c.status.label("rsvp_status"),
                    table["account"].c.id.label("account_id"),
                    table["account"].c.uuid,
                    table["account"].c.email,
                    table["user"].c.id.label("user_id"),
                    table["user"].c.first_name,
                    table["user"].c.last_name,
                    table["user"].c.bio,
                    table["user"].c.profile_picture.label("profile_picture_id"),
                    profile_resource.c.directory.label("profile_picture_directory"),
                    profile_resource.c.filename.label("profile_picture_filename"),
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
                    .outerjoin(
                        profile_resource,
                        table["user"].c.profile_picture == profile_resource.c.id,
                    )
                )
                .where(table["rsvp"].c.event_id == event_id)
            )
            rsvp_result = session.execute(rsvp_stmt).fetchall()
            rsvps = []
            for rsvp_row in rsvp_result:
                rsvp = dict(rsvp_row._mapping)
                rsvp["user"] = {
                    "id": rsvp.get("user_id"),
                    "first_name": rsvp.get("first_name"),
                    "last_name": rsvp.get("last_name"),
                    "bio": rsvp.get("bio"),
                    "profile_picture": (
                        {
                            "id": rsvp.get("profile_picture_id"),
                            "directory": rsvp.get("profile_picture_directory"),
                            "filename": rsvp.get("profile_picture_filename"),
                        }
                        if rsvp.get("profile_picture_id")
                        else None
                    ),
                }
                rsvp.pop("user_id", None)
                rsvp.pop("first_name", None)
                rsvp.pop("last_name", None)
                rsvp.pop("bio", None)
                rsvp.pop("profile_picture_id", None)
                rsvp.pop("profile_picture_directory", None)
                rsvp.pop("profile_picture_filename", None)
                rsvps.append(rsvp)
            event["rsvps"] = rsvps
            event["rsvp_count"] = len(rsvps)

            # Fetch top 3 latest comments and total count for this event
            comment_count_stmt = select(func.count(table["comment"].c.id)).where(
                table["comment"].c.event_id == event_id
            )
            total_comments = session.execute(comment_count_stmt).scalar() or 0

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
                .limit(3)
            )
            comments_result = session.execute(comments_stmt).fetchall()
            latest_comments = []
            for row_comment in comments_result:
                latest_comments.append(
                    {
                        "comment_id": row_comment._mapping["comment_id"],
                        "message": row_comment._mapping["message"],
                        "created_date": row_comment._mapping["created_date"],
                        "account": {
                            "id": row_comment._mapping["account_id"],
                            "uuid": row_comment._mapping["uuid"],
                            "email": row_comment._mapping["email"],
                        },
                        "user": {
                            "first_name": row_comment._mapping["first_name"],
                            "last_name": row_comment._mapping["last_name"],
                        },
                    }
                )
            event["latest_comments"] = latest_comments
            event["total_comments"] = total_comments

            past_events.append(event)

        # Active events: today or future, status active
        active_stmt = (
            select(
                table["event"],
                table["address"].c.country.label("address_country"),
                table["address"].c.province.label("address_province"),
                table["address"].c.city.label("address_city"),
                table["address"].c.barangay.label("address_barangay"),
                table["address"].c.house_building_number.label(
                    "address_house_building_number"
                ),
                table["address"].c.country_code.label("address_country_code"),
                table["address"].c.province_code.label("address_province_code"),
                table["address"].c.city_code.label("address_city_code"),
                table["address"].c.barangay_code.label("address_barangay_code"),
                table["resource"].c.directory.label("image_directory"),
                table["resource"].c.filename.label("image_filename"),
                table["organization"].c.name.label("organization_name"),
                table["organization"].c.description.label("organization_description"),
                table["organization"].c.logo.label("organization_logo"),
                table["organization"].c.category.label("organization_category"),
                logo_resource.c.directory.label("logo_directory"),
                logo_resource.c.filename.label("logo_filename"),
            )
            .select_from(
                table["event"]
                .join(
                    table["organization"],
                    table["event"].c.organization_id == table["organization"].c.id,
                )
                .outerjoin(
                    table["address"],
                    table["event"].c.address_id == table["address"].c.id,
                )
                .outerjoin(
                    table["resource"], table["event"].c.image == table["resource"].c.id
                )
                .outerjoin(
                    logo_resource, table["organization"].c.logo == logo_resource.c.id
                )
            )
            .where(
                (table["event"].c.organization_id == organization_id)
                & (table["event"].c.event_date >= func.current_date())
                & month_year_filter(table["event"].c.event_date)[0]
                & month_year_filter(table["event"].c.event_date)[1]
            )
            .order_by(table["event"].c.event_date.asc())
        )
        active_events_result = session.execute(active_stmt).fetchall()
        active_events = []
        for row in active_events_result:
            event = dict(row._mapping)
            event_id = event["id"]
            event["image"] = (
                {
                    "id": event["image"],
                    "directory": event["image_directory"],
                    "filename": event["image_filename"],
                }
                if event["image"]
                else None
            )
            event.pop("image_directory", None)
            event.pop("image_filename", None)
            event["address"] = {
                "id": event["address_id"],
                "country": event["address_country"],
                "province": event["address_province"],
                "city": event["address_city"],
                "barangay": event["address_barangay"],
                "house_building_number": event["address_house_building_number"],
                "country_code": event["address_country_code"],
                "province_code": event["address_province_code"],
                "city_code": event["address_city_code"],
                "barangay_code": event["address_barangay_code"],
            }
            event.pop("address_country", None)
            event.pop("address_province", None)
            event.pop("address_city", None)
            event.pop("address_barangay", None)
            event.pop("address_house_building_number", None)
            event.pop("address_country_code", None)
            event.pop("address_province_code", None)
            event.pop("address_city_code", None)
            event.pop("address_barangay_code", None)

            # Add organization object
            event["organization"] = {
                "id": event["organization_id"],
                "name": event["organization_name"],
                "description": event["organization_description"],
                "logo": (
                    {
                        "id": event["organization_logo"],
                        "directory": event.get("logo_directory"),
                        "filename": event.get("logo_filename"),
                    }
                    if event.get("organization_logo")
                    else None
                ),
                "category": event["organization_category"],
            }
            event.pop("organization_name", None)
            event.pop("organization_description", None)
            event.pop("organization_logo", None)
            event.pop("organization_category", None)
            event.pop("logo_directory", None)
            event.pop("logo_filename", None)

            # Fetch RSVPs for this event, join user and profile picture
            profile_resource = table["resource"].alias("profile_resource")
            rsvp_stmt = (
                select(
                    table["rsvp"].c.id.label("rsvp_id"),
                    table["rsvp"].c.status.label("rsvp_status"),
                    table["account"].c.id.label("account_id"),
                    table["account"].c.uuid,
                    table["account"].c.email,
                    table["user"].c.id.label("user_id"),
                    table["user"].c.first_name,
                    table["user"].c.last_name,
                    table["user"].c.bio,
                    table["user"].c.profile_picture.label("profile_picture_id"),
                    profile_resource.c.directory.label("profile_picture_directory"),
                    profile_resource.c.filename.label("profile_picture_filename"),
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
                    .outerjoin(
                        profile_resource,
                        table["user"].c.profile_picture == profile_resource.c.id,
                    )
                )
                .where(table["rsvp"].c.event_id == event_id)
            )
            rsvp_result = session.execute(rsvp_stmt).fetchall()
            rsvps = []
            for rsvp_row in rsvp_result:
                rsvp = dict(rsvp_row._mapping)
                rsvp["user"] = {
                    "id": rsvp.get("user_id"),
                    "first_name": rsvp.get("first_name"),
                    "last_name": rsvp.get("last_name"),
                    "bio": rsvp.get("bio"),
                    "profile_picture": (
                        {
                            "id": rsvp.get("profile_picture_id"),
                            "directory": rsvp.get("profile_picture_directory"),
                            "filename": rsvp.get("profile_picture_filename"),
                        }
                        if rsvp.get("profile_picture_id")
                        else None
                    ),
                }
                rsvp.pop("user_id", None)
                rsvp.pop("first_name", None)
                rsvp.pop("last_name", None)
                rsvp.pop("bio", None)
                rsvp.pop("profile_picture_id", None)
                rsvp.pop("profile_picture_directory", None)
                rsvp.pop("profile_picture_filename", None)
                rsvps.append(rsvp)
            event["rsvps"] = rsvps
            event["rsvp_count"] = len(rsvps)

            # Fetch top 3 latest comments and total count for this event
            comment_count_stmt = select(func.count(table["comment"].c.id)).where(
                table["comment"].c.event_id == event_id
            )
            total_comments = session.execute(comment_count_stmt).scalar() or 0

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
                .limit(3)
            )
            comments_result = session.execute(comments_stmt).fetchall()
            latest_comments = []
            for row_comment in comments_result:
                latest_comments.append(
                    {
                        "comment_id": row_comment._mapping["comment_id"],
                        "message": row_comment._mapping["message"],
                        "created_date": row_comment._mapping["created_date"],
                        "account": {
                            "id": row_comment._mapping["account_id"],
                            "uuid": row_comment._mapping["uuid"],
                            "email": row_comment._mapping["email"],
                        },
                        "user": {
                            "first_name": row_comment._mapping["first_name"],
                            "last_name": row_comment._mapping["last_name"],
                        },
                    }
                )
            event["latest_comments"] = latest_comments
            event["total_comments"] = total_comments

            active_events.append(event)

        return {
            "past_events": past_events,
            "active_events": active_events,
        }
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/by_status_with_comments", tags=["Get Events By Status With Comments"])
async def get_events_by_status_with_comments(
    status: str = Query(
        "active", description="Event status (e.g., active, cancelled, etc.)"
    ),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Events per page (max 100)"),
):
    session = db.session
    try:
        offset = (page - 1) * limit

        # Get total count for pagination info
        count_stmt = (
            select(func.count())
            .select_from(table["event"])
            .where(
                (table["event"].c.status == status)
                & (table["event"].c.event_date >= func.current_date())
            )
        )
        total_events = session.execute(count_stmt).scalar()

        # Get paginated events by status
        select_events = (
            select(table["event"])
            .where(
                (table["event"].c.status == status)
                & (table["event"].c.event_date >= func.current_date())
            )
            .order_by(table["event"].c.event_date.asc())
            .limit(limit)
            .offset(offset)
        )
        events_result = session.execute(select_events).fetchall()
        events = [dict(row._mapping) for row in events_result]

        # For each event, get top 3 latest comments
        for event in events:
            event_id = event["id"]
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
                .limit(3)
            )
            comments_result = session.execute(comments_stmt).fetchall()
            latest_comments = []
            for row in comments_result:
                latest_comments.append(
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
            event["latest_comments"] = latest_comments

        return {
            "events": events,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_events,
                "pages": (total_events + limit - 1) // limit,
            },
        }
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/all_with_comments", tags=["Get All Events With Comments"])
async def get_all_events_with_comments(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(5, ge=1, le=20, description="Events per page (max 20)"),
    session_token: Optional[str] = Cookie(None, alias="session_token"),
):
    session = db.session
    try:
        offset = (page - 1) * limit

        # Get total count for pagination info (any status, any date)
        count_stmt = select(func.count()).select_from(table["event"])
        total_events = session.execute(count_stmt).scalar()

        # If session_token is provided, get account_id and user_id
        account_id = None
        user_id = None
        if session_token:
            try:
                account_uuid = get_account_uuid_from_session(session_token)
                select_account = select(table["account"].c.id).where(
                    table["account"].c.uuid == account_uuid
                )
                account_id = session.execute(select_account).scalar()
                # Get user_id for membership check
                select_user = select(table["user"].c.id).where(
                    table["user"].c.account_id == account_id
                )
                user_id = session.execute(select_user).scalar()
            except Exception:
                account_id = None
                user_id = None

        logo_resource = table["resource"].alias("logo_resource")

        events_stmt = (
            select(
                table["event"],
                table["organization"].c.account_id.label("org_account_id"),
                table["organization"].c.id.label("org_id"),
                table["organization"].c.name.label("org_name"),
                table["organization"].c.description.label("org_description"),
                table["organization"].c.logo.label("org_logo"),
                logo_resource.c.directory.label("logo_directory"),
                logo_resource.c.filename.label("logo_filename"),
                table["resource"].c.directory.label("image_directory"),
                table["resource"].c.filename.label("image_filename"),
                table["address"].c.country.label("address_country"),
                table["address"].c.province.label("address_province"),
                table["address"].c.city.label("address_city"),
                table["address"].c.barangay.label("address_barangay"),
                table["address"].c.house_building_number.label(
                    "address_house_building_number"
                ),
                table["address"].c.country_code.label("address_country_code"),
                table["address"].c.province_code.label("address_province_code"),
                table["address"].c.city_code.label("address_city_code"),
                table["address"].c.barangay_code.label("address_barangay_code"),
            )
            .select_from(
                table["event"]
                .join(
                    table["organization"],
                    table["event"].c.organization_id == table["organization"].c.id,
                )
                .outerjoin(
                    table["resource"],
                    table["event"].c.image == table["resource"].c.id,
                )
                .outerjoin(
                    logo_resource,
                    table["organization"].c.logo == logo_resource.c.id,
                )
                .outerjoin(
                    table["address"],
                    table["event"].c.address_id == table["address"].c.id,
                )
            )
            .order_by(table["event"].c.created_date.desc())
            .limit(limit)
            .offset(offset)
        )
        events_result = session.execute(events_stmt).fetchall()
        events = []
        for row in events_result:
            event_data = dict(row._mapping)
            org_id = event_data.get("org_id")
            # Group organization details, including logo resource info
            event_data["organization"] = {
                "id": event_data.pop("org_id"),
                "account_id": event_data.pop("org_account_id"),
                "name": event_data.pop("org_name"),
                "description": event_data.pop("org_description"),
                "logo": (
                    {
                        "id": event_data.get("org_logo"),
                        "directory": event_data.get("logo_directory"),
                        "filename": event_data.get("logo_filename"),
                    }
                    if event_data.get("org_logo")
                    else None
                ),
            }
            event_data.pop("org_logo", None)
            event_data.pop("logo_directory", None)
            event_data.pop("logo_filename", None)
            event_data["image"] = (
                {
                    "id": event_data.get("image"),
                    "directory": event_data.get("image_directory"),
                    "filename": event_data.get("image_filename"),
                }
                if event_data.get("image")
                else None
            )
            event_data.pop("image_directory", None)
            event_data.pop("image_filename", None)
            event_data["address"] = {
                "id": event_data.get("address_id"),
                "country": event_data.get("address_country"),
                "province": event_data.get("address_province"),
                "city": event_data.get("address_city"),
                "barangay": event_data.get("address_barangay"),
                "house_building_number": event_data.get(
                    "address_house_building_number"
                ),
                "country_code": event_data.get("address_country_code"),
                "province_code": event_data.get("address_province_code"),
                "city_code": event_data.get("address_city_code"),
                "barangay_code": event_data.get("address_barangay_code"),
            }
            event_data.pop("address_country", None)
            event_data.pop("address_province", None)
            event_data.pop("address_city", None)
            event_data.pop("address_barangay", None)
            event_data.pop("address_house_building_number", None)
            event_data.pop("address_country_code", None)
            event_data.pop("address_province_code", None)
            event_data.pop("address_city_code", None)
            event_data.pop("address_barangay_code", None)

            # Membership check: Get authenticated user's membership status in this event's organization
            membership_status = None
            if user_id and org_id:
                membership_stmt = select(table["membership"].c.status).where(
                    (table["membership"].c.organization_id == org_id)
                    & (table["membership"].c.user_id == user_id)
                )
                membership_status = session.execute(membership_stmt).scalar()
            event_data["user_membership_status_with_organizer"] = membership_status

            # If authenticated user, fetch RSVP status for this event
            if account_id:
                rsvp_stmt = select(table["rsvp"].c.id, table["rsvp"].c.status).where(
                    (table["rsvp"].c.event_id == event_data["id"])
                    & (table["rsvp"].c.attendee == account_id)
                )
                rsvp_result = session.execute(rsvp_stmt).fetchone()
                if rsvp_result:
                    event_data["user_rsvp"] = {
                        "rsvp_id": rsvp_result.id,
                        "status": rsvp_result.status,
                    }
                else:
                    event_data["user_rsvp"] = None

            events.append(event_data)

        # For each event, get total comments count and top 3 latest comments (including organization details if commenter is org)
        for event in events:
            event_id = event["id"]
            
            # Get total comments count for this event
            total_comments_stmt = select(func.count()).select_from(table["comment"]).where(
                table["comment"].c.event_id == event_id
            )
            total_comments = session.execute(total_comments_stmt).scalar()
            event["total_comments"] = total_comments
            
            comment_profile_resource = table["resource"].alias(
                "comment_profile_resource"
            )
            comment_logo_resource = table["resource"].alias("comment_logo_resource")
            comments_stmt = (
                select(
                    table["comment"].c.id.label("comment_id"),
                    table["comment"].c.message,
                    table["comment"].c.created_date,
                    table["account"].c.id.label("account_id"),
                    table["account"].c.uuid,
                    table["account"].c.email,
                    table["role"].c.name.label("role_name"),
                    # User fields
                    table["user"].c.first_name.label("user_first_name"),
                    table["user"].c.last_name.label("user_last_name"),
                    table["user"].c.profile_picture.label("profile_picture_id"),
                    comment_profile_resource.c.directory.label(
                        "profile_picture_directory"
                    ),
                    comment_profile_resource.c.filename.label(
                        "profile_picture_filename"
                    ),
                    # Organization fields
                    table["organization"].c.name.label("organization_name"),
                    table["organization"].c.description.label(
                        "organization_description"
                    ),
                    table["organization"].c.logo.label("organization_logo_id"),
                    comment_logo_resource.c.directory.label(
                        "organization_logo_directory"
                    ),
                    comment_logo_resource.c.filename.label(
                        "organization_logo_filename"
                    ),
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
                        comment_profile_resource,
                        table["user"].c.profile_picture
                        == comment_profile_resource.c.id,
                    )
                    .outerjoin(
                        table["organization"],
                        table["organization"].c.account_id == table["account"].c.id,
                    )
                    .outerjoin(
                        comment_logo_resource,
                        table["organization"].c.logo == comment_logo_resource.c.id,
                    )
                )
                .where(table["comment"].c.event_id == event_id)
                .order_by(table["comment"].c.created_date.desc())
                .limit(3)
            )
            comments_result = session.execute(comments_stmt).fetchall()
            latest_comments = []
            for row in comments_result:
                data = row._mapping
                role_name = data.get("role_name")
                comment_obj = {
                    "comment_id": data["comment_id"],
                    "message": data["message"],
                    "created_date": data["created_date"],
                    "account": {
                        "id": data["account_id"],
                        "uuid": data["uuid"],
                        "email": data["email"],
                    },
                    "role": role_name,
                }
                if role_name == "organization":
                    comment_obj["organization"] = {
                        "name": data["organization_name"],
                        "description": data["organization_description"],
                        "logo": (
                            {
                                "id": data["organization_logo_id"],
                                "directory": data["organization_logo_directory"],
                                "filename": data["organization_logo_filename"],
                            }
                            if data["organization_logo_id"]
                            else None
                        ),
                    }
                else:
                    comment_obj["user"] = {
                        "first_name": data["user_first_name"],
                        "last_name": data["user_last_name"],
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
                latest_comments.append(comment_obj)
            event["latest_comments"] = latest_comments

        return {
            "random_events": events,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_events,
                "pages": (total_events + limit - 1) // limit,
            },
        }
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.get("/user/rsvped", tags=["Get User RSVPed Events By Month and Year"])
async def get_user_rsvped_events_by_month_year(
    account_uuid: str = Query(..., description="Account UUID of the user"),
    month: int = Query(..., ge=1, le=12, description="Month (1-12)"),
    year: int = Query(..., ge=1900, description="Year (e.g., 2024)"),
):
    session = db.session
    try:
        # Get account_id from uuid
        select_account = select(table["account"].c.id).where(
            table["account"].c.uuid == account_uuid
        )
        account_id = session.execute(select_account).scalar()
        if account_id is None:
            raise HTTPException(status_code=404, detail="Account not found")

        # Get user_id for membership check
        select_user = select(table["user"].c.id).where(
            table["user"].c.account_id == account_id
        )
        user_id = session.execute(select_user).scalar()

        # Helper for filtering by month/year
        def month_year_filter(col):
            return (
                func.extract("month", col) == month,
                func.extract("year", col) == year,
            )

        # Fetch events where user has RSVP, join address, organization, and resource tables
        # Create an alias for the resource table for organization logo
        logo_resource = table["resource"].alias("logo_resource")
        stmt = (
            select(
                table["event"].c.id.label("event_id"),
                table["event"].c.organization_id.label("event_organization_id"),
                table["event"].c.title,
                table["event"].c.event_date,
                table["event"].c.address_id,
                table["event"].c.description,
                table["event"].c.image,
                table["event"].c.created_date,
                table["event"].c.last_modified_date,
                table["rsvp"].c.status.label("rsvp_status"),
                table["address"].c.country.label("address_country"),
                table["address"].c.province.label("address_province"),
                table["address"].c.city.label("address_city"),
                table["address"].c.barangay.label("address_barangay"),
                table["address"].c.house_building_number.label(
                    "address_house_building_number"
                ),
                table["address"].c.country_code.label("address_country_code"),
                table["address"].c.province_code.label("address_province_code"),
                table["address"].c.city_code.label("address_city_code"),
                table["address"].c.barangay_code.label("address_barangay_code"),
                table["organization"].c.id.label("organization_id"),
                table["organization"].c.name.label("organization_name"),
                table["organization"].c.description.label("organization_description"),
                table["organization"].c.logo.label("organization_logo"),
                table["organization"].c.category.label("organization_category"),
                table["resource"].c.directory.label("image_directory"),
                table["resource"].c.filename.label("image_filename"),
                logo_resource.c.directory.label("logo_directory"),
                logo_resource.c.filename.label("logo_filename"),
            )
            .select_from(
                table["event"]
                .join(table["rsvp"], table["event"].c.id == table["rsvp"].c.event_id)
                .outerjoin(
                    table["address"],
                    table["event"].c.address_id == table["address"].c.id,
                )
                .outerjoin(
                    table["organization"],
                    table["event"].c.organization_id == table["organization"].c.id,
                )
                .outerjoin(
                    table["resource"],
                    table["event"].c.image == table["resource"].c.id,
                )
                .outerjoin(
                    logo_resource,
                    table["organization"].c.logo == logo_resource.c.id,
                )
            )
            .where(
                (table["rsvp"].c.attendee == account_id)
                & month_year_filter(table["event"].c.event_date)[0]
                & month_year_filter(table["event"].c.event_date)[1]
            )
            .order_by(table["event"].c.event_date.desc())
        )
        events_result = session.execute(stmt).fetchall()
        events = []
        for row in events_result:
            event_data = dict(row._mapping)
            event_data["address"] = {
                "id": event_data["address_id"],
                "country": event_data["address_country"],
                "province": event_data["address_province"],
                "city": event_data["address_city"],
                "barangay": event_data["address_barangay"],
                "house_building_number": event_data["address_house_building_number"],
                "country_code": event_data.get("address_country_code"),
                "province_code": event_data.get("address_province_code"),
                "city_code": event_data.get("address_city_code"),
                "barangay_code": event_data.get("address_barangay_code"),
            }
            event_data.pop("address_country", None)
            event_data.pop("address_province", None)
            event_data.pop("address_city", None)
            event_data.pop("address_barangay", None)
            event_data.pop("address_house_building_number", None)
            event_data.pop("address_country_code", None)
            event_data.pop("address_province_code", None)
            event_data.pop("address_city_code", None)
            event_data.pop("address_barangay_code", None)

            event_data["organization"] = {
                "id": event_data.pop("organization_id"),
                "name": event_data.pop("organization_name"),
                "description": event_data.pop("organization_description"),
                "logo": (
                    {
                        "id": event_data["organization_logo"],
                        "directory": event_data.get("logo_directory"),
                        "filename": event_data.get("logo_filename"),
                    }
                    if event_data.get("organization_logo")
                    else None
                ),
                "category": event_data.pop("organization_category"),
            }
            event_data.pop("organization_logo", None)
            event_data.pop("logo_directory", None)
            event_data.pop("logo_filename", None)

            event_data["image"] = (
                {
                    "id": event_data["image"],
                    "directory": event_data.get("image_directory"),
                    "filename": event_data.get("image_filename"),
                }
                if event_data.get("image")
                else None
            )
            event_data.pop("image_directory", None)
            event_data.pop("image_filename", None)

            # Membership status for this event's organization
            membership_status = None
            org_id = event_data.get("event_organization_id")
            if user_id and org_id:
                membership_stmt = select(table["membership"].c.status).where(
                    (table["membership"].c.organization_id == org_id)
                    & (table["membership"].c.user_id == user_id)
                )
                membership_status = session.execute(membership_stmt).scalar()
            event_data["user_membership_status_with_organizer"] = membership_status

            # Add top 3 latest comments and total count of comments for this event
            event_id = event_data["event_id"]
            comment_profile_resource = table["resource"].alias(
                "comment_profile_resource"
            )
            comment_logo_resource = table["resource"].alias("comment_logo_resource")

            # Total comments count
            comment_count_stmt = select(func.count(table["comment"].c.id)).where(
                table["comment"].c.event_id == event_id
            )
            total_comments = session.execute(comment_count_stmt).scalar() or 0
            event_data["total_comments"] = total_comments

            # Top 3 latest comments
            comments_stmt = (
                select(
                    table["comment"].c.id.label("comment_id"),
                    table["comment"].c.message,
                    table["comment"].c.created_date,
                    table["account"].c.id.label("account_id"),
                    table["account"].c.uuid,
                    table["account"].c.email,
                    table["role"].c.name.label("role_name"),
                    # User fields
                    table["user"].c.first_name.label("user_first_name"),
                    table["user"].c.last_name.label("user_last_name"),
                    table["user"].c.profile_picture.label("profile_picture_id"),
                    comment_profile_resource.c.directory.label(
                        "profile_picture_directory"
                    ),
                    comment_profile_resource.c.filename.label(
                        "profile_picture_filename"
                    ),
                    # Organization fields
                    table["organization"].c.name.label("organization_name"),
                    table["organization"].c.description.label(
                        "organization_description"
                    ),
                    table["organization"].c.logo.label("organization_logo_id"),
                    comment_logo_resource.c.directory.label(
                        "organization_logo_directory"
                    ),
                    comment_logo_resource.c.filename.label(
                        "organization_logo_filename"
                    ),
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
                        comment_profile_resource,
                        table["user"].c.profile_picture
                        == comment_profile_resource.c.id,
                    )
                    .outerjoin(
                        table["organization"],
                        table["organization"].c.account_id == table["account"].c.id,
                    )
                    .outerjoin(
                        comment_logo_resource,
                        table["organization"].c.logo == comment_logo_resource.c.id,
                    )
                )
                .where(table["comment"].c.event_id == event_id)
                .order_by(table["comment"].c.created_date.desc())
                .limit(3)
            )
            comments_result = session.execute(comments_stmt).fetchall()
            latest_comments = []
            for row_comment in comments_result:
                data = row_comment._mapping
                role_name = data.get("role_name")
                comment_obj = {
                    "comment_id": data["comment_id"],
                    "message": data["message"],
                    "created_date": data["created_date"],
                    "account": {
                        "id": data["account_id"],
                        "uuid": data["uuid"],
                        "email": data["email"],
                    },
                    "role": role_name,
                }
                if role_name == "organization":
                    comment_obj["organization"] = {
                        "name": data["organization_name"],
                        "description": data["organization_description"],
                        "logo": (
                            {
                                "id": data["organization_logo_id"],
                                "directory": data["organization_logo_directory"],
                                "filename": data["organization_logo_filename"],
                            }
                            if data["organization_logo_id"]
                            else None
                        ),
                    }
                else:
                    comment_obj["user"] = {
                        "first_name": data["user_first_name"],
                        "last_name": data["user_last_name"],
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
                latest_comments.append(comment_obj)
            event_data["latest_comments"] = latest_comments
            event_data["total_comments"] = total_comments

            events.append(event_data)

        return {"rsvped_events": events}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/user/events_with_comments", tags=["Get User Events With Comments"])
async def get_user_events_with_comments(
    account_uuid: str = Query(..., description="Account UUID of the user"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Events per page (max 100)"),
):
    session = db.session
    try:
        offset = (page - 1) * limit

        # Get account_id from uuid
        select_account = select(table["account"].c.id).where(
            table["account"].c.uuid == account_uuid
        )
        account_id = session.execute(select_account).scalar()
        if account_id is None:
            raise HTTPException(status_code=404, detail="Account not found")

        # Create an alias for the resource table for organization logo
        logo_resource = table["resource"].alias("logo_resource")

        # Get total count for pagination
        count_stmt = (
            select(func.count())
            .select_from(
                table["event"].join(
                    table["rsvp"], table["event"].c.id == table["rsvp"].c.event_id
                )
            )
            .where(table["rsvp"].c.attendee == account_id)
        )
        total_events = session.execute(count_stmt).scalar()

        # Fetch paginated events linked to user (via RSVP), join address, resource, organization, logo_resource
        events_stmt = (
            select(
                table["event"],
                table["rsvp"].c.status.label("rsvp_status"),
                table["address"].c.country.label("address_country"),
                table["address"].c.province.label("address_province"),
                table["address"].c.city.label("address_city"),
                table["address"].c.barangay.label("address_barangay"),
                table["address"].c.house_building_number.label(
                    "address_house_building_number"
                ),
                table["address"].c.country_code.label("address_country_code"),
                table["address"].c.province_code.label("address_province_code"),
                table["address"].c.city_code.label("address_city_code"),
                table["address"].c.barangay_code.label("address_barangay_code"),
                table["resource"].c.directory.label("image_directory"),
                table["resource"].c.filename.label("image_filename"),
                table["organization"].c.id.label("org_id"),
                table["organization"].c.name.label("organization_name"),
                table["organization"].c.description.label("organization_description"),
                table["organization"].c.logo.label("organization_logo"),
                table["organization"].c.category.label("organization_category"),
                logo_resource.c.directory.label("logo_directory"),
                logo_resource.c.filename.label("logo_filename"),
            )
            .select_from(
                table["event"]
                .join(table["rsvp"], table["event"].c.id == table["rsvp"].c.event_id)
                .outerjoin(
                    table["address"],
                    table["event"].c.address_id == table["address"].c.id,
                )
                .outerjoin(
                    table["resource"], table["event"].c.image == table["resource"].c.id
                )
                .outerjoin(
                    table["organization"],
                    table["event"].c.organization_id == table["organization"].c.id,
                )
                .outerjoin(
                    logo_resource, table["organization"].c.logo == logo_resource.c.id
                )
            )
            .where(table["rsvp"].c.attendee == account_id)
            .order_by(table["event"].c.event_date.desc())
            .limit(limit)
            .offset(offset)
        )
        events_result = session.execute(events_stmt).fetchall()
        events = []
        for row in events_result:
            event = dict(row._mapping)
            event["address"] = {
                "id": event.get("address_id"),
                "country": event.get("address_country"),
                "province": event.get("address_province"),
                "city": event.get("address_city"),
                "barangay": event.get("address_barangay"),
                "house_building_number": event.get("address_house_building_number"),
                "country_code": event.get("address_country_code"),
                "province_code": event.get("address_province_code"),
                "city_code": event.get("address_city_code"),
                "barangay_code": event.get("address_barangay_code"),
            }
            event.pop("address_country", None)
            event.pop("address_province", None)
            event.pop("address_city", None)
            event.pop("address_barangay", None)
            event.pop("address_house_building_number", None)
            event.pop("address_country_code", None)
            event.pop("address_province_code", None)
            event.pop("address_city_code", None)
            event.pop("address_barangay_code", None)

            event["image"] = (
                {
                    "id": event.get("image"),
                    "directory": event.get("image_directory"),
                    "filename": event.get("image_filename"),
                }
                if event.get("image")
                else None
            )
            event.pop("image_directory", None)
            event.pop("image_filename", None)

            event["organization"] = {
                "id": event.pop("org_id"),
                "name": event.pop("organization_name"),
                "description": event.pop("organization_description"),
                "logo": (
                    {
                        "id": event.get("organization_logo"),
                        "directory": event.get("logo_directory"),
                        "filename": event.get("logo_filename"),
                    }
                    if event.get("organization_logo")
                    else None
                ),
                "category": event.pop("organization_category"),
            }
            event.pop("organization_logo", None)
            event.pop("logo_directory", None)
            event.pop("logo_filename", None)

            # Attach RSVP status to the event
            event["rsvp_status"] = event.get("rsvp_status", "none")

            # For each event, fetch latest 3 comments (with correct commenter details)
            event_id = event["id"]
            comment_profile_resource = table["resource"].alias(
                "comment_profile_resource"
            )
            comment_logo_resource = table["resource"].alias("comment_logo_resource")
            comments_stmt = (
                select(
                    table["comment"].c.id.label("comment_id"),
                    table["comment"].c.message,
                    table["comment"].c.created_date,
                    table["account"].c.id.label("account_id"),
                    table["account"].c.uuid,
                    table["account"].c.email,
                    table["role"].c.name.label("role_name"),
                    # User fields
                    table["user"].c.first_name.label("user_first_name"),
                    table["user"].c.last_name.label("user_last_name"),
                    table["user"].c.profile_picture.label("profile_picture_id"),
                    comment_profile_resource.c.directory.label(
                        "profile_picture_directory"
                    ),
                    comment_profile_resource.c.filename.label(
                        "profile_picture_filename"
                    ),
                    # Organization fields
                    table["organization"].c.name.label("organization_name"),
                    table["organization"].c.description.label(
                        "organization_description"
                    ),
                    table["organization"].c.logo.label("organization_logo_id"),
                    comment_logo_resource.c.directory.label(
                        "organization_logo_directory"
                    ),
                    comment_logo_resource.c.filename.label(
                        "organization_logo_filename"
                    ),
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
                        comment_profile_resource,
                        table["user"].c.profile_picture
                        == comment_profile_resource.c.id,
                    )
                    .outerjoin(
                        table["organization"],
                        table["organization"].c.account_id == table["account"].c.id,
                    )
                    .outerjoin(
                        comment_logo_resource,
                        table["organization"].c.logo == comment_logo_resource.c.id,
                    )
                )
                .where(table["comment"].c.event_id == event_id)
                .order_by(table["comment"].c.created_date.desc())
                .limit(3)
            )
            comments_result = session.execute(comments_stmt).fetchall()
            latest_comments = []
            for row in comments_result:
                data = row._mapping
                role_name = data.get("role_name")
                comment_obj = {
                    "comment_id": data["comment_id"],
                    "message": data["message"],
                    "created_date": data["created_date"],
                    "account": {
                        "id": data["account_id"],
                        "uuid": data["uuid"],
                        "email": data["email"],
                    },
                    "role": role_name,
                }
                if role_name == "organization":
                    comment_obj["organization"] = {
                        "name": data["organization_name"],
                        "description": data["organization_description"],
                        "logo": (
                            {
                                "id": data["organization_logo_id"],
                                "directory": data["organization_logo_directory"],
                                "filename": data["organization_logo_filename"],
                            }
                            if data["organization_logo_id"]
                            else None
                        ),
                    }
                else:
                    comment_obj["user"] = {
                        "first_name": data["user_first_name"],
                        "last_name": data["user_last_name"],
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
                latest_comments.append(comment_obj)
            event["latest_comments"] = latest_comments

            events.append(event)

        return {
            "events": events,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_events,
                "pages": (total_events + limit - 1) // limit,
            },
        }
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/user/events_by_rsvp_status_with_comments",
    tags=["Get User Events By RSVP Status With Comments"],
)
async def get_user_events_by_rsvp_status_with_comments(
    account_uuid: str = Query(..., description="Account UUID of the user"),
    rsvp_status: str = Query(
        ..., description="RSVP status (e.g., joined, pending, declined)"
    ),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Events per page (max 100)"),
):
    session = db.session
    try:
        offset = (page - 1) * limit

        # Get account_id from uuid
        select_account = select(table["account"].c.id).where(
            table["account"].c.uuid == account_uuid
        )
        account_id = session.execute(select_account).scalar()
        if account_id is None:
            raise HTTPException(status_code=404, detail="Account not found")

        # Create an alias for the resource table for organization logo
        logo_resource = table["resource"].alias("logo_resource")

        # Get total count for pagination
        count_stmt = (
            select(func.count())
            .select_from(
                table["event"].join(
                    table["rsvp"], table["event"].c.id == table["rsvp"].c.event_id
                )
            )
            .where(
                (table["rsvp"].c.attendee == account_id)
                & (table["rsvp"].c.status == rsvp_status)
                & (table["event"].c.event_date >= func.current_date())
            )
        )
        total_events = session.execute(count_stmt).scalar()

        # Fetch paginated events with joins
        events_stmt = (
            select(
                table["event"],
                table["address"].c.country.label("address_country"),
                table["address"].c.province.label("address_province"),
                table["address"].c.city.label("address_city"),
                table["address"].c.barangay.label("address_barangay"),
                table["address"].c.house_building_number.label(
                    "address_house_building_number"
                ),
                table["address"].c.country_code.label("address_country_code"),
                table["address"].c.province_code.label("address_province_code"),
                table["address"].c.city_code.label("address_city_code"),
                table["address"].c.barangay_code.label("address_barangay_code"),
                table["resource"].c.directory.label("image_directory"),
                table["resource"].c.filename.label("image_filename"),
                table["organization"].c.id.label("org_id"),
                table["organization"].c.name.label("organization_name"),
                table["organization"].c.description.label("organization_description"),
                table["organization"].c.logo.label("organization_logo"),
                table["organization"].c.category.label("organization_category"),
                logo_resource.c.directory.label("logo_directory"),
                logo_resource.c.filename.label("logo_filename"),
            )
            .select_from(
                table["event"]
                .join(table["rsvp"], table["event"].c.id == table["rsvp"].c.event_id)
                .outerjoin(
                    table["address"],
                    table["event"].c.address_id == table["address"].c.id,
                )
                .outerjoin(
                    table["resource"], table["event"].c.image == table["resource"].c.id
                )
                .outerjoin(
                    table["organization"],
                    table["event"].c.organization_id == table["organization"].c.id,
                )
                .outerjoin(
                    logo_resource,
                    table["organization"].c.logo == logo_resource.c.id,
                )
            )
            .where(
                (table["rsvp"].c.attendee == account_id)
                & (table["rsvp"].c.status == rsvp_status)
                & (table["event"].c.event_date >= func.current_date())
            )
            .order_by(table["event"].c.event_date.asc())
            .limit(limit)
            .offset(offset)
        )
        events_result = session.execute(events_stmt).fetchall()
        events = []
        for row in events_result:
            event = dict(row._mapping)
            event["address"] = {
                "id": event.get("address_id"),
                "country": event.get("address_country"),
                "province": event.get("address_province"),
                "city": event.get("address_city"),
                "barangay": event.get("address_barangay"),
                "house_building_number": event.get("address_house_building_number"),
                "country_code": event.get("address_country_code"),
                "province_code": event.get("address_province_code"),
                "city_code": event.get("address_city_code"),
                "barangay_code": event.get("address_barangay_code"),
            }
            event.pop("address_country", None)
            event.pop("address_province", None)
            event.pop("address_city", None)
            event.pop("address_barangay", None)
            event.pop("address_house_building_number", None)
            event.pop("address_country_code", None)
            event.pop("address_province_code", None)
            event.pop("address_city_code", None)
            event.pop("address_barangay_code", None)

            event["image"] = (
                {
                    "id": event.get("image"),
                    "directory": event.get("image_directory"),
                    "filename": event.get("image_filename"),
                }
                if event.get("image")
                else None
            )
            event.pop("image_directory", None)
            event.pop("image_filename", None)

            event["organization"] = {
                "id": event.pop("org_id"),
                "name": event.pop("organization_name"),
                "description": event.pop("organization_description"),
                "logo": (
                    {
                        "id": event.get("organization_logo"),
                        "directory": event.get("logo_directory"),
                        "filename": event.get("logo_filename"),
                    }
                    if event.get("organization_logo")
                    else None
                ),
                "category": event.pop("organization_category"),
            }
            event.pop("organization_logo", None)
            event.pop("logo_directory", None)
            event.pop("logo_filename", None)

            # Get user_id for membership check
            select_user = select(table["user"].c.id).where(
                table["user"].c.account_id == account_id
            )
            user_id = session.execute(select_user).scalar()

            # Add user_membership_status_with_organizer
            membership_status = None
            if user_id and event["organization"]["id"]:
                membership_stmt = select(table["membership"].c.status).where(
                    (
                        table["membership"].c.organization_id
                        == event["organization"]["id"]
                    )
                    & (table["membership"].c.user_id == user_id)
                )
                membership_status = session.execute(membership_stmt).scalar()
            event["user_membership_status_with_organizer"] = membership_status

            # Add user_rsvp (we already know the RSVP status from the query filter)
            rsvp_stmt = select(table["rsvp"].c.id).where(
                (table["rsvp"].c.event_id == event["id"])
                & (table["rsvp"].c.attendee == account_id)
            )
            rsvp_id = session.execute(rsvp_stmt).scalar()
            if rsvp_id:
                event["user_rsvp"] = {"rsvp_id": rsvp_id, "status": rsvp_status}
            else:
                event["user_rsvp"] = None

            # For each event, fetch latest 3 comments (with correct commenter details)
            event_id = event["id"]

            comment_count_stmt = select(func.count(table["comment"].c.id)).where(
                table["comment"].c.event_id == event_id
            )
            total_comments = session.execute(comment_count_stmt).scalar() or 0

            comment_profile_resource = table["resource"].alias(
                "comment_profile_resource"
            )
            comment_logo_resource = table["resource"].alias("comment_logo_resource")
            comments_stmt = (
                select(
                    table["comment"].c.id.label("comment_id"),
                    table["comment"].c.message,
                    table["comment"].c.created_date,
                    table["account"].c.id.label("account_id"),
                    table["account"].c.uuid,
                    table["account"].c.email,
                    table["role"].c.name.label("role_name"),
                    # User fields
                    table["user"].c.first_name.label("user_first_name"),
                    table["user"].c.last_name.label("user_last_name"),
                    table["user"].c.profile_picture.label("profile_picture_id"),
                    comment_profile_resource.c.directory.label(
                        "profile_picture_directory"
                    ),
                    comment_profile_resource.c.filename.label(
                        "profile_picture_filename"
                    ),
                    # Organization fields
                    table["organization"].c.name.label("organization_name"),
                    table["organization"].c.description.label(
                        "organization_description"
                    ),
                    table["organization"].c.logo.label("organization_logo_id"),
                    comment_logo_resource.c.directory.label(
                        "organization_logo_directory"
                    ),
                    comment_logo_resource.c.filename.label(
                        "organization_logo_filename"
                    ),
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
                        comment_profile_resource,
                        table["user"].c.profile_picture
                        == comment_profile_resource.c.id,
                    )
                    .outerjoin(
                        table["organization"],
                        table["organization"].c.account_id == table["account"].c.id,
                    )
                    .outerjoin(
                        comment_logo_resource,
                        table["organization"].c.logo == comment_logo_resource.c.id,
                    )
                )
                .where(table["comment"].c.event_id == event_id)
                .order_by(table["comment"].c.created_date.desc())
                .limit(3)
            )
            comments_result = session.execute(comments_stmt).fetchall()
            latest_comments = []
            for row in comments_result:
                data = row._mapping
                role_name = data.get("role_name")
                comment_obj = {
                    "comment_id": data["comment_id"],
                    "message": data["message"],
                    "created_date": data["created_date"],
                    "account": {
                        "id": data["account_id"],
                        "uuid": data["uuid"],
                        "email": data["email"],
                    },
                    "role": role_name,
                }
                if role_name == "organization":
                    comment_obj["organization"] = {
                        "name": data["organization_name"],
                        "description": data["organization_description"],
                        "logo": (
                            {
                                "id": data["organization_logo_id"],
                                "directory": data["organization_logo_directory"],
                                "filename": data["organization_logo_filename"],
                            }
                            if data["organization_logo_id"]
                            else None
                        ),
                    }
                else:
                    comment_obj["user"] = {
                        "first_name": data["user_first_name"],
                        "last_name": data["user_last_name"],
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
                latest_comments.append(comment_obj)
            event["latest_comments"] = latest_comments
            event["total_comments"] = total_comments
            events.append(event)

        return {
            "events": events,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_events,
                "pages": (total_events + limit - 1) // limit,
            },
        }
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{event_id}", tags=["Get Event By ID"])
async def get_event_by_id(
    event_id: int = Path(..., description="ID of the event to retrieve")
):
    session = db.session
    try:
        # Create an alias for the resource table for organization logo
        logo_resource = table["resource"].alias("logo_resource")

        stmt = (
            select(
                table["event"],
                table["organization"].c.id.label("org_id"),
                table["organization"].c.name.label("org_name"),
                table["organization"].c.description.label("org_description"),
                table["organization"].c.logo.label("org_logo"),
                logo_resource.c.directory.label("logo_directory"),
                logo_resource.c.filename.label("logo_filename"),
                table["resource"].c.directory.label("image_directory"),
                table["resource"].c.filename.label("image_filename"),
                table["address"].c.country.label("address_country"),
                table["address"].c.province.label("address_province"),
                table["address"].c.city.label("address_city"),
                table["address"].c.barangay.label("address_barangay"),
                table["address"].c.house_building_number.label(
                    "address_house_building_number"
                ),
                table["address"].c.country_code.label("address_country_code"),
                table["address"].c.province_code.label("address_province_code"),
                table["address"].c.city_code.label("address_city_code"),
                table["address"].c.barangay_code.label("address_barangay_code"),
            )
            .select_from(
                table["event"]
                .join(
                    table["organization"],
                    table["event"].c.organization_id == table["organization"].c.id,
                )
                .outerjoin(
                    table["resource"],
                    table["event"].c.image == table["resource"].c.id,
                )
                .outerjoin(
                    logo_resource,
                    table["organization"].c.logo == logo_resource.c.id,
                )
                .outerjoin(
                    table["address"],
                    table["event"].c.address_id == table["address"].c.id,
                )
            )
            .where(table["event"].c.id == event_id)
        )
        result = session.execute(stmt).fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Event not found")

        event_data = dict(result._mapping)
        event_data["organization"] = {
            "id": event_data.pop("org_id"),
            "name": event_data.pop("org_name"),
            "description": event_data.pop("org_description"),
            "logo": (
                {
                    "id": event_data.get("org_logo"),
                    "directory": event_data.get("logo_directory"),
                    "filename": event_data.get("logo_filename"),
                }
                if event_data.get("org_logo")
                else None
            ),
        }
        event_data.pop("org_logo", None)
        event_data.pop("logo_directory", None)
        event_data.pop("logo_filename", None)
        event_data["image"] = (
            {
                "id": event_data.get("image"),
                "directory": event_data.get("image_directory"),
                "filename": event_data.get("image_filename"),
            }
            if event_data.get("image")
            else None
        )
        event_data.pop("image_directory", None)
        event_data.pop("image_filename", None)
        event_data["address"] = {
            "id": event_data.get("address_id"),
            "country": event_data.get("address_country"),
            "province": event_data.get("address_province"),
            "city": event_data.get("address_city"),
            "barangay": event_data.get("address_barangay"),
            "house_building_number": event_data.get("address_house_building_number"),
            "country_code": event_data.get("address_country_code"),
            "province_code": event_data.get("address_province_code"),
            "city_code": event_data.get("address_city_code"),
            "barangay_code": event_data.get("address_barangay_code"),
        }
        event_data.pop("address_country", None)
        event_data.pop("address_province", None)
        event_data.pop("address_city", None)
        event_data.pop("address_barangay", None)
        event_data.pop("address_house_building_number", None)
        event_data.pop("address_country_code", None)
        event_data.pop("address_province_code", None)
        event_data.pop("address_city_code", None)
        event_data.pop("address_barangay_code", None)

        return event_data
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{event_id}/with_comments", tags=["Get Event By ID With Comments"])
async def get_event_by_id_with_comments(
    event_id: int = Path(..., description="ID of the event to retrieve"),
    account_uuid: str = Query(..., description="Account UUID of the user"),
):
    session = db.session
    try:
        # Get account_id from uuid if provided
        account_id = None
        user_id = None
        if account_uuid:
            select_account = select(table["account"].c.id).where(
                table["account"].c.uuid == account_uuid
            )
            account_id = session.execute(select_account).scalar()
            if account_id:
                # Get user_id for membership check
                select_user = select(table["user"].c.id).where(
                    table["user"].c.account_id == account_id
                )
                user_id = session.execute(select_user).scalar()

        # Create an alias for the resource table for organization logo
        logo_resource = table["resource"].alias("logo_resource")

        stmt = (
            select(
                table["event"],
                table["organization"].c.id.label("org_id"),
                table["organization"].c.name.label("org_name"),
                table["organization"].c.description.label("org_description"),
                table["organization"].c.logo.label("org_logo"),
                logo_resource.c.directory.label("logo_directory"),
                logo_resource.c.filename.label("logo_filename"),
                table["resource"].c.directory.label("image_directory"),
                table["resource"].c.filename.label("image_filename"),
                table["address"].c.country.label("address_country"),
                table["address"].c.province.label("address_province"),
                table["address"].c.city.label("address_city"),
                table["address"].c.barangay.label("address_barangay"),
                table["address"].c.house_building_number.label(
                    "address_house_building_number"
                ),
                table["address"].c.country_code.label("address_country_code"),
                table["address"].c.province_code.label("address_province_code"),
                table["address"].c.city_code.label("address_city_code"),
                table["address"].c.barangay_code.label("address_barangay_code"),
            )
            .select_from(
                table["event"]
                .join(
                    table["organization"],
                    table["event"].c.organization_id == table["organization"].c.id,
                )
                .outerjoin(
                    table["resource"],
                    table["event"].c.image == table["resource"].c.id,
                )
                .outerjoin(
                    logo_resource,
                    table["organization"].c.logo == logo_resource.c.id,
                )
                .outerjoin(
                    table["address"],
                    table["event"].c.address_id == table["address"].c.id,
                )
            )
            .where(table["event"].c.id == event_id)
        )
        result = session.execute(stmt).fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Event not found")

        event_data = dict(result._mapping)
        event_data["organization"] = {
            "id": event_data.pop("org_id"),
            "name": event_data.pop("org_name"),
            "description": event_data.pop("org_description"),
            "logo": (
                {
                    "id": event_data.get("org_logo"),
                    "directory": event_data.get("logo_directory"),
                    "filename": event_data.get("logo_filename"),
                }
                if event_data.get("org_logo")
                else None
            ),
        }
        event_data.pop("org_logo", None)
        event_data.pop("logo_directory", None)
        event_data.pop("logo_filename", None)
        event_data["image"] = (
            {
                "id": event_data.get("image"),
                "directory": event_data.get("image_directory"),
                "filename": event_data.get("image_filename"),
            }
            if event_data.get("image")
            else None
        )
        event_data.pop("image_directory", None)
        event_data.pop("image_filename", None)
        event_data["address"] = {
            "id": event_data.get("address_id"),
            "country": event_data.get("address_country"),
            "province": event_data.get("address_province"),
            "city": event_data.get("address_city"),
            "barangay": event_data.get("address_barangay"),
            "house_building_number": event_data.get("address_house_building_number"),
            "country_code": event_data.get("address_country_code"),
            "province_code": event_data.get("address_province_code"),
            "city_code": event_data.get("address_city_code"),
            "barangay_code": event_data.get("address_barangay_code"),
        }
        event_data.pop("address_country", None)
        event_data.pop("address_province", None)
        event_data.pop("address_city", None)
        event_data.pop("address_barangay", None)
        event_data.pop("address_house_building_number", None)
        event_data.pop("address_country_code", None)
        event_data.pop("address_province_code", None)
        event_data.pop("address_city_code", None)
        event_data.pop("address_barangay_code", None)
        
        # Add user_membership_status_with_organizer if user_id is available
        membership_status = None
        if user_id and event_data["organization"]["id"]:
            membership_stmt = select(table["membership"].c.status).where(
                (
                    table["membership"].c.organization_id
                    == event_data["organization"]["id"]
                )
                & (table["membership"].c.user_id == user_id)
            )
            membership_status = session.execute(membership_stmt).scalar()
        event_data["user_membership_status_with_organizer"] = membership_status
        
        # Add user_rsvp if account_id is available
        if account_id:
            rsvp_stmt = select(table["rsvp"].c.id, table["rsvp"].c.status).where(
                (table["rsvp"].c.event_id == event_id)
                & (table["rsvp"].c.attendee == account_id)
            )
            rsvp_result = session.execute(rsvp_stmt).fetchone()
            if rsvp_result:
                event_data["user_rsvp"] = {
                    "rsvp_id": rsvp_result.id,
                    "status": rsvp_result.status,
                }
            else:
                event_data["user_rsvp"] = None
        else:
            event_data["user_rsvp"] = None
            
        # Get total comments count for this event
        comment_count_stmt = select(func.count(table["comment"].c.id)).where(
            table["comment"].c.event_id == event_id
        )
        total_comments = session.execute(comment_count_stmt).scalar() or 0
        event_data["total_comments"] = total_comments
        
        # Fetch top 3 latest comments with commenter details
        comment_profile_resource = table["resource"].alias("comment_profile_resource")
        comment_logo_resource = table["resource"].alias("comment_logo_resource")
        comments_stmt = (
            select(
                table["comment"].c.id.label("comment_id"),
                table["comment"].c.message,
                table["comment"].c.created_date,
                table["account"].c.id.label("account_id"),
                table["account"].c.uuid,
                table["account"].c.email,
                table["role"].c.name.label("role_name"),
                # User fields
                table["user"].c.first_name.label("user_first_name"),
                table["user"].c.last_name.label("user_last_name"),
                table["user"].c.profile_picture.label("profile_picture_id"),
                comment_profile_resource.c.directory.label("profile_picture_directory"),
                comment_profile_resource.c.filename.label("profile_picture_filename"),
                # Organization fields
                table["organization"].c.name.label("organization_name"),
                table["organization"].c.description.label("organization_description"),
                table["organization"].c.logo.label("organization_logo_id"),
                comment_logo_resource.c.directory.label("organization_logo_directory"),
                comment_logo_resource.c.filename.label("organization_logo_filename"),
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
                    comment_profile_resource,
                    table["user"].c.profile_picture == comment_profile_resource.c.id,
                )
                .outerjoin(
                    table["organization"],
                    table["organization"].c.account_id == table["account"].c.id,
                )
                .outerjoin(
                    comment_logo_resource,
                    table["organization"].c.logo == comment_logo_resource.c.id,
                )
            )
            .where(table["comment"].c.event_id == event_id)
            .order_by(table["comment"].c.created_date.desc())
            .limit(3)
        )
        comments_result = session.execute(comments_stmt).fetchall()
        latest_comments = []
        for row in comments_result:
            data = row._mapping
            role_name = data.get("role_name")
            comment_obj = {
                "comment_id": data["comment_id"],
                "message": data["message"],
                "created_date": data["created_date"],
                "account": {
                    "id": data["account_id"],
                    "uuid": data["uuid"],
                    "email": data["email"],
                },
                "role": role_name,
            }
            if role_name == "organization":
                comment_obj["organization"] = {
                    "name": data["organization_name"],
                    "description": data["organization_description"],
                    "logo": (
                        {
                            "id": data["organization_logo_id"],
                            "directory": data["organization_logo_directory"],
                            "filename": data["organization_logo_filename"],
                        }
                        if data["organization_logo_id"]
                        else None
                    ),
                }
            else:
                comment_obj["user"] = {
                    "first_name": data["user_first_name"],
                    "last_name": data["user_last_name"],
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
            latest_comments.append(comment_obj)
        event_data["latest_comments"] = latest_comments

        return event_data
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/user/past_events_with_comments", tags=["Get User Past Events With Comments"]
)
async def get_user_past_events_with_comments(
    account_uuid: str = Query(..., description="Account UUID of the user"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(10, ge=1, le=100, description="Events per page (max 100)"),
):
    session = db.session
    try:
        offset = (page - 1) * limit

        select_account = select(table["account"].c.id).where(
            table["account"].c.uuid == account_uuid
        )
        account_id = session.execute(select_account).scalar()
        if account_id is None:
            raise HTTPException(status_code=404, detail="Account not found")

        logo_resource = table["resource"].alias("logo_resource")

        count_stmt = (
            select(func.count())
            .select_from(
                table["event"].join(
                    table["rsvp"], table["event"].c.id == table["rsvp"].c.event_id
                )
            )
            .where(
                (table["rsvp"].c.attendee == account_id)
                & (table["event"].c.event_date < func.current_date())
            )
        )
        total_events = session.execute(count_stmt).scalar()

        events_stmt = (
            select(
                table["event"],
                table["rsvp"].c.status.label("rsvp_status"),
                table["address"].c.country.label("address_country"),
                table["address"].c.province.label("address_province"),
                table["address"].c.city.label("address_city"),
                table["address"].c.barangay.label("address_barangay"),
                table["address"].c.house_building_number.label(
                    "address_house_building_number"
                ),
                table["address"].c.country_code.label("address_country_code"),
                table["address"].c.province_code.label("address_province_code"),
                table["address"].c.city_code.label("address_city_code"),
                table["address"].c.barangay_code.label("address_barangay_code"),
                table["resource"].c.directory.label("image_directory"),
                table["resource"].c.filename.label("image_filename"),
                table["organization"].c.id.label("org_id"),
                table["organization"].c.name.label("organization_name"),
                table["organization"].c.description.label("organization_description"),
                table["organization"].c.logo.label("organization_logo"),
                table["organization"].c.category.label("organization_category"),
                logo_resource.c.directory.label("logo_directory"),
                logo_resource.c.filename.label("logo_filename"),
            )
            .select_from(
                table["event"]
                .join(table["rsvp"], table["event"].c.id == table["rsvp"].c.event_id)
                .outerjoin(
                    table["address"],
                    table["event"].c.address_id == table["address"].c.id,
                )
                .outerjoin(
                    table["resource"], table["event"].c.image == table["resource"].c.id
                )
                .outerjoin(
                    table["organization"],
                    table["event"].c.organization_id == table["organization"].c.id,
                )
                .outerjoin(
                    logo_resource, table["organization"].c.logo == logo_resource.c.id
                )
            )
            .where(
                (table["rsvp"].c.attendee == account_id)
                & (table["event"].c.event_date < func.current_date())
            )
            .order_by(table["event"].c.event_date.desc())
            .limit(limit)
            .offset(offset)
        )
        events_result = session.execute(events_stmt).fetchall()
        events = []
        for row in events_result:
            event = dict(row._mapping)
            event["address"] = {
                "id": event.get("address_id"),
                "country": event.get("address_country"),
                "province": event.get("address_province"),
                "city": event.get("address_city"),
                "barangay": event.get("address_barangay"),
                "house_building_number": event.get("address_house_building_number"),
                "country_code": event.get("address_country_code"),
                "province_code": event.get("address_province_code"),
                "city_code": event.get("address_city_code"),
                "barangay_code": event.get("address_barangay_code"),
            }
            event.pop("address_country", None)
            event.pop("address_province", None)
            event.pop("address_city", None)
            event.pop("address_barangay", None)
            event.pop("address_house_building_number", None)
            event.pop("address_country_code", None)
            event.pop("address_province_code", None)
            event.pop("address_city_code", None)
            event.pop("address_barangay_code", None)

            event["image"] = (
                {
                    "id": event.get("image"),
                    "directory": event.get("image_directory"),
                    "filename": event.get("image_filename"),
                }
                if event.get("image")
                else None
            )
            event.pop("image_directory", None)
            event.pop("image_filename", None)

            event["organization"] = {
                "id": event.pop("org_id"),
                "name": event.pop("organization_name"),
                "description": event.pop("organization_description"),
                "logo": (
                    {
                        "id": event.get("organization_logo"),
                        "directory": event.get("logo_directory"),
                        "filename": event.get("logo_filename"),
                    }
                    if event.get("organization_logo")
                    else None
                ),
                "category": event.pop("organization_category"),
            }
            event.pop("organization_logo", None)
            event.pop("logo_directory", None)
            event.pop("logo_filename", None)

            # Get user_id for membership check
            select_user = select(table["user"].c.id).where(
                table["user"].c.account_id == account_id
            )
            user_id = session.execute(select_user).scalar()

            # Add user_membership_status_with_organizer
            membership_status = None
            if user_id and event["organization"]["id"]:
                membership_stmt = select(table["membership"].c.status).where(
                    (
                        table["membership"].c.organization_id
                        == event["organization"]["id"]
                    )
                    & (table["membership"].c.user_id == user_id)
                )
                membership_status = session.execute(membership_stmt).scalar()
            event["user_membership_status_with_organizer"] = membership_status

            event_id = event["id"]

             # Get total comment count for this event
            comment_count_stmt = select(func.count(table["comment"].c.id)).where(
                table["comment"].c.event_id == event_id
            )
            total_comments = session.execute(comment_count_stmt).scalar() or 0
            event["total_comments"] = total_comments
            
            comment_profile_resource = table["resource"].alias(
                "comment_profile_resource"
            )
            comment_logo_resource = table["resource"].alias("comment_logo_resource")

            comments_stmt = (
                select(
                    table["comment"].c.id.label("comment_id"),
                    table["comment"].c.message,
                    table["comment"].c.created_date,
                    table["account"].c.id.label("account_id"),
                    table["account"].c.uuid,
                    table["account"].c.email,
                    table["role"].c.name.label("role_name"),
                    table["user"].c.first_name.label("user_first_name"),
                    table["user"].c.last_name.label("user_last_name"),
                    table["user"].c.profile_picture.label("profile_picture_id"),
                    comment_profile_resource.c.directory.label(
                        "profile_picture_directory"
                    ),
                    comment_profile_resource.c.filename.label(
                        "profile_picture_filename"
                    ),
                    table["organization"].c.name.label("organization_name"),
                    table["organization"].c.description.label(
                        "organization_description"
                    ),
                    table["organization"].c.logo.label("organization_logo_id"),
                    comment_logo_resource.c.directory.label(
                        "organization_logo_directory"
                    ),
                    comment_logo_resource.c.filename.label(
                        "organization_logo_filename"
                    ),
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
                        comment_profile_resource,
                        table["user"].c.profile_picture
                        == comment_profile_resource.c.id,
                    )
                    .outerjoin(
                        table["organization"],
                        table["organization"].c.account_id == table["account"].c.id,
                    )
                    .outerjoin(
                        comment_logo_resource,
                        table["organization"].c.logo == comment_logo_resource.c.id,
                    )
                )
                .where(table["comment"].c.event_id == event_id)
                .order_by(table["comment"].c.created_date.desc())
                .limit(3)
            )
            comments_result = session.execute(comments_stmt).fetchall()
            latest_comments = []
            for row in comments_result:
                data = row._mapping
                role_name = data.get("role_name")
                comment_obj = {
                    "comment_id": data["comment_id"],
                    "message": data["message"],
                    "created_date": data["created_date"],
                    "account": {
                        "id": data["account_id"],
                        "uuid": data["uuid"],
                        "email": data["email"],
                    },
                    "role": role_name,
                }
                if role_name == "organization":
                    comment_obj["organization"] = {
                        "name": data["organization_name"],
                        "description": data["organization_description"],
                        "logo": (
                            {
                                "id": data["organization_logo_id"],
                                "directory": data["organization_logo_directory"],
                                "filename": data["organization_logo_filename"],
                            }
                            if data["organization_logo_id"]
                            else None
                        ),
                    }
                else:
                    comment_obj["user"] = {
                        "first_name": data["user_first_name"],
                        "last_name": data["user_last_name"],
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
                latest_comments.append(comment_obj)
            event["latest_comments"] = latest_comments

            events.append(event)

        return {
            "events": events,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_events,
                "pages": (total_events + limit - 1) // limit,
            },
        }
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
