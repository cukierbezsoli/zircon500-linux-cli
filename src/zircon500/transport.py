"""Linux ``hidraw`` discovery and HID Feature Report transport for Zircon 500."""

from __future__ import annotations

from dataclasses import dataclass
import errno
import fcntl
import os
from pathlib import Path
import re
import select
import statistics
import time

from .protocol import (
    REPORT_ID_FEATURE,
    REPORT_LENGTH,
    SUPPORTED_DEVICES,
    DeviceStatus,
    build_status_query,
    parse_status_response,
)

# Linux <linux/hidraw.h>: _IOC(_IOC_WRITE | _IOC_READ, 'H', 0x06 / 0x07, len)
_IOC_WRITE = 1
_IOC_READ = 2


def _hid_ioc_sfeature(length: int) -> int:
    return ((_IOC_WRITE | _IOC_READ) << 30) | (length << 16) | (ord("H") << 8) | 0x06


def _hid_ioc_gfeature(length: int) -> int:
    return ((_IOC_WRITE | _IOC_READ) << 30) | (length << 16) | (ord("H") << 8) | 0x07


class TransportError(RuntimeError):
    """Base error raised for HID transport failures."""


class DeviceNotFoundError(TransportError):
    """Raised when no supported Genesis Zircon 500 interface is attached."""


class DevicePermissionError(TransportError):
    """Raised when ``/dev/hidraw*`` rejects access due to missing udev rules."""


@dataclass(frozen=True, slots=True)
class HidrawDeviceInfo:
    """Metadata describing a discovered Linux ``hidraw`` endpoint."""

    path: Path
    vid: int
    pid: int
    mode_label: str
    product: str
    serial: str
    interface_number: int | None
    has_vendor_usage_page: bool
    has_feature_0c: bool
    readable: bool
    writable: bool
    has_input_05: bool = False

    @property
    def is_control_interface(self) -> bool:
        return self.has_feature_0c or (
            self.has_vendor_usage_page and self.interface_number == 1
        )


def _descriptor_capabilities(desc: bytes) -> tuple[bool, bool, bool]:
    """Quick check for Usage Page ``0xFF00``, Feature Report ``0x0c``, and Input ``0x05``."""
    has_ff00 = b"\x06\x00\xff" in desc
    # Report ID 0x0c (`85 0c`) near a Feature item (`b1 ...`) and 0x05 (`85 05`) Input (`81 ...`).
    has_feat_0c = b"\x85\x0c" in desc and (b"\xb1" in desc)
    has_in_05 = b"\x85\x05" in desc and (b"\x81" in desc)
    return has_ff00, has_feat_0c, has_in_05


def _parse_uevent(uevent_text: str) -> tuple[int | None, int | None, str, str]:
    vid = pid = None
    name = ""
    serial = ""
    for line in uevent_text.splitlines():
        if line.startswith("HID_ID="):
            m = re.match(r"HID_ID=[0-9A-Fa-f]+:([0-9A-Fa-f]+):([0-9A-Fa-f]+)", line)
            if m:
                vid = int(m.group(1), 16)
                pid = int(m.group(2), 16)
        elif line.startswith("HID_NAME="):
            name = line.split("=", 1)[1].strip()
        elif line.startswith("HID_UNIQ="):
            serial = line.split("=", 1)[1].strip()
    return vid, pid, name, serial


def _read_interface_number(sysfs_hidraw_dir: Path) -> int | None:
    try:
        dev_real = (sysfs_hidraw_dir / "device").resolve()
        for parent in (dev_real, *dev_real.parents):
            b_if = parent / "bInterfaceNumber"
            if b_if.is_file():
                return int(b_if.read_text(encoding="utf-8").strip(), 16)
            if parent.name == "devices":
                break
    except (OSError, ValueError):
        return None
    return None


def discover_devices(
    *,
    sys_class_root: Path = Path("/sys/class/hidraw"),
    dev_root: Path = Path("/dev"),
) -> list[HidrawDeviceInfo]:
    """Enumerate supported Genesis Zircon 500 HID interfaces via sysfs."""
    if not sys_class_root.exists():
        return []

    found: list[HidrawDeviceInfo] = []
    for entry in sorted(sys_class_root.iterdir()):
        uevent_file = entry / "device" / "uevent"
        if not uevent_file.is_file():
            continue
        try:
            uevent_text = uevent_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        vid, pid, product, serial = _parse_uevent(uevent_text)
        if vid is None or pid is None or (vid, pid) not in SUPPORTED_DEVICES:
            continue

        desc_file = entry / "device" / "report_descriptor"
        has_ff00 = False
        has_feat_0c = False
        has_in_05 = False
        if desc_file.is_file():
            try:
                has_ff00, has_feat_0c, has_in_05 = _descriptor_capabilities(desc_file.read_bytes())
            except OSError:
                pass

        if_num = _read_interface_number(entry)
        dev_path = dev_root / entry.name
        found.append(
            HidrawDeviceInfo(
                path=dev_path,
                vid=vid,
                pid=pid,
                mode_label=SUPPORTED_DEVICES[(vid, pid)],
                product=product or SUPPORTED_DEVICES[(vid, pid)],
                serial=serial,
                interface_number=if_num,
                has_vendor_usage_page=has_ff00,
                has_feature_0c=has_feat_0c,
                readable=os.access(dev_path, os.R_OK),
                writable=os.access(dev_path, os.W_OK),
                has_input_05=has_in_05,
            )
        )

    found.sort(
        key=lambda d: (
            0 if d.has_feature_0c else 1,
            0 if d.has_vendor_usage_page else 1,
            0 if d.interface_number == 1 else 1,
            str(d.path),
        )
    )
    return found


