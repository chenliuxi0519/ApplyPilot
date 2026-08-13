"""checkpointer 的版本契约、加密行为和真实读写。

checkpointer 自带内部表和迁移列表，表结构随库版本走。这里锁住：
锁定的版本没被改动、setup() 只碰它自己的表、落库的是密文、
以及一段带工具调用的中文对话能真的存进 Postgres 再原样取回来。
"""

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast

import psycopg
import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import Checkpoint
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.encrypted import EncryptedSerializer
from psycopg.rows import dict_row

from app.agent import checkpointer
from app.agent.checkpointer import (
    CHECKPOINT_TABLES,
    CheckpointNotConfiguredError,
    build_serde,
    encryption_key,
    open_checkpointer,
)
from app.core.config import settings
from tests.agent.test_serialization import build_transcript

# 与 pyproject 中锁定的版本一致；升级依赖时必须同步改这里，
# 让"换了 checkpointer 版本"永远是一次显式改动。
PINNED_LANGGRAPH = "1.2.11"
PINNED_CHECKPOINT_POSTGRES = "3.1.2"

TEST_KEY = "applypilot-test-key-32-bytes!!!!"  # 32 字节，测试专用
OTHER_KEY = "another-test-key-32-bytes!!!!!!!"

# 只出现在测试数据里的中文，用来在原始存储中搜明文。
SECRET_TEXT = "我的托福成绩是一百零五分"


@pytest.fixture
def encryption_configured(monkeypatch: pytest.MonkeyPatch) -> str:
    """测试显式使用一把测试密钥，而不是退回明文。"""
    monkeypatch.setattr(settings, "CHECKPOINT_ENCRYPTION_KEY", TEST_KEY)
    return TEST_KEY


# --------------------------------------------------------------------------
# 版本契约
# --------------------------------------------------------------------------


def test_the_pinned_versions_are_the_installed_ones() -> None:
    assert version("langgraph") == PINNED_LANGGRAPH
    assert version("langgraph-checkpoint-postgres") == PINNED_CHECKPOINT_POSTGRES


def test_setup_only_creates_the_checkpointer_own_tables() -> None:
    created = {
        line.split("CREATE TABLE IF NOT EXISTS ")[1].split()[0].strip("( \n")
        for migration in PostgresSaver.MIGRATIONS
        for line in migration.splitlines()
        if "CREATE TABLE IF NOT EXISTS " in line
    }

    assert created == set(CHECKPOINT_TABLES)


def test_the_migration_list_is_the_one_we_reviewed() -> None:
    assert len(PostgresSaver.MIGRATIONS) == 10


def test_the_official_thread_deletion_api_exists() -> None:
    assert callable(PostgresSaver.delete_thread)
    assert callable(PostgresSaver.adelete_thread)


def test_we_never_touch_the_checkpoint_tables_by_hand() -> None:
    source = Path(checkpointer.__file__).read_text(encoding="utf-8")

    for table in CHECKPOINT_TABLES:
        assert f"DELETE FROM {table}" not in source
        assert f"INSERT INTO {table}" not in source
        assert f"UPDATE {table}" not in source


# --------------------------------------------------------------------------
# 连接串
# --------------------------------------------------------------------------


def test_the_checkpoint_uri_drops_the_sqlalchemy_dialect() -> None:
    uri = settings.CHECKPOINT_DATABASE_URI

    assert uri.startswith("postgresql://")
    assert "+psycopg" not in uri


def test_the_checkpoint_uri_points_at_the_same_database() -> None:
    assert settings.POSTGRES_DB in settings.CHECKPOINT_DATABASE_URI


def test_the_connection_is_configured_the_way_the_saver_needs() -> None:
    assert checkpointer.CONNECTION_KWARGS["autocommit"] is True
    assert checkpointer.CONNECTION_KWARGS["prepare_threshold"] == 0
    assert checkpointer.CONNECTION_KWARGS["row_factory"] is dict_row


# --------------------------------------------------------------------------
# 密钥配置：启动即失败，绝不明文
# --------------------------------------------------------------------------


def test_a_missing_key_is_refused_at_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHECKPOINT_ENCRYPTION_KEY", None)

    with pytest.raises(CheckpointNotConfiguredError):
        encryption_key()


