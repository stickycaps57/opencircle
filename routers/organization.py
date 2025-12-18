from fastapi import APIRouter, HTTPException, Form, Path
from lib.database import Database
from sqlalchemy import insert, update, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from fastapi import Cookie
from utils.session_utils import get_account_uuid_from_session
from sqlalchemy import or_
from sqlalchemy.sql import func
from utils.notification_service import NotificationService

router = APIRouter(
    prefix="/organization",
    tags=["Organization Management"],
)

db = Database()
table = db.tables


@router.post("/join", tags=["Join Organization"])
async def join_organization(
    organization_id: int = Form(...),
    session_token: str = Cookie(None, alias="session_token"),
):
    session = db.session
    notification_service = NotificationService()

    # Validate session token
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")

    # Get account_uuid from session
    account_uuid = get_account_uuid_from_session(session_token)

    # Get user details by joining user and account tables
    user = (
        session.query(table["user"])
        .join(table["account"], table["user"].c.account_id == table["account"].c.id)
        .filter(table["account"].c.uuid == account_uuid)
        .first()
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user_id = user.id
    user_name = f"{user.first_name} {user.last_name}"
    user_account_id = user.account_id

    # Check if organization exists and get its account_id
    org = session.query(table["organization"]).filter_by(id=organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Check if membership already exists
    existing_membership = (
        session.query(table["membership"])
        .filter_by(organization_id=organization_id, user_id=user_id)
        .first()
    )

    if existing_membership:
        # If membership exists but was rejected, update it to pending
        if existing_membership.status == "rejected":
            try:
                update_stmt = (
                    update(table["membership"])
                    .where(
                        table["membership"].c.organization_id == organization_id,
                        table["membership"].c.user_id == user_id,
                    )
                    .values(status="pending")
                )
                session.execute(update_stmt)
                session.commit()

                # Notify organization about resubmitted membership request
                try:
                    notification_service.notify_organization_new_membership_request(
                        organization_account_id=org.account_id,
                        user_name=user_name,
                        user_account_id=user_account_id,
                    )
                except Exception as e:
                    print(f"Error sending membership request notification: {e}")

                return {"message": "Membership request resubmitted"}
            except SQLAlchemyError as e:
                session.rollback()
                raise HTTPException(status_code=500, detail="Database error: " + str(e))
        else:
            # If membership exists with status pending or approved, return error
            raise HTTPException(
                status_code=409, detail="Membership already exists or is pending"
            )

    # Insert new membership with pending status
    try:
        stmt = insert(table["membership"]).values(
            organization_id=organization_id, user_id=user_id, status="pending"
        )
        session.execute(stmt)
        session.commit()

        # Notify organization about new membership request
        try:
            notification_service.notify_organization_new_membership_request(
                organization_account_id=org.account_id,
                user_name=user_name,
                user_account_id=user_account_id,
            )
        except Exception as e:
            print(f"Error sending membership request notification: {e}")

        return {"message": "Membership request submitted"}
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
        notification_service.close()


@router.post("/leave", tags=["Leave Organization"])
async def leave_organization(
    organization_id: int = Form(...),
    session_token: str = Cookie(None, alias="session_token"),
):
    session = db.session
    # Validate session token
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")

    # Get account_uuid from session
    account_uuid = get_account_uuid_from_session(session_token)

    # Get user_id by joining user and account tables
    user = (
        session.query(table["user"])
        .join(table["account"], table["user"].c.account_id == table["account"].c.id)
        .filter(table["account"].c.uuid == account_uuid)
        .first()
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user_id = user.id

    # Check if organization exists
    org = session.query(table["organization"]).filter_by(id=organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Delete membership
    try:
        stmt = (
            table["membership"]
            .delete()
            .where(
                table["membership"].c.organization_id == organization_id,
                table["membership"].c.user_id == user_id,
            )
        )
        result = session.execute(stmt)
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Membership not found")
        session.commit()
        return {"message": "Successfully left organization"}
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.post("/leave-organization", tags=["Leave Organization"])
async def leave_organization_status(
    organization_id: int = Form(...),
    session_token: str = Cookie(None, alias="session_token"),
):
    """
    Leave an organization by setting membership status to 'left'.
    This preserves the membership record for historical purposes.
    """
    session = db.session

    # Validate session token
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")

    # Get account_uuid from session
    account_uuid = get_account_uuid_from_session(session_token)

    # Get user_id by joining user and account tables
    user = (
        session.query(table["user"])
        .join(table["account"], table["user"].c.account_id == table["account"].c.id)
        .filter(table["account"].c.uuid == account_uuid)
        .first()
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user_id = user.id

    # Check if organization exists
    org = session.query(table["organization"]).filter_by(id=organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Check if membership exists and is currently active (approved)
    existing_membership = (
        session.query(table["membership"])
        .filter_by(organization_id=organization_id, user_id=user_id)
        .first()
    )

    if not existing_membership:
        raise HTTPException(status_code=404, detail="Membership not found")

    if existing_membership.status != "approved":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot leave organization. Current membership status is '{existing_membership.status}'",
        )

    # Update membership status to 'left'
    try:
        stmt = (
            update(table["membership"])
            .where(
                table["membership"].c.organization_id == organization_id,
                table["membership"].c.user_id == user_id,
            )
            .values(status="left")
        )
        result = session.execute(stmt)
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Membership not found")

        session.commit()
        return {"message": "Successfully left organization"}
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.put("/membership/status", tags=["Change Membership Status"])
async def change_membership_status(
    user_id: int = Form(...),
    status: str = Form(...),
    session_token: str = Cookie(None, alias="session_token"),
):
    session = db.session
    notification_service = NotificationService()

    # Validate session token
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")

    # Get account_uuid from session
    account_uuid = get_account_uuid_from_session(session_token)

    try:
        # Get organization_id by joining organization and account tables
        org = (
            session.query(table["organization"])
            .join(
                table["account"],
                table["organization"].c.account_id == table["account"].c.id,
            )
            .filter(table["account"].c.uuid == account_uuid)
            .first()
        )
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        organization_id = org.id
        organization_name = org.name

        # Get user's account_id for notification
        user_account = (
            session.query(table["user"].c.account_id)
            .filter(table["user"].c.id == user_id)
            .first()
        )

        stmt = (
            update(table["membership"])
            .where(
                table["membership"].c.organization_id == organization_id,
                table["membership"].c.user_id == user_id,
            )
            .values(status=status)
        )
        result = session.execute(stmt)
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Membership not found")
        session.commit()

        # Send notification if membership was approved
        if status == "approved" and user_account:
            notification_service.notify_organization_membership_accepted(
                user_account_id=user_account.account_id,
                organization_id=organization_id,
                organization_name=organization_name,
            )

        return {"message": "Membership status updated"}
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
        notification_service.close()


@router.get("/memberships", tags=["Get User Memberships"])
async def get_user_memberships(account_uuid: str):
    session = db.session
    try:
        # Get user_id by joining user and account tables
        user = (
            session.query(table["user"])
            .join(table["account"], table["user"].c.account_id == table["account"].c.id)
            .filter(table["account"].c.uuid == account_uuid)
            .first()
        )
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user_id = user.id
        organizations = []

        # Get all organizations the user is a member of
        memberships = (
            session.query(table["membership"])
            .filter_by(user_id=user_id, status="approved")
            .all()
        )
        if not memberships:
            return {"organizations": organizations}

        for membership in memberships:
            org_id = membership.organization_id
            # Join organization to resource to get logo details
            org = (
                session.query(
                    table["organization"].c.id,
                    table["organization"].c.name,
                    table["organization"].c.description,
                    table["organization"].c.logo,
                    table["resource"].c.directory.label("logo_directory"),
                    table["resource"].c.filename.label("logo_filename"),
                    table["resource"].c.id.label("logo_id"),
                )
                .outerjoin(
                    table["resource"],
                    table["organization"].c.logo == table["resource"].c.id,
                )
                .filter(table["organization"].c.id == org_id)
                .first()
            )
            if not org:
                continue

            # Get all members of this organization, join user and resource for profile picture
            org_memberships = (
                session.query(
                    table["membership"].c.user_id,
                    table["membership"].c.status,
                    table["user"].c.id.label("user_id"),
                    table["user"].c.account_id,
                    table["user"].c.first_name,
                    table["user"].c.last_name,
                    table["user"].c.bio,
                    table["user"].c.profile_picture,
                    table["account"].c.uuid.label("account_uuid"),
                    table["resource"].c.directory.label("profile_picture_directory"),
                    table["resource"].c.filename.label("profile_picture_filename"),
                    table["resource"].c.id.label("profile_picture_id"),
                )
                .join(
                    table["user"], table["membership"].c.user_id == table["user"].c.id
                )
                .join(
                    table["account"],
                    table["user"].c.account_id == table["account"].c.id,
                )
                .outerjoin(
                    table["resource"],
                    table["user"].c.profile_picture == table["resource"].c.id,
                )
                .filter(table["membership"].c.organization_id == org_id)
                .all()
            )
            members = []
            for m in org_memberships:
                members.append(
                    {
                        "user_id": m.user_id,
                        "account_uuid": m.account_uuid,
                        "first_name": m.first_name,
                        "last_name": m.last_name,
                        "bio": m.bio,
                        "status": m.status,
                        "profile_picture": (
                            {
                                "id": m.profile_picture_id,
                                "directory": m.profile_picture_directory,
                                "filename": m.profile_picture_filename,
                            }
                            if m.profile_picture_id
                            else None
                        ),
                    }
                )
            # Fetch logo details for the organization
            organization_logo = (
                {
                    "id": org.logo_id,
                    "directory": org.logo_directory,
                    "filename": org.logo_filename,
                }
                if org.logo_id
                else None
            )
            organizations.append(
                {
                    "organization_id": org.id,
                    "organization_name": org.name,
                    "organization_description": org.description,
                    "organization_logo": organization_logo,
                    "membership_status": membership.status,
                    "members": members,
                }
            )
        return {"organizations": organizations}
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.get("/user/joined", tags=["Get User Joined Organizations"])
async def get_user_joined_organizations(
    account_uuid: str,
    session_token: str = Cookie(None, alias="session_token"),
):
    """
    Get all organizations that a user has joined (approved membership)
    """
    session = db.session

    # Validate session token if provided (optional for this endpoint)
    visitor_user_id = None
    if session_token:
        session_account_uuid = get_account_uuid_from_session(session_token)
        if not session_account_uuid:
            raise HTTPException(status_code=401, detail="Invalid session token")

    try:


        # Get the visitor's user ID
        visitor_user_stmt = select(table["user"].c.id).join(
            table["account"], table["user"].c.account_id == table["account"].c.id
        ).where(table["account"].c.uuid == session_account_uuid)
        visitor_user_id = session.execute(visitor_user_stmt).scalar()

        # Get user_id by joining user and account tables
        user = (
            session.query(table["user"])
            .join(table["account"], table["user"].c.account_id == table["account"].c.id)
            .filter(table["account"].c.uuid == account_uuid)
            .first()
        )
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user_id = user.id

        # Get all organizations the user has joined (approved membership)
        joined_organizations_query = (
            session.query(
                table["organization"].c.id,
                table["organization"].c.name,
                table["organization"].c.description,
                table["organization"].c.category,
                table["organization"].c.logo,
                table["organization"].c.created_date.label("organization_created_date"),
                table["membership"].c.created_date.label("membership_date"),
                table["membership"].c.last_modified_date.label(
                    "membership_modified_date"
                ),
                table["account"].c.uuid.label("organization_account_uuid"),
                table["account"].c.email.label("organization_email"),
                table["resource"].c.directory.label("logo_directory"),
                table["resource"].c.filename.label("logo_filename"),
                table["resource"].c.id.label("logo_id"),
            )
            .join(
                table["membership"],
                table["organization"].c.id == table["membership"].c.organization_id,
            )
            .join(
                table["account"],
                table["organization"].c.account_id == table["account"].c.id,
            )
            .outerjoin(
                table["resource"],
                table["organization"].c.logo == table["resource"].c.id,
            )
            .filter(
                table["membership"].c.user_id == user_id,
                table["membership"].c.status == "approved",
            )
            .order_by(table["membership"].c.created_date.desc())
        )

        joined_organizations_result = joined_organizations_query.all()

        organizations = []
        for org in joined_organizations_result:
            # Get member count for each organization
            member_count_stmt = (
                select(func.count())
                .select_from(table["membership"])
                .where(
                    table["membership"].c.organization_id == org.id,
                    table["membership"].c.status == "approved",
                )
            )
            member_count = session.execute(member_count_stmt).scalar()

            # Get recent events count (last 30 days)
            from datetime import datetime, timedelta

            thirty_days_ago = datetime.now() - timedelta(days=30)

            recent_events_count_stmt = (
                select(func.count())
                .select_from(table["event"])
                .where(
                    table["event"].c.organization_id == org.id,
                    table["event"].c.created_date >= thirty_days_ago,
                )
            )
            recent_events_count = session.execute(recent_events_count_stmt).scalar()

            # Get visitor membership status
            visitor_membership_status = None
            if visitor_user_id:
                visitor_membership_stmt = select(table["membership"].c.status).where(
                    (table["membership"].c.organization_id == org.id) &
                    (table["membership"].c.user_id == visitor_user_id)
                )
                visitor_membership_status = session.execute(visitor_membership_stmt).scalar()

            organization_data = {
                "id": org.id,
                "name": org.name,
                "description": org.description,
                "category": org.category,
                "logo": (
                    {
                        "id": org.logo_id,
                        "directory": org.logo_directory,
                        "filename": org.logo_filename,
                    }
                    if org.logo_id
                    else None
                ),
                "organization_created_date": org.organization_created_date,
                "membership_date": org.membership_date,
                "membership_modified_date": org.membership_modified_date,
                "account_uuid": org.organization_account_uuid,
                "email": org.organization_email,
                "stats": {
                    "member_count": member_count,
                    "recent_events_count": recent_events_count,
                },
                "visitor_membership_status": visitor_membership_status,
            }
            organizations.append(organization_data)

        return {
            "user_account_uuid": account_uuid,
            "joined_organizations_count": len(organizations),
            "organizations": organizations,
        }

    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.get("/pending-membership", tags=["Get Pending Membership Organization"])
async def get_pending_membership_organization(account_uuid: str):
    session = db.session
    try:
        # Get user_id by joining user and account tables
        user = (
            session.query(table["user"])
            .join(table["account"], table["user"].c.account_id == table["account"].c.id)
            .filter(table["account"].c.uuid == account_uuid)
            .first()
        )
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user_id = user.id

        # Find pending membership
        pending_memberships = (
            session.query(table["membership"])
            .filter_by(user_id=user_id, status="pending")
            .all()
            # .first()
        )
        if not pending_memberships:
            return {"pending_memberships": []}
            # raise HTTPException(status_code=404, detail="No pending membership found")

        # org = (
        #     session.query(table["organization"])
        #     .filter_by(id=pending_membership.organization_id)
        #     .first()
        # )

        pending_membership_list = []

        for pending_membership in pending_memberships:
            org = (
                session.query(
                    table["organization"].c.id,
                    table["organization"].c.name,
                    table["organization"].c.category,
                    table["organization"].c.logo,
                    table["resource"].c.directory.label("logo_directory"),
                    table["resource"].c.filename.label("logo_filename"),
                    table["resource"].c.id.label("logo_id"),
                )
                .outerjoin(
                    table["resource"],
                    table["organization"].c.logo == table["resource"].c.id,
                )
                .filter(
                    table["organization"].c.id == pending_membership.organization_id
                )
                .first()
            )

            if not org:
                continue

            pending_membership_list.append(
                {
                    "organization_id": org.id,
                    "organization_name": org.name,
                    "organization_category": org.category,
                    "organization_logo": (
                        {
                            "id": org.logo_id,
                            "directory": org.logo_directory,
                            "filename": org.logo_filename,
                        }
                        if org.logo_id
                        else None
                    ),
                    "membership_status": pending_membership.status,
                }
            )

        # if not org:
        #     raise HTTPException(status_code=404, detail="Organization not found")

        # return {
        #     "organization_id": org.id,
        #     "organization_name": getattr(org, "name", None),
        #     "membership_status": pending_membership.status,
        # }

        return {"pending_memberships": pending_membership_list}
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.get("/pending-applications", tags=["Get Pending Membership Applications"])
async def get_pending_membership_applications(
    session_token: str = Cookie(None, alias="session_token"),
):
    session = db.session
    # Validate session token
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")

    # Get account_uuid from session
    account_uuid = get_account_uuid_from_session(session_token)

    try:
        # Get organization_id by joining organization and account tables
        org = (
            session.query(table["organization"])
            .join(
                table["account"],
                table["organization"].c.account_id == table["account"].c.id,
            )
            .filter(table["account"].c.uuid == account_uuid)
            .first()
        )
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        organization_id = org.id

        # Get all pending membership applications for this organization
        pending_memberships = (
            session.query(table["membership"])
            .filter_by(organization_id=organization_id, status="pending")
            .all()
        )
        applications = []
        for membership in pending_memberships:
            user = session.query(table["user"]).filter_by(id=membership.user_id).first()
            account = (
                session.query(table["account"]).filter_by(id=user.account_id).first()
                if user
                else None
            )
            profile_picture = None
            if user and user.profile_picture:
                resource = (
                    session.query(table["resource"])
                    .filter_by(id=user.profile_picture)
                    .first()
                )
                if resource:
                    profile_picture = {
                        "id": resource.id,
                        "directory": resource.directory,
                        "filename": resource.filename,
                    }
            applications.append(
                {
                    "membership_id": membership.id,
                    "user_id": user.id if user else None,
                    "account_uuid": account.uuid if account else None,
                    "first_name": user.first_name if user else None,
                    "last_name": user.last_name if user else None,
                    "bio": user.bio if user else None,
                    "profile_picture": profile_picture,
                    "status": membership.status,
                }
            )
        return {"pending_applications": applications}
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.get("/rejected-applications", tags=["Get Rejected Membership Applications"])
async def get_rejected_membership_applications(
    session_token: str = Cookie(None, alias="session_token"),
):
    session = db.session
    # Validate session token
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")

    # Get account_uuid from session
    account_uuid = get_account_uuid_from_session(session_token)

    try:
        # Get organization_id by joining organization and account tables
        org = (
            session.query(table["organization"])
            .join(
                table["account"],
                table["organization"].c.account_id == table["account"].c.id,
            )
            .filter(table["account"].c.uuid == account_uuid)
            .first()
        )
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")
        organization_id = org.id

        # Get all rejected membership applications for this organization
        rejected_memberships = (
            session.query(table["membership"])
            .filter_by(organization_id=organization_id, status="rejected")
            .all()
        )
        applications = []
        for membership in rejected_memberships:
            user = session.query(table["user"]).filter_by(id=membership.user_id).first()
            account = (
                session.query(table["account"]).filter_by(id=user.account_id).first()
                if user
                else None
            )
            profile_picture = None
            if user and user.profile_picture:
                resource = (
                    session.query(table["resource"])
                    .filter_by(id=user.profile_picture)
                    .first()
                )
                if resource:
                    profile_picture = {
                        "id": resource.id,
                        "directory": resource.directory,
                        "filename": resource.filename,
                    }
            applications.append(
                {
                    "membership_id": membership.id,
                    "user_id": user.id if user else None,
                    "account_uuid": account.uuid if account else None,
                    "first_name": user.first_name if user else None,
                    "last_name": user.last_name if user else None,
                    "bio": user.bio if user else None,
                    "profile_picture": profile_picture,
                    "status": membership.status,
                }
            )
        return {"rejected_applications": applications}
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.get("/organization-members", tags=["Get Organization Members"])
async def get_organization_members(organization_id: int):
    session = db.session
    try:
        # Get organization with logo details
        org = (
            session.query(
                table["organization"].c.id,
                table["organization"].c.name,
                table["organization"].c.logo,
                table["resource"].c.directory.label("logo_directory"),
                table["resource"].c.filename.label("logo_filename"),
                table["resource"].c.id.label("logo_id"),
            )
            .outerjoin(
                table["resource"],
                table["organization"].c.logo == table["resource"].c.id,
            )
            .filter(table["organization"].c.id == organization_id)
            .first()
        )
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        # Get all approved members of the organization
        org_memberships = (
            session.query(
                table["membership"].c.user_id,
                table["membership"].c.status,
                table["user"].c.id.label("user_id"),
                table["user"].c.account_id,
                table["user"].c.first_name,
                table["user"].c.last_name,
                table["user"].c.bio,
                table["user"].c.profile_picture,
                table["account"].c.uuid.label("account_uuid"),
                table["resource"].c.directory.label("profile_picture_directory"),
                table["resource"].c.filename.label("profile_picture_filename"),
                table["resource"].c.id.label("profile_picture_id"),
            )
            .join(table["user"], table["membership"].c.user_id == table["user"].c.id)
            .join(
                table["account"],
                table["user"].c.account_id == table["account"].c.id,
            )
            .outerjoin(
                table["resource"],
                table["user"].c.profile_picture == table["resource"].c.id,
            )
            .filter(
                table["membership"].c.organization_id == organization_id,
                table["membership"].c.status == "approved",
            )
            .all()
        )
        members = []
        for m in org_memberships:
            members.append(
                {
                    "user_id": m.user_id,
                    "account_uuid": m.account_uuid,
                    "first_name": m.first_name,
                    "last_name": m.last_name,
                    "bio": m.bio,
                    "status": m.status,
                    "profile_picture": (
                        {
                            "id": m.profile_picture_id,
                            "directory": m.profile_picture_directory,
                            "filename": m.profile_picture_filename,
                        }
                        if m.profile_picture_id
                        else None
                    ),
                }
            )
        return {
            "organization_id": org.id,
            "organization_name": org.name,
            "organization_logo": (
                {
                    "id": org.logo_id,
                    "directory": org.logo_directory,
                    "filename": org.logo_filename,
                }
                if org.logo_id
                else None
            ),
            "member_count": len(members),
            "members": members,
        }
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.post("/membership-status", tags=["Get Membership Status"])
async def get_membership_status(
    account_uuids: list[str] = Form(...), organization_id: int = Form(...)
):
    session = db.session
    try:
        # Get user_ids for the provided account_uuids
        users = (
            session.query(table["user"].c.id, table["account"].c.uuid)
            .join(table["account"], table["user"].c.account_id == table["account"].c.id)
            .filter(table["account"].c.uuid.in_(account_uuids))
            .all()
        )
        if not users:
            raise HTTPException(
                status_code=404, detail="No users found for provided account_uuids"
            )

        user_id_map = {account_uuid: user_id for user_id, account_uuid in users}

        # Get membership statuses for these users in the organization
        memberships = (
            session.query(table["membership"])
            .filter(
                table["membership"].c.organization_id == organization_id,
                table["membership"].c.user_id.in_(user_id_map.values()),
            )
            .all()
        )

        status_map = {
            membership.user_id: membership.status for membership in memberships
        }

        result = []
        for account_uuid, user_id in user_id_map.items():
            result.append(
                {
                    "account_uuid": account_uuid,
                    "membership_status": status_map.get(user_id, None),
                }
            )

        return {"membership_statuses": result}
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.get("/search", tags=["Search Organizations"])
async def search_organizations(query: str):
    session = db.session
    try:
        organizations = (
            session.query(
                table["organization"].c.id,
                table["organization"].c.name,
                table["organization"].c.description,
                table["organization"].c.category,
                table["organization"].c.logo,
                table["organization"].c.account_id,
                table["account"].c.uuid.label("account_uuid"),
                table["resource"].c.directory.label("logo_directory"),
                table["resource"].c.filename.label("logo_filename"),
                table["resource"].c.id.label("logo_id"),
            )
            .join(
                table["account"],
                table["organization"].c.account_id == table["account"].c.id,
            )
            .outerjoin(
                table["resource"],
                table["organization"].c.logo == table["resource"].c.id,
            )
            .filter(
                or_(
                    func.lower(table["organization"].c.name).ilike(
                        f"%{query.lower()}%"
                    ),
                    func.lower(table["organization"].c.description).ilike(
                        f"%{query.lower()}%"
                    ),
                    func.lower(table["organization"].c.category).ilike(
                        f"%{query.lower()}%"
                    ),
                )
            )
            .order_by(func.lower(table["organization"].c.name))  # alphabetical order
            .limit(20)
            .all()
        )

        results = []
        for org in organizations:
            results.append(
                {
                    "organization_id": org.id,
                    "account_uuid": org.account_uuid,
                    "name": org.name,
                    "description": org.description,
                    "category": org.category,
                    "logo": (
                        {
                            "id": org.logo_id,
                            "directory": org.logo_directory,
                            "filename": org.logo_filename,
                        }
                        if org.logo_id
                        else None
                    ),
                }
            )
        return {"results": results}
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.get("/{organization_id}", tags=["Get Organization Details"])
async def get_organization_by_id(
    organization_id: int = Path(...),
    session_token: str = Cookie(None, alias="session_token"),
):
    session = db.session
    try:
        # First, check if organization exists at all
        org_exists_stmt = select(table["organization"].c.id).where(
            table["organization"].c.id == organization_id
        )
        org_exists = session.execute(org_exists_stmt).scalar()
        
        if not org_exists:
            raise HTTPException(status_code=404, detail=f"Organization with ID {organization_id} not found")

        # Get organization details by joining with account and resource tables
        org_stmt = (
            select(
                table["organization"].c.id,
                table["organization"].c.account_id,
                table["organization"].c.name,
                table["organization"].c.logo,
                table["organization"].c.category,
                table["organization"].c.description,
                table["account"].c.email,
                table["account"].c.uuid,
                table["account"].c.role_id,
                table["resource"].c.directory.label("logo_directory"),
                table["resource"].c.filename.label("logo_filename"),
            )
            .select_from(
                table["organization"]
                .outerjoin(  # Changed from join to outerjoin
                    table["account"],
                    table["organization"].c.account_id == table["account"].c.id,
                )
                .outerjoin(
                    table["resource"],
                    table["organization"].c.logo == table["resource"].c.id,
                )
            )
            .where(table["organization"].c.id == organization_id)
        )

        org_result = session.execute(org_stmt).first()
        if not org_result:
            raise HTTPException(status_code=404, detail=f"Organization data could not be retrieved for ID {organization_id}")

        organization = org_result._mapping

        # Get user's membership status if session_token is provided
        user_membership_status = None
        if session_token:
            try:
                # Get account_uuid from session
                account_uuid = get_account_uuid_from_session(session_token)
                
                # Get user_id from account_uuid
                user_stmt = (
                    select(table["user"].c.id)
                    .select_from(
                        table["user"]
                        .join(table["account"], table["user"].c.account_id == table["account"].c.id)
                    )
                    .where(table["account"].c.uuid == account_uuid)
                )
                user_result = session.execute(user_stmt).scalar()
                
                if user_result:
                    # Check membership status
                    membership_stmt = (
                        select(table["membership"].c.status)
                        .where(
                            (table["membership"].c.organization_id == organization_id) &
                            (table["membership"].c.user_id == user_result)
                        )
                    )
                    user_membership_status = session.execute(membership_stmt).scalar()
            except Exception:
                # If there's any error getting membership status, just continue without it
                pass

        # Return organization details with membership status
        response = {
            "id": organization["id"],
            "account_id": organization["account_id"],
            "name": organization["name"],
            "email": organization["email"],
            "logo": (
                {
                    "id": organization["logo"],
                    "directory": organization["logo_directory"],
                    "filename": organization["logo_filename"],
                }
                if organization["logo"]
                else None
            ),
            "category": organization["category"],
            "description": organization["description"],
            "uuid": organization["uuid"],
            "role_id": organization["role_id"],
        }
        
        # Only add membership_status if we have a session token (indicating a user is viewing)
        if session_token:
            response["user_membership_status"] = user_membership_status
            
        return response
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.get("/profile/{account_uuid}", tags=["Get Organization Profile"])
async def get_organization_profile(
    account_uuid: str = Path(..., description="The UUID of the organization's account"),
    session_token: str = Cookie(...),
):
    session = db.session
    try:
        # Validate session token
        session_account_uuid = get_account_uuid_from_session(session_token)
        if not session_account_uuid:
            raise HTTPException(status_code=401, detail="Invalid session token")
        requesting_account = (
            session.query(table["account"]).filter_by(uuid=session_account_uuid).first()
        )
        if not requesting_account:
            raise HTTPException(status_code=404, detail="Requesting account not found")

        # Get organization info
        org_logo_resource = table["resource"].alias("org_logo_resource")
        org_stmt = (
            select(
                table["organization"].c.id,
                table["organization"].c.name,
                table["organization"].c.description,
                table["organization"].c.category,
                table["organization"].c.logo,
                org_logo_resource.c.directory.label("logo_directory"),
                org_logo_resource.c.filename.label("logo_filename"),
                org_logo_resource.c.id.label("logo_id"),
                table["organization"].c.created_date,
                table["account"].c.id.label("account_id"),
                table["account"].c.username,
            )
            .select_from(
                table["organization"]
                .join(
                    table["account"],
                    table["organization"].c.account_id == table["account"].c.id,
                )
                .outerjoin(
                    org_logo_resource,
                    table["organization"].c.logo == org_logo_resource.c.id,
                )
            )
            .where(table["account"].c.uuid == account_uuid)
        )
        org_result = session.execute(org_stmt).first()
        if not org_result:
            raise HTTPException(status_code=404, detail="Organization not found")
        org_data = org_result._mapping
        account_id = org_data["account_id"]

        # Recent posts (last 5)
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
        import json

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
                                images.append(
                                    {
                                        "id": resource_result.id,
                                        "directory": resource_result.directory,
                                        "filename": resource_result.filename,
                                    }
                                )
                except (json.JSONDecodeError, TypeError):
                    pass
            recent_posts.append(
                {
                    "id": post_dict["id"],
                    "description": post_dict["description"],
                    "images": images,
                    "created_date": post_dict["created_date"],
                }
            )

        # Upcoming events (event_date >= now)
        from datetime import datetime

        now = datetime.now()
        upcoming_events_stmt = (
            select(
                table["event"].c.id,
                table["event"].c.title,
                table["event"].c.event_date,
                table["event"].c.description,
                table["event"].c.image,
                table["event"].c.created_date,
            )
            .where(
                table["event"].c.organization_id == org_data["id"],
                table["event"].c.event_date >= now,
            )
            .order_by(table["event"].c.event_date.asc())
            .limit(5)
        )
        upcoming_events_result = session.execute(upcoming_events_stmt).fetchall()
        upcoming_events = []
        for event in upcoming_events_result:
            event_dict = event._mapping
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
            upcoming_events.append(
                {
                    "id": event_dict["id"],
                    "title": event_dict["title"],
                    "event_date": event_dict["event_date"],
                    "description": event_dict["description"],
                    "image": event_image,
                    "created_date": event_dict["created_date"],
                }
            )

        # Latest past events (event_date < now, last 5)
        past_events_stmt = (
            select(
                table["event"].c.id,
                table["event"].c.title,
                table["event"].c.event_date,
                table["event"].c.description,
                table["event"].c.image,
                table["event"].c.created_date,
            )
            .where(
                table["event"].c.organization_id == org_data["id"],
                table["event"].c.event_date < now,
            )
            .order_by(table["event"].c.event_date.desc())
            .limit(5)
        )
        past_events_result = session.execute(past_events_stmt).fetchall()
        past_events = []
        for event in past_events_result:
            event_dict = event._mapping
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
            past_events.append(
                {
                    "id": event_dict["id"],
                    "title": event_dict["title"],
                    "event_date": event_dict["event_date"],
                    "description": event_dict["description"],
                    "image": event_image,
                    "created_date": event_dict["created_date"],
                }
            )

        # Number of members
        member_count_stmt = (
            select(func.count())
            .select_from(table["membership"])
            .where(
                table["membership"].c.organization_id == org_data["id"],
                table["membership"].c.status == "approved",
            )
        )
        member_count = session.execute(member_count_stmt).scalar()

        # Recently added members (last 5 approved memberships)
        recent_members_stmt = (
            select(
                table["user"].c.id,
                table["user"].c.first_name,
                table["user"].c.last_name,
                table["user"].c.bio,
                table["user"].c.profile_picture,
                table["membership"].c.created_date.label("membership_date"),
                table["account"].c.uuid.label("account_uuid"),
                table["account"].c.email.label("account_email"),
            )
            .select_from(
                table["membership"]
                .join(
                    table["user"], table["membership"].c.user_id == table["user"].c.id
                )
                .join(
                    table["account"],
                    table["user"].c.account_id == table["account"].c.id,
                )
            )
            .where(
                table["membership"].c.organization_id == org_data["id"],
                table["membership"].c.status == "approved",
            )
            .order_by(table["membership"].c.created_date.desc())
            .limit(5)
        )
        recent_members_result = session.execute(recent_members_stmt).fetchall()
        recent_members = []
        for member in recent_members_result:
            member_dict = member._mapping
            profile_picture = None
            if member_dict["profile_picture"]:
                member_resource_stmt = select(
                    table["resource"].c.id,
                    table["resource"].c.directory,
                    table["resource"].c.filename,
                ).where(table["resource"].c.id == member_dict["profile_picture"])
                member_resource_result = session.execute(member_resource_stmt).first()
                if member_resource_result:
                    profile_picture = {
                        "id": member_resource_result.id,
                        "directory": member_resource_result.directory,
                        "filename": member_resource_result.filename,
                    }
            recent_members.append(
                {
                    "id": member_dict["id"],
                    "first_name": member_dict["first_name"],
                    "last_name": member_dict["last_name"],
                    "bio": member_dict["bio"],
                    "profile_picture": profile_picture,
                    "membership_date": member_dict["membership_date"],
                    "account_uuid": member_dict["account_uuid"],
                    "account_email": member_dict["account_email"],
                }
            )

        # Build response
        profile = {
            "name": org_data["name"],
            "username": org_data["username"],
            "description": org_data["description"],
            "category": org_data["category"],
            "logo": (
                {
                    "id": org_data["logo_id"],
                    "directory": org_data["logo_directory"],
                    "filename": org_data["logo_filename"],
                }
                if org_data["logo_id"]
                else None
            ),
            "created_date": org_data["created_date"],
            "recent_posts": recent_posts,
            "upcoming_events": upcoming_events,
            "latest_past_events": past_events,
            "member_count": member_count,
            "recent_members": recent_members,
        }
        return profile
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
