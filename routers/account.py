from fastapi import (
    APIRouter,
    HTTPException,
    Path,
    UploadFile,
    File,
    Form,
    Request,
    Response,
    Cookie,
)
from pydantic import EmailStr, constr
from lib.database import Database
from lib.models import UserModel, OrganizationModel
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import insert, select
import uuid
import bcrypt
from utils.user_utils import create_user
from utils.organization_utils import create_organization
import jwt
import os
from datetime import datetime, timedelta, timezone
from utils.session_utils import (
    add_session,
    delete_session,
    get_account_uuid_from_session,
)


router = APIRouter(
    prefix="/account",
    tags=["Account Management"],
)

db = Database()
table = db.tables
session = db.session
engine = db.engine

SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "fallback-unsafe-key")
SESSION_DURATION_MINUTES = 600  # 10 hours


@router.post("/user", tags=["Create User Account"])
async def create_user_account(
    first_name: constr(min_length=1) = Form(...),
    last_name: constr(min_length=1) = Form(...),
    bio: str = Form(None),
    profile_picture: UploadFile = File(...),
    email: EmailStr = Form(...),
    password: constr(min_length=8) = Form(...),
):
    # Generate a UUID for the account
    account_uuid = uuid.uuid4().hex

    # Hash the password securely
    hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode(
        "utf-8"
    )

    stmt = insert(table["account"]).values(
        uuid=account_uuid,
        email=email,
        password=hashed_password,
        role_id=1,
    )

    try:

        result = session.execute(stmt)
        session.commit()
        account_id = result.inserted_primary_key[0]

        create_user(
            UserModel(
                account_id=account_id,
                first_name=first_name,
                last_name=last_name,
                bio=bio,
                profile_picture=profile_picture,
                uuid=account_uuid,
            )
        )

        session.commit()
        return {"message": "Account created successfully", "uuid": account_uuid}
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=400, detail="Email already exists")
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.post("/organization", tags=["Create Organization Account"])
async def create_organization_account(
    name: constr(min_length=1) = Form(...),
    logo: UploadFile = File(...),
    category: str = Form(...),
    description: str = Form(None),
    email: EmailStr = Form(...),
    password: constr(min_length=8) = Form(...),
):
    # Generate a UUID for the account
    account_uuid = uuid.uuid4().hex

    # Hash the password securely
    hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode(
        "utf-8"
    )

    stmt = insert(table["account"]).values(
        uuid=account_uuid,
        email=email,
        password=hashed_password,
        role_id=2,
    )

    try:
        result = session.execute(stmt)
        session.commit()
        account_id = result.inserted_primary_key[0]

        create_organization(
            OrganizationModel(
                account_id=account_id,
                name=name,
                logo=logo,
                category=category,
                description=description,
                uuid=account_uuid,
            )
        )

        session.commit()
        return {"message": "Account created successfully", "uuid": account_uuid}
    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=400, detail="Email already exists")
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.delete("/uuid/{account_uuid}", tags=["Delete Account"])
async def delete_account_by_uuid(
    account_uuid: str = Path(..., description="The UUID of the account to delete"),
    session_token: str = Cookie(None),
):
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")
    # Use utility function to get account_uuid from session
    session_account_uuid = get_account_uuid_from_session(session_token)
    if session_account_uuid != account_uuid:
        raise HTTPException(
            status_code=403, detail="You are not authorized to delete this account"
        )
    # Proceed with deletion
    delete_stmt = (
        table["account"].delete().where(table["account"].c.uuid == account_uuid)
    )
    try:
        result = session.execute(delete_stmt)
        session.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Account not found")
        # Optionally, delete session after account deletion
        delete_session(session_token)
        return {"message": "Account deleted successfully"}
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.post("/user_signin", tags=["User Sign In"])
async def user_sign_in(
    email: EmailStr = Form(...),
    password: constr(min_length=8) = Form(...),
    request: Request = None,
    response: Response = None,
):
    # Find account by email
    stmt = select(table["account"]).where(table["account"].c.email == email)
    account_result = session.execute(stmt).first()
    if not account_result:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    account = account_result._mapping

    # Check password
    if not bcrypt.checkpw(
        password.encode("utf-8"), account["password"].encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Get user details linked to account, join resource for profile picture
    user_stmt = (
        select(
            table["user"].c.id,
            table["user"].c.account_id,
            table["user"].c.first_name,
            table["user"].c.last_name,
            table["user"].c.bio,
            table["account"].c.email,
            table["user"].c.profile_picture,
            table["resource"].c.directory.label("profile_picture_directory"),
            table["resource"].c.filename.label("profile_picture_filename"),
        )
        .select_from(
            table["user"].outerjoin(
                table["resource"],
                table["user"].c.profile_picture == table["resource"].c.id,
            )
        )
        .where(table["user"].c.account_id == account["id"])
    )
    user_result = session.execute(user_stmt).first()
    if not user_result:
        raise HTTPException(status_code=404, detail="User not found for this account")
    user = user_result._mapping

    # Create session and set cookie
    session_details = add_session(
        account_uuid=account["uuid"],
        request=request,
    )
    session_token = session_details["session_token"]
    expires_at = session_details["expires_at"]

    # response.set_cookie(
    #     key="session_token",
    #     value=session_token,
    #     httponly=True,
    #     secure=True,  # Set to True in production
    #     samesite="Lax",
    #     path="/",
    #     expires=expires_at,
    # )

    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=False,  # False for local HTTP development
        samesite="Lax",  # None for cross-origin cookies
        path="/",
        expires=expires_at,
    )

    # Return user details (do NOT return session token in body)
    return {
        "user": {
            "id": user["id"],
            "account_id": user["account_id"],
            "first_name": user["first_name"],
            "last_name": user["last_name"],
            "bio": user["bio"],
            "email": account["email"],
            "profile_picture": (
                {
                    "id": user["profile_picture"],
                    "directory": user["profile_picture_directory"],
                    "filename": user["profile_picture_filename"],
                }
                if user["profile_picture"]
                else None
            ),
            "uuid": account["uuid"],
            "role_id": account["role_id"],  # Include role_id from account table
        },
        "expires_at": expires_at.isoformat(),
    }


