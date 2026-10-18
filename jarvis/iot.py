"""Phase 14 - optional IoT / smart-device control.

A local-first device layer: a JSON device registry plus pluggable providers.
Nothing is contacted unless you (a) register a device and (b) explicitly
control it. Control is confirmation-gated.

Providers:
  * ``mock``           - in-memory, offline, deterministic (for tests/demos)
  * ``http``           - generic REST webhook: POST {action, value} to the device address
  * ``home_assistant`` - Home Assistant REST API (used only when configured)

Honest by design: unknown providers/devices and unreachable endpoints return
errors; no device state is invented.
"""

from __future__ import annotations

import json
import urllib.request
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import get_data_dir
from .logging import get_logger
from .tools import Tool, ToolResult

logger = get_logger(__name__)

IOT_DIR = Path(get_data_dir()) / "iot"
IOT_DIR.mkdir(parents=True, exist_ok=True)
DEVICES_FILE = IOT_DIR / "devices.json"

PROVIDERS = ("mock", "http", "home_assistant")
ACTIONS = ("on", "off", "toggle", "set", "status")

_SAFE_SCHEMES = ("http", "https")


def _now() -> str:
    return datetime.now().isoformat()


def _new_id(prefix: str = "dev") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _safe_url(url: str) -> bool:
    if not url or "://" not in url:
        return False
    return url.split("://", 1)[0].lower() in _SAFE_SCHEMES


@dataclass
class Device:
    id: str
    name: str
    provider: str = "mock"
    kind: str = "switch"  # switch | light | sensor | scene
    address: str = ""  # provider-specific (URL for http, entity_id for home_assistant)
    state: Dict[str, Any] = field(default_factory=dict)
    capabilities: List[str] = field(default_factory=lambda: ["on", "off", "toggle"])
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _now()

    def summary(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "provider": self.provider,
            "kind": self.kind,
            "address": self.address,
            "state": self.state,
            "capabilities": self.capabilities,
        }


class DeviceStore:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else DEVICES_FILE
        self._items: Dict[str, Dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                self._items = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Failed to load devices: {exc}")
                self._items = {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._items, indent=2), encoding="utf-8")

    def add(self, device: Device) -> str:
        if not device.id:
            device.id = _new_id()
        self._items[device.id] = asdict(device)
        self._save()
        return device.id

    def get(self, device_id: str) -> Optional[Device]:
        data = self._items.get(device_id)
        return Device(**data) if data else None

    def list(self) -> List[Device]:
        return [Device(**v) for v in self._items.values()]

    def update(self, device: Device) -> None:
        self._items[device.id] = asdict(device)
        self._save()

    def remove(self, device_id: str) -> bool:
        if device_id in self._items:
            del self._items[device_id]
            self._save()
            return True
        return False


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------
class DeviceProvider(ABC):
    name: str = "base"

    @abstractmethod
    def available(self) -> bool:
        ...

    @abstractmethod
    def control(self, device: Device, action: str, value: Any = None) -> Dict[str, Any]:
        ...


class MockDeviceProvider(DeviceProvider):
    """In-memory provider used for tests and demos. State is deterministic."""

    name = "mock"

    def available(self) -> bool:
        return True

    def control(self, device: Device, action: str, value: Any = None) -> Dict[str, Any]:
        if action == "status":
            return {"ok": True, "state": dict(device.state)}
        if action == "on":
            device.state["power"] = "on"
        elif action == "off":
            device.state["power"] = "off"
        elif action == "toggle":
            device.state["power"] = "off" if device.state.get("power") == "on" else "on"
        elif action == "set":
            device.state["value"] = value
        else:
            return {"ok": False, "error": f"unsupported action: {action}"}
        return {"ok": True, "state": dict(device.state)}


class HttpDeviceProvider(DeviceProvider):
    """Generic REST device: POST JSON {action, value} to the device address."""

    name = "http"

    def available(self) -> bool:
        return True

    def control(self, device: Device, action: str, value: Any = None) -> Dict[str, Any]:
        if not _safe_url(device.address):
            return {"ok": False, "error": "device address must be an http(s) URL"}
        payload = json.dumps({"action": action, "value": value}).encode("utf-8")
        req = urllib.request.Request(device.address, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=8.0) as resp:  # noqa: S310
                body = resp.read().decode("utf-8", "replace")
            data = json.loads(body) if body.strip() else {}
            return {"ok": True, "state": data.get("state", data)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


class HomeAssistantProvider(DeviceProvider):
    """Home Assistant REST API. Only available when a URL + token are configured."""

    name = "home_assistant"

    def __init__(self, base_url: str = "", token: str = ""):
        self.base_url = (base_url or "").strip().rstrip("/")
        self.token = (token or "").strip()

    @classmethod
    def from_settings(cls) -> "HomeAssistantProvider":
        try:
            from . import db

            base = db.get_setting("iot.home_assistant.url", "") or ""
            token = db.get_setting("iot.home_assistant.token", "") or ""
            return cls(base, token)
        except Exception:  # noqa: BLE001
            return cls()

    def available(self) -> bool:
        return bool(self.base_url) and bool(self.token) and _safe_url(self.base_url)

    def control(self, device: Device, action: str, value: Any = None) -> Dict[str, Any]:
        if not self.available():
            return {"ok": False, "error": "home_assistant not configured (set iot.home_assistant.url and .token)"}
        if not device.address:
            return {"ok": False, "error": "home_assistant device needs an entity_id address"}
        if action == "status":
            return {
                "ok": False,
                "error": "status is not supported for home_assistant; use the HA API directly",
            }
        service = {"on": "turn_on", "off": "turn_off", "toggle": "toggle"}.get(action)
        if action == "set":
            return {"ok": False, "error": "set is not supported for home_assistant"}
        if service is None:
            return {"ok": False, "error": f"unsupported action: {action}"}
        domain = device.address.split(".", 1)[0] if "." in device.address else "homeassistant"
        url = f"{self.base_url}/api/services/{domain}/{service}"
        payload = json.dumps({"entity_id": device.address}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=8.0) as resp:  # noqa: S310
                resp.read()
            return {"ok": True, "state": {"entity_id": device.address, "last_action": action}}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}


