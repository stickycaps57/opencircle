from fastapi import APIRouter, HTTPException, Path, UploadFile, File, Form
from pydantic import EmailStr, constr
from lib.database import Database
from lib.models import UserModel, OrganizationModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy import insert
import uuid
import bcrypt
from lib.database import Database
from utils.user_utils import create_user
from utils.organization_utils import create_organization

router = APIRouter(
    prefix="/account",
    tags=["Account Management"],
)

db = Database()
table = db.tables
session = db.session
engine = db.engine


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
    account_uuid: str = Path(..., description="The UUID of the account to delete")
):
    stmt = table["account"].delete().where(table["account"].c.uuid == account_uuid)
    try:
        result = session.execute(stmt)
        session.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Account not found")
        # TODO: double check if to cascade delete resource is needed
        return {"message": "Account deleted successfully"}
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
