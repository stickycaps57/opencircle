from fastapi import APIRouter, HTTPException, Path, Cookie
from pydantic import BaseModel
from lib.database import Database
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import insert, select, func
from typing import Optional
from utils.resource_utils import add_resource, delete_resource, get_resource
from utils.session_utils import get_account_uuid_from_session
import json
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer


router = APIRouter(
    prefix="/user",
    tags=["user"],
)

db = Database()
table = db.tables
session = db.session


class UserCreate(BaseModel):
    account_id: int
    first_name: str
    last_name: str
    bio: Optional[str] = None
    profile_picture: Optional[int] = None


@router.post("/", tags=["Create user"])
async def create_user(user: UserCreate):

    stmt = insert(table["user"]).values(
        account_id=user.account_id,
        first_name=user.first_name,
        last_name=user.last_name,
        bio=user.bio,
        profile_picture=user.profile_picture,
    )
    try:
        session.execute(stmt)
        session.commit()
        return {"message": "User created successfully"}
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=400, detail="User already exists or invalid account_id"
        )
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.delete("/{user_id}", tags=["Delete user"])
async def delete_user(
    user_id: int = Path(..., description="The ID of the user to delete")
):
    stmt = table["user"].delete().where(table["user"].c.id == user_id)
    try:
        result = session.execute(stmt)
        session.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
        return {"message": "User deleted successfully"}
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.get("/profile/{account_uuid}", tags=["Get User Profile"])
async def get_user_profile(
    account_uuid: str = Path(..., description="The UUID of the user account"),
    session_token: str = Cookie(...),
):
    session = db.session
    try:
        # Validate session token
        session_account_uuid = get_account_uuid_from_session(session_token)
        if not session_account_uuid:
            raise HTTPException(status_code=401, detail="Invalid session token")

        # Get the requesting account to verify it exists
        requesting_account = session.query(table["account"]).filter_by(uuid=session_account_uuid).first()
        if not requesting_account:
            raise HTTPException(status_code=404, detail="Requesting account not found")
        # Get user details with profile picture
        profile_resource = table["resource"].alias("profile_resource")
        user_stmt = (
            select(
                table["user"].c.first_name,
                table["user"].c.last_name,
                table["user"].c.bio,
                table["user"].c.created_date,
                table["user"].c.profile_picture,
                table["user"].c.id.label("user_id"),
                profile_resource.c.directory.label("profile_picture_directory"),
                profile_resource.c.filename.label("profile_picture_filename"),
                profile_resource.c.id.label("profile_picture_id"),
                table["account"].c.id.label("account_id"),
                table["account"].c.username,
            )
            .select_from(
                table["user"]
                .join(table["account"], table["user"].c.account_id == table["account"].c.id)
                .outerjoin(
                    profile_resource,
                    table["user"].c.profile_picture == profile_resource.c.id,
                )
            )
            .where(table["account"].c.uuid == account_uuid)
        )
        user_result = session.execute(user_stmt).first()
        
        if not user_result:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_data = user_result._mapping
        account_id = user_data["account_id"]
        
        # get the membership status of the organization visitor
        organizer_view_user_membership = None
        if session_token:
            try:
                membership_stmt = (
                    select(table["membership"].c.status)
                    .select_from(
                        table["membership"]
                        .join(table["organization"], table["membership"].c.organization_id == table["organization"].c.id)
                        .join(table["account"], table["organization"].c.account_id == table["account"].c.id)
                    )
                    .where(
                        (table["account"].c.uuid == session_account_uuid) &
                        (table["membership"].c.user_id == user_data["user_id"])
                    )
                )
                organizer_view_user_membership = session.execute(membership_stmt).scalar()
            except Exception:
                # If there's any error getting membership status, just continue without it
                pass

        # Get recent posts (last 5 posts)
        posts_stmt = (
            select(
                table["post"].c.id,
                table["post"].c.description,
                table["post"].c.image,
                table["post"].c.created_date,
            )
            .where(table["post"].c.author == account_id)
            .order_by(table["post"].c.created_date.desc())
            .limit(5)
        )
        posts_result = session.execute(posts_stmt).fetchall()
        
        # Process posts and their images
        recent_posts = []
        for post in posts_result:
            post_dict = post._mapping
            images = []
            if post_dict["image"]:
                try:
                    resource_ids = json.loads(post_dict["image"])
                    if resource_ids:
                        for resource_id in resource_ids:
                            resource_stmt = select(
                                table["resource"].c.id,
                                table["resource"].c.directory,
                                table["resource"].c.filename,
                            ).where(table["resource"].c.id == resource_id)
                            resource_result = session.execute(resource_stmt).first()
                            if resource_result:
                                images.append({
                                    "id": resource_result.id,
                                    "directory": resource_result.directory,
                                    "filename": resource_result.filename,
                                })
                except (json.JSONDecodeError, TypeError):
                    pass
            
            recent_posts.append({
                "id": post_dict["id"],
                "description": post_dict["description"],
                "images": images,
                "created_date": post_dict["created_date"],
            })
        
        # Get recent shares (last 5 shares)
        shares_stmt = (
            select(
                table["shares"].c.id,
                table["shares"].c.content_id,
                table["shares"].c.content_type,
                table["shares"].c.comment,
                table["shares"].c.date_created,
            )
            .where(table["shares"].c.account_uuid == account_uuid)
            .order_by(table["shares"].c.date_created.desc())
            .limit(5)
        )
        shares_result = session.execute(shares_stmt).fetchall()
        
        recent_shares = []
        for share in shares_result:
            share_dict = share._mapping
            recent_shares.append({
                "id": share_dict["id"],
                "content_id": share_dict["content_id"],
                "content_type": share_dict["content_type"],
                "comment": share_dict["comment"],
                "date_created": share_dict["date_created"],
            })
        
        # Get organizations the user is a member of (approved memberships only)
        org_logo_resource = table["resource"].alias("org_logo_resource")
        memberships_stmt = (
            select(
                table["organization"].c.id,
                table["organization"].c.name,
                table["organization"].c.category,
                table["organization"].c.description,
                table["organization"].c.logo,
                org_logo_resource.c.directory.label("logo_directory"),
                org_logo_resource.c.filename.label("logo_filename"),
                org_logo_resource.c.id.label("logo_id"),
                table["membership"].c.created_date.label("membership_date"),
            )
            .select_from(
                table["membership"]
                .join(
                    table["organization"],
                    table["membership"].c.organization_id == table["organization"].c.id,
                )
                .join(
                    table["user"],
                    table["membership"].c.user_id == table["user"].c.id,
                )
                .outerjoin(
                    org_logo_resource,
                    table["organization"].c.logo == org_logo_resource.c.id,
                )
            )
            .where(
                table["user"].c.account_id == account_id,
                table["membership"].c.status == "approved",
            )
            .order_by(table["membership"].c.created_date.desc())
        )
        memberships_result = session.execute(memberships_stmt).fetchall()
        
        organizations = []
        for membership in memberships_result:
            membership_dict = membership._mapping
            organizations.append({
                "id": membership_dict["id"],
                "name": membership_dict["name"],
                "category": membership_dict["category"],
                "description": membership_dict["description"],
                "logo": (
                    {
                        "id": membership_dict["logo_id"],
                        "directory": membership_dict["logo_directory"],
                        "filename": membership_dict["logo_filename"],
                    }
                    if membership_dict["logo_id"]
                    else None
                ),
                "membership_date": membership_dict["membership_date"],
            })
        
        # Get recent events the user successfully joined (RSVP status = 'joined')
        recent_events_stmt = (
            select(
                table["event"].c.id,
                table["event"].c.title,
                table["event"].c.event_date,
                table["event"].c.description,
                table["event"].c.image,
                table["rsvp"].c.created_date.label("rsvp_date"),
                table["organization"].c.name.label("organization_name"),
                # Address details
                table["address"].c.country,
                table["address"].c.province,
                table["address"].c.city,
                table["address"].c.barangay,
                table["address"].c.house_building_number,
            )
            .select_from(
                table["rsvp"]
                .join(
                    table["event"],
                    table["rsvp"].c.event_id == table["event"].c.id,
                )
                .join(
                    table["organization"],
                    table["event"].c.organization_id == table["organization"].c.id,
                )
                .join(
                    table["address"],
                    table["event"].c.address_id == table["address"].c.id,
                )
            )
            .where(
                table["rsvp"].c.attendee == account_id,
                table["rsvp"].c.status == "joined",
            )
            .order_by(table["rsvp"].c.created_date.desc())
            .limit(5)
        )
        events_result = session.execute(recent_events_stmt).fetchall()
        
        recent_events = []
        for event in events_result:
            event_dict = event._mapping
            
            # Get event image if exists
            event_image = None
            if event_dict["image"]:
                event_resource_stmt = select(
                    table["resource"].c.id,
                    table["resource"].c.directory,
                    table["resource"].c.filename,
                ).where(table["resource"].c.id == event_dict["image"])
                event_resource_result = session.execute(event_resource_stmt).first()
                if event_resource_result:
                    event_image = {
                        "id": event_resource_result.id,
                        "directory": event_resource_result.directory,
                        "filename": event_resource_result.filename,
                    }
            
            recent_events.append({
                "id": event_dict["id"],
                "title": event_dict["title"],
                "event_date": event_dict["event_date"],
                "description": event_dict["description"],
                "image": event_image,
                "organization_name": event_dict["organization_name"],
                "address": {
                    "country": event_dict["country"],
                    "province": event_dict["province"],
                    "city": event_dict["city"],
                    "barangay": event_dict["barangay"],
                    "house_building_number": event_dict["house_building_number"],
                },
                "rsvp_date": event_dict["rsvp_date"],
            })
        
        # Build the response
        profile = {
            "id": user_data["user_id"],
            "uuid": account_uuid,
            "first_name": user_data["first_name"],
            "last_name": user_data["last_name"],
            "username": user_data["username"],
            "bio": user_data["bio"],
            "profile_picture": (
                {
                    "id": user_data["profile_picture_id"],
                    "directory": user_data["profile_picture_directory"],
                    "filename": user_data["profile_picture_filename"],
                }
                if user_data["profile_picture_id"]
                else None
            ),
            "created_date": user_data["created_date"],
            "recent_posts": recent_posts,
            "recent_shares": recent_shares,
            "organizations": organizations,
            "recent_events": recent_events,
            "organizer_view_user_membership": organizer_view_user_membership
        }
        
        return profile
        
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
