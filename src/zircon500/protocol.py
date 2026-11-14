"""Genesis Zircon 500 (v1) HID protocol codecs, constants, and validation.

This module intentionally implements only safe device configuration and status
commands. Firmware-update / DFU / bootloader opcodes are strictly excluded.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

REPORT_ID_INPUT = 0x05
REPORT_ID_FEATURE = 0x0C
REPORT_LENGTH = 33  # 1-byte report ID + 32-byte payload

SUPPORTED_DEVICES: dict[tuple[int, int], str] = {
    (0x248A, 0x5B2E): "USB Wired",
    (0x248A, 0x5B2F): "2.4 GHz Wireless Receiver",
    (0x331A, 0x5024): "USB Wired (Legacy ID)",
}

# Safe configuration/telemetry opcodes verified in Zircon_500_setup.exe.
CMD_BUTTON = 0x04
CMD_DPI = 0x05
CMD_DPI_LEDS = 0x06
CMD_POLLING_RATE = 0x07
CMD_RGB = 0x08
CMD_LOD = 0x09
CMD_DEBOUNCE = 0x0A
CMD_POWER = 0x0B
CMD_MOTION_WAKE = 0x0C
CMD_MACRO = 0x0E
CMD_RESET_DEFAULTS = 0x0F
CMD_STATUS = 0x20

SAFE_COMMANDS: frozenset[int] = frozenset(
    {
        CMD_BUTTON,
        CMD_DPI,
        CMD_DPI_LEDS,
        CMD_POLLING_RATE,
        CMD_RGB,
        CMD_LOD,
        CMD_DEBOUNCE,
        CMD_POWER,
        CMD_MOTION_WAKE,
        CMD_MACRO,
        CMD_RESET_DEFAULTS,
        CMD_STATUS,
    }
)

SENSOR_SHORT_TO_MODEL: dict[int, int] = {
    0x04: 0x3104,
    0x12: 0x3212,
    0x25: 0x3325,
    0x27: 0x3327,
    0x35: 0x3335,
    0x60: 0x3360,
    0x70: 0x3370,
    0x89: 0x3389,
    0x95: 0x3395,
    0x99: 0x3399,
}

SENSOR_NAMES: dict[int, str] = {
    0x3104: "PAW3104",
    0x3212: "PAW3212",
    0x3325: "PMW3325",
    0x3327: "PMW3327",
    0x3335: "PAW3335",
    0x3360: "PMW3360",
    0x3370: "PAW3370",
    0x3389: "PMW3389",
    0x3395: "PAW3395",
    0x3399: "PMW3399",
}

# Exact 59-step table extracted from FUN_00408760 (0x40887b) for PMW3325 (hw_code = idx + 1).
PMW3325_DPI_STEPS: tuple[int, ...] = (
    *range(200, 5100, 100),
    5500,
    6000,
    6400,
    7000,
    7500,
    8000,
    8500,
    9000,
    9500,
    10000,
)

DEFAULT_DPI_STAGES: tuple[int, ...] = (400, 700, 1100, 1500, 2400, 2500, 2500, 2500)

DEFAULT_DPI_COLORS: tuple[tuple[int, int, int], ...] = (
    (255, 0, 0),
    (0, 255, 0),
    (0, 0, 255),
    (255, 0, 255),
    (0, 255, 255),
    (255, 255, 0),
    (255, 255, 255),
    (255, 255, 255),
)

POLLING_RATE_TO_CODE: dict[int, int] = {
    125: 0x08,
    250: 0x04,
    500: 0x02,
    1000: 0x01,
}

RGB_MODES: dict[int, str] = {
    0: "off",
    1: "colorful-streaming",
    2: "breathing",
    3: "steady",
    4: "neon",
    5: "snake",
    6: "colorful-steady",
    7: "flicker",
    8: "stars-twinkle",
    9: "wave",
}

RGB_MODE_ALIASES: dict[str, int] = {
    "0": 0,
    "off": 0,
    "none": 0,
    "1": 1,
    "colorful-streaming": 1,
    "streaming": 1,
    "2": 2,
    "breathing": 2,
    "3": 3,
    "steady": 3,
    "static": 3,
    "4": 4,
    "neon": 4,
    "5": 5,
    "snake": 5,
    "6": 6,
    "colorful-steady": 6,
    "7": 7,
    "flicker": 7,
    "8": 8,
    "stars-twinkle": 8,
    "twinkle": 8,
    "9": 9,
    "wave": 9,
}

NAMED_COLORS: dict[str, tuple[int, int, int]] = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "magenta": (255, 0, 255),
    "purple": (160, 0, 255),
    "cyan": (0, 255, 255),
    "yellow": (255, 255, 0),
    "orange": (255, 110, 0),
    "white": (255, 255, 255),
    "off": (0, 0, 0),
    "black": (0, 0, 0),
}

# Logical button order (default0.psf / UI) -> hardware slot order in cmd 0x04.
# Slots 3 (Forward) and 4 (Backward) are swapped in cmd 0x04 wire packing (0x430436).
LOGICAL_BUTTON_SLOTS: dict[str, int] = {
    "0": 0,
    "left": 0,
    "1": 1,
    "right": 1,
    "2": 2,
    "middle": 2,
    "scroll": 2,
    "3": 3,
    "forward": 3,
    "4": 4,
    "backward": 4,
    "back": 4,
    "5": 5,
    "dpi": 5,
}

LOGICAL_TO_HW_SLOT: dict[int, int] = {
    0: 0,
    1: 1,
    2: 2,
    3: 4,
    4: 3,
    5: 5,
}

BUTTON_PRESETS: dict[str, tuple[int, int, int]] = {
    "disable": (0x00, 0x00, 0x00),
    "off": (0x00, 0x00, 0x00),
    "left": (0x10, 0x01, 0x00),
    "right": (0x10, 0x02, 0x00),
    "middle": (0x10, 0x04, 0x00),
    "backward": (0x10, 0x08, 0x00),
    "back": (0x10, 0x08, 0x00),
    "forward": (0x10, 0x10, 0x00),
    "triple-click": (0x30, 0x32, 0x03),
    "three-click": (0x30, 0x32, 0x03),
    "dpi-loop": (0x40, 0x01, 0x00),
    "dpi-up": (0x40, 0x02, 0x00),
    "dpi+": (0x40, 0x02, 0x00),
    "dpi-down": (0x40, 0x03, 0x00),
    "dpi-": (0x40, 0x03, 0x00),
    "media": (0x80, 0x83, 0x01),
    "prev": (0x80, 0xB6, 0x00),
    "next": (0x80, 0xB5, 0x00),
    "stop": (0x80, 0xB7, 0x00),
    "play-pause": (0x80, 0xCD, 0x00),
    "mute": (0x80, 0xE2, 0x00),
    "vol-up": (0x80, 0xE9, 0x00),
    "vol+": (0x80, 0xE9, 0x00),
    "vol-down": (0x80, 0xEA, 0x00),
    "vol-": (0x80, 0xEA, 0x00),
    "mail": (0x80, 0x8A, 0x01),
    "calc": (0x80, 0x92, 0x01),
}

HID_KEY_USAGES: dict[str, int] = {
    **{chr(ord("a") + i): 0x04 + i for i in range(26)},
    "1": 0x1E,
    "2": 0x1F,
    "3": 0x20,
    "4": 0x21,
    "5": 0x22,
    "6": 0x23,
    "7": 0x24,
    "8": 0x25,
    "9": 0x26,
    "0": 0x27,
    "enter": 0x28,
    "return": 0x28,
    "esc": 0x29,
    "escape": 0x29,
    "backspace": 0x2A,
    "tab": 0x2B,
    "space": 0x2C,
    "-": 0x2D,
    "minus": 0x2D,
    "=": 0x2E,
    "equal": 0x2E,
    "[": 0x2F,
    "]": 0x30,
    "\\": 0x31,
    ";": 0x33,
    "'": 0x34,
    "`": 0x35,
    ",": 0x36,
    ".": 0x37,
    "/": 0x38,
    "capslock": 0x39,
    **{f"f{i}": 0x3A + (i - 1) for i in range(1, 13)},
    "printscreen": 0x46,
    "scrolllock": 0x47,
    "pause": 0x48,
    "insert": 0x49,
    "home": 0x4A,
    "pageup": 0x4B,
    "delete": 0x4C,
    "del": 0x4C,
    "end": 0x4D,
    "pagedown": 0x4E,
    "right": 0x4F,
    "left": 0x50,
    "down": 0x51,
    "up": 0x52,
}

HID_MODIFIER_BITS: dict[str, int] = {
    "ctrl": 0x01,
    "lctrl": 0x01,
    "shift": 0x02,
    "lshift": 0x02,
    "alt": 0x04,
    "lalt": 0x04,
    "win": 0x08,
    "super": 0x08,
    "meta": 0x08,
    "rctrl": 0x10,
    "rshift": 0x20,
    "ralt": 0x40,
    "rwin": 0x80,
}


class ProtocolError(ValueError):
    """Raised when command inputs violate hardware protocol constraints."""


@dataclass(frozen=True, slots=True)
class DeviceStatus:
    """Decoded status returned by ``cmd 0x20``."""

    raw: bytes
    firmware_tag: str
    sensor_short: int
    sensor_id: int
    sensor_name: str
    battery_pct: int
    charging_state: str
    motion_wake_supported: bool
    power_flag_raw: int
    dpi_status_raw: int = 0
    active_dpi_stage: int | None = None
    dpi_stage_count: int | None = None


def parse_rgb_color(spec: str) -> tuple[int, int, int]:
    """Parse ``#RRGGBB``, ``RRGGBB``, ``R,G,B``, or a named color."""
    cleaned = spec.strip().lower()
    if cleaned in NAMED_COLORS:
        return NAMED_COLORS[cleaned]

    if "," in cleaned:
        parts = [p.strip() for p in cleaned.split(",")]
        if len(parts) != 3:
            raise ProtocolError(f"Invalid RGB triplet '{spec}'; expected R,G,B.")
        try:
            rgb = tuple(int(p, 10) for p in parts)
        except ValueError as exc:
            raise ProtocolError(f"Invalid RGB integers in '{spec}'.") from exc
        if any(not (0 <= c <= 255) for c in rgb):
            raise ProtocolError(f"RGB channels must be in 0..255: '{spec}'.")
        return rgb  # type: ignore[return-value]

    hex_part = cleaned.removeprefix("#").removeprefix("0x")
    if re.fullmatch(r"[0-9a-f]{6}", hex_part):
        return (
            int(hex_part[0:2], 16),
            int(hex_part[2:4], 16),
            int(hex_part[4:6], 16),
        )
    raise ProtocolError(
        f"Invalid color '{spec}'. Use #RRGGBB, R,G,B, or one of: {', '.join(NAMED_COLORS)}."
    )


