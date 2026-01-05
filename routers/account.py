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
from sqlalchemy import insert, select, or_, update
import uuid
import bcrypt
from utils.user_utils import create_user
from utils.organization_utils import create_organization
from utils.two_factor_auth import TwoFactorAuth
from utils.email_otp import get_email_otp_service
import jwt
import os
from datetime import datetime, timedelta, timezone
from typing import Optional
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
    profile_picture: Optional[UploadFile] = File(None),
    email: EmailStr = Form(...),
    username: constr(min_length=3) = Form(...),
    password: constr(min_length=8) = Form(...),
):
    """
    Initiate user account creation with email OTP verification
    """
    # Check if email or username already exists
    check_stmt = select(table["account"]).where(
        or_(table["account"].c.email == email, table["account"].c.username == username)
    )
    existing_account = session.execute(check_stmt).first()
    if existing_account:
        if existing_account.email == email:
            raise HTTPException(status_code=400, detail="Email already exists")
        else:
            raise HTTPException(status_code=400, detail="Username already exists")

    try:
        # Generate a UUID for the account
        account_uuid = uuid.uuid4().hex

        # Hash the password securely
        hashed_password = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        # Generate and send OTP
        email_otp_service = get_email_otp_service()
        full_name = f"{first_name} {last_name}"
        otp_result = email_otp_service.generate_and_send_otp(email, "user", full_name)

        if not otp_result:
            raise HTTPException(
                status_code=500, detail="Failed to send verification email"
            )

        otp_code, otp_expires = otp_result

        # Create account record with OTP (but not verified yet)
        stmt = insert(table["account"]).values(
            uuid=account_uuid,
            email=email,
            username=username,
            password=hashed_password,
            role_id=1,
            email_otp_code=otp_code,
            email_otp_expires=otp_expires,
            email_verified=False,
            otp_attempts=0,
        )

        result = session.execute(stmt)
        session.commit()  # Commit the account first
        account_id = result.inserted_primary_key[0]

        # Now create the user record in a separate transaction
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

        return {
            "message": "Account created. Please check your email for a verification code.",
            "email": email,
            "verification_required": True,
            "next_step": "POST /account/verify-email-otp with your OTP code",
        }

    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=400, detail="Email or username already exists")
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.post("/organization", tags=["Create Organization Account"])
async def create_organization_account(
    name: constr(min_length=1) = Form(...),
    logo: Optional[UploadFile] = File(None),
    category: str = Form(...),
    description: str = Form(None),
    email: EmailStr = Form(...),
    username: constr(min_length=3) = Form(...),
    password: constr(min_length=8) = Form(...),
):
    """
    Initiate organization account creation with email OTP verification
    """
    # Check if email or username already exists
    check_stmt = select(table["account"]).where(
        or_(table["account"].c.email == email, table["account"].c.username == username)
    )
    existing_account = session.execute(check_stmt).first()
    if existing_account:
        if existing_account.email == email:
            raise HTTPException(status_code=400, detail="Email already exists")
        else:
            raise HTTPException(status_code=400, detail="Username already exists")

    try:
        # Generate a UUID for the account
        account_uuid = uuid.uuid4().hex

        # Hash the password securely
        hashed_password = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        # Generate and send OTP
        email_otp_service = get_email_otp_service()
        otp_result = email_otp_service.generate_and_send_otp(
            email, "organization", name
        )

        if not otp_result:
            raise HTTPException(
                status_code=500, detail="Failed to send verification email"
            )

        otp_code, otp_expires = otp_result

        # Create account record with OTP (but not verified yet)
        stmt = insert(table["account"]).values(
            uuid=account_uuid,
            email=email,
            username=username,
            password=hashed_password,
            role_id=2,
            email_otp_code=otp_code,
            email_otp_expires=otp_expires,
            email_verified=False,
            otp_attempts=0,
        )

        result = session.execute(stmt)
        session.commit()  # Commit the account first
        account_id = result.inserted_primary_key[0]

        # Now create the organization record in a separate transaction
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

        return {
            "message": "Organization account created. Please check your email for a verification code.",
            "email": email,
            "verification_required": True,
            "next_step": "POST /account/verify-email-otp with your OTP code",
        }

    except IntegrityError:
        session.rollback()
        raise HTTPException(status_code=400, detail="Email or username already exists")
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
    login: str = Form(..., description="Email or username"),
    password: constr(min_length=8) = Form(...),
    request: Request = None,
    response: Response = None,
):
    session = db.session
    # Find account by email or username
    stmt = select(table["account"]).where(
        or_(table["account"].c.email == login, table["account"].c.username == login)
    )
    account_result = session.execute(stmt).first()
    if not account_result:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    account = account_result._mapping

    # Check password
    if not bcrypt.checkpw(
        password.encode("utf-8"), account["password"].encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Check if email is verified
    if not account.get("email_verified", False):
        raise HTTPException(
            status_code=403,
            detail="Email not verified. Please check your email for verification code or request a new one.",
        )

    # Check if 2FA is enabled
    if account["two_factor_enabled"]:
        # Store account_uuid in a temporary session for 2FA verification
        temp_session_details = add_session(
            account_uuid=account["uuid"],
            request=request,
        )
        temp_session_token = temp_session_details["session_token"]
        is_production = os.environ.get("ENVIRONMENT") == "production"

        response.set_cookie(
            key="temp_session_token",
            value=temp_session_token,
            httponly=True,
            secure=is_production,
            samesite="None",  
            path="/",
            max_age=300,  # 5 minutes for 2FA verification
        )

        return {
            "requires_2fa": True,
            "message": "2FA verification required. Please provide TOTP token or backup code.",
            "account_type": "user",
        }

    # Get user details linked to account, join resource for profile picture
    user_stmt = (
        select(
            table["user"].c.id,
            table["user"].c.account_id,
            table["user"].c.first_name,
            table["user"].c.last_name,
            table["user"].c.bio,
            table["account"].c.email,
            table["account"].c.username,
            table["user"].c.profile_picture,
            table["resource"].c.directory.label("profile_picture_directory"),
            table["resource"].c.filename.label("profile_picture_filename"),
        )
        .select_from(
            table["user"]
            .join(
                table["account"],
                table["user"].c.account_id == table["account"].c.id,
            )
            .outerjoin(
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
    is_production = os.environ.get("ENVIRONMENT") == "production"

    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=is_production,  # True for HTTPS in production, False for local HTTP
        samesite="None",  
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
            "username": account["username"],
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
            "bypass_two_factor": account["bypass_two_factor"],
        },
        "expires_at": expires_at.isoformat(),
    }


@router.post("/organization_signin", tags=["Organization Sign In"])
async def organization_sign_in(
    login: str = Form(..., description="Email or username"),
    password: constr(min_length=8) = Form(...),
    request: Request = None,
    response: Response = None,
):
    # Find account by email or username
    stmt = select(table["account"]).where(
        or_(table["account"].c.email == login, table["account"].c.username == login)
    )
    account_result = session.execute(stmt).first()
    if not account_result:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    account = account_result._mapping

    # Check password
    if not bcrypt.checkpw(
        password.encode("utf-8"), account["password"].encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Check if email is verified
    if not account.get("email_verified", False):
        raise HTTPException(
            status_code=403,
            detail="Email not verified. Please check your email for verification code or request a new one.",
        )

    # Check if 2FA is enabled
    if account["two_factor_enabled"]:
        # Store account_uuid in a temporary session for 2FA verification
        temp_session_details = add_session(
            account_uuid=account["uuid"],
            request=request,
        )
        temp_session_token = temp_session_details["session_token"]
        is_production = os.environ.get("ENVIRONMENT") == "production"

        response.set_cookie(
            key="temp_session_token",
            value=temp_session_token,
            httponly=True,
            secure=is_production,
            samesite="None",  
            path="/",
            max_age=300,  # 5 minutes for 2FA verification
        )

        return {
            "requires_2fa": True,
            "message": "2FA verification required. Please provide TOTP token or backup code.",
            "account_type": "organization",
        }

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
            table["account"].c.username,
            table["resource"].c.directory.label("logo_directory"),
            table["resource"].c.filename.label("logo_filename"),
        )
        .select_from(
            table["organization"]
            .join(
                table["account"],
                table["organization"].c.account_id == table["account"].c.id,
            )
            .outerjoin(
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
    is_production = os.environ.get("ENVIRONMENT") == "production"

    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=is_production,  # True for HTTPS in production, False for local HTTP
        samesite="None",  
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
            "username": account["username"],
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
            "bypass_two_factor": account["bypass_two_factor"],
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


@router.get("/auth_user", tags=["Get Current User"])
async def get_current_user(session_token: str = Cookie(None)):
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")

    try:
        # Use utility function to get account_uuid from session
        account_uuid = get_account_uuid_from_session(session_token)

        # Get account details
        account_stmt = select(table["account"]).where(
            table["account"].c.uuid == account_uuid
        )
        account_result = session.execute(account_stmt).first()
        if not account_result:
            raise HTTPException(status_code=404, detail="Account not found")
        account = account_result._mapping

        # Check if user or organization based on role_id
        if account["role_id"] == 1:  # User
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
                    table["user"]
                    .join(
                        table["account"],
                        table["user"].c.account_id == table["account"].c.id,
                    )
                    .outerjoin(
                        table["resource"],
                        table["user"].c.profile_picture == table["resource"].c.id,
                    )
                )
                .where(table["user"].c.account_id == account["id"])
            )
            user_result = session.execute(user_stmt).first()
            if not user_result:
                raise HTTPException(
                    status_code=404, detail="User not found for this account"
                )
            user = user_result._mapping

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
                    "role_id": account["role_id"],
                    "bypass_two_factor": account["bypass_two_factor"],
                }
            }
        elif account["role_id"] == 2:  # Organization
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
                    table["organization"]
                    .join(
                        table["account"],
                        table["organization"].c.account_id == table["account"].c.id,
                    )
                    .outerjoin(
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
                    "role_id": account["role_id"],
                    "bypass_two_factor": account["bypass_two_factor"],
                }
            }
        else:
            raise HTTPException(status_code=400, detail="Unknown account type")
    except HTTPException as e:
        # Re-raise HTTP exceptions to preserve status code and detail
        raise e
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.post("/verify_2fa", tags=["Verify 2FA"])
async def verify_2fa(
    totp_token: str = Form(..., description="6-digit TOTP token or backup code"),
    account_type: str = Form(..., description="Account type: user or organization"),
    temp_session_token: str = Cookie(None, alias="temp_session_token"),
    request: Request = None,
    response: Response = None,
):
    """
    Verify 2FA token and complete login
    """

    if not temp_session_token:
        raise HTTPException(status_code=401, detail="Temporary session token missing")

    # Get account_uuid from temporary session
    account_uuid = get_account_uuid_from_session(temp_session_token)
    if not account_uuid:
        raise HTTPException(status_code=401, detail="Invalid temporary session token")

    try:
        # Get account details
        account_stmt = select(table["account"]).where(
            table["account"].c.uuid == account_uuid
        )
        account_result = session.execute(account_stmt).first()
        if not account_result:
            raise HTTPException(status_code=404, detail="Account not found")

        account = account_result._mapping

        # Verify that 2FA is enabled
        if not account["two_factor_enabled"]:
            raise HTTPException(
                status_code=400, detail="2FA is not enabled for this account"
            )

        # Verify TOTP token or backup code
        is_valid = False
        updated_backup_codes = account["backup_codes"]

        if len(totp_token) == 6 and totp_token.isdigit():
            # Verify TOTP token
            is_valid = TwoFactorAuth.verify_totp(account["totp_secret"], totp_token)
        else:
            # Try backup code
            is_valid, updated_backup_codes = TwoFactorAuth.verify_backup_code(
                account["backup_codes"], totp_token
            )

            # Update backup codes if one was used
            if is_valid and updated_backup_codes != account["backup_codes"]:
                update_stmt = (
                    update(table["account"])
                    .where(table["account"].c.uuid == account_uuid)
                    .values(backup_codes=updated_backup_codes)
                )
                session.execute(update_stmt)
                session.commit()

        if not is_valid:
            raise HTTPException(
                status_code=400, detail="Invalid TOTP token or backup code"
            )

        # Delete temporary session
        delete_session(temp_session_token)
        response.delete_cookie(key="temp_session_token", path="/")

        # Create new permanent session
        session_details = add_session(
            account_uuid=account["uuid"],
            request=request,
        )
        session_token = session_details["session_token"]
        expires_at = session_details["expires_at"]
        is_production = os.environ.get("ENVIRONMENT") == "production"

        response.set_cookie(
            key="session_token",
            value=session_token,
            httponly=True,
            secure=is_production,  # True for HTTPS in production, False for local HTTP
            samesite="None",  
            path="/",
            expires=expires_at,
        )

        # Return appropriate account details based on type
        if account_type == "member":
            # Get user details
            user_stmt = (
                select(
                    table["user"].c.id,
                    table["user"].c.account_id,
                    table["user"].c.first_name,
                    table["user"].c.last_name,
                    table["user"].c.bio,
                    table["account"].c.email,
                    table["account"].c.username,
                    table["user"].c.profile_picture,
                    table["resource"].c.directory.label("profile_picture_directory"),
                    table["resource"].c.filename.label("profile_picture_filename"),
                )
                .select_from(
                    table["user"]
                    .join(
                        table["account"],
                        table["user"].c.account_id == table["account"].c.id,
                    )
                    .outerjoin(
                        table["resource"],
                        table["user"].c.profile_picture == table["resource"].c.id,
                    )
                )
                .where(table["user"].c.account_id == account["id"])
            )
            user_result = session.execute(user_stmt).first()
            if not user_result:
                raise HTTPException(
                    status_code=404, detail="User not found for this account"
                )
            user = user_result._mapping

            return {
                "user": {
                    "id": user["id"],
                    "account_id": user["account_id"],
                    "first_name": user["first_name"],
                    "last_name": user["last_name"],
                    "bio": user["bio"],
                    "email": account["email"],
                    "username": account["username"],
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
                    "role_id": account["role_id"],
                    "bypass_two_factor": account["bypass_two_factor"],
                },
                "expires_at": expires_at.isoformat(),
            }

        elif account_type == "organization":
            # Get organization details
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
                    table["organization"]
                    .join(
                        table["account"],
                        table["organization"].c.account_id == table["account"].c.id,
                    )
                    .outerjoin(
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
                    "role_id": account["role_id"],
                    "bypass_two_factor": account["bypass_two_factor"],
                },
                "expires_at": expires_at.isoformat(),
            }
        else:
            raise HTTPException(status_code=400, detail="Invalid account type")

    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.post("/verify-email-otp", tags=["Verify Email OTP"])
