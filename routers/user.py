from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, constr
from lib.database import Database
from sqlalchemy.exc import IntegrityError
from sqlalchemy import insert
from typing import Optional
from utils.resource_utils import add_resource, delete_resource, get_resource


router = APIRouter(
    prefix="/user",
    tags=["user"],
)

db = Database()
table = db.tables
session = db.session


class UserCreate(BaseModel):
    account_id: int
    first_name: constr(min_length=1)
    last_name: constr(min_length=1)
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