def get_sensor_dpi_steps(sensor_id: int = 0x3325) -> tuple[int, ...]:
    """Return ordered valid DPI steps for a known sensor ID."""
    if sensor_id == 0x3325:
        return PMW3325_DPI_STEPS
    if sensor_id == 0x3212:
        return tuple(range(200, 4900, 100))[:42]
    if sensor_id in (0x3335, 0x3389):
        return tuple(range(100, 16100, 100))
    if sensor_id == 0x3395:
        return tuple(range(50, 26050, 50))
    if sensor_id == 0x3399:
        return tuple(range(50, 20050, 50))
    return PMW3325_DPI_STEPS


def encode_dpi_value(
    dpi: int,
    *,
    sensor_id: int = 0x3325,
    snap: bool = False,
) -> tuple[int, int]:
    """Encode a DPI integer to ``(hw_code, resolved_dpi)``."""
    steps = get_sensor_dpi_steps(sensor_id)
    base_code = 1 if sensor_id in (0x3212, 0x3325, 0x3327) else 0

    if dpi in steps:
        idx = steps.index(dpi)
        return base_code + idx, dpi

    if not snap:
        raise ProtocolError(
            f"Unsupported DPI {dpi} for {SENSOR_NAMES.get(sensor_id, f'0x{sensor_id:04x}')}. "
            f"Pass --snap to round to nearest valid step (valid range {steps[0]}..{steps[-1]})."
        )

    idx = min(range(len(steps)), key=lambda i: (abs(steps[i] - dpi), steps[i]))
    return base_code + idx, steps[idx]