def test_a_key_of_the_wrong_length_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHECKPOINT_ENCRYPTION_KEY", "too-short")

    with pytest.raises(CheckpointNotConfiguredError):
        encryption_key()


def test_production_refuses_to_start_without_a_key() -> None:
    """非 local 环境缺密钥必须在配置加载时就失败。"""
    for environment in ("staging", "production"):
        with pytest.raises(ValueError, match="CHECKPOINT_ENCRYPTION_KEY"):
            settings.model_copy(
                update={
                    "ENVIRONMENT": environment,
                    "CHECKPOINT_ENCRYPTION_KEY": None,
                }
            ).model_validate(
                {
                    **settings.model_dump(),
                    "ENVIRONMENT": environment,
                    "CHECKPOINT_ENCRYPTION_KEY": None,
                }
            )


def test_an_illegal_key_is_refused_in_every_environment() -> None:
    for environment in ("local", "staging", "production"):
        with pytest.raises(ValueError, match="16、24 或 32 字节"):
            type(settings).model_validate(
                {
                    **settings.model_dump(),
                    "ENVIRONMENT": environment,
                    "CHECKPOINT_ENCRYPTION_KEY": "9-bytes!!",
                }
            )


def test_local_may_run_without_a_key() -> None:
    """本地不强制配置：此时不会有任何 checkpoint 被写入。"""
    loaded = type(settings).model_validate(
        {
            **settings.model_dump(),
            "ENVIRONMENT": "local",
            "CHECKPOINT_ENCRYPTION_KEY": None,
        }
    )

    assert loaded.checkpoint_is_configured is False


# --------------------------------------------------------------------------
# 加密（不依赖数据库）
# --------------------------------------------------------------------------


def test_we_use_the_official_serializer(encryption_configured: str) -> None:
    del encryption_configured

    assert isinstance(build_serde(), EncryptedSerializer)


def test_what_the_serializer_produces_is_ciphertext(
    encryption_configured: str,
) -> None:
    del encryption_configured
    _, blob = build_serde().dumps_typed({"messages": [{"content": SECRET_TEXT}]})

    assert SECRET_TEXT.encode("utf-8") not in blob
    assert b"messages" not in blob


def test_encryption_is_not_deterministic(encryption_configured: str) -> None:
    del encryption_configured
    serde = build_serde()
    payload = {"messages": [{"content": "同一句话"}]}

    assert serde.dumps_typed(payload)[1] != serde.dumps_typed(payload)[1]


def test_a_wrong_key_cannot_read_the_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHECKPOINT_ENCRYPTION_KEY", TEST_KEY)
    sealed = build_serde().dumps_typed({"secret": "值"})

    monkeypatch.setattr(settings, "CHECKPOINT_ENCRYPTION_KEY", OTHER_KEY)

    # AES-EAX 的完整性校验失败，密文不会被当作明文读出来。
    with pytest.raises(ValueError):
        build_serde().loads_typed(sealed)


# --------------------------------------------------------------------------
# 真实 Postgres 读写
# --------------------------------------------------------------------------


Transcript = list[dict[str, Any]]


def _config(thread_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}


def _checkpoint(transcript: Transcript) -> Checkpoint:
    return cast(
        Checkpoint,
        {
            "v": 1,
            "id": str(uuid.uuid4()),
            "ts": "2026-08-13T00:00:00+00:00",
            "channel_values": {"messages": transcript},
            "channel_versions": {"messages": 1},
            "versions_seen": {},
        },
    )


def _put(saver: PostgresSaver, thread_id: str, transcript: Transcript) -> None:
    """写入一个 checkpoint。

    new_versions 必须带上通道版本，否则 channel_values 不会落到
    checkpoint_blobs，读回来会是空的。
    """
    saver.put(_config(thread_id), _checkpoint(transcript), {}, {"messages": 1})


@contextmanager
def _raw_storage() -> Iterator[psycopg.Connection[dict[str, Any]]]:
    """以外部观察者的身份直接读存储。

    只用于断言"落库的到底是什么字节"，不经过 checkpointer，
    因此也不构成业务代码对内部表的依赖。
    """
    with psycopg.connect(
        settings.CHECKPOINT_DATABASE_URI, row_factory=dict_row
    ) as conn:
        yield conn


@pytest.fixture
def thread_id() -> str:
    return f"test-accept:{uuid.uuid4()}"


