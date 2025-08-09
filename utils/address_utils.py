from lib.database import Database
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

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
