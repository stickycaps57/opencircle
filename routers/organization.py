from fastapi import APIRouter, HTTPException, Form
from lib.database import Database
from sqlalchemy import insert, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

router = APIRouter(
    prefix="/organization",
    tags=["Organization Management"],
)

db = Database()
table = db.tables
session = db.session


@router.post("/join", tags=["Join Organization"])
async def join_organization(
    organization_id: int = Form(...),
    user_id: int = Form(...),
):
    # Check if organization exists
    org = session.query(table["organization"]).filter_by(id=organization_id).first()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Check if user exists
    user = session.query(table["user"]).filter_by(id=user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Insert membership (status defaults to 'pending')
    stmt = insert(table["membership"]).values(
        organization_id=organization_id, user_id=user_id, status="pending"
    )
    try:
        session.execute(stmt)
        session.commit()
        return {"message": "Membership request submitted"}
    except IntegrityError:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="Membership already exists or is pending"
        )
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
    user_id: int = Form(...),
):
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
    organization_id: int = Form(...),
    user_id: int = Form(...),
    status: str = Form(...),
):
    try:
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

        # Get all organizations the user is a member of
        memberships = (
            session.query(table["membership"])
            .filter_by(user_id=user_id, status="approved")
            .all()
        )
        if not memberships:
            raise HTTPException(status_code=404, detail="No memberships found for user")

        organizations = []
        for membership in memberships:
            org_id = membership.organization_id
            org = session.query(table["organization"]).filter_by(id=org_id).first()
            if not org:
                continue
            # Get all members of this organization
            org_memberships = (
                session.query(table["membership"])
                .filter_by(organization_id=org_id)
                .all()
            )
            members = []
            for m in org_memberships:
                member_user = (
                    session.query(table["user"]).filter_by(id=m.user_id).first()
                )
                if member_user:
                    members.append(
                        {
                            "user_id": member_user.id,
                            "account_uuid": getattr(member_user, "account_uuid", None),
                            "username": getattr(member_user, "username", None),
                            "status": m.status,
                        }
                    )
            organizations.append(
                {
                    "organization_id": org.id,
                    "organization_name": getattr(org, "name", None),
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
        pending_membership = (
            session.query(table["membership"])
            .filter_by(user_id=user_id, status="pending")
            .first()
        )
        if not pending_membership:
            raise HTTPException(status_code=404, detail="No pending membership found")

        org = (
            session.query(table["organization"])
            .filter_by(id=pending_membership.organization_id)
            .first()
        )
        if not org:
            raise HTTPException(status_code=404, detail="Organization not found")

        return {
            "organization_id": org.id,
            "organization_name": getattr(org, "name", None),
            "membership_status": pending_membership.status,
        }
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