def build_feature_report(
    cmd: int,
    payload: bytes,
    *,
    seq: int = 0,
    rw: int = 0x01,
    transport: int = 0x01,
) -> bytes:
    """Build a zero-padded 33-byte Feature Report ``0x0c`` frame."""
    if cmd not in SAFE_COMMANDS:
        raise ProtocolError(f"Refusing unapproved or unsafe command 0x{cmd:02x}.")
    if not (0 <= rw <= 0xFF and 0 <= transport <= 0xFF):
        raise ProtocolError("Header flags must fit in one byte.")
    if len(payload) > REPORT_LENGTH - 7:
        raise ProtocolError(
            f"Payload too long ({len(payload)} bytes; max {REPORT_LENGTH - 7})."
        )

    frame = bytearray(REPORT_LENGTH)
    frame[0] = REPORT_ID_FEATURE
    frame[1] = transport & 0xFF
    frame[2] = cmd & 0xFF
    frame[3] = 0x00
    frame[4] = seq & 0xFF
    frame[5] = rw & 0xFF
    frame[6] = len(payload) & 0xFF
    frame[7 : 7 + len(payload)] = payload
    return bytes(frame)


def build_status_query(*, seq: int = 0) -> bytes:
    """Build ``cmd 0x20`` live device telemetry query."""
    return build_feature_report(CMD_STATUS, b"", seq=seq, rw=0x00)


