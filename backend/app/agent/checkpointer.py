"""LangGraph PostgreSQL checkpointer 的构造、加密与生命周期。

这里只回答"怎么连、怎么加密、怎么建表"，不含任何编排逻辑；
编排层什么时候读写 checkpoint 是后续阶段的事。

两条硬规则：

1. 加密用官方 ``EncryptedSerializer``，不自研密文格式；
2. 清理 thread 用官方 ``delete_thread``，业务代码不碰 checkpoint 内部表。
"""

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.base import SerializerProtocol
from langgraph.checkpoint.serde.encrypted import EncryptedSerializer
from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from app.core.config import AES_KEY_SIZES, settings

logger = logging.getLogger(__name__)

# checkpointer 要求连接是 autocommit + dict_row，且不要用预备语句。
# 取自官方 PostgresSaver.from_conn_string 的连接参数。
CONNECTION_KWARGS = {
    "autocommit": True,
    "prepare_threshold": 0,
    "row_factory": dict_row,
}

# setup() 只允许创建这四张属于 checkpointer 自己的表。
CHECKPOINT_TABLES = (
    "checkpoint_blobs",
    "checkpoint_migrations",
    "checkpoint_writes",
    "checkpoints",
)


class CheckpointNotConfiguredError(RuntimeError):
    pass


def checkpoint_thread_id(user_id: uuid.UUID, conversation_id: str) -> str:
    """用户前缀是 checkpoint 的租户边界。"""
    return f"{user_id}:{conversation_id}"


def encryption_key() -> bytes:
    """取出 checkpoint 加密密钥。

    启动时的强制检查在 Settings._enforce_checkpoint_encryption：local 之外
    没有密钥根本起不来。这里是第二道——任何真的要写 checkpoint 的路径，
    没有密钥就抛错，绝不"没配就明文存"。
    """
    raw = settings.CHECKPOINT_ENCRYPTION_KEY
    if not raw:
        raise CheckpointNotConfiguredError(
            "CHECKPOINT_ENCRYPTION_KEY 未配置。checkpoint 会存下完整对话与"
            "工具结果，必须加密；请配置 16、24 或 32 字节的密钥。"
        )
    key = raw.encode("utf-8")
    if len(key) not in AES_KEY_SIZES:
        raise CheckpointNotConfiguredError(
            f"CHECKPOINT_ENCRYPTION_KEY 必须是 16、24 或 32 字节，当前为 {len(key)}。"
        )
    return key


def build_serde() -> SerializerProtocol:
    """官方 AES 序列化器，密文落库。"""
    return EncryptedSerializer.from_pycryptodome_aes(key=encryption_key())


def build_pool(
    *, min_size: int = 1, max_size: int = 10
) -> ConnectionPool[Connection[DictRow]]:
    """checkpointer 专用连接池，与 SQLAlchemy 的 engine 相互独立。"""
    return ConnectionPool(
        conninfo=settings.CHECKPOINT_DATABASE_URI,
        min_size=min_size,
        max_size=max_size,
        kwargs=CONNECTION_KWARGS,
        open=False,
    )


@contextmanager
def open_checkpointer(
    *, min_size: int = 1, max_size: int = 10
) -> Iterator[PostgresSaver]:
    """开一个带连接池的 checkpointer，退出时关闭连接池。

    应用内应当在 lifespan 里持有它，避免每个请求都新建连接。
    """
    pool = build_pool(min_size=min_size, max_size=max_size)
    pool.open(wait=True)
    try:
        yield PostgresSaver(pool, serde=build_serde())
    finally:
        pool.close()


_pool: ConnectionPool[Connection[DictRow]] | None = None
_saver: PostgresSaver | None = None


def get_checkpointer() -> PostgresSaver:
    """应用进程内共用的 checkpointer。

    连接池只建一次：每个请求新建连接会把数据库连接数打满。
    """
    global _pool, _saver
    if _saver is None:
        _pool = build_pool()
        _pool.open(wait=True)
        _saver = PostgresSaver(_pool, serde=build_serde())
    return _saver


def close_checkpointer() -> None:
    global _pool, _saver
    if _pool is not None:
        _pool.close()
    _pool, _saver = None, None


def run_setup() -> None:
    """建表。作为受控部署步骤执行，不在请求路径或 lifespan 里调用。

    多 worker 同时建表会互相撞锁，所以这一步必须独占执行一次。
    """
    with open_checkpointer(min_size=1, max_size=1) as saver:
        saver.setup()
    logger.info("checkpoint 内部表已就绪（%d 个迁移）", len(PostgresSaver.MIGRATIONS))
