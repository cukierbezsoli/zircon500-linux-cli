"""Minimalist Rich console UI rendering with uninstall.ico emblem and EN/PL support."""

from __future__ import annotations

from rich import box
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__
from .i18n import t
from .protocol import (
    BUTTON_PRESETS,
    PMW3325_DPI_STEPS,
    DeviceStatus,
)
from .transport import HidrawDeviceInfo

console = Console()

# 22x10 compact shield emblem converted directly from extracted/app/uninstall.ico (128x128)
GENESIS_LOGO_COMPACT = r"""
   ▄▄▄██████████▄▄▄   
 ▄███▀▀▀      ▀▀▀███▄ 
███▀ ▄▄███▀████▄▄ ▀███
███  █▀ ▄▄▄▄▄▄ ██▄ ███
 ██▄ ██ ██  ██ ██ ▄██ 
  ▀██▄▀█▄▀▀▄█ █▀▄██▀  
    ▀██▄█▀▀▀▄█▄██▀    
      ▀████████▀      
        ▀████▀        
          ██          
"""

# 26x12 emblem kept for standalone views
GENESIS_LOGO = r"""
    ▄▄▄▄▄████████▄▄▄▄▄    
  ▄█████▀▀▀▀▀▀▀▀▀▀█████▄  
▄███▀   ▄▄▄▄█▄▄▄▄▄   ▀███▄
███▀  ███▀▀▀▀▀▀▀▀███▄ ▀███
███▄ ███  ▄████▄  ███ ████
 ▀██▄ ██  ██▄ ▀█ ▄██ ▄██▀ 
  ▀▀██▄▀█▄ ▀▀▄█▀▄█▀▄██▀▀  
    ▀███▄▀▀██▀ ██▀▄██▀    
       ▀███▄▄██▀▄█▀       
         ▀████▄█▀         
          ▀████▀          
            ██            
"""


def _battery_bar(pct: int, charging_state: str, lang: str) -> Text:
    filled = max(0, min(8, round(pct * 8 / 100)))
    bar = "█" * filled + "░" * (8 - filled)
    color = "green" if pct >= 50 else ("yellow" if pct >= 20 else "red")
    state_label = t(f"charge_{charging_state}", lang) if charging_state in ("charging", "full", "discharging") else charging_state
    txt = Text()
    txt.append(f"{bar} ", style=color)
    txt.append(f"{pct}% ", style="bold white")
    txt.append(f"({state_label})", style="dim")
    return txt


def render_banner(*, subtitle: str | None = None, lang: str = "en") -> None:
    """Render a compact, minimalist Genesis emblem + version header."""
    grid = Table.grid(padding=(0, 3))
    grid.add_column(no_wrap=True)
    grid.add_column(vertical="middle")

    logo = Text(GENESIS_LOGO_COMPACT.strip("\n"), style="#e51923")
    info = Text()
    info.append("Z I R C O N   5 0 0", style="bold white")
    info.append("\n")
    info.append(f"v{__version__}", style="bold #e51923")
    info.append("  ·  ", style="dim")
    info.append(subtitle or t("banner_sub", lang), style="bright_black" if subtitle is None else "cyan")

    grid.add_row(logo, info)
    console.print(Panel(grid, box=box.ROUNDED, border_style="bright_black", padding=(0, 2)))