async def verify_email_otp(
    email: EmailStr = Form(...),
    otp_code: str = Form(..., description="6-digit OTP code from email"),
):
    """
    Verify email OTP and activate account
    """
    try:
        # Find account by email
        account_stmt = select(table["account"]).where(table["account"].c.email == email)
        account_result = session.execute(account_stmt).first()

        if not account_result:
            raise HTTPException(status_code=404, detail="Account not found")

        account = account_result._mapping

        # Check if account is already verified
        if account["email_verified"]:
            raise HTTPException(status_code=400, detail="Account is already verified")

        # Check OTP attempts
        if account["otp_attempts"] >= 5:
            raise HTTPException(
                status_code=429,
                detail="Too many verification attempts. Please request a new OTP code.",
            )

        # Get email OTP service
        email_otp_service = get_email_otp_service()

        # Verify OTP
        is_valid = email_otp_service.verify_otp(
            otp_code, account["email_otp_code"], account["email_otp_expires"]
        )

        if not is_valid:
            # Increment failed attempts
            update_attempts_stmt = (
                update(table["account"])
                .where(table["account"].c.email == email)
                .values(otp_attempts=account["otp_attempts"] + 1)
            )
            session.execute(update_attempts_stmt)
            session.commit()

            remaining_attempts = 5 - (account["otp_attempts"] + 1)
            if remaining_attempts <= 0:
                raise HTTPException(
                    status_code=429,
                    detail="Too many verification attempts. Please request a new OTP code.",
                )
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid or expired OTP code. {remaining_attempts} attempts remaining.",
                )

        # OTP is valid - activate the account
        update_stmt = (
            update(table["account"])
            .where(table["account"].c.email == email)
            .values(
                email_verified=True,
                email_otp_code=None,
                email_otp_expires=None,
                otp_attempts=0,
            )
        )
        session.execute(update_stmt)
        session.commit()

        # Determine account type for response
        account_type = "user" if account["role_id"] == 1 else "organization"

        return {
            "message": f"Email verified successfully! Your {account_type} account is now active.",
            "email_verified": True,
            "account_type": account_type,
            "next_step": f"You can now login using POST /account/{account_type}_signin",
        }

    except HTTPException as e:
        # Re-raise HTTP exceptions to preserve status code and detail
        raise e
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.post("/resend-email-otp", tags=["Resend Email OTP"])
async def resend_email_otp(
    email: EmailStr = Form(...),
):
    """
    Resend email OTP for account verification
    """
    try:
        # Find account by email
        account_stmt = select(table["account"]).where(table["account"].c.email == email)
        account_result = session.execute(account_stmt).first()

        if not account_result:
            raise HTTPException(status_code=404, detail="Account not found")

        account = account_result._mapping

        # Check if account is already verified
        if account["email_verified"]:
            raise HTTPException(status_code=400, detail="Account is already verified")

        # Get account details for email
        if account["role_id"] == 1:  # User
            # Get user name
            user_stmt = select(table["user"]).where(
                table["user"].c.account_id == account["id"]
            )
            user_result = session.execute(user_stmt).first()
            if not user_result:
                raise HTTPException(status_code=404, detail="User details not found")
            user = user_result._mapping
            name = f"{user['first_name']} {user['last_name']}"
            account_type = "user"
        else:  # Organization
            # Get organization name
            org_stmt = select(table["organization"]).where(
                table["organization"].c.account_id == account["id"]
            )
            org_result = session.execute(org_stmt).first()
            if not org_result:
                raise HTTPException(
                    status_code=404, detail="Organization details not found"
                )
            org = org_result._mapping
            name = org["name"]
            account_type = "organization"

        # Generate new OTP
        email_otp_service = get_email_otp_service()
        otp_result = email_otp_service.generate_and_send_otp(email, account_type, name)

        if not otp_result:
            raise HTTPException(
                status_code=500, detail="Failed to send verification email"
            )

        otp_code, otp_expires = otp_result

        # Update account with new OTP
        update_stmt = (
            update(table["account"])
            .where(table["account"].c.email == email)
            .values(
                email_otp_code=otp_code,
                email_otp_expires=otp_expires,
                otp_attempts=0,  # Reset attempts with new OTP
            )
        )
        session.execute(update_stmt)
        session.commit()

        return {
            "message": "New verification code sent to your email",
            "email": email,
            "next_step": "POST /account/verify-email-otp with your new OTP code",
        }

    except HTTPException as e:
        # Re-raise HTTP exceptions to preserve status code and detail
        raise e
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()