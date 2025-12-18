from sqlalchemy import create_engine, MetaData, Table, Engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Dict
import os


def get_db_config() -> Dict[str, str]:
    return {
        "username": os.getenv("DB_USERNAME"),
        "password": os.getenv("DB_PASSWORD"),
        "host": os.getenv("DB_HOST"),
        "port": os.getenv("DB_PORT"),
        "database": os.getenv("DB_NAME"),
    }

def get_connection_string() -> str:
    db_config = get_db_config()
    
    # Add SSL parameters for cloud databases
    ssl_disabled = os.getenv("DB_SSL_DISABLED", "false").lower() == "true"
    
    base_url = (
        f"mysql+pymysql://{db_config['username']}:{db_config['password']}"
        f"@{db_config['host']}:{db_config['port']}/{db_config['database']}"
    )
    
    # Add SSL parameters if SSL is enabled (default for cloud databases)
    if not ssl_disabled:
        return f"{base_url}?ssl_disabled=false"
    else:
        return f"{base_url}?ssl_disabled=true"


# Instantiate the engine ONCE at module level
ssl_disabled = os.getenv("DB_SSL_DISABLED", "false").lower() == "true"

if ssl_disabled:
    # For local development without SSL
    engine: Engine = create_engine(get_connection_string())
else:
    # For cloud databases with SSL
    engine: Engine = create_engine(
        get_connection_string(),
        connect_args={"ssl_disabled": False}
    )

SessionLocal = sessionmaker(bind=engine)


class Database:
    def __init__(self):
        self._engine = engine
        # commented this line since it always get old or stale data
        # self._session = SessionLocal()
        self._tables = self._get_tables()

    @property
    def engine(self) -> Engine:
        return self._engine

    @property
    def session(self) -> Session:
        # return self._session
        # added this line to get fresh data
        return SessionLocal()

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
