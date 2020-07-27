from typing import Optional

import databases
import sqlalchemy
from pydantic import BaseModel

from RLog import rprint

import logging

logging.basicConfig()
logging.getLogger('sqlalchemy.engine').setLevel(logging.DEBUG)

# SQLAlchemy specific code, as with any other app
DATABASE_URL = "postgresql://ricardo:ricardo@172.20.0.2:5432/chat_database"
database = databases.Database(DATABASE_URL)
metadata = sqlalchemy.MetaData()
users_table = sqlalchemy.Table(
    "users",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("alias", sqlalchemy.String(16), nullable=False),
    sqlalchemy.Column("email", sqlalchemy.String(64), nullable=True),
    sqlalchemy.Column("uuid", sqlalchemy.String(32), nullable=False),
)
# chats_table = sqlalchemy.Table(
#     "chats",
#     metadata,
#     sqlalchemy.Column("uuid", sqlalchemy.String(32), primary_key=True),
#     sqlalchemy.Column("id1", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id"), nullable=False),
#     sqlalchemy.Column("id2", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id"), nullable=False),
# )

engine = sqlalchemy.create_engine(DATABASE_URL)
metadata.create_all(engine)
rprint("LOLAZOOOO")


class User(BaseModel):
    id: int
    alias: str
    email: Optional[str]
    uuid: str

    def __init__(self, _id, alias, email, uuid):
        self.id = _id
        self.alias = alias
        self.email = email
        self.uuid = uuid


class Chat(BaseModel):
    uuid: str
    id1: int
    id2: int

