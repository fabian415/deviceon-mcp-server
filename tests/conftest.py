from __future__ import annotations

import pytest

from deviceon_mcp.client import DeviceOnClient
from deviceon_mcp.config import DEFAULT_PROTECTED_PROCESSES, Settings
from deviceon_mcp.confirm_store import ConfirmStore
from deviceon_mcp.deps import Deps

from fake_deviceon import FakeDeviceOn, FakeTerminal


def make_settings(**kw) -> Settings:
    base = dict(
        base_url="http://deviceon.test/rmm",
        username="agent@example.com",
        password="secret",
        protected_processes=DEFAULT_PROTECTED_PROCESSES,
    )
    base.update(kw)
    return Settings(**base)


@pytest.fixture
def fake() -> FakeDeviceOn:
    return FakeDeviceOn()


@pytest.fixture
async def deps(fake: FakeDeviceOn):
    settings = make_settings()
    client = DeviceOnClient(settings, transport=fake.transport())
    d = Deps(settings=settings, client=client, confirm=ConfirmStore(300), sleep=fake.sleep, now_ms=fake.now_ms,
             terminal=FakeTerminal(fake))
    yield d
    await client.aclose()