def parse_status_response(raw: bytes) -> DeviceStatus:
    """Parse a 33-byte ``HIDIOCGFEATURE(0x0c)`` response to ``cmd 0x20``."""
    if len(raw) < 22:
        raise ProtocolError(f"Short status response: {len(raw)} bytes (expected >= 22).")
    if raw[2] != CMD_STATUS or raw[3] != 0x00:
        raise ProtocolError(
            f"Unexpected status header bytes [2:4] = {raw[2]:02x} {raw[3]:02x}."
        )

    raw_tag = bytes(b for b in raw[8:12] if 0x20 <= b <= 0x7E)
    firmware_tag = raw_tag.decode("ascii", errors="replace") or "unknown"

    sensor_short = raw[0x0F]
    sensor_id = SENSOR_SHORT_TO_MODEL.get(sensor_short, sensor_short)
    sensor_name = SENSOR_NAMES.get(sensor_id, f"0x{sensor_id:04x}")

    charge_byte = raw[0x13]
    battery_pct = raw[0x12]
    if charge_byte == 1:
        charging_state = "charging"
    elif charge_byte == 2:
        charging_state = "full"
        battery_pct = 100
    else:
        charging_state = "discharging"

    wake_supported = raw[8:12] == b"M137" and raw[0x15] != 0
    dpi_raw = raw[0x10] if len(raw) > 0x10 else 0
    stage_1based = (dpi_raw >> 4) & 0x0F
    stage_count = dpi_raw & 0x0F
    dpi_stage_count = stage_count if 1 <= stage_count <= 8 else None
    active_dpi_stage = (
        stage_1based - 1
        if (dpi_stage_count is not None and 1 <= stage_1based <= dpi_stage_count)
        else None
    )
    return DeviceStatus(
        raw=bytes(raw),
        firmware_tag=firmware_tag,
        sensor_short=sensor_short,
        sensor_id=sensor_id,
        sensor_name=sensor_name,
        battery_pct=max(0, min(100, battery_pct)),
        charging_state=charging_state,
        motion_wake_supported=wake_supported,
        power_flag_raw=charge_byte,
        dpi_status_raw=dpi_raw,
        active_dpi_stage=active_dpi_stage,
        dpi_stage_count=dpi_stage_count,
    )


def build_dpi_packet(
    stages: Iterable[int | tuple[int, int]],
    *,
    current_stage: int = 0,
    active_mask: int | None = None,
    sensor_id: int = 0x3325,
    snap: bool = False,
    seq: int = 0,
) -> tuple[bytes, list[tuple[int, int]]]:
    """Build ``cmd 0x05`` (18-byte DPI stage configuration) packet.

    Returns ``(packet, resolved_xy_pairs)`` for the 8 hardware slots.
    """
    stage_list = list(stages)
    if not (1 <= len(stage_list) <= 8):
        raise ProtocolError("DPI stage count must be between 1 and 8.")

    count = len(stage_list)
    if not (0 <= current_stage < count):
        raise ProtocolError(
            f"Active DPI stage {current_stage} out of range for {count} stages."
        )

    if active_mask is None:
        active_mask = (1 << count) - 1
    elif not (1 <= active_mask <= 0xFF):
        raise ProtocolError("active_mask must be in 1..255.")

    padded = list(stage_list)
    pad_value = stage_list[-1]
    while len(padded) < 8:
        padded.append(pad_value)

    resolved: list[tuple[int, int]] = []
    payload = bytearray(18)
    # FUN_00430770 sends 1-based stage index ((stage_0based + 1) << 4) | count.
    payload[0] = (((current_stage + 1) & 0x0F) << 4) | (count & 0x0F)
    payload[1] = active_mask & 0xFF

    for idx, item in enumerate(padded):
        x_req, y_req = item if isinstance(item, tuple) else (item, item)
        hx, rx = encode_dpi_value(x_req, sensor_id=sensor_id, snap=snap)
        hy, ry = encode_dpi_value(y_req, sensor_id=sensor_id, snap=snap)
        payload[2 + 2 * idx] = hx & 0xFF
        payload[3 + 2 * idx] = hy & 0xFF
        resolved.append((rx, ry))

    return build_feature_report(CMD_DPI, bytes(payload), seq=seq), resolved


