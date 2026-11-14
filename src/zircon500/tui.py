"""Minimalist, bilingual (EN/PL) interactive TUI for Genesis Zircon 500 (v1)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import time

from rich.markup import escape
from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Checkbox,
    ContentSwitcher,
    DataTable,
    Footer,
    Input,
    Label,
    RichLog,
    Select,
    Static,
    Switch,
)

from . import __version__
from .i18n import get_saved_lang, normalize_lang, save_lang, t
from .profile import load_profile, reset_profile, save_profile
from .protocol import (
    BUTTON_PRESETS,
    DEFAULT_DPI_STAGES,
    DeviceStatus,
    ProtocolError,
    build_button_packet,
    build_debounce_packet,
    build_dpi_packet,
    build_lod_packet,
    build_motion_wake_packet,
    build_polling_rate_packet,
    build_power_packet,
    build_reset_defaults_packet,
    parse_input_event_report,
)
from .transport import (
    HidrawDeviceInfo,
    PollingRateStats,
    TransportError,
    ZirconHidTransport,
    discover_devices,
    measure_polling_rate,
    select_control_device,
    select_event_devices,
    select_mouse_input_device,
)
from .ui import GENESIS_LOGO_COMPACT

UDEV_RULE_CONTENT = """SUBSYSTEM=="hidraw", ATTRS{idVendor}=="248a", ATTRS{idProduct}=="5b2e", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="usb", ATTRS{idVendor}=="248a", ATTRS{idProduct}=="5b2e", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="248a", ATTRS{idProduct}=="5b2f", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="usb", ATTRS{idVendor}=="248a", ATTRS{idProduct}=="5b2f", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="331a", ATTRS{idProduct}=="5024", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="usb", ATTRS{idVendor}=="331a", ATTRS{idProduct}=="5024", MODE="0660", TAG+="uaccess\""""

NAV_PAGES: tuple[tuple[str, str, str], ...] = (
    ("nav-dpi", "tab-dpi", "nav_dpi"),
    ("nav-sensor", "tab-sensor", "nav_sensor"),
    ("nav-buttons", "tab-buttons", "nav_buttons"),
    ("nav-power", "tab-power", "nav_power"),
    ("nav-device", "tab-device", "nav_device"),
)


def _parse_stage_value(token: str) -> int | tuple[int, int]:
    cleaned = token.strip().lower()
    if "x" in cleaned:
        parts = cleaned.split("x", 1)
        return int(parts[0], 10), int(parts[1], 10)
    return int(cleaned, 10)


