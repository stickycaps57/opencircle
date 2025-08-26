from fastapi import APIRouter, HTTPException, Form
from lib.database import Database
from sqlalchemy import insert, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from fastapi import Cookie
from utils.session_utils import get_account_uuid_from_session
from sqlalchemy import or_
from sqlalchemy.sql import func

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
                return {"message": "Membership request resubmitted"}
            except SQLAlchemyError as e:
                session.rollback()
                raise HTTPException(status_code=500, detail="Database error: " + str(e))
        else:
            # If membership exists with status pending or approved, return error
            raise HTTPException(
                status_code=409, detail="Membership already exists or is pending"
            )

    # Original implementation (commented out):
    # stmt = insert(table["membership"]).values(
    #     organization_id=organization_id, user_id=user_id, status="pending"
    # )
    # try:
    #     session.execute(stmt)
    #     session.commit()
    #     return {"message": "Membership request submitted"}
    # except IntegrityError:
    #     session.rollback()
    #     raise HTTPException(
    #         status_code=409, detail="Membership already exists or is pending"
    #     )

    # Insert new membership with pending status
    try:
        stmt = insert(table["membership"]).values(
            organization_id=organization_id, user_id=user_id, status="pending"
        )
        session.execute(stmt)
        session.commit()
        return {"message": "Membership request submitted"}
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


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


@router.put("/membership/status", tags=["Change Membership Status"])
async def change_membership_status(
    user_id: int = Form(...),
    status: str = Form(...),
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
        return {"message": "Membership status updated"}
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


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