def build_dpi_leds_packet(
    colors: Iterable[str | tuple[int, int, int]],
    *,
    seq: int = 0,
) -> tuple[bytes, list[tuple[int, int, int]]]:
    """Build ``cmd 0x06`` (24-byte DPI indicator RGB palette) packet."""
    parsed: list[tuple[int, int, int]] = []
    for c in colors:
        parsed.append(parse_rgb_color(c) if isinstance(c, str) else c)

    if not (1 <= len(parsed) <= 8):
        raise ProtocolError("Provide between 1 and 8 DPI indicator colors.")

    for rgb in parsed:
        if any(not (0 <= ch <= 255) for ch in rgb):
            raise ProtocolError(f"Invalid RGB channel value in {rgb}.")

    full = list(parsed)
    for i in range(len(full), 8):
        full.append(DEFAULT_DPI_COLORS[i])

    payload = bytearray(24)
    for idx, (r, g, b) in enumerate(full):
        payload[3 * idx : 3 * idx + 3] = bytes((r, g, b))

    return build_feature_report(CMD_DPI_LEDS, bytes(payload), seq=seq), full


def build_polling_rate_packet(hz: int, *, seq: int = 0) -> bytes:
    """Build ``cmd 0x07`` polling rate packet (125 / 250 / 500 / 1000 Hz)."""
    if hz not in POLLING_RATE_TO_CODE:
        valid = ", ".join(str(v) for v in sorted(POLLING_RATE_TO_CODE))
        raise ProtocolError(f"Unsupported polling rate {hz} Hz. Valid: {valid}.")
    return build_feature_report(
        CMD_POLLING_RATE, bytes([POLLING_RATE_TO_CODE[hz]]), seq=seq
    )


def parse_rgb_mode(mode: int | str) -> int:
    """Resolve an RGB mode index or alias name to hardware ID ``0..9``."""
    if isinstance(mode, int):
        if mode not in RGB_MODES:
            raise ProtocolError(f"Unsupported RGB mode {mode} (valid: 0..9).")
        return mode
    key = mode.strip().lower().replace("_", "-").replace(" ", "-")
    if key not in RGB_MODE_ALIASES:
        valid = ", ".join(RGB_MODES.values())
        raise ProtocolError(f"Unknown RGB mode '{mode}'. Valid: {valid}.")
    return RGB_MODE_ALIASES[key]


