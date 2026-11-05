import os

import psycopg
from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

# The database is the one app.db.migrate passes, else DATABASE_URL (the alembic command line). psycopg connects with it as it is, so
# whatever it holds (a URI, keywords, the search_path option of the tests) is used; there is no offline (--sql) mode.
dsn = context.config.attributes.get("dsn") or os.environ["DATABASE_URL"]
engine = create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(dsn), poolclass=NullPool)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=None)  # no models: the migrations are written by hand
    with context.begin_transaction():
        context.run_migrations()
