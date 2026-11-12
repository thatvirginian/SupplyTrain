# =============================================================================
# backend/core/database.py
# =============================================================================
# The one SQLAlchemy engine (Postgres on Azure) and the helper every route uses
# to reach it. Connection settings come from environment variables / .env:
#   PGUSER, PGPASSWORD, PGHOST, PGPORT, PGDATABASE
# =============================================================================

import os
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from dotenv import load_dotenv

load_dotenv(override=True)

connection_url = URL.create(
    drivername="postgresql+psycopg2",
    username=os.getenv("PGUSER"),
    password=os.getenv("PGPASSWORD"),
    host=os.getenv("PGHOST"),
    port=os.getenv("PGPORT"),
    database=os.getenv("PGDATABASE"),
    query={"sslmode": "require"},
)

engine = create_engine(
    connection_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)


def get_engine():
    """The engine for the running app (app.py stores it in app.config['ENGINE'])."""
    from flask import current_app
    return current_app.config['ENGINE']
