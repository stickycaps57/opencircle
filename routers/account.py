from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, EmailStr, constr
from lib.database import Database
from sqlalchemy.exc import IntegrityError
from sqlalchemy import insert
import uuid
import bcrypt
from lib.database import Database

router = APIRouter(
    prefix="/account",
    tags=["account"],
)

db = Database()
table = db.tables
session = db.session
engine = db.engine


class AccountCredentials(BaseModel):
    email: EmailStr
    password: constr(min_length=8)
    role_id: int


@router.post("/", tags=["Create account"])
async def create_account(account: AccountCredentials):
    # Generate a UUID for the account
    account_uuid = uuid.uuid4().hex

    # Hash the password securely
    hashed_password = bcrypt.hashpw(
        account.password.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")

    stmt = insert(table["account"]).values(
        uuid=account_uuid,
        email=account.email,
        password=hashed_password,
        role_id=account.role_id,
    )

    try:
        session.execute(stmt)
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


@router.delete("/uuid/{account_uuid}", tags=["Delete account"])
async def delete_account_by_uuid(
    account_uuid: str = Path(..., description="The UUID of the account to delete")
):
    stmt = table["account"].delete().where(table["account"].c.uuid == account_uuid)
    try:
        result = session.execute(stmt)
        session.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Account not found")
        return {"message": "Account deleted successfully"}
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()
