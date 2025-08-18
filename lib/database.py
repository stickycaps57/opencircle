from sqlalchemy import create_engine, MetaData, Table, Engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Dict


class Database:

    def __init__(self):
        self._engine = self._get_engine()
        self._session = self._get_session()
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

    @staticmethod
    def _get_db_config() -> Dict[str, str]:
        """Get database config from secret manager

        Returns:
            Dict[str, str]: database configuration
        """
        # TODO: Get credential from secret manager

        return {
            "username": "root",
            "password": "password",
            "host": "192.168.100.25",
            "port": "3306",
            "database": "opencircle",
        }

    def _get_connection_string(self) -> str:
        """Get connection string

        Returns:
            str: connection string
        """

        db_config = self._get_db_config()
        return (
            f"mysql+pymysql://{db_config['username']}:{db_config['password']}"
            f"@{db_config['host']}:{db_config['port']}/{db_config['database']}"
        )

    def _get_engine(self) -> Engine:
        """Get SQLAlchemy engine to connect to database

        Returns:
            Engine: SQLAlchemy engine
        """

        connection_string = self._get_connection_string()
        return create_engine(connection_string)

    def _get_session(self) -> Session:
        """Get SQLAlchemy session

        Returns:
            Session: SQLAlchemy session
        """

        engine = self.engine
        Session = sessionmaker(bind=engine)
        return Session()

    def _get_tables(self) -> Dict[str, Table]:
        """Get all tables created using SQLAlchemy Table.
        Used for session queries.

        Returns:
            Dict[str, Table]: All tables created using SQLAlchemy Table
        """

        metadata = MetaData()
        # Dynamically reflect all tables from the database
        metadata.reflect(bind=self.engine)
        return {
            table_name: Table(table_name, metadata, autoload_with=self.engine)
            for table_name in metadata.tables
        }