class ZirconTuiApp(App[None]):
    """Minimalist keyboard + mouse configurator for Genesis Zircon 500 (v1)."""

    TITLE = "Genesis Zircon 500"
    CSS = """
    Screen {
        background: #0e1015;
        color: #e6e8ef;
    }

    #top-bar {
        height: 11;
        padding: 0 2;
        background: #13161e;
        border-bottom: solid #262b38;
        align: left middle;
    }

    #logo-box {
        width: 24;
        height: 10;
        content-align: center middle;
    }

    #header-main {
        width: 1fr;
        height: auto;
        padding-left: 2;
    }

    #app-title {
        text-style: bold;
        color: #ffffff;
    }

    #status-summary {
        color: #b8becd;
        margin-top: 1;
        margin-bottom: 1;
    }

    #toolbar {
        height: auto;
        align: left middle;
    }

    #toolbar Button {
        height: 1;
        min-width: 14;
        border: none;
        background: #1e2330;
        color: #d8dce8;
        margin-right: 1;
        padding: 0 2;
    }

    #toolbar Button:hover {
        background: #2b3244;
    }

    #toolbar Button.-active-pill {
        background: #e51923;
        color: #ffffff;
        text-style: bold;
    }

    #workspace {
        height: 1fr;
    }

    #nav-rail {
        width: 24;
        background: #11131a;
        border-right: solid #262b38;
        padding: 1 0;
    }

    .nav-btn {
        width: 100%;
        height: 3;
        border: none;
        border-left: wide transparent;
        background: transparent;
        color: #9ba3b5;
        content-align: left middle;
        padding: 0 2;
        text-style: none;
    }

    .nav-btn:hover {
        background: #181c26;
        color: #ffffff;
    }

    .nav-btn:focus {
        background: #1a1e29;
        color: #ffffff;
    }

    .nav-btn.-selected {
        background: #1a1d27;
        border-left: wide #e51923;
        color: #ffffff;
        text-style: bold;
    }

    #pages {
        width: 1fr;
        padding: 1 3;
    }

    .page-scroll {
        height: 1fr;
    }

    .page-title {
        text-style: bold;
        color: #ffffff;
        margin-bottom: 0;
    }

    .hint {
        color: #7d8597;
        margin-bottom: 1;
    }

    .field-block {
        height: auto;
        margin-bottom: 0;
    }

    .field-row {
        height: auto;
        align: left middle;
    }

    .field-lbl {
        width: 26;
        color: #d4d8e4;
    }

    .inline-lbl {
        width: 20;
        color: #d4d8e4;
        padding-left: 2;
    }

    .compact-in {
        width: 14;
        margin-right: 1;
    }

    .wide-in {
        width: 34;
        margin-right: 1;
    }

    .chip-btn {
        height: 1;
        min-width: 7;
        border: none;
        background: #1e2330;
        color: #d4d8e4;
        margin-right: 1;
        padding: 0 1;
    }

    .chip-btn:hover {
        background: #2b3244;
    }

    #dpi-grid {
        grid-size: 4 2;
        grid-gutter: 0 1;
        height: auto;
        margin-bottom: 1;
    }

    .dpi-cell {
        height: auto;
        background: #141720;
        padding: 0 1;
        border: round #222736;
    }

    .dpi-cell.-active-cell {
        background: #1d151b;
        border: round #e51923;
    }

    .dpi-cell.-disabled-cell {
        background: #0d0f14;
        border: round #191d28;
        opacity: 0.45;
    }

    .dpi-cell-title {
        color: #8f97aa;
        text-style: bold;
    }

    .dpi-cell.-active-cell .dpi-cell-title {
        color: #ff6b72;
    }

    .dpi-cell.-disabled-cell .dpi-cell-title {
        color: #4f5668;
    }

    .actions {
        height: auto;
        margin-top: 1;
    }

    .actions Button {
        height: 1;
        border: none;
        padding: 0 2;
        margin-right: 1;
    }

    #dev-table {
        height: 8;
        margin-bottom: 1;
    }

    #udev-box {
        background: #13161e;
        border: round #262b38;
        padding: 1;
        color: #98d8f4;
    }

    #tx-log {
        display: none;
        height: 5;
        border-top: solid #262b38;
        background: #0a0c10;
        padding: 0 2;
    }

    #tx-log.-open {
        display: block;
    }

    #status-toast {
        height: 1;
        background: #13161e;
        border-top: solid #262b38;
        padding: 0 2;
        color: #b8becd;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("escape", "quit", "Quit"),
        Binding("l", "toggle_lang", "EN/PL", priority=True),
        Binding("d", "toggle_dry_run", "Dry-Run"),
        Binding("x", "toggle_hex_log", "Hex Log"),
        Binding("r", "refresh_device", "Refresh"),
        Binding("f1", "select_tab('tab-dpi')", "1:DPI", priority=True),
        Binding("f2", "select_tab('tab-sensor')", "2:Sensor", priority=True),
        Binding("f3", "select_tab('tab-buttons')", "3:Buttons", priority=True),
        Binding("f4", "select_tab('tab-power')", "4:Power", priority=True),
        Binding("f5", "select_tab('tab-device')", "5:Device", priority=True),
        Binding("1", "select_tab('tab-dpi')", "1", show=False),
        Binding("2", "select_tab('tab-sensor')", "2", show=False),
        Binding("3", "select_tab('tab-buttons')", "3", show=False),
        Binding("4", "select_tab('tab-power')", "4", show=False),
        Binding("5", "select_tab('tab-device')", "5", show=False),
    ]

    def __init__(
        self,
        *,
        device_path: Path | None = None,
        dry_run: bool = False,
        lang: str | None = None,
    ) -> None:
        super().__init__()
        self.device_path = device_path
        self.dry_run = dry_run
        self.lang = normalize_lang(lang) if lang else get_saved_lang()
        self._profile = load_profile()
        self._seq = 0
        self._active_tab = "tab-dpi"
        self._devices: list[HidrawDeviceInfo] = []
        self._selected: HidrawDeviceInfo | None = None
        self._status: DeviceStatus | None = None
        self._last_error: str | None = None
        self._suppress_dpi_events: bool = False
        self._event_fds: dict[int, Path] = {}
        self._event_readers: set[int] = set()
        self._poll_timer: object | None = None
        self._status_sync_timer: object | None = None
        self._status_sync_inflight: bool = False
        self._hid_busy: bool = False
        self._saw_hid_event: bool = False
        self._hz_test_running: bool = False

    def _tr(self, key: str, **kwargs: object) -> str:
        return t(key, self.lang, **kwargs)

    def compose(self) -> ComposeResult:
        logo_text = Text(GENESIS_LOGO_COMPACT.strip("\n"), style="#e51923")

        with Horizontal(id="top-bar"):
            yield Static(logo_text, id="logo-box")
            with Vertical(id="header-main"):
                yield Static(
                    "[bold]GENESIS ZIRCON 500[/bold]",
                    id="app-title",
                )
                yield Static(self._tr("tui_detecting"), id="status-summary")
                with Horizontal(id="toolbar"):
                    yield Button(self._tr("btn_lang"), id="btn-lang")
                    yield Button(
                        self._tr("btn_dry_on" if self.dry_run else "btn_dry_off"),
                        id="btn-dry-run",
                        classes="-active-pill" if self.dry_run else "",
                    )
                    yield Button(self._tr("btn_hex"), id="btn-hex-log")
                    yield Button(self._tr("btn_refresh"), id="btn-refresh")

        with Horizontal(id="workspace"):
            with Vertical(id="nav-rail"):
                for nav_id, _, i18n_key in NAV_PAGES:
                    cls = "nav-btn -selected" if nav_id == "nav-dpi" else "nav-btn"
                    yield Button(self._tr(i18n_key), id=nav_id, classes=cls)

            with ContentSwitcher(initial="tab-dpi", id="pages"):
                # 1. DPI Stages (no unused RGB hex fields)
                with VerticalScroll(id="tab-dpi", classes="page-scroll"):
                    yield Static(self._tr("dpi_title"), id="lbl-dpi-title", classes="page-title")
                    yield Static(self._tr("dpi_desc"), id="lbl-dpi-desc", classes="hint")
                    with Horizontal(classes="field-row field-block"):
                        yield Label(self._tr("dpi_active_lbl"), id="lbl-dpi-active", classes="field-lbl")
                        p_count = int(self._profile["dpi_count"])
                        p_stages = list(self._profile["dpi_stages"])
                        p_active = min(int(self._profile["active_dpi"]), p_count - 1)
                        yield Select(
                            [(self._tr("dpi_select_opt", n=i + 1, dpi=p_stages[i]), i) for i in range(p_count)],
                            value=p_active,
                            allow_blank=False,
                            compact=True,
                            id="sel-dpi-active",
                        )
                        yield Label(self._tr("dpi_count_lbl"), id="lbl-dpi-count", classes="inline-lbl")
                        yield Select([(str(n), n) for n in range(1, 9)], value=p_count, allow_blank=False, compact=True, id="sel-dpi-count")
                    with Horizontal(classes="field-row field-block"):
                        yield Checkbox(self._tr("dpi_snap_lbl"), value=bool(self._profile["dpi_snap"]), compact=True, id="chk-dpi-snap")
                    with Grid(id="dpi-grid"):
                        for i in range(8):
                            with Vertical(id=f"cell-dpi-{i}", classes="dpi-cell"):
                                yield Label(self._tr("dpi_stage_cell", n=i + 1), id=f"lbl-stage-{i}", classes="dpi-cell-title")
                                yield Input(value=str(p_stages[i]), placeholder="DPI", compact=True, id=f"in-dpi-{i}")
                    with Horizontal(classes="actions"):
                        yield Button(self._tr("dpi_apply"), id="btn-apply-dpi", variant="primary")
                        yield Button(self._tr("dpi_defaults"), id="btn-reset-dpi-fields")

                # 2. Sensor & Input Latency
                with VerticalScroll(id="tab-sensor", classes="page-scroll"):
                    yield Static(self._tr("sensor_title"), id="lbl-sensor-title", classes="page-title")
                    with Vertical(classes="field-block"):
                        with Horizontal(classes="field-row"):
                            yield Label(self._tr("sensor_rate_lbl"), id="lbl-rate", classes="field-lbl")
                            yield Select(
                                [("1000 Hz (1 ms)", 1000), ("500 Hz (2 ms)", 500), ("250 Hz (4 ms)", 250), ("125 Hz (8 ms)", 125)],
                                value=int(self._profile["polling_rate"]),
                                allow_blank=False,
                                compact=True,
                                id="sel-rate",
                            )
                        yield Static(self._tr("sensor_rate_hint"), id="hint-rate", classes="hint")
                    with Vertical(classes="field-block"):
                        with Horizontal(classes="field-row"):
                            yield Label(self._tr("sensor_lod_lbl"), id="lbl-lod", classes="field-lbl")
                            yield Select([("2 mm (default)", 2), ("1 mm (low)", 1)], value=int(self._profile["lod"]), allow_blank=False, compact=True, id="sel-lod")
                        yield Static(self._tr("sensor_lod_hint"), id="hint-lod", classes="hint")
                    with Vertical(classes="field-block"):
                        with Horizontal(classes="field-row"):
                            yield Label(self._tr("sensor_deb_lbl"), id="lbl-deb", classes="field-lbl")
                            yield Input(value=str(self._profile["debounce_ms"]), placeholder="2..20", compact=True, id="in-debounce", classes="compact-in")
                            yield Button("2ms", id="btn-deb-2", classes="chip-btn")
                            yield Button("4ms", id="btn-deb-4", classes="chip-btn")
                            yield Button("8ms", id="btn-deb-8", classes="chip-btn")
                            yield Button("12ms", id="btn-deb-12", classes="chip-btn")
                        yield Static(self._tr("sensor_deb_hint"), id="hint-deb", classes="hint")
                    with Horizontal(classes="actions"):
                        yield Button(self._tr("sensor_apply"), id="btn-apply-sensor", variant="primary")
                        yield Button(self._tr("sensor_test_btn"), id="btn-test-hz")
                    yield Static(self._tr("sensor_test_hint"), id="hint-test-hz", classes="hint")
                    yield Static("", id="lbl-hz-result", classes="hint")

                # 3. Buttons
                with VerticalScroll(id="tab-buttons", classes="page-scroll"):
                    yield Static(self._tr("btn_title"), id="lbl-btn-title", classes="page-title")
                    with Vertical(classes="field-block"):
                        with Horizontal(classes="field-row"):
                            yield Label(self._tr("btn_slot_lbl"), id="lbl-btn-slot", classes="field-lbl")
                            yield Select(
                                [
                                    ("0: Left", "left"),
                                    ("1: Right", "right"),
                                    ("2: Middle / Scroll", "middle"),
                                    ("3: Forward (-> HW4)", "forward"),
                                    ("4: Backward (-> HW3)", "backward"),
                                    ("5: DPI", "dpi"),
                                ],
                                value="forward",
                                allow_blank=False,
                                compact=True,
                                id="sel-btn-slot",
                            )
                        yield Static(self._tr("btn_slot_hint"), id="hint-btn-slot", classes="hint")
                    with Horizontal(classes="field-row field-block"):
                        yield Label(self._tr("btn_preset_lbl"), id="lbl-btn-preset", classes="field-lbl")
                        yield Select([(name, name) for name in BUTTON_PRESETS.keys()], value="dpi-loop", allow_blank=False, compact=True, id="sel-btn-preset")
                    with Vertical(classes="field-block"):
                        with Horizontal(classes="field-row"):
                            yield Label(self._tr("btn_custom_lbl"), id="lbl-btn-custom", classes="field-lbl")
                            yield Input(value="", placeholder="key:ctrl+c | key:space | fire:50:3", compact=True, id="in-btn-custom", classes="wide-in")
                        yield Static(self._tr("btn_custom_hint"), id="hint-btn-custom", classes="hint")
                    with Horizontal(classes="actions"):
                        yield Button(self._tr("btn_apply"), id="btn-apply-button", variant="primary")
                        yield Button(self._tr("btn_clear"), id="btn-clear-btn-custom")
                        yield Button(self._tr("btn_reset_all"), id="btn-reset-buttons")

                # 4. Power & Reset (without unsupported "turn off RGB while moving")
                with VerticalScroll(id="tab-power", classes="page-scroll"):
                    yield Static(self._tr("pwr_title"), id="lbl-pwr-title", classes="page-title")
                    with Vertical(classes="field-block"):
                        with Horizontal(classes="field-row"):
                            yield Label(self._tr("pwr_sleep_lbl"), id="lbl-pwr-sleep", classes="field-lbl")
                            yield Input(value=str(self._profile["sleep_minutes"]), placeholder="1..60", compact=True, id="in-sleep", classes="compact-in")
                        yield Static(self._tr("pwr_sleep_hint"), id="hint-pwr-sleep", classes="hint")
                    with Vertical(classes="field-block"):
                        with Horizontal(classes="field-row"):
                            yield Label(self._tr("pwr_wake_lbl"), id="lbl-pwr-wake", classes="field-lbl")
                            yield Switch(value=bool(self._profile["motion_wake"]), id="switch-motion-wake")
                        yield Static(self._tr("pwr_wake_hint"), id="hint-pwr-wake", classes="hint")
                    with Horizontal(classes="actions"):
                        yield Button(self._tr("pwr_apply"), id="btn-apply-power", variant="primary")
                    yield Static(self._tr("rst_title"), id="lbl-rst-title", classes="page-title")
                    yield Static(self._tr("rst_hint"), id="hint-rst", classes="hint")
                    with Horizontal(classes="field-row field-block"):
                        yield Checkbox(self._tr("rst_confirm"), value=False, compact=True, id="chk-confirm-reset")
                    with Horizontal(classes="actions"):
                        yield Button(self._tr("rst_apply"), id="btn-reset-defaults", variant="error")

                # 5. Device & udev
                with VerticalScroll(id="tab-device", classes="page-scroll"):
                    yield Static(self._tr("dev_title"), id="lbl-dev-title", classes="page-title")
                    yield DataTable(id="dev-table", zebra_stripes=True)
                    yield Static(self._tr("dev_udev_hint"), id="hint-udev", classes="hint")
                    rules_path = Path(__file__).resolve().parents[2] / "udev" / "69-genesis-zircon-500.rules"
                    install_cmd = (
                        f"sudo cp '{rules_path}' /etc/udev/rules.d/ && "
                        "sudo udevadm control --reload-rules && "
                        "sudo udevadm trigger --subsystem-match=hidraw --action=add"
                    )
                    yield Static(f"{UDEV_RULE_CONTENT}\n\n{escape(install_cmd)}", id="udev-box")

        yield RichLog(id="tx-log", markup=True, wrap=True, highlight=False)
        yield Static(self._tr("ready_toast"), id="status-toast")
        yield Footer()

    def on_mount(self) -> None:
        self._rebuild_device_table_columns()
        self.refresh_device_state()
        self._sync_dpi_grid_ui()
        if not self.dry_run:
            self._status_sync_timer = self.set_interval(0.8, self._schedule_status_sync)
        self.query_one("#nav-dpi", Button).focus()

    def on_unmount(self) -> None:
        if self._status_sync_timer is not None:
            stop_fn = getattr(self._status_sync_timer, "stop", None)
            if callable(stop_fn):
                stop_fn()
            self._status_sync_timer = None
        self._close_event_fds()

    def _remove_event_fd(self, fd: int) -> None:
        if fd in self._event_readers:
            try:
                asyncio.get_running_loop().remove_reader(fd)
            except (RuntimeError, NotImplementedError, ValueError):
                pass
            self._event_readers.discard(fd)
        if fd in self._event_fds:
            self._event_fds.pop(fd, None)
            try:
                os.close(fd)
            except OSError:
                pass

    def _close_event_fds(self) -> None:
        if self._poll_timer is not None:
            stop_fn = getattr(self._poll_timer, "stop", None)
            if callable(stop_fn):
                stop_fn()
            self._poll_timer = None
        for fd in list(self._event_fds):
            self._remove_event_fd(fd)

    def _ensure_event_fds(self) -> None:
        if self.dry_run or self._selected is None:
            self._close_event_fds()
            return
        targets = select_event_devices(self._selected, self._devices)
        target_paths = {dev.path for dev in targets}
        if target_paths and set(self._event_fds.values()) == target_paths:
            return
        self._close_event_fds()
        need_fallback_timer = False
        for dev in targets:
            try:
                fd = os.open(dev.path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            # Drain any pre-existing queued reports so only fresh presses trigger UI sync.
            while True:
                try:
                    data = os.read(fd, 64)
                    if not data:
                        break
                except BlockingIOError:
                    break
                except OSError:
                    break
            self._event_fds[fd] = dev.path
            try:
                asyncio.get_running_loop().add_reader(fd, lambda fd=fd: self._poll_hid_events(fd))
                self._event_readers.add(fd)
            except PermissionError:
                self._remove_event_fd(fd)
            except (RuntimeError, NotImplementedError):
                need_fallback_timer = True
        if need_fallback_timer and self._event_fds:
            self._poll_timer = self.set_interval(0.15, self._poll_hid_events)

    def _poll_hid_events(self, target_fd: int | None = None) -> None:
        if self.dry_run or not self._event_fds:
            return
        fds = [target_fd] if (target_fd is not None and target_fd in self._event_fds) else list(self._event_fds)
        latest_stage: int | None = None
        latest_hz: int | None = None
        for fd in fds:
            dev_path = self._event_fds.get(fd)
            while True:
                try:
                    pkt = os.read(fd, 64)
                except BlockingIOError:
                    break
                except OSError:
                    self._remove_event_fd(fd)
                    break
                if not pkt:
                    break
                stage_idx, hz = parse_input_event_report(pkt)
                if stage_idx is not None:
                    latest_stage = stage_idx
                if hz is not None:
                    latest_hz = hz
                if stage_idx is None and hz is None:
                    is_secondary = self._selected is not None and dev_path is not None and dev_path != self._selected.path
                    if pkt[0] == 0x05 or (is_secondary and pkt[0] not in (0x01, 0x02)):
                        hex_str = " ".join(f"{b:02x}" for b in pkt[:16])
                        name = dev_path.name if dev_path else f"fd{fd}"
                        self._log_hex(f"[cyan][RX IN {escape(name)}] {hex_str}[/cyan]")

        if latest_stage is not None or latest_hz is not None:
            self._saw_hid_event = True
        if latest_stage is not None:
            count = self._get_dpi_count()
            clamped = min(latest_stage, count - 1)
            self._set_active_dpi_select(clamped)
            self._sync_dpi_grid_ui(rebuild_options=False)
            self._set_toast(f"[cyan]● {escape(self._tr('dpi_hw_sync', stage=clamped + 1))}[/cyan]")
            self._log_hex(f"[cyan][RX IN 0x05] DPI stage -> {clamped + 1}/{count}[/cyan]")
        if latest_hz is not None:
            sel_rate = self.query_one("#sel-rate", Select)
            if sel_rate.value != latest_hz:
                self._suppress_dpi_events = True
                try:
                    sel_rate.value = latest_hz
                finally:
                    self._suppress_dpi_events = False
                self._set_toast(f"[cyan]● {escape(self._tr('dpi_rate_hw_sync', hz=latest_hz))}[/cyan]")

    def _schedule_status_sync(self) -> None:
        """Gently poll ``cmd 0x20`` on ``tab-dpi`` if hardware does not push Input ``0x05``."""
        if (
            self.dry_run
            or self._selected is None
            or self._active_tab != "tab-dpi"
            or self._saw_hid_event
            or self._hz_test_running
            or self._status_sync_inflight
            or self._hid_busy
        ):
            return
        self.run_worker(self._sync_status_async(self._selected.path), exclusive=False)

    async def _sync_status_async(self, path: Path) -> None:
        self._status_sync_inflight = True
        try:
            def _read() -> DeviceStatus:
                with ZirconHidTransport(path) as hid:
                    return hid.query_status()

            st = await asyncio.to_thread(_read)
        except (TransportError, OSError):
            return
        finally:
            self._status_sync_inflight = False

        if self._selected is None or self._selected.path != path:
            return
        prev = self._status
        prev_key = (
            (prev.active_dpi_stage, prev.dpi_stage_count, prev.battery_pct, prev.charging_state)
            if prev is not None
            else None
        )
        new_key = (st.active_dpi_stage, st.dpi_stage_count, st.battery_pct, st.charging_state)
        if prev_key == new_key:
            return

        prev_stage = prev.active_dpi_stage if prev is not None else None
        self._status = st
        if st.active_dpi_stage is not None and st.active_dpi_stage != prev_stage:
            count = self._get_dpi_count()
            clamped = min(st.active_dpi_stage, count - 1)
            self._set_active_dpi_select(clamped)
            self._sync_dpi_grid_ui(rebuild_options=False)
            self._set_toast(f"[cyan]● {escape(self._tr('dpi_hw_sync', stage=clamped + 1))}[/cyan]")
            self._log_hex(
                f"[cyan][SYNC 0x20] DPI stage -> {clamped + 1}/{count} "
                f"(raw[16]=0x{st.dpi_status_raw:02x})[/cyan]"
            )
        self._render_device_status_views()

    def _get_dpi_count(self) -> int:
        val = self.query_one("#sel-dpi-count", Select).value
        if val is Select.BLANK or val is None:
            return 6
        return max(1, min(8, int(val)))

    def _get_active_dpi_stage(self, count: int) -> int:
        val = self.query_one("#sel-dpi-active", Select).value
        if val is Select.BLANK or val is None:
            return 0
        return max(0, min(count - 1, int(val)))

    def _set_active_dpi_select(self, stage_idx: int) -> None:
        sel = self.query_one("#sel-dpi-active", Select)
        if sel.value != stage_idx:
            with sel.prevent(Select.Changed):
                sel.value = stage_idx

    def _sync_dpi_grid_ui(self, *, rebuild_options: bool = True) -> None:
        count = self._get_dpi_count()
        active = self._get_active_dpi_stage(count)
        sel_active = self.query_one("#sel-dpi-active", Select)

        if rebuild_options:
            opts = [
                (
                    self._tr(
                        "dpi_select_opt",
                        n=i + 1,
                        dpi=self.query_one(f"#in-dpi-{i}", Input).value.strip() or "?",
                    ),
                    i,
                )
                for i in range(count)
            ]
            with sel_active.prevent(Select.Changed):
                sel_active.set_options(opts)
                sel_active.value = active
        elif sel_active.value != active:
            self._set_active_dpi_select(active)

        for i in range(8):
            cell = self.query_one(f"#cell-dpi-{i}", Vertical)
            lbl = self.query_one(f"#lbl-stage-{i}", Label)
            inp = self.query_one(f"#in-dpi-{i}", Input)
            if i < count:
                inp.disabled = False
                cell.remove_class("-disabled-cell")
                is_active = i == active
                cell.set_class(is_active, "-active-cell")
                lbl.update(self._tr("dpi_stage_cell_active" if is_active else "dpi_stage_cell", n=i + 1))
            else:
                inp.disabled = True
                cell.remove_class("-active-cell")
                cell.add_class("-disabled-cell")
                lbl.update(self._tr("dpi_stage_cell_off", n=i + 1))

    @on(Select.Changed, "#sel-dpi-count")
    def _on_dpi_count_changed(self, _: Select.Changed) -> None:
        if not self._suppress_dpi_events:
            self._sync_dpi_grid_ui(rebuild_options=True)

    @on(Select.Changed, "#sel-dpi-active")
    def _on_dpi_active_changed(self, _: Select.Changed) -> None:
        if not self._suppress_dpi_events:
            self._sync_dpi_grid_ui(rebuild_options=False)

    @on(Input.Changed)
    def _on_stage_input_changed(self, event: Input.Changed) -> None:
        inp_id = event.input.id or ""
        if inp_id.startswith("in-dpi-") and not self._suppress_dpi_events:
            idx = int(inp_id.rsplit("-", 1)[-1])
            if idx < self._get_dpi_count():
                self._sync_dpi_grid_ui(rebuild_options=True)

    def _rebuild_device_table_columns(self) -> None:
        table = self.query_one("#dev-table", DataTable)
        table.clear(columns=True)
        table.add_columns(
            self._tr("col_path"),
            self._tr("col_vidpid"),
            self._tr("col_mode"),
            self._tr("col_if"),
            self._tr("col_role"),
            self._tr("col_perms"),
        )

    def _set_toast(self, markup_msg: str) -> None:
        self.query_one("#status-toast", Static).update(markup_msg)

    def _log_hex(self, markup_msg: str) -> None:
        self.query_one("#tx-log", RichLog).write(markup_msg)

    def _next_seq(self) -> int:
        val = self._seq
        self._seq = (self._seq + 1) & 0xFF
        return val

    def _apply_language_texts(self) -> None:
        self.query_one("#app-title", Static).update(
            "[bold]GENESIS ZIRCON 500[/bold]"
        )
        self.query_one("#btn-lang", Button).label = self._tr("btn_lang")
        self.query_one("#btn-dry-run", Button).label = self._tr("btn_dry_on" if self.dry_run else "btn_dry_off")
        self.query_one("#btn-hex-log", Button).label = self._tr("btn_hex")
        self.query_one("#btn-refresh", Button).label = self._tr("btn_refresh")

        for nav_id, _, key in NAV_PAGES:
            self.query_one(f"#{nav_id}", Button).label = self._tr(key)

        label_map = {
            "#lbl-dpi-title": "dpi_title",
            "#lbl-dpi-desc": "dpi_desc",
            "#lbl-dpi-active": "dpi_active_lbl",
            "#lbl-dpi-count": "dpi_count_lbl",
            "#lbl-sensor-title": "sensor_title",
            "#lbl-rate": "sensor_rate_lbl",
            "#hint-rate": "sensor_rate_hint",
            "#lbl-lod": "sensor_lod_lbl",
            "#hint-lod": "sensor_lod_hint",
            "#lbl-deb": "sensor_deb_lbl",
            "#hint-deb": "sensor_deb_hint",
            "#hint-test-hz": "sensor_test_hint",
            "#lbl-btn-title": "btn_title",
            "#lbl-btn-slot": "btn_slot_lbl",
            "#hint-btn-slot": "btn_slot_hint",
            "#lbl-btn-preset": "btn_preset_lbl",
            "#lbl-btn-custom": "btn_custom_lbl",
            "#hint-btn-custom": "btn_custom_hint",
            "#lbl-pwr-title": "pwr_title",
            "#lbl-pwr-sleep": "pwr_sleep_lbl",
            "#hint-pwr-sleep": "pwr_sleep_hint",
            "#lbl-pwr-wake": "pwr_wake_lbl",
            "#hint-pwr-wake": "pwr_wake_hint",
            "#lbl-rst-title": "rst_title",
            "#hint-rst": "rst_hint",
            "#lbl-dev-title": "dev_title",
            "#hint-udev": "dev_udev_hint",
        }
        for sel, key in label_map.items():
            self.query_one(sel).update(self._tr(key))

        self.query_one("#chk-dpi-snap", Checkbox).label = self._tr("dpi_snap_lbl")
        self.query_one("#chk-confirm-reset", Checkbox).label = self._tr("rst_confirm")

        btn_map = {
            "#btn-apply-dpi": "dpi_apply",
            "#btn-reset-dpi-fields": "dpi_defaults",
            "#btn-apply-sensor": "sensor_apply",
            "#btn-test-hz": "sensor_test_btn",
            "#btn-apply-button": "btn_apply",
            "#btn-clear-btn-custom": "btn_clear",
            "#btn-reset-buttons": "btn_reset_all",
            "#btn-apply-power": "pwr_apply",
            "#btn-reset-defaults": "rst_apply",
        }
        for sel, key in btn_map.items():
            self.query_one(sel, Button).label = self._tr(key)

        self._rebuild_device_table_columns()
        self._render_device_status_views()
        self._sync_dpi_grid_ui(rebuild_options=True)

    def action_toggle_lang(self) -> None:
        self.lang = "pl" if self.lang == "en" else "en"
        save_lang(self.lang)
        self._apply_language_texts()
        self._set_toast(f"[cyan]✓ {self._tr('btn_lang')}[/cyan]")

    def action_toggle_dry_run(self) -> None:
        self.dry_run = not self.dry_run
        btn = self.query_one("#btn-dry-run", Button)
        btn.label = self._tr("btn_dry_on" if self.dry_run else "btn_dry_off")
        btn.set_class(self.dry_run, "-active-pill")
        self._ensure_event_fds()
        if not self.dry_run and self._status_sync_timer is None:
            self._status_sync_timer = self.set_interval(0.8, self._schedule_status_sync)
        self._set_toast(f"[yellow]{self._tr('btn_dry_on' if self.dry_run else 'btn_dry_off')}[/yellow]")

    def action_toggle_hex_log(self) -> None:
        log = self.query_one("#tx-log", RichLog)
        is_open = not log.has_class("-open")
        log.set_class(is_open, "-open")
        self.query_one("#btn-hex-log", Button).set_class(is_open, "-active-pill")

    def action_refresh_device(self) -> None:
        self.refresh_device_state()

    def action_select_tab(self, tab_id: str) -> None:
        self._active_tab = tab_id
        self.query_one("#pages", ContentSwitcher).current = tab_id
        for nav_id, pane_id, _ in NAV_PAGES:
            self.query_one(f"#{nav_id}", Button).set_class(pane_id == tab_id, "-selected")

    def on_key(self, event: object) -> None:
        key = getattr(event, "key", "")
        focused = self.focused
        if isinstance(focused, Button) and focused.id and focused.id.startswith("nav-"):
            ids = [item[0] for item in NAV_PAGES]
            if key in ("down", "up") and focused.id in ids:
                idx = ids.index(focused.id)
                nxt = ids[(idx + (1 if key == "down" else -1)) % len(ids)]
                self.query_one(f"#{nxt}", Button).focus()
                self.action_select_tab(dict((i[0], i[1]) for i in NAV_PAGES)[nxt])

    def refresh_device_state(self) -> None:
        self._devices = discover_devices()
        self._selected = None
        self._status = None
        self._last_error = None
        self._saw_hid_event = False

        self._hid_busy = True
        try:
            self._selected = select_control_device(self.device_path)
            with ZirconHidTransport(self._selected.path) as hid:
                self._status = hid.query_status()
        except TransportError as exc:
            self._last_error = str(exc)
        finally:
            self._hid_busy = False

        self._ensure_event_fds()
        self._sync_from_status()
        self._render_device_status_views()

    def _sync_from_status(self) -> None:
        st = self._status
        if st is None or st.dpi_stage_count is None:
            return
        sel_count = self.query_one("#sel-dpi-count", Select)
        if sel_count.value != st.dpi_stage_count:
            with sel_count.prevent(Select.Changed):
                sel_count.value = st.dpi_stage_count
        self._sync_dpi_grid_ui(rebuild_options=True)
        if st.active_dpi_stage is not None:
            self._set_active_dpi_select(st.active_dpi_stage)
            self._sync_dpi_grid_ui(rebuild_options=False)

    def _render_device_status_views(self) -> None:
        table = self.query_one("#dev-table", DataTable)
        table.clear()
        if not self._devices:
            table.add_row("—", "—", self._tr("no_devices"), "—", "—", "—")
        else:
            for d in self._devices:
                role = self._tr("role_ctrl") if d.is_control_interface else self._tr("role_hid")
                if self._selected and d.path == self._selected.path:
                    role = f"● {role}"
                perms = self._tr("perm_ok") if (d.readable and d.writable) else self._tr("perm_none")
                table.add_row(
                    str(d.path),
                    f"{d.vid:04x}:{d.pid:04x}",
                    d.mode_label,
                    f"if{d.interface_number:02d}" if d.interface_number is not None else "—",
                    role,
                    perms,
                )

        summary = self.query_one("#status-summary", Static)
        if self._status is not None and self._selected is not None:
            charge_txt = self._tr(f"charge_{self._status.charging_state}")
            dpi_part = (
                f" · DPI {self._status.active_dpi_stage + 1}/{self._status.dpi_stage_count}"
                if (
                    self._status.dpi_stage_count is not None
                    and self._status.active_dpi_stage is not None
                )
                else ""
            )
            summary.update(
                f"[bold green]●[/bold green] "
                + escape(
                    self._tr(
                        "tui_connected",
                        path=str(self._selected.path),
                        mode=self._selected.mode_label,
                        sensor=self._status.sensor_name,
                        fw=self._status.firmware_tag or "N/A",
                        bat=self._status.battery_pct,
                        charge=charge_txt,
                    )
                    + dpi_part
                )
            )
            self._log_hex(
                f"[green]✓ cmd 0x20 {escape(str(self._selected.path))}: "
                f"{self._status.sensor_name}, FW={escape(self._status.firmware_tag)}, "
                f"{self._status.battery_pct}%, raw[16]=0x{self._status.dpi_status_raw:02x}[/green]"
            )
        elif self._selected is not None:
            summary.update(
                f"[bold yellow]●[/bold yellow] "
                + escape(
                    self._tr(
                        "tui_locked",
                        path=str(self._selected.path),
                        mode=self._selected.mode_label,
                    )
                )
            )
            if self._last_error:
                self._log_hex(f"[yellow]! {escape(self._last_error)}[/yellow]")
        else:
            summary.update(f"[bold red]●[/bold red] {escape(self._tr('tui_missing'))}")

    def _dispatch_packets(
        self,
        packets: list[tuple[str, bytes]],
        success_msg: str,
        *,
        refresh_after: bool = False,
        settle_s: float = 0.06,
    ) -> bool:
        for label, frame in packets:
            patched = bytearray(frame)
            patched[4] = self._next_seq()
            trimmed = bytes(patched[: max(7 + patched[6], 8)])
            hex_str = " ".join(f"{b:02x}" for b in trimmed)
            rest = len(patched) - len(trimmed)
            suffix = f" (+{rest}×00)" if rest else ""
            prefix = "[cyan][DRY-RUN][/cyan]" if self.dry_run else "[magenta][TX][/magenta]"
            self._log_hex(f"{prefix} {escape(label)} (cmd=0x{patched[2]:02x}, len={patched[6]}): {hex_str}{suffix}")

        if self.dry_run:
            self._set_toast(f"[cyan]✓ [dry-run] {escape(success_msg)}[/cyan]")
            return True

        self._hid_busy = True
        try:
            endpoint = select_control_device(self.device_path)
            with ZirconHidTransport(endpoint.path) as hid:
                for _, frame in packets:
                    patched = bytearray(frame)
                    patched[4] = hid.next_seq()
                    hid.send_feature(bytes(patched))
                    time.sleep(settle_s)
                if refresh_after:
                    self._status = hid.query_status()
        except TransportError as exc:
            self._log_hex(f"[red]✕ {escape(str(exc))}[/red]")
            self._set_toast(f"[bold red]✕ {escape(str(exc))}[/bold red]")
            return False
        finally:
            self._hid_busy = False

        if refresh_after and self._status is not None:
            self._sync_from_status()
            self._render_device_status_views()

        self._set_toast(f"[bold green]✓ {escape(success_msg)}[/bold green]")
        return True

    def _apply_dpi(self) -> None:
        try:
            count = self._get_dpi_count()
            active = self._get_active_dpi_stage(count)
            snap = bool(self.query_one("#chk-dpi-snap", Checkbox).value)
            stages = [_parse_stage_value(self.query_one(f"#in-dpi-{i}", Input).value) for i in range(count)]
            sensor_id = self._status.sensor_id if self._status else 0x3325
            pkt_dpi, resolved = build_dpi_packet(stages, current_stage=active, sensor_id=sensor_id, snap=snap)
        except (ProtocolError, ValueError) as exc:
            self._set_toast(f"[red]✕ {escape(str(exc))}[/red]")
            return

        formatted = [str(x) if x == y else f"{x}x{y}" for x, y in resolved]
        summary = ", ".join(formatted[:count])
        ok = self._dispatch_packets(
            [("DPI stages", pkt_dpi)],
            f"DPI [{summary}] (Stage {active + 1}/{count})",
            refresh_after=True,
        )
        if ok and not self.dry_run:
            # Keep unused stage slots as currently entered while persisting applied stages locally.
            all_stages = [
                formatted[i] if i < count else (self.query_one(f"#in-dpi-{i}", Input).value.strip() or formatted[i])
                for i in range(8)
            ]
            self._suppress_dpi_events = True
            try:
                for i in range(count):
                    self.query_one(f"#in-dpi-{i}", Input).value = all_stages[i]
            finally:
                self._suppress_dpi_events = False
            self._sync_dpi_grid_ui(rebuild_options=True)
            self._profile = save_profile(
                {
                    "dpi_stages": all_stages,
                    "dpi_count": count,
                    "active_dpi": active,
                    "dpi_snap": snap,
                }
            )

    def _apply_sensor(self) -> None:
        try:
            hz = int(self.query_one("#sel-rate", Select).value)
            lod = int(self.query_one("#sel-lod", Select).value)
            deb = int(self.query_one("#in-debounce", Input).value.strip(), 10)
            pkt_rate = build_polling_rate_packet(hz)
            pkt_lod = build_lod_packet(lod)
            pkt_deb = build_debounce_packet(deb)
        except (ProtocolError, ValueError) as exc:
            self._set_toast(f"[red]✕ {escape(str(exc))}[/red]")
            return

        ok = self._dispatch_packets(
            [(f"Rate {hz}Hz", pkt_rate), (f"LOD {lod}mm", pkt_lod), (f"Debounce {deb}ms", pkt_deb)],
            f"{hz} Hz · {lod} mm LOD · {deb} ms debounce",
        )
        if ok and not self.dry_run:
            self._profile = save_profile({"polling_rate": hz, "lod": lod, "debounce_ms": deb})

    def _start_hz_test(self) -> None:
        if self._hz_test_running:
            return
        if self.dry_run:
            msg = "[cyan]✓ [dry-run] Poll test skipped in simulation mode[/cyan]"
            self.query_one("#lbl-hz-result", Static).update(msg)
            self._set_toast(msg)
            return
        try:
            mouse_ep = select_mouse_input_device()
        except TransportError as exc:
            msg = f"[red]✕ {escape(str(exc))}[/red]"
            self.query_one("#lbl-hz-result", Static).update(msg)
            self._set_toast(msg)
            return

        self._hz_test_running = True
        btn = self.query_one("#btn-test-hz", Button)
        btn.disabled = True
        running_msg = self._tr("sensor_test_running", path=mouse_ep.path, sec=2.5)
        self.query_one("#lbl-hz-result", Static).update(f"[cyan]● {escape(running_msg)}[/cyan]")
        self._set_toast(f"[cyan]● {escape(running_msg)}[/cyan]")

        def _worker() -> None:
            try:
                stats = measure_polling_rate(mouse_ep.path, duration_s=2.5)
                self.call_from_thread(self._finish_hz_test, stats, None)
            except TransportError as exc:
                self.call_from_thread(self._finish_hz_test, None, str(exc))

        self.run_worker(_worker, thread=True, exclusive=True)

    def _finish_hz_test(self, stats: PollingRateStats | None, error: str | None) -> None:
        self._hz_test_running = False
        self.query_one("#btn-test-hz", Button).disabled = False
        lbl = self.query_one("#lbl-hz-result", Static)
        if error is not None or stats is None:
            msg = f"[red]✕ {escape(error or 'Unknown error')}[/red]"
            lbl.update(msg)
            self._set_toast(msg)
            return
        if stats.interval_count == 0:
            msg = f"[yellow]! {escape(self._tr('sensor_test_empty', path=stats.device_path))}[/yellow]"
            lbl.update(msg)
            self._set_toast(msg)
            return
        summary = self._tr(
            "sensor_test_result",
            path=stats.device_path,
            med_hz=stats.median_hz,
            med_ms=stats.median_dt_ms,
            avg_hz=stats.avg_hz,
            count=stats.packet_count,
        )
        msg = (
            f"[bold green]✓ {escape(summary)}[/bold green] "
            f"[dim](p95 {stats.p95_hz:.0f} Hz · min/max {stats.min_dt_ms:.2f}/{stats.max_dt_ms:.2f} ms)[/dim]"
        )
        lbl.update(msg)
        self._set_toast(f"[bold green]✓ {escape(summary)}[/bold green]")
        self._log_hex(msg)

    def _apply_button(self) -> None:
        try:
            slot = str(self.query_one("#sel-btn-slot", Select).value)
            custom = self.query_one("#in-btn-custom", Input).value.strip()
            action = custom or str(self.query_one("#sel-btn-preset", Select).value)
            pkt, logical, hw_slot, triple = build_button_packet(slot, action)
        except (ProtocolError, ValueError) as exc:
            self._set_toast(f"[red]✕ {escape(str(exc))}[/red]")
            return

        self._dispatch_packets(
            [(f"Button L{logical}->HW{hw_slot}", pkt)],
            f"{slot} -> {action} [0x{triple[0]:02x} 0x{triple[1]:02x} 0x{triple[2]:02x}]",
        )

    def _reset_all_buttons(self) -> None:
        """Restore factory bindings for all 6 mouse buttons via cmd 0x04 without wiping DPI/rate."""
        defaults = (
            ("left", "left"),
            ("right", "right"),
            ("middle", "middle"),
            ("forward", "forward"),
            ("backward", "backward"),
            ("dpi", "dpi-loop"),
        )
        packets: list[tuple[str, bytes]] = []
        for slot, action in defaults:
            pkt, logical, hw_slot, _ = build_button_packet(slot, action)
            packets.append((f"Button L{logical}->HW{hw_slot} ({action})", pkt))
        self.query_one("#in-btn-custom", Input).value = ""
        self._dispatch_packets(packets, "Default bindings restored for all 6 buttons")

    def _apply_power(self) -> None:
        try:
            sleep_min = int(self.query_one("#in-sleep", Input).value.strip(), 10)
            wake = bool(self.query_one("#switch-motion-wake", Switch).value)
            packets = [("Power Manager", build_power_packet(sleep_min, False))]
            motion_wake_ok = self._status is not None and self._status.motion_wake_supported
            if motion_wake_ok:
                packets.append(("Motion Wake-Up", build_motion_wake_packet(wake)))
        except (ProtocolError, ValueError) as exc:
            self._set_toast(f"[red]✕ {escape(str(exc))}[/red]")
            return

        ok = self._dispatch_packets(packets, f"Sleep {sleep_min} min")
        if ok and not self.dry_run:
            updates: dict[str, object] = {"sleep_minutes": sleep_min}
            if motion_wake_ok:
                updates["motion_wake"] = wake
            self._profile = save_profile(updates)

    def _apply_reset_defaults(self) -> None:
        if not bool(self.query_one("#chk-confirm-reset", Checkbox).value):
            self._set_toast(f"[yellow]! {escape(self._tr('rst_confirm'))}[/yellow]")
            return
        pkt = build_reset_defaults_packet()
        ok = self._dispatch_packets(
            [("Restore Defaults", pkt)],
            "Factory defaults restored",
            refresh_after=True,
            settle_s=0.15,
        )
        if ok and not self.dry_run:
            defs = reset_profile()
            self._profile = defs
            self._suppress_dpi_events = True
            try:
                for i in range(8):
                    self.query_one(f"#in-dpi-{i}", Input).value = str(defs["dpi_stages"][i])
                self.query_one("#chk-dpi-snap", Checkbox).value = bool(defs["dpi_snap"])
                self.query_one("#sel-rate", Select).value = int(defs["polling_rate"])
                self.query_one("#sel-lod", Select).value = int(defs["lod"])
                self.query_one("#in-debounce", Input).value = str(defs["debounce_ms"])
                self.query_one("#in-sleep", Input).value = str(defs["sleep_minutes"])
                self.query_one("#switch-motion-wake", Switch).value = bool(defs["motion_wake"])
            finally:
                self._suppress_dpi_events = False
            self._sync_dpi_grid_ui(rebuild_options=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        nav_map = {n: p for n, p, _ in NAV_PAGES}
        if bid in nav_map:
            self.action_select_tab(nav_map[bid])
        elif bid == "btn-lang":
            self.action_toggle_lang()
        elif bid == "btn-dry-run":
            self.action_toggle_dry_run()
        elif bid == "btn-hex-log":
            self.action_toggle_hex_log()
        elif bid == "btn-refresh":
            self.refresh_device_state()
        elif bid == "btn-apply-dpi":
            self._apply_dpi()
        elif bid == "btn-reset-dpi-fields":
            self._suppress_dpi_events = True
            try:
                for i in range(8):
                    self.query_one(f"#in-dpi-{i}", Input).value = str(DEFAULT_DPI_STAGES[i])
            finally:
                self._suppress_dpi_events = False
            self._sync_dpi_grid_ui(rebuild_options=True)
            self._set_toast("✓ DPI fields restored to defaults")
        elif bid in ("btn-deb-2", "btn-deb-4", "btn-deb-8", "btn-deb-12"):
            self.query_one("#in-debounce", Input).value = bid.split("-")[-1]
        elif bid == "btn-apply-sensor":
            self._apply_sensor()
        elif bid == "btn-test-hz":
            self._start_hz_test()
        elif bid == "btn-apply-button":
            self._apply_button()
        elif bid == "btn-clear-btn-custom":
            self.query_one("#in-btn-custom", Input).value = ""
        elif bid == "btn-reset-buttons":
            self._reset_all_buttons()
        elif bid == "btn-apply-power":
            self._apply_power()
        elif bid == "btn-reset-defaults":
            self._apply_reset_defaults()


def run_tui(*, device: Path | None = None, dry_run: bool = False, lang: str | None = None) -> None:
    """Launch the minimalist interactive Textual TUI application."""
    app = ZirconTuiApp(device_path=device, dry_run=dry_run, lang=lang)
    app.run()
