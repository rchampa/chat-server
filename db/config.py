from typing import Optional

import databases
import sqlalchemy
from pydantic import BaseModel

from RLog import rprint

# SQLAlchemy specific code, as with any other app
DATABASE_URL = "postgresql://ricardo:ricardo@172.20.0.2:5432/chat_database"
database = databases.Database(DATABASE_URL)
metadata = sqlalchemy.MetaData()
notes = sqlalchemy.Table(
    "notes",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("text", sqlalchemy.String),
    sqlalchemy.Column("completed", sqlalchemy.Boolean),
)
users = sqlalchemy.Table(
    "users",
    metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
    sqlalchemy.Column("email", sqlalchemy.String(64), nullable=True),
    sqlalchemy.Column("uuid", sqlalchemy.String(32), nullable=False),
)
private = sqlalchemy.Table(
    "chats",
    metadata,
    sqlalchemy.Column("uuid", sqlalchemy.String(32), primary_key=True),
    sqlalchemy.Column("id1", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id"), nullable=False),
    sqlalchemy.Column("id2", sqlalchemy.Integer, sqlalchemy.ForeignKey("users.id"), nullable=False),
)
engine = sqlalchemy.create_engine(DATABASE_URL)
metadata.create_all(engine)
rprint("LOLAZOOOO")


class User(BaseModel):
    id: int
    email: Optional[str]
    uuid: str


class Chat(BaseModel):
    uuid: str
    id1: int
    id2: int


class NoteIn(BaseModel):
    text: str
    completed: bool


class Note(BaseModel):
    id: int
    text: str
    completed: bool