def render_info_dashboard(
    devices: list[HidrawDeviceInfo],
    selected: HidrawDeviceInfo | None,
    status: DeviceStatus | None,
    permission_error: str | None = None,
    *,
    lang: str = "en",
) -> None:
    """Display minimalist overview: emblem + live telemetry + interfaces + commands."""
    top_grid = Table.grid(padding=(0, 3))
    top_grid.add_column(no_wrap=True)
    top_grid.add_column(vertical="middle", ratio=1)

    logo = Text(GENESIS_LOGO_COMPACT.strip("\n"), style="#e51923")

    telemetry = Table.grid(padding=(0, 2))
    telemetry.add_column(style="dim", no_wrap=True)
    telemetry.add_column()
    telemetry.add_row(
        "Genesis Zircon 500",
        Text.assemble((f"v{__version__} · ", "bold #e51923"), (t("banner_sub", lang), "dim")),
    )

    if status is not None and selected is not None:
        telemetry.add_row(t("lbl_device", lang), f"{selected.path} ({selected.mode_label})")
        telemetry.add_row(t("lbl_sensor", lang), status.sensor_name)
        telemetry.add_row(t("lbl_fw", lang), status.firmware_tag or "N/A")
        telemetry.add_row(t("lbl_battery", lang), _battery_bar(status.battery_pct, status.charging_state, lang))
        if status.dpi_stage_count is not None and status.active_dpi_stage is not None:
            telemetry.add_row(
                t("lbl_dpi_stage", lang),
                f"{status.active_dpi_stage + 1} / {status.dpi_stage_count}",
            )
        telemetry.add_row(
            t("lbl_wake", lang),
            t("yes", lang) if status.motion_wake_supported else Text(t("no", lang), style="dim"),
        )
    else:
        if selected is not None:
            telemetry.add_row(t("lbl_device", lang), f"{selected.path} ({selected.mode_label})")
        if permission_error:
            telemetry.add_row(t("status_title", lang), Text(permission_error, style="red"))
            telemetry.add_row("", Text(t("status_fix", lang), style="dim"))
        else:
            telemetry.add_row(t("status_title", lang), Text(t("status_failed", lang), style="yellow"))

    top_grid.add_row(logo, telemetry)
    console.print(Panel(top_grid, box=box.ROUNDED, border_style="bright_black", padding=(0, 2)))

    dev_table = Table(
        title=t("iface_table_title", lang),
        title_justify="left",
        title_style="bold white",
        box=box.SIMPLE_HEAD,
        header_style="dim bold",
        expand=True,
    )
    dev_table.add_column(t("col_path", lang), style="cyan", no_wrap=True)
    dev_table.add_column(t("col_vidpid", lang), style="dim", no_wrap=True)
    dev_table.add_column(t("col_mode", lang))
    dev_table.add_column(t("col_if", lang), justify="center")
    dev_table.add_column(t("col_role", lang))
    dev_table.add_column(t("col_perms", lang), justify="right")

    if not devices:
        dev_table.add_row("—", "—", t("no_devices", lang), "—", "—", "—")
    else:
        for d in devices:
            role = t("role_ctrl", lang) if d.is_control_interface else t("role_hid", lang)
            if selected and d.path == selected.path:
                role = f"[bold green]●[/bold green] {role}"
            perms = (
                f"[green]{t('perm_ok', lang)}[/green]"
                if (d.readable and d.writable)
                else f"[red]{t('perm_none', lang)}[/red]"
            )
            dev_table.add_row(
                str(d.path),
                f"{d.vid:04x}:{d.pid:04x}",
                d.mode_label,
                f"if{d.interface_number:02d}" if d.interface_number is not None else "—",
                role,
                perms,
            )
    console.print(dev_table)

    help_table = Table(
        title=t("quick_title", lang),
        title_justify="left",
        title_style="bold white",
        box=box.SIMPLE_HEAD,
        show_header=False,
        expand=True,
    )
    help_table.add_column(style="bold cyan", no_wrap=True)
    help_table.add_column(style="dim")
    help_table.add_row("zircon500", t("q_tui", lang))
    help_table.add_row("zircon500 dpi 400 800 1600 --active 1", t("q_dpi", lang))
    help_table.add_row("zircon500 rate 1000", t("q_rate", lang))
    help_table.add_row("zircon500 lod 2", t("q_lod", lang))
    help_table.add_row("zircon500 debounce 2", t("q_deb", lang))
    help_table.add_row("zircon500 button forward dpi-loop", t("q_btn", lang))
    console.print(help_table)


def render_packet_preview(title: str, packets: list[tuple[str, bytes]]) -> None:
    """Print clean formatted 33-byte HID Feature frames."""
    table = Table(
        title=title,
        title_justify="left",
        title_style="bold yellow",
        box=box.SIMPLE_HEAD,
        header_style="dim bold",
        expand=True,
    )
    table.add_column("Step", style="cyan", no_wrap=True)
    table.add_column("Cmd", style="magenta", justify="center", no_wrap=True)
    table.add_column("Len", justify="right", no_wrap=True)
    table.add_column("HID Feature 0x0c (33 B)")

    for label, pkt in packets:
        trimmed = pkt[: max(7 + pkt[6], 8)]
        hex_main = " ".join(f"{b:02x}" for b in trimmed)
        rest = len(pkt) - len(trimmed)
        suffix = f" [dim]+ {rest}×00[/dim]" if rest else ""
        table.add_row(label, f"0x{pkt[2]:02x}", str(pkt[6]), f"{hex_main}{suffix}")
    console.print(table)


def render_dpi_steps(*, lang: str = "en") -> None:
    """Display the 59 hardware DPI steps verified for PMW3325 (0x3325)."""
    table = Table(
        title=t("steps_sub", lang),
        title_justify="left",
        box=box.SIMPLE_HEAD,
        header_style="dim bold",
    )
    for _ in range(4):
        table.add_column("Code", justify="right", style="cyan")
        table.add_column("DPI", justify="right", style="bold white")

    rows = (len(PMW3325_DPI_STEPS) + 3) // 4
    for r in range(rows):
        cells: list[str] = []
        for c in range(4):
            idx = r + c * rows
            if idx < len(PMW3325_DPI_STEPS):
                cells.extend((f"0x{idx + 1:02x}", str(PMW3325_DPI_STEPS[idx])))
            else:
                cells.extend(("", ""))
        table.add_row(*cells)
    console.print(table)


def render_button_presets(*, lang: str = "en") -> None:
    """Display built-in button preset names."""
    table = Table(
        title=t("presets_sub", lang),
        title_justify="left",
        box=box.SIMPLE_HEAD,
        header_style="dim bold",
    )
    table.add_column("Name", style="cyan")
    table.add_column("Bytes (type, p1, p2)", style="dim")
    for name, (tp, p1, p2) in BUTTON_PRESETS.items():
        table.add_row(name, f"0x{tp:02x}, 0x{p1:02x}, 0x{p2:02x}")
    console.print(table)


def render_success(message: str) -> None:
    console.print(f"[bold green]✓[/bold green] {escape(message)}")


def render_error(message: str, *, lang: str = "en") -> None:
    console.print(f"[bold red]✕ {t('err_prefix', lang)}[/bold red] {escape(message)}")
