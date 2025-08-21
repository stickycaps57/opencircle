from sqlalchemy import create_engine, MetaData, Table, Engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Dict


def get_db_config() -> Dict[str, str]:
    # TODO: Get credential from secret manager
    return {
        "username": "root",
        "password": "password",
        "host": "192.168.100.25",
        "port": "3306",
        "database": "opencircle",
    }


def get_connection_string() -> str:
    db_config = get_db_config()
    return (
        f"mysql+pymysql://{db_config['username']}:{db_config['password']}"
        f"@{db_config['host']}:{db_config['port']}/{db_config['database']}"
    )


# Instantiate the engine ONCE at module level
engine: Engine = create_engine(get_connection_string())

SessionLocal = sessionmaker(bind=engine)


class Database:
    def __init__(self):
        self._engine = engine
        self._session = SessionLocal()
        self._tables = self._get_tables()

    @property
    def engine(self) -> Engine:
        return self._engine

    @property
    def session(self) -> Session:
        return self._session

    @property
    def tables(self) -> Dict[str, Table]:
        return self._tables

    def _get_tables(self) -> Dict[str, Table]:
        metadata = MetaData()
        metadata.reflect(bind=self.engine)
        return {
            table_name: Table(table_name, metadata, autoload_with=self.engine)
            for table_name in metadata.tables
        }