def build_rgb_packet(
    mode: int | str,
    *,
    brightness: int = 4,
    speed: int = 3,
    direction: int | str = 0,
    colors: Iterable[str | tuple[int, int, int]] | None = None,
    seq: int = 0,
) -> bytes:
    """Build ``cmd 0x08`` RGB lighting configuration packet."""
    mode_id = parse_rgb_mode(mode)
    if not (1 <= brightness <= 4):
        raise ProtocolError("RGB brightness must be in 1..4.")
    if not (1 <= speed <= 5):
        raise ProtocolError("RGB speed must be in 1..5.")

    if isinstance(direction, str):
        dir_key = direction.strip().lower()
        if dir_key in ("0", "cw", "right", "forward"):
            dir_val = 0
        elif dir_key in ("1", "ccw", "left", "reverse"):
            dir_val = 1
        else:
            raise ProtocolError("Direction must be 'cw' (0) or 'ccw' (1).")
    else:
        if direction not in (0, 1):
            raise ProtocolError("Direction must be 0 or 1.")
        dir_val = direction

    parsed_colors: list[tuple[int, int, int]] = []
    if colors is not None:
        for c in colors:
            rgb = parse_rgb_color(c) if isinstance(c, str) else c
            if any(not (0 <= ch <= 255) for ch in rgb):
                raise ProtocolError(f"RGB values must be 0..255: {rgb}.")
            parsed_colors.append(rgb)

    nibbles = ((brightness & 0x0F) << 4) | (speed & 0x0F)
    payload = bytearray([mode_id, nibbles])

    if mode_id == 1:
        payload.append(dir_val)
    elif mode_id == 2:
        palette = parsed_colors or [DEFAULT_DPI_COLORS[0]]
        if len(palette) > 7:
            raise ProtocolError("Breathing mode supports at most 7 colors.")
        payload.append(len(palette))
        for r, g, b in palette:
            payload.extend((r, g, b))
    elif mode_id == 3:
        r, g, b = parsed_colors[0] if parsed_colors else (255, 0, 0)
        payload.extend((r, g, b))
    elif mode_id == 6:
        palette = list(parsed_colors) if parsed_colors else list(DEFAULT_DPI_COLORS[:7])
        if len(palette) > 7:
            raise ProtocolError("Colorful-steady mode supports at most 7 colors.")
        for i in range(len(palette), 7):
            palette.append(DEFAULT_DPI_COLORS[i])
        for r, g, b in palette[:7]:
            payload.extend((r, g, b))
    elif mode_id == 7:
        c0 = parsed_colors[0] if len(parsed_colors) >= 1 else (255, 0, 0)
        c1 = parsed_colors[1] if len(parsed_colors) >= 2 else (0, 0, 255)
        payload.extend((*c0, *c1))

    return build_feature_report(CMD_RGB, bytes(payload), seq=seq)


def build_lod_packet(lod_mm: int, *, seq: int = 0) -> bytes:
    """Build ``cmd 0x09`` Lift-Off Distance packet (``1`` mm or ``2`` mm)."""
    if lod_mm not in (1, 2):
        raise ProtocolError("Lift-Off Distance must be 1 or 2 mm.")
    return build_feature_report(CMD_LOD, bytes((lod_mm, 0x00)), seq=seq)


def build_debounce_packet(ms: int, *, seq: int = 0) -> bytes:
    """Build ``cmd 0x0a`` key debounce time packet (``2..20`` ms in OEM UI)."""
    if not (2 <= ms <= 20):
        raise ProtocolError("Debounce time must be between 2 and 20 ms.")
    return build_feature_report(CMD_DEBOUNCE, bytes((ms,)), seq=seq)


def build_power_packet(
    sleep_minutes: int,
    lighting_off_while_move: bool = False,
    *,
    seq: int = 0,
) -> bytes:
    """Build ``cmd 0x0b`` wireless power-down & move-dimming packet."""
    if not (1 <= sleep_minutes <= 60):
        raise ProtocolError("Power-down idle timer must be between 1 and 60 minutes.")
    return build_feature_report(
        CMD_POWER,
        bytes((sleep_minutes, 1 if lighting_off_while_move else 0)),
        seq=seq,
    )


def build_motion_wake_packet(enabled: bool, *, seq: int = 0) -> bytes:
    """Build ``cmd 0x0c`` motion wake-up enable/disable packet."""
    return build_feature_report(
        CMD_MOTION_WAKE, bytes((1 if enabled else 0,)), seq=seq
    )


def resolve_button_slot(slot: int | str) -> tuple[int, int]:
    """Return ``(logical_slot, hw_slot)`` for slot ``0..5`` or name."""
    if isinstance(slot, int):
        if slot not in LOGICAL_TO_HW_SLOT:
            raise ProtocolError("Button slot must be in 0..5.")
        return slot, LOGICAL_TO_HW_SLOT[slot]

    key = slot.strip().lower()
    if key not in LOGICAL_BUTTON_SLOTS:
        raise ProtocolError(
            "Unknown button slot. Valid: left, right, middle, forward, backward, dpi (or 0..5)."
        )
    logical = LOGICAL_BUTTON_SLOTS[key]
    return logical, LOGICAL_TO_HW_SLOT[logical]


