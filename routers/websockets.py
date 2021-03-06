import asyncio
import contextvars
import uuid
from typing import List, Dict

import aioredis
from aioredis import Redis
from aioredis.errors import ConnectionClosedError as ServerConnectionClosedError
from fastapi import APIRouter, Depends
from starlette.websockets import WebSocket, WebSocketDisconnect
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from RLog import rprint

REDIS_HOST = 'redis'
REDIS_PORT = 6379
XREAD_TIMEOUT = 0
XREAD_COUNT = 100
NUM_PREVIOUS = 30
STREAM_MAX_LEN = 100
ALLOWED_ROOMS = ['chat:1', 'chat:2', 'chat:3', 'chat:4', 'chat:5']
PORT = 9080
HOST = "0.0.0.0"
router = APIRouter()

cvar_tenant = contextvars.ContextVar[str]('tenant', default=None)
cvar_chat_info = contextvars.ContextVar[dict]('chat_info', default=None)


async def chat_info_vars(username: str = None, room: str = None) -> Dict[str, str]:
    """
    URL parameter info needed for a user to participate in a chat
    :param username:
    :type username:
    :param room:
    :type room:
    """
    if username is None and room is None:
        return {"username": str(uuid.uuid4()), "room": 'chat:1'}
    return {"username": username, "room": room}


async def verify_user_for_room(chat_info: dict) -> bool:
    """
    Check for duplicated user names and if the room exist.
    """
    verified = True
    pool: Redis = await get_redis_pool()
    if not pool:
        rprint('Redis connection failure')
        return False
    # check for duplicated user names
    already_exists = await pool.sismember(cvar_tenant.get() + ":users", cvar_chat_info.get()['username'])
    if already_exists:
        rprint(chat_info['username'] + ' user already_exists in ' + chat_info['room'])
        verified = False
    # check for restricted names

    # check for restricted rooms
    # check for non existent rooms
    # whitelist rooms
    if not chat_info['room'] in ALLOWED_ROOMS:
        verified = False
    pool.close()
    return verified


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, chat_info: dict = Depends(chat_info_vars)) -> None:
    tenant_id: str = ":".join([websocket.url.hostname.replace('.', '_'), chat_info['room']])
    rprint("tenant_id: " + tenant_id)
    cvar_tenant.set(tenant_id)
    cvar_chat_info.set(chat_info)

    # check the user is allowed into the chat room
    verified = await verify_user_for_room(chat_info)
    # open connection
    await websocket.accept()
    if not verified:
        rprint('failed verification')
        rprint(chat_info)
        await websocket.close()
    else:
        # spin up coro's for inbound and outbound communication over the socket
        rprint("websocket_endpoint asyncio.gather")
        await asyncio.gather(ws_recieve(websocket, chat_info),
                             ws_send(websocket, chat_info))


@router.websocket("/ws/moderator")
async def websocket_moderator_endpoint(websocket: WebSocket, chat_info: dict = Depends(chat_info_vars)) -> None:
    # check the user is allowed into the chat room
    # verified = await verify_user_for_room(chat_info)
    # open connection

    if not chat_info['username'] == 'moderator':
        rprint('failed verification')
        await websocket.close()
        return

    await websocket.accept()
    # spin up coro's for inbound and outbound communication over the socket
    await asyncio.gather(ws_send_moderator(websocket, chat_info))


async def get_redis_pool() -> Redis or None:
    try:
        pool: Redis = await aioredis.create_redis_pool((REDIS_HOST, REDIS_PORT), encoding='utf-8')
        return pool
    except ConnectionRefusedError as e:
        rprint('cannot connect to redis on:', REDIS_HOST, REDIS_PORT)
        return None


async def get_chat_history():
    pass


async def ws_send_moderator(websocket: WebSocket, chat_info: dict) -> None:
    """
    wait for new items on chat stream and
    send data from server to client over a WebSocket

    :param websocket:
    :type websocket:
    :param chat_info:
    :type chat_info:
    """
    pool: Redis = await get_redis_pool()
    streams = chat_info['room'].split(',')
    latest_ids = ['$' for i in streams]
    ws_connected = True
    rprint(streams, latest_ids)
    while pool and ws_connected:
        try:
            events = await pool.xread(
                streams=streams,
                count=XREAD_COUNT,
                timeout=XREAD_TIMEOUT,
                latest_ids=latest_ids
            )
            for _, e_id, e in events:
                e['e_id'] = e_id
                await websocket.send_json(e)
                #latest_ids = [e_id]
        except ConnectionClosedError:
            ws_connected = False

        except ConnectionClosedOK:
            ws_connected = False


