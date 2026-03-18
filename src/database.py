from asyncpg import Pool, create_pool
from asyncpg.pool import PoolAcquireContext
from asyncpg.connection import Connection
from abc import ABC, abstractmethod

from config import DB_HOST, DB_NAME, DB_PASS, DB_PORT, DB_USER

db_pool: Pool | None = None


class ConnProxy(ABC, PoolAcquireContext):
    @abstractmethod
    async def __aenter__(self) -> Connection:
        raise NotImplementedError()


async def create_db_pool():
    global db_pool
    db_pool = await create_pool(
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS,
        host=DB_HOST,
        port=int(DB_PORT),
        min_size=1,
        max_size=10,
    )


def get_pool() -> Pool:
    if db_pool is None:
        raise RuntimeError("DB pool is not initialized")
    return db_pool


def db_conn() -> ConnProxy:
    return get_pool().acquire()


async def fetchval(query: str, *args):
    async with db_conn() as conn:
        return await conn.fetchval(query, *args)


async def fetchrow(query: str, *args):
    async with db_conn() as conn:
        return await conn.fetchrow(query, *args)


async def fetch(query: str, *args):
    async with db_conn() as conn:
        return await conn.fetch(query, *args)


async def execute(query: str, *args):
    async with db_conn() as conn:
        return await conn.execute(query, *args)


async def executemany(query: str, args_list):
    async with db_conn() as conn:
        async with conn.transaction():
            await conn.executemany(query, args_list)