class IoTManager:
    """Coordinates devices and providers."""

    def __init__(self, store: Optional[DeviceStore] = None):
        self.store = store or DeviceStore()
        self.providers: Dict[str, DeviceProvider] = {
            "mock": MockDeviceProvider(),
            "http": HttpDeviceProvider(),
            "home_assistant": HomeAssistantProvider.from_settings(),
        }

    def provider_status(self) -> List[Dict[str, Any]]:
        return [{"name": name, "available": p.available()} for name, p in self.providers.items()]

    def add_device(
        self,
        name: str,
        provider: str = "mock",
        kind: str = "switch",
        address: str = "",
        capabilities: Optional[List[str]] = None,
    ) -> Device:
        if provider not in PROVIDERS:
            raise ValueError(f"unknown provider: {provider}")
        if provider == "http" and address and not _safe_url(address):
            raise ValueError("http provider address must be an http(s) URL")
        device = Device(
            id=_new_id(),
            name=name,
            provider=provider,
            kind=kind,
            address=address,
            capabilities=capabilities or ["on", "off", "toggle"],
        )
        self.store.add(device)
        return device

    def control(self, device_id: str, action: str, value: Any = None) -> Dict[str, Any]:
        device = self.store.get(device_id)
        if device is None:
            return {"ok": False, "error": f"device not found: {device_id}"}
        if action not in ACTIONS:
            return {"ok": False, "error": f"unsupported action: {action}"}
        provider = self.providers.get(device.provider)
        if provider is None:
            return {"ok": False, "error": f"unknown provider: {device.provider}"}
        if not provider.available():
            return {"ok": False, "error": f"provider unavailable: {device.provider}"}
        result = provider.control(device, action, value)
        if result.get("ok") and "state" in result:
            device.state = result["state"]
            self.store.update(device)
        return result


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
class IotProvidersTool(Tool):
    name = "iot.providers"
    description = "List IoT providers and whether each is available"
    permissions = ["iot.read"]

    def run(self) -> ToolResult:
        return ToolResult(success=True, result={"providers": IoTManager().provider_status()}, tool=self.name)


class IotDevicesTool(Tool):
    name = "iot.devices"
    description = "List registered smart devices"
    permissions = ["iot.read"]

    def run(self) -> ToolResult:
        devices = [d.summary() for d in IoTManager().store.list()]
        return ToolResult(success=True, result={"count": len(devices), "devices": devices}, tool=self.name)


class IotAddDeviceTool(Tool):
    name = "iot.add_device"
    description = "Register a smart device (provider: mock|http|home_assistant)"
    permissions = ["iot.write"]

    def run(self, device_name: str = "", provider: str = "mock", kind: str = "switch", address: str = "") -> ToolResult:
        if not device_name:
            return ToolResult(success=False, error="device_name is required", tool=self.name)
        try:
            device = IoTManager().add_device(name=device_name, provider=provider, kind=kind, address=address)
        except ValueError as exc:
            return ToolResult(success=False, error=str(exc), tool=self.name)
        return ToolResult(success=True, result=device.summary(), tool=self.name)


class IotRemoveDeviceTool(Tool):
    name = "iot.remove_device"
    description = "Remove a registered device"
    permissions = ["iot.write"]

    def run(self, device_id: str = "") -> ToolResult:
        if not device_id:
            return ToolResult(success=False, error="device_id is required", tool=self.name)
        ok = DeviceStore().remove(device_id)
        if not ok:
            return ToolResult(success=False, error=f"device not found: {device_id}", tool=self.name)
        return ToolResult(success=True, result={"removed": device_id}, tool=self.name)


class IotStatusTool(Tool):
    name = "iot.status"
    description = "Get the current state of a device"
    permissions = ["iot.read"]

    def run(self, device_id: str = "") -> ToolResult:
        if not device_id:
            return ToolResult(success=False, error="device_id is required", tool=self.name)
        result = IoTManager().control(device_id, "status")
        if not result.get("ok"):
            return ToolResult(success=False, error=result.get("error"), tool=self.name)
        return ToolResult(success=True, result=result.get("state", {}), tool=self.name)


class IotControlTool(Tool):
    name = "iot.control"
    description = "Control a device (on/off/toggle/set). Confirmation required."
    permissions = ["iot.control"]

    def run(self, device_id: str = "", action: str = "", value: Any = None) -> ToolResult:
        if not device_id:
            return ToolResult(success=False, error="device_id is required", tool=self.name)
        if action not in ACTIONS:
            return ToolResult(success=False, error=f"action must be one of: {', '.join(ACTIONS)}", tool=self.name)
        result = IoTManager().control(device_id, action, value)
        if not result.get("ok"):
            return ToolResult(success=False, error=result.get("error"), tool=self.name)
        return ToolResult(success=True, result={"device_id": device_id, "action": action, "state": result.get("state", {})}, tool=self.name)


def get_iot_tools() -> List[Tool]:
    """Return all Phase 14 IoT tools."""
    return [
        IotProvidersTool(),
        IotDevicesTool(),
        IotAddDeviceTool(),
        IotRemoveDeviceTool(),
        IotStatusTool(),
        IotControlTool(),
    ]


def get_iot_tools_for_registry() -> List[Tool]:
    return get_iot_tools()