@router.post("/organization_signin", tags=["Organization Sign In"])
async def organization_sign_in(
    email: EmailStr = Form(...),
    password: constr(min_length=8) = Form(...),
    request: Request = None,
    response: Response = None,
):
    # Find account by email
    stmt = select(table["account"]).where(table["account"].c.email == email)
    account_result = session.execute(stmt).first()
    if not account_result:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    account = account_result._mapping

    # Check password
    if not bcrypt.checkpw(
        password.encode("utf-8"), account["password"].encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Get organization details linked to account, join resource for logo
    org_stmt = (
        select(
            table["organization"].c.id,
            table["organization"].c.account_id,
            table["organization"].c.name,
            table["organization"].c.logo,
            table["organization"].c.category,
            table["organization"].c.description,
            table["account"].c.email,
            table["resource"].c.directory.label("logo_directory"),
            table["resource"].c.filename.label("logo_filename"),
        )
        .select_from(
            table["organization"].outerjoin(
                table["resource"],
                table["organization"].c.logo == table["resource"].c.id,
            )
        )
        .where(table["organization"].c.account_id == account["id"])
    )
    org_result = session.execute(org_stmt).first()
    if not org_result:
        raise HTTPException(
            status_code=404, detail="Organization not found for this account"
        )
    organization = org_result._mapping

    # Create session and set cookie
    session_details = add_session(
        account_uuid=account["uuid"],
        request=request,
    )
    session_token = session_details["session_token"]
    expires_at = session_details["expires_at"]

    # response.set_cookie(
    #     key="session_token",
    #     value=session_token,
    #     httponly=True,
    #     secure=True,  # Set to True in production
    #     samesite="Lax",
    #     path="/",
    #     expires=expires_at,
    # )

    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=False,  # False for local HTTP development
        samesite="Lax",  # None for cross-origin cookies
        path="/",
        expires=expires_at,
    )

    # Return organization details (do NOT return session token in body)
    return {
        "organization": {
            "id": organization["id"],
            "account_id": organization["account_id"],
            "name": organization["name"],
            "email": account["email"],
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
            "uuid": account["uuid"],
            "role_id": account["role_id"],  # Include role_id from account table
        },
        "expires_at": expires_at.isoformat(),
    }


@router.post("/logout", tags=["Logout"])
async def logout(response: Response, session_token: str = Cookie(None)):
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")
    try:
        # Remove session from database
        session_deleted = delete_session(session_token)
        if session_deleted == 0:
            raise HTTPException(status_code=404, detail="Session not found")
        # Remove cookie from client
        response.delete_cookie(key="session_token", path="/")
        return {"message": "Successfully logged out"}
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
