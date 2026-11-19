"""Tests of the 'control' toolset and the generic request -> confirm_action flow."""

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from deviceon_mcp import actions
from deviceon_mcp.tools import control
from deviceon_mcp.tools.control import capabilities, data, kvm, power, protect, screenshot

from fake_deviceon import DID


@pytest.fixture
def cdeps(deps):
    control.register(FastMCP("test"), deps)  # registers the action executors
    return deps


# ---- generic confirm flow -------------------------------------------------

async def test_request_does_nothing_until_confirmed(cdeps, fake):
    r = await power.request_power_action(cdeps, DID, "restart", "hung app")
    assert fake.power_calls == []
    assert r["summary"]["power_action"] == "restart" and r["warnings"]
    done = await actions.confirm_action(cdeps, r["confirm_token"])
    assert done["status"] == "sent" and fake.power_calls == [{"did": DID, "action": "restart"}]


async def test_confirm_token_is_single_use(cdeps):
    r = await power.request_power_action(cdeps, DID, "restart")
    await actions.confirm_action(cdeps, r["confirm_token"])
    with pytest.raises(ToolError):
        await actions.confirm_action(cdeps, r["confirm_token"])


async def test_confirm_action_rejects_tokens_of_unregistered_actions(cdeps):
    token = cdeps.confirm.issue("something_else", {"did": DID})
    with pytest.raises(ToolError, match="own confirm tool"):
        await actions.confirm_action(cdeps, token)


# ---- capabilities ---------------------------------------------------------

async def test_capabilities_reports_usable_actions(cdeps):
    r = await capabilities.get_device_capabilities(cdeps, DID)
    t = r["tools"]
    assert t["request_power_action"]["supported_actions"] == ["shutdown", "restart", "start"]
    assert t["request_power_action"]["usable_now"] == ["shutdown", "restart"]  # online: no WOL
    assert t["request_protection_action"]["allowed_actions"] == ["protect", "unprotect", "install", "update", "activate"]
    assert t["request_recovery_action"]["remote_backup_exists"] is False
    assert t["device_log"]["event_types"][0] == "Application"
    assert t["take_screenshot"]["available"] and t["request_kvm_session"]["available"]


async def test_capabilities_offline_only_allows_start(cdeps, fake):
    fake.connected = False
    r = await capabilities.get_device_capabilities(cdeps, DID)
    assert r["tools"]["request_power_action"]["usable_now"] == ["start"]
    assert any("offline" in n for n in r["notes"])


# ---- power ----------------------------------------------------------------

async def test_power_rejects_unsupported_and_wrong_state(cdeps, fake):
    with pytest.raises(ToolError, match="supports only"):
        await power.request_power_action(cdeps, DID, "hibernate")
    with pytest.raises(ToolError, match="already online"):
        await power.request_power_action(cdeps, DID, "start")
    fake.connected = False
    with pytest.raises(ToolError, match="offline"):
        await power.request_power_action(cdeps, DID, "restart")
    r = await power.request_power_action(cdeps, DID, "start")
    assert "Wake-on-LAN" in r["warnings"][0]


async def test_sleep_maps_to_suspend_function(cdeps, fake):
    fake.power_functions = "suspend,shutdown"
    r = await power.request_power_action(cdeps, DID, "sleep")
    assert r["summary"]["power_action"] == "sleep"


# ---- screenshot -----------------------------------------------------------

async def test_screenshot_returns_png(cdeps):
    img, fmt, info = await screenshot.take_screenshot(cdeps, DID)
    assert fmt == "png" and img.startswith(b"\x89PNG") and info["captured"] is True


async def test_screenshot_without_logged_on_user(cdeps, fake):
    fake.screenshot_login = False
    img, fmt, info = await screenshot.take_screenshot(cdeps, DID)
    assert img is None and info["captured"] is False


async def test_screenshot_tool_returns_image_content(cdeps):
    mcp = FastMCP("t")
    control.register(mcp, cdeps)
    content = await mcp.call_tool("take_screenshot", {"did": DID})
    blocks = content[0] if isinstance(content, tuple) else content
    assert any(getattr(b, "type", None) == "image" and b.mimeType == "image/png" for b in blocks)


# ---- set data -------------------------------------------------------------

