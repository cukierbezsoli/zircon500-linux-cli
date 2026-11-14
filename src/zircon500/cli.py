"""Typer CLI entrypoint for Genesis Zircon 500 (v1)."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Annotated, Optional

from rich.panel import Panel
import typer

from . import __version__
from .i18n import get_saved_lang, normalize_lang, save_lang, t
from .profile import load_profile, reset_profile, save_profile
from .protocol import (
    DEFAULT_DPI_STAGES,
    ProtocolError,
    build_button_packet,
    build_debounce_packet,
    build_dpi_leds_packet,
    build_dpi_packet,
    build_lod_packet,
    build_motion_wake_packet,
    build_polling_rate_packet,
    build_power_packet,
    build_reset_defaults_packet,
    build_rgb_packet,
)
from .transport import (
    TransportError,
    ZirconHidTransport,
    discover_devices,
    measure_polling_rate,
    select_control_device,
    select_mouse_input_device,
)
from .ui import (
    console,
    render_banner,
    render_button_presets,
    render_dpi_steps,
    render_error,
    render_info_dashboard,
    render_packet_preview,
    render_success,
)

app = typer.Typer(
    name="zircon500",
    help="Genesis Zircon 500 (v1) — interactive Linux TUI & CLI mouse configurator.",
    no_args_is_help=False,
    rich_markup_mode="rich",
)

UDEV_RULE_TEXT = """# Genesis Zircon 500 (v1) - Wired USB & 2.4 GHz Wireless Receiver
# Priority 69 (< 73-seat-late.rules) grants desktop session R/W ACL via uaccess.
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="248a", ATTRS{idProduct}=="5b2e", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="usb", ATTRS{idVendor}=="248a", ATTRS{idProduct}=="5b2e", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="248a", ATTRS{idProduct}=="5b2f", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="usb", ATTRS{idVendor}=="248a", ATTRS{idProduct}=="5b2f", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="331a", ATTRS{idProduct}=="5024", MODE="0660", TAG+="uaccess"
SUBSYSTEM=="usb", ATTRS{idVendor}=="331a", ATTRS{idProduct}=="5024", MODE="0660", TAG+="uaccess"
"""

DeviceOption = Annotated[
    Optional[Path],
    typer.Option("--device", "-d", help="Override target /dev/hidrawX device path."),
]
DryRunOption = Annotated[
    bool,
    typer.Option("--dry-run", help="Preview 33-byte HID frames without writing to the mouse."),
]
VerboseOption = Annotated[
    bool,
    typer.Option("--verbose", "-v", help="Print transmitted HID frames in hexadecimal."),
]
LangOption = Annotated[
    Optional[str],
    typer.Option("--lang", "-l", help="UI language: 'en' (default) or 'pl'."),
]


def _resolve_lang(lang: str | None) -> str:
    if lang is not None:
        return normalize_lang(lang)
    return get_saved_lang()


def _transmit(
    packets: list[tuple[str, bytes]],
    *,
    device: Path | None,
    dry_run: bool,
    verbose: bool,
    lang: str,
    success_msg: str,
) -> None:
    if dry_run:
        render_banner(subtitle=t("dry_run_sub", lang), lang=lang)
        render_packet_preview(t("pkt_preview_title", lang), packets)
        render_success(f"[dry-run] {success_msg}")
        return

    if verbose:
        render_packet_preview(t("pkt_tx_title", lang), packets)

    try:
        endpoint = select_control_device(device)
        with ZirconHidTransport(endpoint.path) as hid:
            for _, frame in packets:
                patched = bytearray(frame)
                patched[4] = hid.next_seq()
                hid.send_feature(bytes(patched))
                time.sleep(0.06)
    except TransportError as exc:
        render_error(str(exc), lang=lang)
        raise typer.Exit(code=1) from exc

    render_success(f"{success_msg} ({endpoint.path})")


def _parse_stage_token(token: str) -> int | tuple[int, int]:
    cleaned = token.strip().lower()
    if "x" in cleaned:
        parts = cleaned.split("x", 1)
        return int(parts[0], 10), int(parts[1], 10)
    return int(cleaned, 10)


@app.callback(invoke_without_command=True)
def root_callback(
    ctx: typer.Context,
    version: Annotated[
        bool,
        typer.Option("--version", help="Show CLI version and Genesis emblem."),
    ] = False,
    device: DeviceOption = None,
    dry_run: DryRunOption = False,
    lang: LangOption = None,
) -> None:
    """Launch the interactive TUI when invoked without a subcommand."""
    active_lang = _resolve_lang(lang)
    if lang is not None:
        save_lang(active_lang)
    if version:
        render_banner(subtitle=t("version_sub", active_lang, ver=__version__), lang=active_lang)
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        from .tui import run_tui

        run_tui(device=device, dry_run=dry_run, lang=active_lang)


@app.command()
def tui(
    device: DeviceOption = None,
    dry_run: DryRunOption = False,
    lang: LangOption = None,
) -> None:
    """Open the interactive keyboard & mouse TUI."""
    from .tui import run_tui

    active_lang = _resolve_lang(lang)
    if lang is not None:
        save_lang(active_lang)
    run_tui(device=device, dry_run=dry_run, lang=active_lang)


@app.command()
def info(device: DeviceOption = None, lang: LangOption = None) -> None:
    """Show Genesis emblem, detected HID endpoints, and live device telemetry."""
    active_lang = _resolve_lang(lang)
    devices = discover_devices()
    selected = None
    status = None
    perm_error: str | None = None

    try:
        selected = select_control_device(device)
        with ZirconHidTransport(selected.path) as hid:
            status = hid.query_status()
    except TransportError as exc:
        perm_error = str(exc)

    render_info_dashboard(devices, selected, status, perm_error, lang=active_lang)


@app.command()
def dpi(
    stages: Annotated[
        Optional[list[str]],
        typer.Argument(help="1..8 DPI values (e.g. 400 800 1600 or 800x1200 for separate axes)."),
    ] = None,
    active: Annotated[
        int,
        typer.Option("--active", "-a", min=0, max=7, help="Active stage index (0..7)."),
    ] = 0,
    mask: Annotated[
        Optional[int],
        typer.Option("--mask", min=1, max=255, help="Bitmask of enabled stages (e.g. 63 = first 6)."),
    ] = None,
    colors: Annotated[
        Optional[str],
        typer.Option("--colors", "-c", help="Comma-separated LED colors per stage (e.g. 'red,blue,#00ff00')."),
    ] = None,
    sensor_id: Annotated[
        str,
        typer.Option("--sensor", help="Hex sensor ID (default 0x3325 for Zircon 500 v1)."),
    ] = "0x3325",
    snap: Annotated[
        bool,
        typer.Option("--snap", help="Round unsupported values to nearest PMW3325 hardware step."),
    ] = False,
    list_steps: Annotated[
        bool,
        typer.Option("--list-steps", help="Print all 59 hardware DPI levels for PMW3325."),
    ] = False,
    device: DeviceOption = None,
    dry_run: DryRunOption = False,
    verbose: VerboseOption = False,
    lang: LangOption = None,
) -> None:
    """Configure DPI stages (cmd 0x05) and indicator LED colors (cmd 0x06)."""
    active_lang = _resolve_lang(lang)
    if list_steps:
        render_banner(subtitle=t("steps_sub", active_lang), lang=active_lang)
        render_dpi_steps(lang=active_lang)
        return

    try:
        sid = int(sensor_id, 16)
        parsed_stages = [_parse_stage_token(tok) for tok in (stages or [])]
        if not parsed_stages:
            parsed_stages = list(DEFAULT_DPI_STAGES[:6])

        pkt_dpi, resolved = build_dpi_packet(
            parsed_stages,
            current_stage=active,
            active_mask=mask,
            sensor_id=sid,
            snap=snap,
        )
        packets = [("DPI stages", pkt_dpi)]
        if colors:
            color_items = [item.strip() for item in colors.split(",") if item.strip()]
            pkt_leds, _ = build_dpi_leds_packet(color_items)
            packets.append(("DPI LEDs", pkt_leds))
    except (ProtocolError, ValueError) as exc:
        render_error(str(exc), lang=active_lang)
        raise typer.Exit(code=2) from exc

    active_pair = resolved[active]
    summary = ", ".join(str(x) if x == y else f"{x}x{y}" for x, y in resolved[: len(parsed_stages)])
    _transmit(
        packets,
        device=device,
        dry_run=dry_run,
        verbose=verbose,
        lang=active_lang,
        success_msg=f"Saved DPI [{summary}] (active #{active}: {active_pair[0]} DPI)",
    )
    if not dry_run:
        prev_stages = load_profile()["dpi_stages"]
        formatted = [str(x) if x == y else f"{x}x{y}" for x, y in resolved]
        count = len(parsed_stages)
        save_profile(
            {
                "dpi_stages": [formatted[i] if i < count else prev_stages[i] for i in range(8)],
                "dpi_count": count,
                "active_dpi": min(active, count - 1),
                "dpi_snap": snap,
            }
        )


@app.command()
def rate(
    hz: Annotated[int, typer.Argument(help="USB report rate in Hz: 125, 250, 500, or 1000 (fastest 1 ms).")],
    device: DeviceOption = None,
    dry_run: DryRunOption = False,
    verbose: VerboseOption = False,
    lang: LangOption = None,
) -> None:
    """Set USB polling rate (cmd 0x07)."""
    active_lang = _resolve_lang(lang)
    try:
        pkt = build_polling_rate_packet(hz)
    except ProtocolError as exc:
        render_error(str(exc), lang=active_lang)
        raise typer.Exit(code=2) from exc

    _transmit(
        [(f"Polling {hz}Hz", pkt)],
        device=device,
        dry_run=dry_run,
        verbose=verbose,
        lang=active_lang,
        success_msg=f"Polling rate set to {hz} Hz",
    )
    if not dry_run:
        save_profile({"polling_rate": hz})


@app.command()
def rgb(
    mode: Annotated[
        str,
        typer.Option("--mode", "-m", help="Effect: off, colorful-streaming, breathing, steady, neon, snake, colorful-steady, flicker, stars-twinkle, wave."),
    ] = "colorful-streaming",
    brightness: Annotated[
        int,
        typer.Option("--brightness", "-b", min=1, max=4, help="LED brightness level (1..4)."),
    ] = 4,
    speed: Annotated[
        int,
        typer.Option("--speed", "-s", min=1, max=5, help="Animation speed (1..5)."),
    ] = 3,
    direction: Annotated[
        str,
        typer.Option("--direction", help="Stream direction (for colorful-streaming): cw or ccw."),
    ] = "cw",
    color: Annotated[
        Optional[list[str]],
        typer.Option("--color", "-c", help="Color #RRGGBB or name (repeat up to 7 times for multi-color modes)."),
    ] = None,
    device: DeviceOption = None,
    dry_run: DryRunOption = False,
    verbose: VerboseOption = False,
    lang: LangOption = None,
) -> None:
    """Set RGB chassis lighting (cmd 0x08)."""
    active_lang = _resolve_lang(lang)
    try:
        pkt = build_rgb_packet(
            mode,
            brightness=brightness,
            speed=speed,
            direction=direction,
            colors=color,
        )
    except ProtocolError as exc:
        render_error(str(exc), lang=active_lang)
        raise typer.Exit(code=2) from exc

    _transmit(
        [(f"RGB {mode}", pkt)],
        device=device,
        dry_run=dry_run,
        verbose=verbose,
        lang=active_lang,
        success_msg=f"RGB set: mode={mode}, brightness={brightness}/4, speed={speed}/5",
    )


@app.command()
def lod(
    mm: Annotated[int, typer.Argument(help="Lift-Off Distance in mm (1 = low, keeps cursor steady; 2 = high).")],
    device: DeviceOption = None,
    dry_run: DryRunOption = False,
    verbose: VerboseOption = False,
    lang: LangOption = None,
) -> None:
    """Set sensor Lift-Off Distance (cmd 0x09)."""
    active_lang = _resolve_lang(lang)
    try:
        pkt = build_lod_packet(mm)
    except ProtocolError as exc:
        render_error(str(exc), lang=active_lang)
        raise typer.Exit(code=2) from exc

    _transmit(
        [(f"LOD {mm}mm", pkt)],
        device=device,
        dry_run=dry_run,
        verbose=verbose,
        lang=active_lang,
        success_msg=f"Lift-Off Distance set to {mm} mm",
    )
    if not dry_run:
        save_profile({"lod": mm})


@app.command()
def debounce(
    ms: Annotated[int, typer.Argument(help="Click noise filter in ms (2..20; lower = faster click, raise if double-clicking).")],
    device: DeviceOption = None,
    dry_run: DryRunOption = False,
    verbose: VerboseOption = False,
    lang: LangOption = None,
) -> None:
    """Set switch debounce delay (cmd 0x0a)."""
    active_lang = _resolve_lang(lang)
    try:
        pkt = build_debounce_packet(ms)
    except ProtocolError as exc:
        render_error(str(exc), lang=active_lang)
        raise typer.Exit(code=2) from exc

    _transmit(
        [(f"Debounce {ms}ms", pkt)],
        device=device,
        dry_run=dry_run,
        verbose=verbose,
        lang=active_lang,
        success_msg=f"Debounce delay set to {ms} ms",
    )
    if not dry_run:
        save_profile({"debounce_ms": ms})


@app.command()
def power(
    sleep: Annotated[
        int,
        typer.Option("--sleep", "-s", min=1, max=60, help="Wireless idle sleep timeout in minutes (1..60)."),
    ] = 5,
    off_while_moving: Annotated[
        bool,
        typer.Option("--off-while-moving/--keep-on-moving", help="Turn off LEDs while moving mouse to save battery."),
    ] = False,
    motion_wake: Annotated[
        Optional[bool],
        typer.Option("--motion-wake/--no-motion-wake", help="Wake mouse on movement instead of click (M137 firmware)."),
    ] = None,
    device: DeviceOption = None,
    dry_run: DryRunOption = False,
    verbose: VerboseOption = False,
    lang: LangOption = None,
) -> None:
    """Configure 2.4 GHz power saving (cmd 0x0b) and Motion Wake-Up (cmd 0x0c)."""
    active_lang = _resolve_lang(lang)
    try:
        packets = [("Power Manager", build_power_packet(sleep, off_while_moving))]
        if motion_wake is not None:
            packets.append(("Motion Wake-Up", build_motion_wake_packet(motion_wake)))
    except ProtocolError as exc:
        render_error(str(exc), lang=active_lang)
        raise typer.Exit(code=2) from exc

    _transmit(
        packets,
        device=device,
        dry_run=dry_run,
        verbose=verbose,
        lang=active_lang,
        success_msg=f"Power saved: sleep={sleep} min, led-off-move={off_while_moving}",
    )
    if not dry_run:
        updates: dict[str, object] = {"sleep_minutes": sleep}
        if motion_wake is not None:
            updates["motion_wake"] = motion_wake
        save_profile(updates)


@app.command()
def button(
    slot: Annotated[
        Optional[str],
        typer.Argument(help="Button: left (0), right (1), middle (2), forward (3), backward (4), dpi (5)."),
    ] = None,
    action: Annotated[
        Optional[str],
        typer.Argument(help="Preset (e.g. dpi-loop, vol-up), key:ctrl+c, fire:50:3, or raw:t:p1:p2."),
    ] = None,
    list_presets: Annotated[
        bool,
        typer.Option("--list", help="List built-in button action presets."),
    ] = False,
    device: DeviceOption = None,
    dry_run: DryRunOption = False,
    verbose: VerboseOption = False,
    lang: LangOption = None,
) -> None:
    """Remap a single mouse button (cmd 0x04 with automatic 3<->4 slot swap)."""
    active_lang = _resolve_lang(lang)
    if list_presets:
        render_banner(subtitle=t("presets_sub", active_lang), lang=active_lang)
        render_button_presets(lang=active_lang)
        return

    if not slot or not action:
        render_error("Provide both <slot> <action> arguments (or use --list).", lang=active_lang)
        raise typer.Exit(code=2)

    try:
        pkt, logical, hw_slot, triple = build_button_packet(slot, action)
    except ProtocolError as exc:
        render_error(str(exc), lang=active_lang)
        raise typer.Exit(code=2) from exc

    _transmit(
        [(f"Button L{logical}->HW{hw_slot}", pkt)],
        device=device,
        dry_run=dry_run,
        verbose=verbose,
        lang=active_lang,
        success_msg=(
            f"Button {slot} (logical {logical} -> HW {hw_slot}) = "
            f"{action} [0x{triple[0]:02x} 0x{triple[1]:02x} 0x{triple[2]:02x}]"
        ),
    )


@app.command("reset-defaults")
def reset_defaults(
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Confirm factory profile reset."),
    ] = False,
    device: DeviceOption = None,
    dry_run: DryRunOption = False,
    verbose: VerboseOption = False,
    lang: LangOption = None,
) -> None:
    """Restore factory mouse profile in RAM/EEPROM (cmd 0x0f 0xff — safe, non-DFU)."""
    active_lang = _resolve_lang(lang)
    if not yes and not dry_run:
        typer.confirm(
            "Restore factory profile settings on Genesis Zircon 500?",
            abort=True,
        )

    pkt = build_reset_defaults_packet()
    _transmit(
        [("Restore Defaults", pkt)],
        device=device,
        dry_run=dry_run,
        verbose=verbose,
        lang=active_lang,
        success_msg="Factory profile reset sent (cmd 0x0f)",
    )
    if not dry_run:
        reset_profile()


@app.command("poll-test")
def poll_test(
    seconds: Annotated[
        float,
        typer.Option("--seconds", "-s", min=0.5, max=15.0, help="Capture duration in seconds."),
    ] = 3.0,
    device: DeviceOption = None,
    lang: LangOption = None,
) -> None:
    """Measure real live USB Interrupt-IN polling rate (Hz / ms) while moving the mouse."""
    active_lang = _resolve_lang(lang)
    render_banner(subtitle=t("poll_sub", active_lang), lang=active_lang)
    try:
        target = select_mouse_input_device(device)
        console.print(f"[cyan]● {t('sensor_test_running', active_lang, path=target.path, sec=seconds)}[/cyan]")
        stats = measure_polling_rate(target.path, duration_s=seconds)
    except TransportError as exc:
        render_error(str(exc), lang=active_lang)
        raise typer.Exit(code=1) from exc

    if stats.interval_count == 0:
        console.print(f"[yellow]! {t('sensor_test_empty', active_lang, path=stats.device_path)}[/yellow]")
        raise typer.Exit(code=1)

    console.print(
        Panel(
            f"[bold]{t('sensor_test_result', active_lang, path=stats.device_path, med_hz=stats.median_hz, med_ms=stats.median_dt_ms, avg_hz=stats.avg_hz, count=stats.packet_count)}[/bold]\n"
            f"[dim]p95: {stats.p95_hz:.0f} Hz · Δt min/median/max: "
            f"{stats.min_dt_ms:.2f} / {stats.median_dt_ms:.2f} / {stats.max_dt_ms:.2f} ms[/dim]",
            border_style="green",
        )
    )


@app.command("udev-rules")
def udev_rules(lang: LangOption = None) -> None:
    """Print Linux udev rules and non-root installation command."""
    active_lang = _resolve_lang(lang)
    render_banner(subtitle=t("udev_sub", active_lang), lang=active_lang)
    rules_path = Path(__file__).resolve().parents[2] / "udev" / "69-genesis-zircon-500.rules"
    console.print(Panel(UDEV_RULE_TEXT.strip(), title="69-genesis-zircon-500.rules", border_style="bright_black"))
    console.print(
        Panel(
            "sudo rm -f /etc/udev/rules.d/99-genesis-zircon-500.rules\n"
            f"sudo cp '{rules_path}' /etc/udev/rules.d/\n"
            "sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=hidraw --action=add",
            title="Install",
            border_style="green",
        )
    )


def main() -> None:
    """Entrypoint for the ``zircon500`` console script."""
    app()


if __name__ == "__main__":
    main()
