import asyncio
import contextvars
from typing import List, Dict, Any, Optional
from datetime import datetime
from enum import Enum


import aioredis
import sqlalchemy
from aioredis import Redis
from aioredis.errors import ConnectionClosedError as ServerConnectionClosedError
from databases.backends.postgres import Record
from fastapi import APIRouter, Depends
from starlette.websockets import WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from RLog import rprint
from db.config import database

REDIS_HOST = 'redis'
REDIS_PORT = 6379
XREAD_TIMEOUT = 0
XREAD_COUNT = 100
NUM_PREVIOUS = 30
STREAM_MAX_LEN = 100
PORT = 9080
HOST = "0.0.0.0"
router = APIRouter()


class UserWS:
    def __init__(self, identifier: int, uuid: str, email: Optional[str], alias: str):
        self.identifier: int = identifier
        self.uuid: str = uuid
        self.alias: str = alias
        self.email: Optional[str] = email


class Chat2:
    def __init__(self, user1: UserWS, user2: UserWS):
        self.user1: UserWS = user1
        self.user2: UserWS = user2
        u1 = min(self.user1.identifier, self.user2.identifier)
        u2 = max(self.user1.identifier, self.user2.identifier)
        self.tenant_id = f"{u1}-{u2}"
        rprint("tenant_id: " + self.tenant_id)


class ConnectionState(Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"


class MessageType(Enum):
    ANNOUNCEMENT = "announcement"
    COMMENT = "comment"

# cvar_tenant = contextvars.ContextVar[str]('tenant', default=None)
# cvar_chat_info = contextvars.ContextVar[Chat2]('chat_info', default=None)


def _sql_to_user(result: Record) -> UserWS:
    if len(result.keys()) == 3:
        user = UserWS(result["id"], result["uuid"], None, result["alias"])
    else:
        user = UserWS(result["id"], result["uuid"], result["email"], result["alias"])
    return user


async def chat_info_vars(uuid1: str, uuid2: str) -> Optional[Chat2]:
    """
    URL parameter info needed for a user to participate in a chat
    :param uuid1:
    :type str:
    :param uuid2:
    :type str:
    """
    stmt = sqlalchemy.sql.text("select * from users where uuid=:u1")
    stmt = stmt.bindparams(u1=uuid1)
    result1 = await database.fetch_one(stmt)
    if result1 is None:
        return None

    stmt = sqlalchemy.sql.text("select * from users where uuid=:u2")
    stmt = stmt.bindparams(u2=uuid2)
    result2 = await database.fetch_one(stmt)
    if result2 is None:
        return None

    return Chat2(_sql_to_user(result1), _sql_to_user(result2))


# async def verify_user_for_room(chat_info: Chat2) -> bool:
#     """
#     Check for duplicated user names and if the room exist.
#     """
#     verified = True
#     pool: Redis = await get_redis_pool()
#     if not pool:
#         rprint('Redis connection failure')
#         return False
#     # check for duplicated user names
#     already_exists = await pool.sismember(cvar_tenant.get() + ":users", cvar_chat_info.get()['username'])
#     if already_exists:
#         rprint(chat_info['username'] + ' user already_exists in ' + chat_info['room'])
#         verified = False
#     # check for restricted names
#
#     # check for restricted rooms
#     # check for non existent rooms
#     # whitelist rooms
#     if not chat_info['room'] in ALLOWED_ROOMS:
#         verified = False
#     pool.close()
#     return verified


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, chat_info: Optional[Chat2] = Depends(chat_info_vars)) -> None:
    if chat_info is None:
        return

    chat_info: Chat2 = chat_info
    await websocket.accept()
    rprint("websocket_endpoint asyncio.gather")
    await asyncio.gather(ws_recieve(websocket, chat_info),
                         ws_send(websocket, chat_info))


async def get_redis_pool() -> Redis or None:
    try:
        pool: Redis = await aioredis.create_redis_pool((REDIS_HOST, REDIS_PORT), encoding='utf-8')
        return pool
    except ConnectionRefusedError as e:
        rprint('cannot connect to redis on:', REDIS_HOST, REDIS_PORT)
        return None


async def get_chat_history():
    pass


