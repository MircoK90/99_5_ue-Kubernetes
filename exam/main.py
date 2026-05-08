"""
User API — talks to a MySQL database that runs as a sidecar container
in the same Pod, so it is reachable on localhost.

The MySQL root password is NOT hardcoded — it is injected into this
container via an environment variable, which itself is sourced from
a Kubernetes Secret (see my-secret-eval.yml + my-deployment-eval.yml).
"""
import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, text


# Create the FastAPI server
server = FastAPI(title='User API')


# === Database connection settings ===
# Both the API container and the MySQL container live in the SAME Pod.
# Containers in the same Pod share the network namespace, so the DB
# is reachable on localhost / 127.0.0.1.
mysql_url = '127.0.0.1:3306'
mysql_user = 'root'

# The password is read from an env var that Kubernetes injects from a Secret.
# We fall back to '' if the variable is missing — this lets the API start
# (so probes can hit /status) and only fails on the first DB call.
mysql_password = os.environ.get('MYSQL_ROOT_PASSWORD', '')

database_name = 'Main'

# Build the SQLAlchemy connection URL.
# We pin the driver explicitly (mysql+mysqldb) for forward compatibility
# with newer SQLAlchemy versions that no longer auto-pick a default driver.
connection_url = 'mysql+mysqldb://{user}:{password}@{url}/{database}'.format(
    user=mysql_user,
    password=mysql_password,
    url=mysql_url,
    database=database_name,
)

# Create the SQLAlchemy engine (lazy — does not connect until first query).
mysql_engine = create_engine(connection_url)


class User(BaseModel):
    user_id: int = 0
    username: str = 'daniel'
    email: str = 'daniel@datascientest.com'


@server.get('/status')
async def get_status():
    """Returns 1 if the API is up. Used by liveness/readiness probes too."""
    return 1


@server.get('/users')
async def get_users():
    """Return all users from the Users table."""
    # text() wraps raw SQL — required by SQLAlchemy 1.4+ / 2.x.
    with mysql_engine.connect() as connection:
        results = connection.execute(text('SELECT * FROM Users;'))
        rows = results.fetchall()

    return [
        User(user_id=row[0], username=row[1], email=row[2])
        for row in rows
    ]


@server.get('/users/{user_id:int}', response_model=User)
async def get_user(user_id: int):
    """Return a single user by ID, or 404 if not found."""
    # Parameterised query — never format SQL strings with user input
    # (the original code was vulnerable to SQL injection).
    with mysql_engine.connect() as connection:
        results = connection.execute(
            text('SELECT * FROM Users WHERE Users.id = :uid'),
            {'uid': user_id},
        )
        rows = results.fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail='Unknown User ID')

    row = rows[0]
    return User(user_id=row[0], username=row[1], email=row[2])