async def test_set_data_shows_current_and_coerces_types(cdeps, fake):
    r = await data.request_set_data(cdeps, DID, "Modbus_Handler", {"/Coils/LED0": "true", "/Holding Registers/Data0": "42"})
    changes = {c["sensor"]: c for c in r["summary"]["changes"]}
    assert changes["/Coils/LED0"] == {"sensor": "/Coils/LED0", "current": False, "new": True}
    assert changes["/Holding Registers/Data0"]["new"] == 42
    assert fake.set_data_calls == []
    done = await actions.confirm_action(cdeps, r["confirm_token"])
    assert done["status"] == "ok"
    assert fake.set_data_calls[0]["sensorIds"] == [{"n": "/Coils/LED0", "bv": True}, {"n": "/Holding Registers/Data0", "v": 42}]


async def test_set_data_refuses_read_only_unknown_and_bad_types(cdeps):
    with pytest.raises(ToolError, match="read-only"):
        await data.request_set_data(cdeps, DID, "Modbus_Handler", {"/Discrete Inputs/Input0": False})
    with pytest.raises(ToolError, match="no sensor"):
        await data.request_set_data(cdeps, DID, "Modbus_Handler", {"/Coils/LED9": True})
    with pytest.raises(ToolError, match="boolean"):
        await data.request_set_data(cdeps, DID, "Modbus_Handler", {"/Coils/LED0": 3})
    with pytest.raises(ToolError, match="no plugin"):
        await data.request_set_data(cdeps, DID, "Nope", {"/x": 1})


# ---- KVM ------------------------------------------------------------------

async def test_kvm_generates_repeater_id_and_returns_connection(cdeps, fake):
    r = await kvm.request_kvm_session(cdeps, DID)
    rid = r["summary"]["repeater_id"]
    assert 10_000 <= rid < 100_000 and fake.kvm_calls == []
    done = await actions.confirm_action(cdeps, r["confirm_token"])
    assert done["connection"] == {"host": "kvm.deviceon.test", "port": 6082, "kvm_mode": "default", "repeater_id": rid}
    assert fake.kvm_calls == [{"agentid": fake._device()["agentId"], "mode": 3, "forceRestartWinVNC": 0, "repeaterid": rid}]
    assert "noVNC" in done["next_step"] and "UltraVNC" in done["next_step"]
    assert "port_note" not in done  # fake portal returns 6082
    assert any("UltraVNC" in w for w in r["warnings"])


# ---- protection / recovery ------------------------------------------------

async def test_protection_requires_installed_software(cdeps, fake):
    fake.protection["installed"] = False
    with pytest.raises(ToolError, match="install"):
        await protect.request_protection_action(cdeps, DID, "protect")
    r = await protect.request_protection_action(cdeps, DID, "install")
    await actions.confirm_action(cdeps, r["confirm_token"])
    assert fake.protection_calls == [{"did": DID, "action": "install"}]


async def test_expired_license_is_a_warning(cdeps, fake):
    fake.protection["expired"] = True
    r = await protect.request_protection_action(cdeps, DID, "protect")
    assert any("expired" in w for w in r["warnings"])


async def test_recovery_remote_restore_needs_remote_backup(cdeps, fake):
    with pytest.raises(ToolError, match="no remote backup"):
        await protect.request_recovery_action(cdeps, DID, "recovery", remote=True)
    fake.remote_backup = True
    r = await protect.request_recovery_action(cdeps, DID, "recovery", remote=True)
    assert "RESTORES" in r["warnings"][0]
    await actions.confirm_action(cdeps, r["confirm_token"])
    assert fake.recovery_calls == [{"did": DID, "action": "recovery", "remote": True}]


async def test_recovery_option_validation(cdeps, fake):
    with pytest.raises(ToolError, match="asz_percent"):
        await protect.request_recovery_action(cdeps, DID, "backup", asz_percent=50)
    with pytest.raises(ToolError, match="remote"):
        await protect.request_recovery_action(cdeps, DID, "install", remote=True)
    r = await protect.request_recovery_action(cdeps, DID, "install", asz_percent=30)
    await actions.confirm_action(cdeps, r["confirm_token"])
    assert fake.recovery_calls == [{"did": DID, "action": "install", "asz": 30}]