async def ws_recieve(websocket: WebSocket, chat_info: Chat2) -> None:
    """
    receive json data from client over a WebSocket, add messages onto the
    associated chat stream

    :param websocket:
    :type websocket:
    :param chat_info:
    :type Chat2:
    """
    rprint("ws_recieve first line")
    ws_connected = False
    pool: Redis = await get_redis_pool()
    # chat_info: Chat2 = cvar_chat_info.get()
    added: int = await add_connected_user(chat_info, pool)

    await announce(pool, chat_info, ConnectionState.CONNECTED)
    ws_connected = True

    while ws_connected:
        try:
            data = await websocket.receive_json()
            rprint("ws_recieve data=" + str(data))
            if type(data) == list and len(data):
                data = data[0]
            fields = {
                'uname': chat_info.user1.alias,
                'msg': data['msg'],
                'type': MessageType.COMMENT.value,
            }
            await pool.xadd(stream=chat_info.tenant_id + ":stream",
                            fields=fields,
                            message_id=b'*',
                            max_len=STREAM_MAX_LEN)
            #rprint('################contextvar ', cvar_tenant.get())
        except WebSocketDisconnect:
            await add_disconnected_user(chat_info, pool)
            await announce(pool, chat_info, ConnectionState.DISCONNECTED)
            ws_connected = False

        except ServerConnectionClosedError:
            rprint('redis server connection closed')
            return

        except ConnectionRefusedError:
            rprint('redis server connection closed')
            return

    pool.close()


async def ws_send(websocket: WebSocket, chat_info: Chat2) -> None:
    """
    wait for new items on chat stream and
    send data from server to client over a WebSocket

    :param websocket:
    :type websocket:
    :param chat_info:
    :type chat_info:
    """
    rprint("ws_send first line")
    pool = await get_redis_pool()
    latest_ids = ['$']
    ws_connected = True
    first_run = True
    while pool and ws_connected:
        try:
            rprint("ws_send first line loop")
            if first_run:
                rprint("ws_send first_run")
                # fetch some previous chat history
                events = await pool.xrevrange(
                    stream=chat_info.tenant_id + ":stream",
                    count=NUM_PREVIOUS,
                    start='+',
                    stop='-'
                )
                first_run = False
                events.reverse()
                for e_id, e in events:
                    e['e_id'] = e_id
                    rprint("ws_send first_run" + str(e))
                    await websocket.send_json(e)
            else:
                events = await pool.xread(
                    streams=[chat_info.tenant_id + ":stream"],
                    count=XREAD_COUNT,
                    timeout=XREAD_TIMEOUT,
                    latest_ids=latest_ids
                )
                # just for testing purposes

                rprint("ENVIANDO MENSAJES A: "+chat_info.user1.alias)
                ####################################
                for _, e_id, e in events:
                    e['e_id'] = e_id
                    rprint("ws_send e=" + str(e))
                    await websocket.send_json(e)
                    latest_ids = [e_id]
                    rprint("ws_send latest_ids = " + str(latest_ids))
            rprint("ws_send last line loop")
        except ConnectionClosedError:
            ws_connected = False

        except ConnectionClosedOK:
            ws_connected = False

        except ServerConnectionClosedError:
            rprint('redis server connection closed')
            return
    pool.close()


async def add_connected_user(chat_info: Chat2, pool: Redis) -> int:
    rprint("connected " + str(chat_info))
    added: int = await pool.sadd(f"{chat_info.tenant_id}:users", f"{chat_info.user1} connected at {datetime.utcnow()}")
    return added


async def add_disconnected_user(chat_info: Chat2, pool: Redis) -> int:
    rprint("disconnected " + str(chat_info))
    removed: int = await pool.srem(f"{chat_info.tenant_id}:users", f"{chat_info.user1} disconnected at {datetime.utcnow()}")
    return removed


# async def room_users(chat_info: dict, pool: Redis) -> List[str]:
#     rprint("room_users " + str(dict))
#     #users = await pool.smembers(chat_info['room']+":users")
#     users = await pool.smembers(cvar_tenant.get()+":users")
#     rprint(len(users))
#     return users


async def announce(pool: Redis, chat_info: Chat2, action: ConnectionState) -> None:
    """
    add an announcement event onto the redis chat stream
    """
    rprint("announce")
    fields = {
        'msg': f"{chat_info.user1.alias} {action}",
        'action': action.value,
        'type': 'announcement'
    }
    await pool.xadd(stream=f"{chat_info.tenant_id}:stream",
                    fields=fields,
                    message_id=b'*',
                    max_len=STREAM_MAX_LEN)