def select_control_device(device_path: Path | None = None) -> HidrawDeviceInfo:
    """Pick the vendor Feature Report ``0x0c`` endpoint, or a specific path."""
    devices = discover_devices()
    if device_path is not None:
        resolved = device_path.resolve()
        for dev in devices:
            if dev.path.resolve() == resolved:
                return dev
        if device_path.exists():
            return HidrawDeviceInfo(
                path=device_path,
                vid=0,
                pid=0,
                mode_label="Custom hidraw",
                product=str(device_path),
                serial="",
                interface_number=None,
                has_vendor_usage_page=False,
                has_feature_0c=True,
                readable=os.access(device_path, os.R_OK),
                writable=os.access(device_path, os.W_OK),
            )
        raise DeviceNotFoundError(f"Specified hidraw device does not exist: {device_path}")

    if not devices:
        raise DeviceNotFoundError(
            "No Genesis Zircon 500 device found (expected 248a:5b2e wired, "
            "248a:5b2f wireless dongle, or 331a:5024)."
        )

    for dev in devices:
        if dev.is_control_interface:
            return dev
    return devices[0]


def select_mouse_input_device(device_path: Path | None = None) -> HidrawDeviceInfo:
    """Pick the standard HID Mouse input endpoint (``if00``) for live packet sampling."""
    devices = discover_devices()
    if device_path is not None:
        resolved = device_path.resolve()
        for dev in devices:
            if dev.path.resolve() == resolved:
                return dev
        if device_path.exists():
            return HidrawDeviceInfo(
                path=device_path,
                vid=0,
                pid=0,
                mode_label="Custom hidraw",
                product=str(device_path),
                serial="",
                interface_number=None,
                has_vendor_usage_page=False,
                has_feature_0c=False,
                readable=os.access(device_path, os.R_OK),
                writable=os.access(device_path, os.W_OK),
            )
        raise DeviceNotFoundError(f"Specified hidraw device does not exist: {device_path}")

    if not devices:
        raise DeviceNotFoundError(
            "No Genesis Zircon 500 device found (expected 248a:5b2e wired, "
            "248a:5b2f wireless dongle, or 331a:5024)."
        )

    for dev in devices:
        if not dev.is_control_interface and dev.interface_number == 0:
            return dev
    for dev in devices:
        if not dev.is_control_interface:
            return dev
    return devices[0]


def select_event_devices(
    selected: HidrawDeviceInfo | None,
    devices: list[HidrawDeviceInfo],
) -> list[HidrawDeviceInfo]:
    """Return all non-mouse readable endpoints (``if01``/``if02``) that may emit Input ``0x05``."""
    if selected is None:
        return []
    result: list[HidrawDeviceInfo] = []
    seen_paths: set[Path] = set()

    if selected.readable and selected.interface_number != 0:
        result.append(selected)
        seen_paths.add(selected.path)

    for dev in devices:
        if dev.path in seen_paths or not dev.readable or dev.interface_number == 0:
            continue
        same_hw = (dev.vid, dev.pid, dev.serial) == (selected.vid, selected.pid, selected.serial)
        if same_hw and (dev.has_input_05 or dev.is_control_interface):
            result.append(dev)
            seen_paths.add(dev.path)

    return result


@dataclass(frozen=True, slots=True)
class PollingRateStats:
    """Measured live HID Interrupt-IN packet cadence on the mouse endpoint."""

    device_path: Path
    duration_s: float
    packet_count: int
    interval_count: int
    avg_hz: float
    median_hz: float
    p95_hz: float
    min_dt_ms: float
    median_dt_ms: float
    max_dt_ms: float


