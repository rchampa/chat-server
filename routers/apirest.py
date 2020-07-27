import os
import socket
from typing import List

import sqlalchemy
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from starlette.templating import Jinja2Templates

from RLog import rprint
from db.config import database, users_table, User

PORT = 9080
router = APIRouter()
templates = Jinja2Templates(directory="templates")


def get_local_ip() -> str:
    """
    copy and paste from
    https://stackoverflow.com/questions/166506/finding-local-ip-addresses-using-pythons-stdlib
    """
    if os.environ.get('CHAT_HOST_IP', False):
        return os.environ['CHAT_HOST_IP']
    try:
        ip = [l for l in (
            [ip for ip in socket.gethostbyname_ex(socket.gethostname())[2] if
             not ip.startswith("127.")][:1], [
                [(s.connect(('8.8.8.8', 53)), s.getsockname()[0], s.close()) for s
                 in
                 [socket.socket(socket.AF_INET, socket.SOCK_DGRAM)]][0][1]]) if l][0][0]
    except OSError as e:
        rprint(e)
        return '127.0.0.1'

    return ip


@router.get("/")
async def get(request: Request) -> Response:
    rprint("get request")
    return templates.TemplateResponse("chat.html",
                                      {"request": request,
                                       "ip": get_local_ip(),
                                       "port": PORT})


@router.get("/chat2")
async def get(request: Request) -> Response:
    rprint("get request")
    return templates.TemplateResponse("chat2.html",
                                      {"request": request,
                                       "ip": get_local_ip(),
                                       "port": PORT})


@router.get("/moderator")
async def get(request: Request) -> Response:
    return templates.TemplateResponse("moderator_chat.html",
                                      {"request": request,
                                       "ip": get_local_ip(),
                                       "port": PORT})


class NewUser(BaseModel):
    uuid: str
    alias: str


@router.post("/user/new")
async def post(new_user: NewUser) -> NewUser:
    query = users_table.insert().values(uuid=new_user.uuid, alias=new_user.alias)
    last_record_id = await database.execute(query)
    return new_user


class RequestConnection(BaseModel):
    uuid1: str
    uuid2: str


@router.post("/user", response_model=List[User])
async def post(request: RequestConnection) -> List[User]:
    """
    https://docs.sqlalchemy.org/en/13/core/tutorial.html
    """
    stmt = sqlalchemy.sql.text("select * from users where uuid=:u1 or uuid=:u2")
    stmt = stmt.bindparams(u1=request.uuid1, u2=request.uuid2)
    results = await database.fetch_all(stmt)
    return results