async def ws_recieve(websocket: WebSocket, chat_info: dict) -> None:
    """
    receive json data from client over a WebSocket, add messages onto the
    associated chat stream

    :param websocket:
    :type websocket:
    :param chat_info:
    :type chat_info:
    """
    rprint("ws_recieve first line")
    ws_connected = False
    pool: Redis = await get_redis_pool()
    added: int = await add_room_user(chat_info, pool)

    if added:
        await announce(pool, chat_info, 'connected')
        ws_connected = True
    else:
        rprint('duplicate user error')

    while ws_connected:
        try:
            data = await websocket.receive_json()
            rprint("ws_recieve data=" + str(data))
            if type(data) == list and len(data):
                data = data[0]
            fields = {
                'uname': chat_info['username'],
                'msg': data['msg'],
                'type': 'comment',
                'room': chat_info['room']
            }
            await pool.xadd(stream=cvar_tenant.get() + ":stream",
                            fields=fields,
                            message_id=b'*',
                            max_len=STREAM_MAX_LEN)
            #rprint('################contextvar ', cvar_tenant.get())
        except WebSocketDisconnect:
            await remove_room_user(chat_info, pool)
            await announce(pool, chat_info, 'disconnected')
            ws_connected = False

        except ServerConnectionClosedError:
            rprint('redis server connection closed')
            return

        except ConnectionRefusedError:
            rprint('redis server connection closed')
            return

    pool.close()


async def ws_send(websocket: WebSocket, chat_info: dict) -> None:
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
                    stream=cvar_tenant.get() + ":stream",
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
                    streams=[cvar_tenant.get() + ":stream"],
                    count=XREAD_COUNT,
                    timeout=XREAD_TIMEOUT,
                    latest_ids=latest_ids
                )
                # just for testing purposes

                rprint("ENVIANDO MENSAJES A: "+cvar_chat_info.get()['username'])
                ####################################
                for _, e_id, e in events:
                    e['e_id'] = e_id
                    rprint("ws_send e=" + str(e))
                    await websocket.send_json(e)
                    latest_ids = [e_id]
                    rprint("ws_send latest_ids = " + str(latest_ids))
            rprint("ws_send last line loop")
            #rprint('################contextvar ', cvar_tenant.get())
        except ConnectionClosedError:
            ws_connected = False

        except ConnectionClosedOK:
            ws_connected = False

        except ServerConnectionClosedError:
            rprint('redis server connection closed')
            return
    pool.close()


async def add_room_user(chat_info: dict, pool: Redis) -> int:
    rprint("add_room_user " + str(chat_info))
    #added; int = await pool.sadd(chat_info['room']+":users", chat_info['username'])
    added: int = await pool.sadd(cvar_tenant.get()+":users", cvar_chat_info.get()['username'])
    return added


async def remove_room_user(chat_info: dict, pool: Redis) -> int:
    rprint("remove_room_user " + str(chat_info))
    #removed = await pool.srem(chat_info['room']+":users", chat_info['username'])
    removed: int = await pool.srem(cvar_tenant.get()+":users", cvar_chat_info.get()['username'])
    return removed


async def room_users(chat_info: dict, pool: Redis) -> List[str]:
    rprint("room_users " + str(dict))
    #users = await pool.smembers(chat_info['room']+":users")
    users = await pool.smembers(cvar_tenant.get()+":users")
    rprint(len(users))
    return users


async def announce(pool: Redis, chat_info: dict, action: str) -> None:
    """
    add an announcement event onto the redis chat stream
    """
    rprint("announce")
    users = await room_users(chat_info, pool)
    fields = {
        'msg': f"{chat_info['username']} {action}",
        'action': action,
        'type': 'announcement',
        'users': ", ".join(users),
        'room': chat_info['room']
    }
    #rprint(fields)

    await pool.xadd(stream=cvar_tenant.get() + ":stream",
                    fields=fields,
                    message_id=b'*',
                    max_len=STREAM_MAX_LEN)