def compute_polling_rate_stats(
    device_path: Path,
    timestamps_ns: list[int],
    duration_s: float,
) -> PollingRateStats:
    """Compute polling rate statistics from nanosecond packet timestamps."""
    dts_ms = [
        (b - a) / 1_000_000.0
        for a, b in zip(timestamps_ns, timestamps_ns[1:])
        if b > a
    ]
    if not dts_ms:
        return PollingRateStats(
            device_path=device_path,
            duration_s=duration_s,
            packet_count=len(timestamps_ns),
            interval_count=0,
            avg_hz=0.0,
            median_hz=0.0,
            p95_hz=0.0,
            min_dt_ms=0.0,
            median_dt_ms=0.0,
            max_dt_ms=0.0,
        )

    span_s = (timestamps_ns[-1] - timestamps_ns[0]) / 1_000_000_000.0
    avg_hz = (len(dts_ms) / span_s) if span_s > 0 else 0.0
    median_dt_ms = float(statistics.median(dts_ms))
    median_hz = (1000.0 / median_dt_ms) if median_dt_ms > 0 else 0.0
    sorted_dt = sorted(dts_ms)
    p5_dt = sorted_dt[max(0, int(0.05 * (len(sorted_dt) - 1)))]
    p95_hz = (1000.0 / p5_dt) if p5_dt > 0 else 0.0
    return PollingRateStats(
        device_path=device_path,
        duration_s=duration_s,
        packet_count=len(timestamps_ns),
        interval_count=len(dts_ms),
        avg_hz=avg_hz,
        median_hz=median_hz,
        p95_hz=p95_hz,
        min_dt_ms=sorted_dt[0],
        median_dt_ms=median_dt_ms,
        max_dt_ms=sorted_dt[-1],
    )


def measure_polling_rate(device_path: Path, duration_s: float = 3.0) -> PollingRateStats:
    """Read live HID movement reports (non-destructively, ``O_RDONLY``) to measure Hz."""
    if not 0.2 <= duration_s <= 15.0:
        raise TransportError(f"Measurement duration {duration_s}s out of range [0.2, 15.0].")

    try:
        fd = os.open(device_path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EPERM):
            raise DevicePermissionError(
                f"Permission denied opening {device_path}. "
                "Install udev rules ('zircon500 udev-rules') or run with sufficient privileges."
            ) from exc
        raise TransportError(f"Failed to open {device_path}: {exc}") from exc

    timestamps_ns: list[int] = []
    try:
        # Flush stale buffered reports before starting timing window.
        while True:
            try:
                if not os.read(fd, 64):
                    break
            except BlockingIOError:
                break

        poller = select.poll()
        poller.register(fd, select.POLLIN)
        deadline = time.monotonic() + duration_s

        while True:
            remaining_ms = int((deadline - time.monotonic()) * 1000.0)
            if remaining_ms <= 0:
                break
            events = poller.poll(remaining_ms)
            if not events:
                continue
            now_ns = time.perf_counter_ns()
            while True:
                try:
                    data = os.read(fd, 64)
                except BlockingIOError:
                    break
                if not data:
                    break
                timestamps_ns.append(now_ns)
    finally:
        os.close(fd)

    return compute_polling_rate_stats(device_path, timestamps_ns, duration_s)


class ZirconHidTransport:
    """Context-managed ``HIDIOCSFEATURE`` / ``HIDIOCGFEATURE`` transport."""

    def __init__(self, device_path: Path) -> None:
        self.device_path = device_path
        self._fd: int | None = None
        self._seq: int = 0

    def __enter__(self) -> ZirconHidTransport:
        try:
            self._fd = os.open(self.device_path, os.O_RDWR)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EPERM):
                raise DevicePermissionError(
                    f"Permission denied opening {self.device_path}. "
                    "Install udev rules ('zircon500 udev-rules') or run with sufficient privileges."
                ) from exc
            raise TransportError(f"Failed to open {self.device_path}: {exc}") from exc
        return self

    def __exit__(self, *_: object) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None

    def next_seq(self) -> int:
        seq = self._seq
        self._seq = (self._seq + 1) & 0xFF
        return seq

    def send_feature(self, frame: bytes) -> None:
        if self._fd is None:
            raise TransportError("Transport is not open.")
        if len(frame) != REPORT_LENGTH:
            raise TransportError(
                f"Expected {REPORT_LENGTH}-byte Feature Report, got {len(frame)}."
            )
        buf = bytearray(frame)
        try:
            fcntl.ioctl(self._fd, _hid_ioc_sfeature(len(buf)), buf, True)
        except OSError as exc:
            raise TransportError(f"HIDIOCSFEATURE failed on {self.device_path}: {exc}") from exc

    def get_feature(self, report_id: int = REPORT_ID_FEATURE) -> bytes:
        if self._fd is None:
            raise TransportError("Transport is not open.")
        buf = bytearray(REPORT_LENGTH)
        buf[0] = report_id & 0xFF
        try:
            fcntl.ioctl(self._fd, _hid_ioc_gfeature(len(buf)), buf, True)
        except OSError as exc:
            raise TransportError(f"HIDIOCGFEATURE failed on {self.device_path}: {exc}") from exc
        return bytes(buf)

    def query_status(self) -> DeviceStatus:
        """Query ``cmd 0x20`` live status, mirroring Windows retry-on-zero-len behavior."""
        last_exc: Exception | None = None
        for attempt in range(2):
            frame = build_status_query(seq=self.next_seq())
            self.send_feature(frame)
            time.sleep(0.015)
            rx = self.get_feature(REPORT_ID_FEATURE)
            if rx[6] == 0 and attempt == 0:
                continue
            try:
                return parse_status_response(rx)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
        raise TransportError(f"Device did not return a valid 0x20 status response: {last_exc}")
