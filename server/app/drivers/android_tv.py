"""ADB-over-WiFi driver for Android TV / Google TV / Fire TV.

All three speak the same ADB protocol on port 5555 once the user enables
"USB debugging" / "ADB debugging" in Developer Options on the TV. The first
connection prompts an on-screen "Allow this device?" — accept once and the
TV remembers the controller's RSA fingerprint forever.

We use `adb_shell` (pure Python; no system `adb` binary required) and feed
keypresses with `input keyevent N`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from adb_shell.adb_device_async import AdbDeviceTcpAsync
from adb_shell.auth.keygen import keygen
from adb_shell.auth.sign_pythonrsa import PythonRSASigner


# Android KEYCODE constants we need. Reference:
# https://developer.android.com/reference/android/view/KeyEvent
_KEYCODES: dict[str, int] = {
    "0": 7, "1": 8, "2": 9, "3": 10, "4": 11,
    "5": 12, "6": 13, "7": 14, "8": 15, "9": 16,
    "Enter":     66,   # KEYCODE_ENTER
    "Ok":        23,   # KEYCODE_DPAD_CENTER
    "Dot":       56,   # KEYCODE_PERIOD (sub-channel separator works for Live TV)
    "Dash":      69,   # KEYCODE_MINUS
    "Vol_up":    24,
    "Vol_dn":    25,
    "Mute":      164,
    "Ch_next":   166,
    "Ch_prev":   167,
    "Up":        19,
    "Down":      20,
    "Left":      21,
    "Right":     22,
    "Back":      4,
    "Home":      3,
    "Menu":      82,
    "Power":     26,   # KEYCODE_POWER (toggle)
    "PowerOn":   224,  # KEYCODE_WAKEUP
    "PowerOff":  223,  # KEYCODE_SLEEP
    "Tv":        170,  # KEYCODE_TV (live tv input)
}


class AdbError(RuntimeError):
    pass


class AdbClient:
    """Per-TV ADB connection. Lazy-connects; safe to call repeatedly."""

    def __init__(
        self,
        host_port: str,
        adb_key_path: Path,
        *,
        timeout: float = 5.0,
        connect_timeout: float = 8.0,
    ) -> None:
        host, _, port = host_port.partition(":")
        self._host = host
        self._port = int(port) if port else 5555
        self._key_path = adb_key_path
        self._timeout = timeout
        self._connect_timeout = connect_timeout
        self._device: AdbDeviceTcpAsync | None = None

    async def _connect(self) -> AdbDeviceTcpAsync:
        if self._device is not None and self._device.available:
            return self._device

        ensure_adb_key(self._key_path)
        with self._key_path.open("rb") as fh:
            priv = fh.read()
        with self._key_path.with_suffix(".pub").open("rb") as fh:
            pub = fh.read()
        signer = PythonRSASigner(pub.decode(), priv.decode())

        device = AdbDeviceTcpAsync(self._host, self._port, default_transport_timeout_s=self._timeout)
        try:
            await device.connect(rsa_keys=[signer], auth_timeout_s=self._connect_timeout)
        except Exception as exc:  # noqa: BLE001
            raise AdbError(f"adb connect {self._host}:{self._port}: {exc}") from exc
        self._device = device
        return device

    async def close(self) -> None:
        if self._device is not None:
            try:
                await self._device.close()
            except Exception:  # noqa: BLE001
                pass
            self._device = None

    # ---- Commands ----
    async def keyevent(self, code: int) -> None:
        device = await self._connect()
        try:
            await device.shell(f"input keyevent {code}", read_timeout_s=self._timeout)
        except Exception as exc:  # noqa: BLE001
            raise AdbError(f"keyevent {code}: {exc}") from exc

    async def send_logical(self, key: str) -> None:
        code = _KEYCODES.get(key)
        if code is None:
            raise AdbError(f"unsupported key: {key!r}")
        await self.keyevent(code)

    async def healthy(self) -> bool:
        try:
            await self._connect()
            return True
        except AdbError:
            return False


def ensure_adb_key(path: Path) -> None:
    """Generate an RSA key pair at `path` (and `path.pub`) if missing."""
    pub = path.with_suffix(".pub")
    if path.exists() and pub.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    keygen(str(path))
