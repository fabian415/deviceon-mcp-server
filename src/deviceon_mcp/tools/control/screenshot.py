"""Screenshot of the device's desktop, returned as an image the agent can look at."""

from __future__ import annotations

import base64
import binascii

from mcp.server.fastmcp.exceptions import ToolError

from ...client import DeviceOnError
from ...deps import Deps
from ..common.devices import device_ref, get_device_checked, require_online

PLUGIN = "screenshot"


def image_format(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data.startswith(b"BM"):
        return "bmp"
    return "png"


async def take_screenshot(deps: Deps, did: int) -> tuple[bytes | None, str | None, dict]:
    """Returns (image bytes, format, info). Image is None when no user is logged on."""
    dev = await get_device_checked(deps, did, require_plugin=PLUGIN)
    require_online(dev, "a screenshot")
    try:
        result = await deps.client.get_screenshot(did)
    except DeviceOnError as ex:
        raise ToolError(f"screenshot failed: {ex}") from ex
    info = {"device": device_ref(dev)}
    if result.get("login") is False:
        return None, None, {**info, "captured": False, "reason": "no user is logged on to the device's desktop"}
    b64 = result.get("picBase64")
    if not b64:
        raise ToolError(f"device {did} returned no image (response: {result})")
    try:
        data = base64.b64decode(b64)
    except (binascii.Error, ValueError) as ex:
        raise ToolError(f"device {did} returned an invalid image: {ex}") from ex
    fmt = image_format(data)
    return data, fmt, {**info, "captured": True, "format": fmt, "bytes": len(data)}
