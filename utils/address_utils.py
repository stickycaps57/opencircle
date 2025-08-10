from lib.database import Database
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import update

db = Database()
table = db.tables
session = db.session


def add_address(
    country: str,
    province: str,
    city: str,
    barangay: str,
    house_building_number: str,
):
    stmt = insert(table["address"]).values(
        country=country,
        province=province,
        city=city,
        barangay=barangay,
        house_building_number=house_building_number,
    )
    try:
        result = session.execute(stmt)
        session.commit()
        address_id = result.inserted_primary_key[0]
        return address_id
    except IntegrityError:
        session.rollback()
        raise
    except SQLAlchemyError as e:
        session.rollback()
        raise
    finally:
        session.close()


def update_address(
    address_id: int,
    country: str = None,
    province: str = None,
    city: str = None,
    barangay: str = None,
    house_building_number: str = None,
):

    update_values = {}
    if country is not None:
        update_values["country"] = country
    if province is not None:
        update_values["province"] = province
    if city is not None:
        update_values["city"] = city
    if barangay is not None:
        update_values["barangay"] = barangay
    if house_building_number is not None:
        update_values["house_building_number"] = house_building_number
    if not update_values:
        return False  # Nothing to update

    stmt = (
        update(table["address"])
        .where(table["address"].c.id == address_id)
        .values(**update_values)
    )
    try:
        result = session.execute(stmt)
        session.commit()
        return result.rowcount
    except Exception as e:
        session.rollback()
        raise
    finally:
        session.close()
