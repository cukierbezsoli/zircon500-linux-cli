"""Unit, transport discovery, and CLI tests for Genesis Zircon 500 (v1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from zircon500.cli import app
from zircon500.transport import (
    HidrawDeviceInfo,
    compute_polling_rate_stats,
    select_event_devices,
    select_mouse_input_device,
)
from zircon500.protocol import (
    CMD_BUTTON,
    CMD_DEBOUNCE,
    CMD_DPI,
    CMD_DPI_LEDS,
    CMD_LOD,
    CMD_MOTION_WAKE,
    CMD_POLLING_RATE,
    CMD_POWER,
    CMD_RESET_DEFAULTS,
    CMD_RGB,
    CMD_STATUS,
    PMW3325_DPI_STEPS,
    REPORT_ID_FEATURE,
    REPORT_LENGTH,
    SAFE_COMMANDS,
    ProtocolError,
    build_button_packet,
    build_debounce_packet,
    build_dpi_leds_packet,
    build_dpi_packet,
    build_feature_report,
    build_lod_packet,
    build_motion_wake_packet,
    build_polling_rate_packet,
    build_power_packet,
    build_reset_defaults_packet,
    build_rgb_packet,
    build_status_query,
    encode_dpi_value,
    get_sensor_dpi_steps,
    parse_button_action,
    parse_input_event_report,
    parse_rgb_color,
    parse_status_response,
)
from zircon500.transport import discover_devices, select_control_device


def test_frame_layout_and_safe_command_allowlist() -> None:
    pkt = build_feature_report(CMD_POLLING_RATE, b"\x01", seq=0x12A)
    assert len(pkt) == REPORT_LENGTH
    assert pkt[0] == REPORT_ID_FEATURE
    assert pkt[1] == 0x01
    assert pkt[2] == CMD_POLLING_RATE
    assert pkt[3] == 0x00
    assert pkt[4] == 0x2A  # wrapped & 0xFF
    assert pkt[5] == 0x01  # write flag
    assert pkt[6] == 0x01
    assert pkt[7] == 0x01
    assert all(b == 0 for b in pkt[8:])

    # Ensure strictly no DFU / bootloader / non-allowlisted opcodes can be framed
    for forbidden_cmd in (0x01, 0x02, 0x03, 0x10, 0x55, 0xAA, 0xFF):
        assert forbidden_cmd not in SAFE_COMMANDS
        with pytest.raises(ProtocolError):
            build_feature_report(forbidden_cmd, b"\x00")


def test_status_query_and_response_parsing() -> None:
    q = build_status_query(seq=7)
    assert len(q) == REPORT_LENGTH
    assert q[2] == CMD_STATUS
    assert q[4] == 7
    assert q[5] == 0x00  # read flag
    assert q[6] == 0x00

    # Valid PMW3325 + M137 charging frame
    rx = bytearray(REPORT_LENGTH)
    rx[0] = REPORT_ID_FEATURE
    rx[1] = 0x01
    rx[2] = CMD_STATUS
    rx[3] = 0x00
    rx[6] = 0x10
    rx[8:12] = b"M137"
    rx[0x0F] = 0x25  # PMW3325
    rx[0x12] = 64
    rx[0x13] = 1  # charging
    rx[0x15] = 0x01  # motion wake supported

    st = parse_status_response(bytes(rx))
    assert st.firmware_tag == "M137"
    assert st.sensor_id == 0x3325
    assert st.sensor_name == "PMW3325"
    assert st.battery_pct == 64
    assert st.charging_state == "charging"
    assert st.motion_wake_supported is True

    # Full state forces 100% and decodes active DPI stage / count from raw[0x10]
    rx[0x10] = 0x26  # 1-based stage 2 of 6 stages
    rx[0x12] = 88
    rx[0x13] = 2
    st_full = parse_status_response(bytes(rx))
    assert st_full.charging_state == "full"
    assert st_full.battery_pct == 100
    assert st_full.dpi_stage_count == 6
    assert st_full.active_dpi_stage == 1  # 0-based stage 1

    # Hardware Input Report 0x05 notification parsing
    assert parse_input_event_report(bytes((0x05, 0x06, 0x00, 0x01, 0x03))) == (2, 1000)
    assert parse_input_event_report(bytes((0x05, 0x01, 0x00, 0x00, 0x00))) == (None, None)

    # Discharging state preserves raw percentage
    rx[0x12] = 45
    rx[0x13] = 0
    st_dis = parse_status_response(bytes(rx))
    assert st_dis.charging_state == "discharging"
    assert st_dis.battery_pct == 45


def test_pmw3325_dpi_table_and_packet() -> None:
    assert len(PMW3325_DPI_STEPS) == 59
    assert get_sensor_dpi_steps(0x3325) == PMW3325_DPI_STEPS
    assert PMW3325_DPI_STEPS[0] == 200
    assert PMW3325_DPI_STEPS[48] == 5000
    assert PMW3325_DPI_STEPS[49] == 5500
    assert PMW3325_DPI_STEPS[51] == 6400
    assert PMW3325_DPI_STEPS[-1] == 10000

    hw_6400, val_6400 = encode_dpi_value(6400, sensor_id=0x3325)
    assert hw_6400 == 52  # 0-based index 51 + 1
    assert val_6400 == 6400

    with pytest.raises(ProtocolError):
        encode_dpi_value(6500, sensor_id=0x3325, snap=False)

    hw_snapped, val_snapped = encode_dpi_value(6500, sensor_id=0x3325, snap=True)
    assert (hw_snapped, val_snapped) == (52, 6400)

    pkt, resolved = build_dpi_packet([400, (800, 1200), 6400], current_stage=1)
    assert pkt[2] == CMD_DPI
    assert pkt[6] == 0x12
    assert pkt[7] == (((1 + 1) << 4) | 3)  # wire uses 1-based stage (2), count=3
    assert pkt[8] == 0b0000_0111  # default mask for 3 stages
    assert resolved[0] == (400, 400)
    assert resolved[1] == (800, 1200)
    assert resolved[2] == (6400, 6400)
    # Last stage repeated through slots 3..7
    assert resolved[7] == (6400, 6400)
    assert pkt[9:15] == bytes((3, 3, 7, 11, 52, 52))

    # Stage 0 must still encode non-zero 1-based stage (1) on wire
    pkt0, _ = build_dpi_packet([400, 800], current_stage=0)
    assert pkt0[7] == 0x12


def test_dpi_leds_and_polling_rate_and_lod_debounce() -> None:
    pkt_leds, full = build_dpi_leds_packet(["#ff0000", "cyan", "00ff00"])
    assert pkt_leds[2] == CMD_DPI_LEDS
    assert pkt_leds[6] == 0x18
    assert full[:3] == [(255, 0, 0), (0, 255, 255), (0, 255, 0)]
    assert pkt_leds[7:13] == bytes((255, 0, 0, 0, 255, 255))

    for hz, code in ((125, 0x08), (250, 0x04), (500, 0x02), (1000, 0x01)):
        pkt_rate = build_polling_rate_packet(hz)
        assert pkt_rate[2] == CMD_POLLING_RATE
        assert pkt_rate[6] == 0x01
        assert pkt_rate[7] == code

    with pytest.raises(ProtocolError):
        build_polling_rate_packet(333)

    assert build_lod_packet(1)[6:9] == b"\x02\x01\x00"
    assert build_lod_packet(2)[6:9] == b"\x02\x02\x00"
    with pytest.raises(ProtocolError):
        build_lod_packet(3)

    assert build_debounce_packet(8)[6:8] == b"\x01\x08"
    with pytest.raises(ProtocolError):
        build_debounce_packet(1)
    with pytest.raises(ProtocolError):
        build_debounce_packet(21)


def test_rgb_modes_power_motion_wake_and_reset() -> None:
    # Mode 0 (off)
    pkt_off = build_rgb_packet("off", brightness=2, speed=5)
    assert pkt_off[2] == CMD_RGB
    assert pkt_off[6] == 0x02
    assert pkt_off[7] == 0x00
    assert pkt_off[8] == 0x25

    # Mode 1 (streaming with ccw direction)
    pkt_stream = build_rgb_packet("colorful-streaming", brightness=4, speed=3, direction="ccw")
    assert pkt_stream[6:10] == bytes((0x03, 0x01, 0x43, 0x01))

    # Mode 2 (breathing with 2 colors)
    pkt_breath = build_rgb_packet("breathing", colors=["red", "#0000ff"])
    assert pkt_breath[6:16] == bytes((9, 2, 0x43, 2, 255, 0, 0, 0, 0, 255))

    # Mode 3 (steady)
    pkt_steady = build_rgb_packet("steady", brightness=3, speed=4, colors=["#e51923"])
    assert pkt_steady[6:12] == bytes((5, 3, 0x34, 0xE5, 0x19, 0x23))

    # Mode 6 (colorful-steady: 7 RGB colors padded)
    pkt_csteady = build_rgb_packet("colorful-steady", colors=["white"])
    assert pkt_csteady[6] == 23
    assert pkt_csteady[9:12] == bytes((255, 255, 255))

    # Mode 7 (flicker: 2 RGB colors)
    pkt_flicker = build_rgb_packet("flicker", colors=["red", "green"])
    assert pkt_flicker[6:15] == bytes((8, 7, 0x43, 255, 0, 0, 0, 255, 0))

    # Power & Motion Wake
    pkt_pwr = build_power_packet(15, True)
    assert pkt_pwr[2] == CMD_POWER
    assert pkt_pwr[6:9] == bytes((2, 15, 1))

    pkt_wake = build_motion_wake_packet(True)
    assert pkt_wake[2] == CMD_MOTION_WAKE
    assert pkt_wake[6:8] == bytes((1, 1))

    pkt_rst = build_reset_defaults_packet()
    assert pkt_rst[2] == CMD_RESET_DEFAULTS
    assert pkt_rst[6:8] == bytes((1, 0xFF))

    assert parse_rgb_color("#12ab34") == (0x12, 0xAB, 0x34)


def test_button_slot_swap_and_action_parsers() -> None:
    # Logical 3 (forward) -> hardware slot 4
    pkt_fwd, log_fwd, hw_fwd, trip_fwd = build_button_packet("forward", "dpi-loop")
    assert (log_fwd, hw_fwd) == (3, 4)
    assert trip_fwd == (0x40, 0x01, 0x00)
    assert pkt_fwd[2] == CMD_BUTTON
    assert pkt_fwd[6:11] == bytes((4, 4, 0x40, 0x01, 0x00))

    # Logical 4 (backward) -> hardware slot 3
    _, log_bwd, hw_bwd, trip_bwd = build_button_packet("backward", "triple-click")
    assert (log_bwd, hw_bwd) == (4, 3)
    assert trip_bwd == (0x30, 0x32, 0x03)

    assert parse_button_action("disable") == (0x00, 0x00, 0x00)
    assert parse_button_action("key:ctrl+shift+c") == (0x70, 0x03, 0x06)
    assert parse_button_action("key:space") == (0x60, 0x00, 0x2C)
    assert parse_button_action("fire:40:5") == (0x30, 40, 5)
    assert parse_button_action("raw:0x80:0xe9:0x00") == (0x80, 0xE9, 0x00)

    with pytest.raises(ProtocolError):
        parse_button_action("key:ctrl")  # missing non-modifier key


def _create_fake_hidraw(
    tmp_path: Path,
    name: str,
    vid_hex: str,
    pid_hex: str,
    if_num: int,
    desc: bytes,
    product: str = "Gaming Mouse",
) -> tuple[Path, Path]:
    sys_root = tmp_path / "sys_hidraw"
    dev_root = tmp_path / "dev"
    dev_root.mkdir(exist_ok=True)
    dev_node = dev_root / name
    dev_node.write_text("", encoding="utf-8")

    # Build hierarchy matching .../usb1/1-1:1.<if>/0003:VID:PID.0001/hidraw/<name>
    usb_if = tmp_path / "devices" / f"1-1:1.{if_num}"
    usb_if.mkdir(parents=True, exist_ok=True)
    (usb_if / "bInterfaceNumber").write_text(f"{if_num:02x}\n", encoding="utf-8")

    hid_dev = usb_if / f"0003:{vid_hex}:{pid_hex}.0001"
    hid_dev.mkdir(parents=True, exist_ok=True)
    (hid_dev / "uevent").write_text(
        f"HID_ID=0003:{vid_hex}:{pid_hex}\nHID_NAME={product}\nHID_UNIQ=Z500\n",
        encoding="utf-8",
    )
    (hid_dev / "report_descriptor").write_bytes(desc)

    hidraw_dir = sys_root / name
    hidraw_dir.mkdir(parents=True, exist_ok=True)
    (hidraw_dir / "device").symlink_to(hid_dev)
    return sys_root, dev_root


def test_discover_and_select_control_endpoint_wired_and_dongle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Interface 0: standard mouse descriptor; Interface 1: vendor FF00 + Feature 0x0c
    _create_fake_hidraw(tmp_path, "hidraw2", "0000248A", "00005B2E", 0, b"\x05\x01\x09\x02")
    sys_root, dev_root = _create_fake_hidraw(
        tmp_path, "hidraw3", "0000248A", "00005B2E", 1, b"\x06\x00\xff\x85\x0c\xb1\x02"
    )
    # Wireless 2.4 GHz dongle on hidraw4 (IF 1)
    _create_fake_hidraw(
        tmp_path, "hidraw4", "0000248A", "00005B2F", 1, b"\x06\x00\xff\x85\x0c\xb1\x02", "Wireless Receiver"
    )

    found = discover_devices(sys_class_root=sys_root, dev_root=dev_root)
    assert len(found) == 3
    assert found[0].path.name == "hidraw3"
    assert found[0].is_control_interface is True
    assert found[0].mode_label == "USB Wired"

    assert any(d.pid == 0x5B2F and d.mode_label == "2.4 GHz Wireless Receiver" for d in found)
    assert found[-1].path.name == "hidraw2"
    assert found[-1].is_control_interface is False

    monkeypatch.setattr(
        "zircon500.transport.discover_devices",
        lambda: found,
    )
    selected = select_control_device()
    assert selected.path.name == "hidraw3"


def test_cli_smoke_dry_run_and_banner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    runner = CliRunner()

    res_ver = runner.invoke(app, ["--version"])
    assert res_ver.exit_code == 0
    assert "Z I R C O N   5 0 0" in res_ver.stdout
    assert "v1.0.0" in res_ver.stdout
    assert "Version 1.0.0" in res_ver.stdout

    res_ver_pl = runner.invoke(app, ["--version", "--lang", "pl"])
    assert res_ver_pl.exit_code == 0
    assert "Wersja 1.0.0" in res_ver_pl.stdout

    res_steps = runner.invoke(app, ["dpi", "--list-steps"])
    assert res_steps.exit_code == 0
    assert "6400" in res_steps.stdout
    assert "10000" in res_steps.stdout

    res_dpi = runner.invoke(
        app, ["dpi", "400", "800", "6400", "--active", "2", "--colors", "red,green,cyan", "--dry-run"]
    )
    assert res_dpi.exit_code == 0
    assert "[dry-run]" in res_dpi.stdout
    assert "0c 01 05 00" in res_dpi.stdout
    assert "0c 01 06 00" in res_dpi.stdout

    res_rate = runner.invoke(app, ["rate", "1000", "--dry-run"])
    assert res_rate.exit_code == 0
    assert "0c 01 07 00" in res_rate.stdout

    res_rgb = runner.invoke(
        app, ["rgb", "--mode", "steady", "--color", "#e51923", "--brightness", "4", "--dry-run"]
    )
    assert res_rgb.exit_code == 0
    assert "0c 01 08 00" in res_rgb.stdout

    res_lod = runner.invoke(app, ["lod", "1", "--dry-run"])
    assert res_lod.exit_code == 0
    assert "0c 01 09 00" in res_lod.stdout

    res_deb = runner.invoke(app, ["debounce", "8", "--dry-run"])
    assert res_deb.exit_code == 0
    assert "0c 01 0a 00" in res_deb.stdout

    res_pwr = runner.invoke(
        app, ["power", "--sleep", "10", "--off-while-moving", "--motion-wake", "--dry-run"]
    )
    assert res_pwr.exit_code == 0
    assert "0c 01 0b 00" in res_pwr.stdout
    assert "0c 01 0c 00" in res_pwr.stdout

    res_btn = runner.invoke(app, ["button", "forward", "dpi-loop", "--dry-run"])
    assert res_btn.exit_code == 0
    assert "0c 01 04 00" in res_btn.stdout

    res_udev = runner.invoke(app, ["udev-rules"])
    assert res_udev.exit_code == 0
    assert "69-genesis-zircon-500.rules" in res_udev.stdout
    assert 'GROUP="plugdev"' not in res_udev.stdout
    assert "248a" in res_udev.stdout
    assert "5b2e" in res_udev.stdout
    assert "5b2f" in res_udev.stdout


def test_interactive_tui_navigation_and_dry_run_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from textual.widgets import Button, ContentSwitcher, Input, RichLog, Select

    from zircon500.tui import ZirconTuiApp

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    async def _run() -> None:
        tui_app = ZirconTuiApp(dry_run=True)
        async with tui_app.run_test(size=(120, 40)) as pilot:
            # English default
            assert tui_app.lang == "en"
            assert "EN" in str(tui_app.query_one("#btn-lang", Button).label)
            assert "Apply DPI" in str(tui_app.query_one("#btn-apply-dpi", Button).label)

            # Toggle language to Polish cleanly via L hotkey, then back to EN
            await pilot.press("l")
            await pilot.pause()
            assert tui_app.lang == "pl"
            assert "Zastosuj DPI" in str(tui_app.query_one("#btn-apply-dpi", Button).label)

            await pilot.click("#btn-lang")
            await pilot.pause()
            assert tui_app.lang == "en"

            # Hex log drawer hidden by default, toggleable via X
            log_widget = tui_app.query_one("#tx-log", RichLog)
            assert not log_widget.has_class("-open")
            await pilot.press("x")
            await pilot.pause()
            assert log_widget.has_class("-open")

            # 1. DPI page active by default; changing enabled count clamps active stage,
            #    disables unused boxes, and switching back to 6 re-enables boxes 0..5.
            pages = tui_app.query_one("#pages", ContentSwitcher)
            assert pages.current == "tab-dpi"
            sel_count = tui_app.query_one("#sel-dpi-count", Select)
            sel_active = tui_app.query_one("#sel-dpi-active", Select)
            sel_count.value = 6
            await pilot.pause()
            sel_active.value = 4
            await pilot.pause()
            sel_count.value = 2
            await pilot.pause()
            assert tui_app.query_one("#in-dpi-1", Input).disabled is False
            assert tui_app.query_one("#in-dpi-2", Input).disabled is True
            assert tui_app.query_one("#in-dpi-5", Input).disabled is True
            assert sel_active.value == 1  # clamped from 4 into 0..1
            await pilot.click("#btn-apply-dpi")

            sel_count.value = 6
            await pilot.pause()
            assert tui_app.query_one("#in-dpi-5", Input).disabled is False
            assert tui_app.query_one("#in-dpi-6", Input).disabled is True
            await pilot.click("#btn-apply-dpi")

            # 2. Switch pages via F2..F5 and sidebar click, trigger applies
            await pilot.press("f2")
            await pilot.pause()
            assert pages.current == "tab-sensor"
            await pilot.click("#btn-apply-sensor")
            await pilot.click("#btn-test-hz")

            await pilot.click("#nav-buttons")
            await pilot.pause()
            assert pages.current == "tab-buttons"
            tui_app.query_one("#sel-btn-slot", Select).value = "dpi"
            tui_app.query_one("#sel-btn-preset", Select).value = "disable"
            await pilot.pause()
            await pilot.click("#btn-apply-button")
            await pilot.pause()
            tui_app.query_one("#sel-btn-preset", Select).value = "dpi-loop"
            await pilot.pause()
            await pilot.click("#btn-apply-button")
            await pilot.pause()
            await pilot.click("#btn-reset-buttons")
            await pilot.pause()

            await pilot.press("f4")
            await pilot.pause()
            assert pages.current == "tab-power"
            await pilot.click("#btn-apply-power")
            await pilot.click("#chk-confirm-reset", offset=(2, 0))
            await pilot.click("#btn-reset-defaults")

            await pilot.press("f5")
            await pilot.pause()
            assert pages.current == "tab-device"

            log_text = "\n".join(line.text for line in log_widget.lines)
            normalized_log = " ".join(log_text.split())
            assert "cmd=0x05" in normalized_log
            assert "cmd=0x07" in normalized_log
            assert "cmd=0x09" in normalized_log
            assert "cmd=0x0a" in normalized_log
            assert "cmd=0x04" in normalized_log
            assert "01 04 05 00 00 00" in normalized_log
            assert "01 04 05 40 01 00" in normalized_log
            assert "cmd=0x0b" in normalized_log
            assert "cmd=0x0f" in normalized_log
            assert "cmd=0x08" not in normalized_log

    asyncio.run(_run())


def test_profile_persistence_across_tui_restarts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    from textual.widgets import Checkbox, Input, Select
    from zircon500.protocol import DeviceStatus
    from zircon500.tui import ZirconTuiApp

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    _create_fake_hidraw(tmp_path, "hidraw2", "0000248A", "00005B2E", 0, b"\x05\x01\x09\x02")
    sys_root, dev_root = _create_fake_hidraw(
        tmp_path, "hidraw3", "0000248A", "00005B2E", 1, b"\x05\x01\x85\x05\x81\x02\x06\x00\xff\x85\x0c\xb1\x02"
    )
    discovered = discover_devices(sys_class_root=sys_root, dev_root=dev_root)
    ctrl = next(d for d in discovered if d.path.name == "hidraw3")
    sent_frames: list[bytes] = []

    class _FakeTransport:
        def __init__(self, _path: Path) -> None:
            self._seq = 0

        def __enter__(self) -> _FakeTransport:
            return self

        def __exit__(self, *_: object) -> None:
            pass

        def next_seq(self) -> int:
            self._seq = (self._seq + 1) & 0xFF
            return self._seq

        def send_feature(self, frame: bytes) -> None:
            sent_frames.append(frame)

        def query_status(self) -> DeviceStatus:
            return DeviceStatus(b"\x00" * 33, "M147", 0x25, 0x3325, "PMW3325", 100, "charging", False, 1, 0x16, 1, 6)

    monkeypatch.setattr("zircon500.tui.discover_devices", lambda: discovered)
    monkeypatch.setattr("zircon500.tui.select_control_device", lambda _p=None: ctrl)
    monkeypatch.setattr("zircon500.tui.ZirconHidTransport", _FakeTransport)
    monkeypatch.setattr("zircon500.tui.time.sleep", lambda _s: None)

    async def _run() -> None:
        # 1st session: change stage 2 (index 1) from 700 -> 800 and apply.
        app1 = ZirconTuiApp(dry_run=False, lang="pl")
        async with app1.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.05)
            inp1 = app1.query_one("#in-dpi-1", Input)
            assert inp1.value == "700"
            inp1.value = "800"
            app1.query_one("#sel-dpi-active", Select).value = 1
            await pilot.click("#btn-apply-dpi")
            await pilot.pause(0.05)

        # 2nd session ("restart"): stage 2 must still be 800 DPI!
        app2 = ZirconTuiApp(dry_run=False, lang="pl")
        async with app2.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.05)
            assert app2.query_one("#in-dpi-1", Input).value == "800"
            assert app2.query_one("#sel-dpi-active", Select).value == 1

            # Reset defaults restores local saved profile back to 700 too.
            await pilot.press("f4")
            await pilot.pause(0.05)
            await pilot.click("#chk-confirm-reset", offset=(2, 0))
            await pilot.click("#btn-reset-defaults")
            await pilot.pause(0.05)
            assert app2.query_one("#in-dpi-1", Input).value == "700"

    asyncio.run(_run())
    assert any(f[2] == 0x05 for f in sent_frames)
    assert any(f[2] == 0x0F for f in sent_frames)


def test_polling_rate_stats_and_mouse_endpoint_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_devs = [
        HidrawDeviceInfo(
            path=Path("/dev/hidraw3"),
            vid=0x248A,
            pid=0x5B2E,
            mode_label="USB Wired",
            product="Zircon 500",
            serial="",
            interface_number=1,
            has_vendor_usage_page=True,
            has_feature_0c=True,
            readable=True,
            writable=True,
        ),
        HidrawDeviceInfo(
            path=Path("/dev/hidraw2"),
            vid=0x248A,
            pid=0x5B2E,
            mode_label="USB Wired",
            product="Zircon 500",
            serial="",
            interface_number=0,
            has_vendor_usage_page=False,
            has_feature_0c=False,
            readable=True,
            writable=True,
        ),
    ]
    monkeypatch.setattr("zircon500.transport.discover_devices", lambda: fake_devs)
    assert select_mouse_input_device().path == Path("/dev/hidraw2")

    # 1ms (1_000_000 ns) cadence -> 1000 Hz
    ts_1000hz = [1_000_000_000 + i * 1_000_000 for i in range(101)]
    st = compute_polling_rate_stats(Path("/dev/hidraw2"), ts_1000hz, 0.1)
    assert st.packet_count == 101
    assert st.interval_count == 100
    assert st.median_dt_ms == pytest.approx(1.0)
    assert st.median_hz == pytest.approx(1000.0)
    assert st.avg_hz == pytest.approx(1000.0)

    empty = compute_polling_rate_stats(Path("/dev/hidraw2"), [], 1.0)
    assert empty.interval_count == 0
    assert empty.median_hz == 0.0

    res = CliRunner().invoke(app, ["poll-test", "--help"])
    assert res.exit_code == 0
    assert "seconds" in res.stdout


def test_tui_live_dpi_sync_multi_event_fd_and_cmd20_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import os
    from textual.containers import Vertical
    from textual.widgets import Select
    from zircon500.protocol import DeviceStatus
    from zircon500.tui import ZirconTuiApp

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    _create_fake_hidraw(tmp_path, "hidraw2", "0000248A", "00005B2E", 0, b"\x05\x01\x09\x02")
    _create_fake_hidraw(
        tmp_path, "hidraw3", "0000248A", "00005B2E", 1, b"\x05\x01\x85\x05\x81\x02\x06\x00\xff\x85\x0c\xb1\x02"
    )
    sys_root, dev_root = _create_fake_hidraw(
        tmp_path, "hidraw4", "0000248A", "00005B2E", 2, b"\x06\xef\xff\x85\x05\x81\x02\xb1\x02"
    )
    discovered = discover_devices(sys_class_root=sys_root, dev_root=dev_root)
    ctrl = next(d for d in discovered if d.path.name == "hidraw3")
    ev_devs = select_event_devices(ctrl, discovered)
    assert [d.path.name for d in ev_devs] == ["hidraw3", "hidraw4"]

    # Pipe simulates an Interrupt-IN 0x05 event coming from if02 (/dev/hidraw4).
    r_fd, w_fd = os.pipe()
    os.set_blocking(r_fd, False)
    status_seq = [
        DeviceStatus(b"\x00" * 33, "M147", 0x25, 0x3325, "PMW3325", 100, "charging", False, 1, 0x06, 0, 6),
        DeviceStatus(b"\x00" * 33, "M147", 0x25, 0x3325, "PMW3325", 100, "charging", False, 1, 0x46, 4, 6),
    ]
    orig_open = os.open

    class _FakeTransport:
        def __init__(self, _path: Path) -> None:
            pass

        def __enter__(self) -> _FakeTransport:
            return self

        def __exit__(self, *_: object) -> None:
            pass

        def query_status(self) -> DeviceStatus:
            return status_seq.pop(0) if len(status_seq) > 1 else status_seq[0]

    def _fake_open(path: object, flags: int, *args: object) -> int:
        if Path(str(path)).name == "hidraw4" and flags == (os.O_RDONLY | os.O_NONBLOCK):
            return os.dup(r_fd)
        if Path(str(path)).name == "hidraw3":
            raise OSError("skip hidraw3 in pipe test")
        return orig_open(path, flags, *args)

    monkeypatch.setattr("zircon500.tui.discover_devices", lambda: discovered)
    monkeypatch.setattr("zircon500.tui.select_control_device", lambda _p=None: ctrl)
    monkeypatch.setattr("zircon500.tui.ZirconHidTransport", _FakeTransport)
    monkeypatch.setattr("zircon500.tui.os.open", _fake_open)

    async def _run() -> None:
        tui_app = ZirconTuiApp(dry_run=False, lang="en")
        try:
            async with tui_app.run_test() as pilot:
                await pilot.pause(0.05)
                assert tui_app.query_one("#sel-dpi-active", Select).value == 0

                # User changes unsaved DPI count to 8 locally; cmd 0x20 fallback must NOT clobber it.
                tui_app.query_one("#sel-dpi-count", Select).value = 8
                await pilot.pause(0.02)
                await tui_app._sync_status_async(ctrl.path)
                await pilot.pause(0.05)
                assert tui_app.query_one("#sel-dpi-count", Select).value == 8
                assert tui_app.query_one("#sel-dpi-active", Select).value == 4
                assert tui_app.query_one("#cell-dpi-4", Vertical).has_class("-active-cell")

                # Now simulate a live Interrupt-IN 0x05 report from if02 -> stage 2 (0-based 1)
                os.write(w_fd, bytes((0x05, 0x06, 0x00, 0x01, 0x02)) + b"\x00" * 59)
                await pilot.pause(0.1)
                assert tui_app._saw_hid_event is True
                assert tui_app.query_one("#sel-dpi-active", Select).value == 1
                assert tui_app.query_one("#cell-dpi-1", Vertical).has_class("-active-cell")
        finally:
            for fd_to_close in (r_fd, w_fd):
                try:
                    os.close(fd_to_close)
                except OSError:
                    pass

    asyncio.run(_run())
