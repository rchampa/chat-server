import asyncio
import contextvars
import aioredis
import uvloop
from aioredis import Redis
from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.staticfiles import StaticFiles
from RLog import rprint
from routers import apirest, websockets
from db.config import database

REDIS_HOST = 'redis'
REDIS_PORT = 6379
PORT = 9080
HOST = "0.0.0.0"
cvar_redis = contextvars.ContextVar('redis', default=None)


class CustomHeaderMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, header_value='Example'):
        rprint('__init__')
        super().__init__(app)
        self.header_value = header_value

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers['Custom'] = self.header_value
        return response


# uvloop is written in Cython and is built on top of libuv  http://magic.io/blog/uvloop-blazing-fast-python-networking/
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
app.add_middleware(CustomHeaderMiddleware)
app.include_router(apirest.router)
app.include_router(websockets.router)


@app.on_event("startup")
async def handle_startup() -> None:
    rprint("startup")
    await database.connect()
    try:
        pool = await aioredis.create_redis_pool((REDIS_HOST, REDIS_PORT), encoding='utf-8', maxsize=20)
        cvar_redis.set(pool)
        rprint("Connected to Redis on ", REDIS_HOST, REDIS_PORT)
    except ConnectionRefusedError as e:
        rprint('cannot connect to redis on:', REDIS_HOST, REDIS_PORT)
        return


@app.on_event("shutdown")
async def handle_shutdown() -> None:
    await database.disconnect()
    rprint("shutdown: database.disconnect")
    if cvar_redis.get() is not None:
        redis: Redis = cvar_redis.get()
        redis.close()
        await redis.wait_closed()
        rprint("closed connection Redis on ", REDIS_HOST, REDIS_PORT)
    else:
        rprint("ERROR: cvar_redis.get() devuelve NONE")


if __name__ == "__main__":
    import uvicorn
    rprint("Starting app")
    rprint(dir(app))
    rprint(app.url_path_for('websocket_endpoint'))
    uvicorn.run('chat:app', host=HOST, port=PORT, log_level='info', reload=True)#, uds='uvicorn.sock')