def test_a_transcript_round_trips_through_postgres(
    encryption_configured: str, thread_id: str
) -> None:
    """写进真实 Postgres 再取回来，工具调用和中文都不能变。"""
    del encryption_configured
    transcript = build_transcript()

    with open_checkpointer() as saver:
        saver.setup()
        try:
            _put(saver, thread_id, transcript)
            restored = saver.get_tuple(_config(thread_id))

            assert restored is not None
            messages = restored.checkpoint["channel_values"]["messages"]
            assert messages == transcript

            block = messages[1]["content"][1]
            assert block["id"] == "toolu_01ABC"
            assert block["name"] == "update_application_status"
            assert block["input"]["target_status"] == "submitted"
            assert block["input"]["备注"] == "已寄出材料"
            assert messages[1]["content"][0]["text"] == "好的，我来把它标记为已提交 🎓"
        finally:
            saver.delete_thread(thread_id)


def test_the_stored_bytes_hold_no_plaintext(
    encryption_configured: str, thread_id: str
) -> None:
    """数据库原始存储里搜不到中文明文。"""
    del encryption_configured
    transcript = build_transcript()
    transcript.append({"role": "user", "content": SECRET_TEXT})

    with open_checkpointer() as saver:
        saver.setup()
        try:
            _put(saver, thread_id, transcript)

            with _raw_storage() as conn:
                rows = conn.execute(
                    "SELECT checkpoint::text AS c FROM checkpoints "
                    "WHERE thread_id = %s",
                    (thread_id,),
                ).fetchall()
                blobs = conn.execute(
                    "SELECT blob FROM checkpoint_blobs WHERE thread_id = %s",
                    (thread_id,),
                ).fetchall()

            assert rows, "checkpoint 应该已经写入"
            raw = "".join(row["c"] for row in rows)
            assert SECRET_TEXT not in raw
            assert "toolu_01ABC" not in raw
            for blob in blobs:
                assert SECRET_TEXT.encode("utf-8") not in bytes(blob["blob"])
        finally:
            saver.delete_thread(thread_id)


def test_a_wrong_key_cannot_read_a_stored_checkpoint(
    monkeypatch: pytest.MonkeyPatch, thread_id: str
) -> None:
    monkeypatch.setattr(settings, "CHECKPOINT_ENCRYPTION_KEY", TEST_KEY)
    with open_checkpointer() as saver:
        saver.setup()
        _put(saver, thread_id, build_transcript())

    monkeypatch.setattr(settings, "CHECKPOINT_ENCRYPTION_KEY", OTHER_KEY)
    try:
        with open_checkpointer() as saver, pytest.raises(ValueError):
            saver.get_tuple(_config(thread_id))
    finally:
        monkeypatch.setattr(settings, "CHECKPOINT_ENCRYPTION_KEY", TEST_KEY)
        with open_checkpointer() as saver:
            saver.delete_thread(thread_id)


def test_the_official_api_removes_the_thread(
    encryption_configured: str, thread_id: str
) -> None:
    del encryption_configured
    with open_checkpointer() as saver:
        saver.setup()
        _put(saver, thread_id, build_transcript())
        assert saver.get_tuple(_config(thread_id)) is not None

        saver.delete_thread(thread_id)

        assert saver.get_tuple(_config(thread_id)) is None
        with _raw_storage() as conn:
            for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                left = conn.execute(
                    f"SELECT count(*) AS n FROM {table} WHERE thread_id = %s",
                    (thread_id,),
                ).fetchone()
                assert left is not None and left["n"] == 0


def test_writing_a_checkpoint_leaves_the_business_tables_alone(
    encryption_configured: str, thread_id: str
) -> None:
    del encryption_configured
    with open_checkpointer() as saver:
        saver.setup()
        with _raw_storage() as conn:
            before = conn.execute("SELECT count(*) AS n FROM agent_run").fetchone()
        try:
            _put(saver, thread_id, build_transcript())
            with _raw_storage() as conn:
                after = conn.execute("SELECT count(*) AS n FROM agent_run").fetchone()
        finally:
            saver.delete_thread(thread_id)

    assert before is not None and after is not None
    assert before["n"] == after["n"]


def test_a_serialized_transcript_is_json_safe(encryption_configured: str) -> None:
    del encryption_configured
    transcript = build_transcript()

    assert json.loads(json.dumps(transcript)) == transcript