def parse_button_action(action: str | tuple[int, int, int]) -> tuple[int, int, int]:
    """Parse preset name, ``key:...``, ``fire:delay:count``, or ``raw:t:p1:p2``."""
    if isinstance(action, tuple):
        if len(action) != 3 or any(not (0 <= x <= 255) for x in action):
            raise ProtocolError("Button tuple must contain 3 byte integers (0..255).")
        return action

    text = action.strip().lower()
    if text in BUTTON_PRESETS:
        return BUTTON_PRESETS[text]

    if text.startswith("fire:"):
        parts = text.split(":")
        if len(parts) != 3:
            raise ProtocolError("Expected 'fire:<delay_ms>:<repeat_count>' (e.g. fire:50:3).")
        delay_ms, repeat_cnt = int(parts[1], 0), int(parts[2], 0)
        if not (1 <= delay_ms <= 255 and 1 <= repeat_cnt <= 255):
            raise ProtocolError("Fire delay and repeat count must be in 1..255.")
        return (0x30, delay_ms, repeat_cnt)

    if text.startswith("key:"):
        combo = text[4:]
        tokens = [t.strip() for t in combo.split("+") if t.strip()]
        if not tokens:
            raise ProtocolError("Empty key combo after 'key:'.")
        mod_mask = 0
        key_code: int | None = None
        for tok in tokens:
            if tok in HID_MODIFIER_BITS:
                mod_mask |= HID_MODIFIER_BITS[tok]
            elif tok in HID_KEY_USAGES:
                if key_code is not None:
                    raise ProtocolError(f"Only one non-modifier key allowed in '{action}'.")
                key_code = HID_KEY_USAGES[tok]
            else:
                raise ProtocolError(f"Unknown key or modifier token '{tok}'.")
        if key_code is None:
            raise ProtocolError(f"Key combo '{action}' must include a non-modifier key.")
        return (0x70 if mod_mask else 0x60, mod_mask, key_code)

    if text.startswith("raw:"):
        parts = text.split(":")
        if len(parts) != 4:
            raise ProtocolError("Expected 'raw:<type>:<p1>:<p2>' (hex or decimal).")
        vals = tuple(int(p, 0) for p in parts[1:])
        if any(not (0 <= v <= 255) for v in vals):
            raise ProtocolError("Raw button bytes must be 0..255.")
        return vals  # type: ignore[return-value]

    raise ProtocolError(
        f"Unknown button action '{action}'. Use preset name ({', '.join(BUTTON_PRESETS)}), "
        "fire:<ms>:<count>, key:<combo>, or raw:<type>:<p1>:<p2>."
    )


def build_button_packet(
    slot: int | str,
    action: str | tuple[int, int, int],
    *,
    seq: int = 0,
) -> tuple[bytes, int, int, tuple[int, int, int]]:
    """Build ``cmd 0x04`` packet for a single mouse button slot.

    Returns ``(packet, logical_slot, hw_slot, (type, p1, p2))``.
    """
    logical, hw_slot = resolve_button_slot(slot)
    triple = parse_button_action(action)
    payload = bytes((hw_slot, triple[0], triple[1], triple[2]))
    return build_feature_report(CMD_BUTTON, payload, seq=seq), logical, hw_slot, triple


def build_reset_defaults_packet(*, seq: int = 0) -> bytes:
    """Build ``cmd 0x0f`` factory-defaults restore packet (non-DFU)."""
    return build_feature_report(CMD_RESET_DEFAULTS, bytes((0xFF,)), seq=seq)


CODE_TO_POLLING_RATE: dict[int, int] = {code: hz for hz, code in POLLING_RATE_TO_CODE.items()}


def parse_input_event_report(raw: bytes) -> tuple[int | None, int | None]:
    """Decode a vendor Input Report ``0x05`` (hardware DPI/rate button event).

    Per ``FUN_0042e820``, when ``raw[0] == 0x05`` and ``raw[1] == 0x06``,
    ``raw[3]`` carries the polling-rate code and ``raw[4]`` carries the
    1-based active DPI stage (``1..8``). Returns ``(active_stage_0based, hz)``.
    """
    if len(raw) < 5 or raw[0] != 0x05 or raw[1] != 0x06:
        return None, None
    hz = CODE_TO_POLLING_RATE.get(raw[3])
    stage_1based = raw[4]
    stage_0based = stage_1based - 1 if 1 <= stage_1based <= 8 else None
    return stage_0based, hz
