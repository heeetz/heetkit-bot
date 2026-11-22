"""Consolidated command access/privacy using synthetic identities and profiles."""

import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.ai_user_blocks import AIUserBlocklist
from app.command_restrictions import CommandRestrictionStore
from app.database.database import Database
from app.database.models import PrivacyOptOut
from app.database.repository import AIMemoryRepository, UserRepository
from app.management import ApplicationManagement
from app.webview_host import DESKTOP_OPERATIONS, WebUIBridge


def rule(**changes):
    return {"username": "viewer", "command_ids": ["ask"], "expires_at": None, "note": "private", **changes}


def test_ai_move_repeatable_interrupted_and_unresolved_compatibility(tmp_path, monkeypatch):
    blocks = AIUserBlocklist(tmp_path / "ai.json")
    blocks.block("viewer", "123")
    blocks.block("unknown")
    store = CommandRestrictionStore(tmp_path / "rules.json")
    store.save(rule(command_ids=["ping"]), channel_id="200", user_id="456", valid_command_ids={"ping"})
    original_unblock = blocks.unblock
    monkeypatch.setattr(blocks, "unblock", lambda _: (_ for _ in ()).throw(OSError("interrupted")))
    with pytest.raises(OSError):
        store.migrate_ai_blocks(blocks, "200")
    assert len(store.list()) == 3
    monkeypatch.setattr(blocks, "unblock", original_unblock)
    store.migrate_ai_blocks(blocks, "200")
    store.migrate_ai_blocks(blocks, "201")
    assert len(store.list()) == 3 and not blocks.list()
    assert store.match("200", "123", "ask", "newname")
    assert not store.match("201", "123", "ask", "newname")
    pending = next(item for item in store.list() if item.username == "unknown")
    assert pending.twitch_user_id is None
    assert store.match("200", "789", "ask", "unknown")
    assert store.get(pending.id).twitch_user_id == "789"
    assert not store.match("200", "777", "ask", "unknown")
    store.remove(pending.id)
    assert not store.match("200", "789", "ask", "unknown")
    assert next(item for item in store.list() if not item.legacy_ai).note == "private"


def test_missing_channel_legacy_is_visible_safe_until_configured(tmp_path):
    blocks = AIUserBlocklist(tmp_path / "ai.json")
    blocks.block("unknown")
    store = CommandRestrictionStore(tmp_path / "rules.json")
    store.migrate_ai_blocks(blocks, None)
    assert store.list()[0].channel_id is None
    assert store.match("201", "123", "ask", "unknown")
    store.migrate_ai_blocks(blocks, "200")
    assert store.list()[0].channel_id == "200"
    assert not store.match("201", "123", "ask", "unknown")


def test_legacy_numeric_login_cannot_collide_with_verified_account_id(tmp_path):
    blocks = AIUserBlocklist(tmp_path / "ai.json")
    blocks.block("viewer", "123")
    blocks.block("123")
    store = CommandRestrictionStore(tmp_path / "rules.json")
    store.migrate_ai_blocks(blocks, "200")
    assert len(store.list()) == 2
    assert store.match("200", "123", "ask", "viewer")
    assert store.match("200", "456", "ask", "123")


@pytest.fixture
async def privacy_core():
    database = Database("sqlite+aiosqlite:///:memory:")
    await database.initialize()
    users = UserRepository(database.session_factory)
    memory = AIMemoryRepository(database.session_factory)
    services = SimpleNamespace(users=users, twitch=SimpleNamespace(resolve_user_id=AsyncMock(return_value="123")),
                               settings=SimpleNamespace(twitch_channel_user_id="200"))
    management = ApplicationManagement(SimpleNamespace(services=services), None)
    try:
        yield database, users, memory, management
    finally:
        await database.close()


async def test_optout_management_metadata_duplicates_paging_and_withdrawal(privacy_core):
    database, users, memory, management = privacy_core
    await users.upsert_seen("123", "viewer", channel_id="200")
    await memory.append("123", "question", "reply", channel_id="201")
    before = datetime.now(timezone.utc)
    result = await management._add_opt_out("@viewer")
    assert result["ok"] and result["total"] == 1
    row = result["users"][0]
    assert row["username"] == "viewer" and datetime.fromisoformat(row["opted_out_at"]) >= before
    assert not await users.get_by_username("viewer", channel_id="200")
    assert not await memory.get_recent("123", 5, channel_id="201")
    again = await management._add_opt_out("viewer")
    assert again["users"] == result["users"]
    await users.opt_out("456", username="other")
    assert (await management._get_opt_outs("view", 0, 1))["total"] == 1
    assert len((await management._get_opt_outs("", 1, 1))["users"]) == 1
    assert not (await management._get_opt_outs("", 0, 101))["ok"]
    assert not (await management._withdraw_opt_out("123", False))["ok"]
    assert (await management._withdraw_opt_out("123", True))["ok"]
    assert not await users.is_storage_opted_out("123")
    assert not await memory.get_recent("123", 5, channel_id="201")
    assert not (await management._withdraw_opt_out("123", True))["ok"]


async def test_historical_metadata_and_selfservice_never_invent_date(privacy_core):
    database, users, _, management = privacy_core
    async with database.session_factory() as session:
        session.add(PrivacyOptOut(twitch_user_id="123"))
        await session.commit()
    assert (await management._get_opt_outs())["users"] == [{"twitch_user_id": "123", "username": None, "opted_out_at": None}]
    await users.opt_out("123", username="verifiedchatlogin")
    row = (await management._get_opt_outs())["users"][0]
    assert row["username"] == "verifiedchatlogin" and row["opted_out_at"] is None


async def test_withdrawal_cannot_repopulate_from_inflight_requests(privacy_core):
    database, users, memory, _ = privacy_core
    started, finish = asyncio.Event(), asyncio.Event()
    async def old_request():
        with users.storage_scope("123"):
            started.set()
            await finish.wait()
            assert users.logs_suppressed("123")
            await users.upsert_seen("123", "old", channel_id="200")
            await memory.append("123", "old", "old", channel_id="200")
    task = asyncio.create_task(old_request())
    await started.wait()
    await users.opt_out("123", username="viewer")
    await users.withdraw_opt_out("123")
    finish.set()
    await task
    assert not await users.get_by_username("old", channel_id="200")
    assert not await memory.get_recent("123", 5, channel_id="200")
    with users.storage_scope("123"):
        await memory.append("123", "fresh", "reply", channel_id="200")
    assert len(await memory.get_recent("123", 5, channel_id="200")) == 1


async def test_native_bridge_uses_same_privacy_operations_and_allowlist(privacy_core):
    _, _, _, management = privacy_core
    bridge = WebUIBridge.__new__(WebUIBridge)
    bridge._backend = management._backend
    calls = []
    def complete(coroutine, **kwargs):
        calls.append(coroutine)
        return {"pending": coroutine}
    bridge._wait_for_backend = complete
    assert {"get_opt_outs", "add_opt_out", "withdraw_opt_out"} <= set(DESKTOP_OPERATIONS)
    result = bridge.call("add_opt_out", {"username": "viewer"})
    assert (await result["pending"])["ok"]
    result = bridge.call("get_opt_outs", {"query": "view", "offset": 0, "limit": 1})
    assert (await result["pending"])["total"] == 1
    result = bridge.call("withdraw_opt_out", {"twitch_user_id": "123", "confirmed": False})
    assert not (await result["pending"])["ok"]
    result = bridge.call("withdraw_opt_out", {"twitch_user_id": "123", "confirmed": True})
    assert (await result["pending"])["total"] == 0
