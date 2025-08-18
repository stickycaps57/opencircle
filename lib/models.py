from pydantic import BaseModel, EmailStr, constr
from typing import Optional
from fastapi import UploadFile


class AccountModel(BaseModel):
    email: EmailStr
    password: constr(min_length=8)
    role_id: int
    profile_picture: Optional[bytes] = None


# TODO: add is_verified for email verification
class UserModel(BaseModel):
    account_id: int
    first_name: constr(min_length=1)
    last_name: constr(min_length=1)
    bio: Optional[str] = None
    profile_picture: Optional[UploadFile] = None  # TODO: change to string (path)
    uuid: str


# TODO: add is_verified for email verification
class OrganizationModel(BaseModel):
    account_id: int
    name: constr(min_length=1)
    logo: Optional[UploadFile] = None  # TODO: change to string (path)
    category: str
    description: Optional[str] = None
    uuid: str


class SessionModel(BaseModel):
    account_uuid: constr(min_length=32)


class PostModel(BaseModel):
    account_uuid: int
    account_id: Optional[int]
    image: Optional[UploadFile] = None
    description: Optional[str] = None


class EventModel(BaseModel):
    account_uuid: str
    title: constr(min_length=1)
    event_date: str
    country: str
    province: str
    city: str
    barangay: str
    house_building_number: str
    description: Optional[str] = None
    image: Optional[UploadFile] = None
    is_autoaccept: Optional[bool] = True
