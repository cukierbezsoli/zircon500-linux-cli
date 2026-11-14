# Genesis Zircon 500 (v1) — Reverse-Engineered USB & 2.4 GHz HID Protocol

> [!NOTE]
> Documented exclusively from static disassembly and decompilation of `Zircon_500_setup.exe`
> (SHA-256 `acd0f100dafc9ed1a324d52b7e967a74962122128691f224218e4549b78b6163`, extracted from
> `Genesis_Zircon_500_setup_V1.1.4.exe`).
>
> **Safety exclusion**: All firmware-update / bootloader / DFU routines are intentionally omitted and MUST NOT be implemented in the Linux CLI.

---

## 1. USB Identifiers & HID Interfaces

| Mode | VID | PID | Observed Product String | Vendor Interface | Notes |
| --- | --- | --- | --- | --- | --- |
| Wired USB (primary) | `0x248a` | `0x5b2e` | `XCTECH USB Gaming Mouse` | `MI_01` (`if1`), Usage Page `0xFF00` | Verified live on `/dev/hidraw3` |
| 2.4 GHz Wireless Dongle | `0x248a` | `0x5b2f` | `SSCYPL Wireless-Receiver` | `MI_01` (`if1`), Usage Page `0xFF00` | Same packet protocol (`M137` status) |
| Wired USB (legacy ID in `.exe`) | `0x331a` | `0x5024` | — | `MI_01` (`if1`), Usage Page `0xFF00` | Present in device table of `.exe` |

### Report Descriptor Summary (`MI_01`, Usage Page `0xFF00`)

- **Input Report ID `0x05`**: `33` bytes (`0x21`)
- **Feature Report ID `0x0c`**: `33` bytes (`0x21`)

Linux userspace talks to `MI_01` / Usage Page `0xFF00` via `/dev/hidraw*` using `HIDIOCSFEATURE(33)` (`0xC0214806`) and `HIDIOCGFEATURE(33)` (`0xC0214807`).

---

## 2. Common Feature Report Frame (33 bytes)

Every configuration or status command uses Feature Report `0x0c`, zero-padded to `33` bytes (`0x21`):

```text
Offset   Size  Field        Description
------   ----  -----        -------------------------------------------------
0x00     1     report_id    Always 0x0c
0x01     1     transport    0x01 (wired/wireless active)
0x02     1     cmd          Command opcode (Section 3)
0x03     1     sub          Always 0x00
0x04     1     seq          Rolling sequence counter (0x00..0xFF, +1 per tx)
0x05     1     rw           0x01 = write, 0x00 = read/status query (cmd 0x20)
0x06     1     length       Payload byte count starting immediately at offset 0x07
0x07     len   payload      Command-specific payload bytes, zero-padded to 33 bytes
```

Total frame length transmitted over `HIDIOCSFEATURE` / `HIDIOCGFEATURE` is always `33` bytes.

---

## 3. Safe Command Reference

| `cmd` | `rw` | `length` | Function |
| --- | --- | --- | --- |
| `0x04` | `0x01` | `0x04` (4) | Program a single mouse button (`[hw_slot, type, p1, p2]`) |
| `0x05` | `0x01` | `0x12` (18) | DPI stages, active count, active bitmask, current stage, X/Y steps |
| `0x06` | `0x01` | `0x18` (24) | DPI stage indicator RGB colors (`8` stages × `3` bytes `[R, G, B]`) |
| `0x07` | `0x01` | `0x01` (1) | USB Polling Rate (`0x08=125 Hz`, `0x04=250 Hz`, `0x02=500 Hz`, `0x01=1000 Hz`) |
| `0x08` | `0x01` | `2..23` (`0x17`) | RGB Lighting mode, brightness, speed, direction, and palette |
| `0x09` | `0x01` | `0x02` (2) | Lift-Off Distance (`[lod, 0x00]`, where `lod = 1` or `2` mm) |
| `0x0a` | `0x01` | `0x01` (1) | Button Debounce / Key Response Time (`[ms]`) |
| `0x0b` | `0x01` | `0x02` (2) | Power Manager (`[sleep_minutes, light_off_while_move]`) |
| `0x0c` | `0x01` | `0x01` (1) | Motion Wake-Up (`[0/1]`, requires `M137` wake capability) |
| `0x0e` | `0x01` | variable | Upload hardware Macro events |
| `0x0f` | `0x01` | `0x01` (1) | Restore Factory Defaults (`[0xff]`) |
| `0x20` | `0x00` | `0x00` (0) | Query Device Status (sensor ID, battery %, charge state, wake capability) |

---

## 4. Detailed Payload Layouts (`buf[7..]`)

### 4.1 `cmd 0x20` — Query Device Status

1. Send `HIDIOCSFEATURE(33)`: `[0x0c, 0x01, 0x20, 0x00, seq, 0x00, 0x00, 0x00...]`
2. Sleep `~10 ms` and read `HIDIOCGFEATURE(33)` with `rx[0] = 0x0c`. Retry once if `rx[6] == 0`.

**Response fields**:
- `rx[2] == 0x20` and `rx[3] == 0x00`
- `rx[8:12]`: Firmware/device tag (e.g. `b"M137"`; `rx[0x15]` non-zero exposes Motion Wake-Up support)
- `rx[0x0f]`: Sensor short ID:
  - `0x04 -> 0x3104` (48 steps, 100–8000 DPI)
  - `0x12 -> 0x3212` (42 steps, 200–4800 DPI)
  - `0x25 -> 0x3325` (**PMW3325**, standard Genesis Zircon 500 v1: 59 steps, 200–10000 DPI)
  - `0x27 -> 0x3327` (74 steps, 200–12400 DPI)
  - `0x35 -> 0x3335` (160 steps, 100–16000 DPI)
  - `0x60 -> 0x3360` (121 steps, 100–12000 / 24000 DPI)
  - `0x70 -> 0x3370` (290 steps, 50–19000 DPI)
  - `0x89 -> 0x3389` (160 steps, 100–16000 DPI)
  - `0x95 -> 0x3395` (520 steps, 50–26000 DPI)
  - `0x99 -> 0x3399` (400 steps, 50–20000 DPI)
- `rx[0x12]`: Battery level (`0..100`%)
- `rx[0x13]`: Charge state (`1 = charging`, `2 = full -> 100%`, else `discharging`)

### 4.2 `cmd 0x05` — DPI Stages (`length = 0x12`, `buf[7..24]`)

```text
buf[7]       = ((current_stage & 0x0f) << 4) | (enabled_count & 0x0f)
buf[8]       = active_mask                   # default 0x3f (6 enabled stages)
buf[9 + 2*i] = hw_code(dpi_x[i])             # stage i = 0..7
buf[10+ 2*i] = hw_code(dpi_y[i])
```

True DPI = `table[idx] * 50`.  
For **PMW3325 (`0x3325`)**, `hw_code = idx + 1` (`1..59`):
- `1..49`: `200..5000` DPI in `100` DPI steps (`[200, 300, ..., 5000]`)
- `50..59`: `[5500, 6000, 6400, 7000, 7500, 8000, 8500, 9000, 9500, 10000]`

### 4.3 `cmd 0x06` — DPI Indicator Colors (`length = 0x18`, `buf[7..30]`)

Eight 3-byte `[R, G, B]` tuples for stages `0..7` (little-endian `COLORREF` `[R, G, B, 0x00]` in memory).  
Factory defaults: `[(255,0,0), (0,255,0), (0,0,255), (255,0,255), (0,255,255), (255,255,0), (255,255,255), (255,255,255)]`.

### 4.4 `cmd 0x07` — Polling Rate (`length = 0x01`, `buf[7]`)

`buf[7]`: `1000 // hz` -> `0x08` (`125 Hz`), `0x04` (`250 Hz`), `0x02` (`500 Hz`), `0x01` (`1000 Hz`).

### 4.5 `cmd 0x08` — RGB Lighting (`length = buf[6]`, `buf[7..]`)

```text
buf[7] = mode
buf[8] = ((brightness & 0x0f) << 4) | (speed & 0x0f)   # brightness 1..4, speed 1..5
buf[9..] = mode-specific bytes
```

| `mode` | Effect Name | `buf[6]` (`length`) | Extra bytes `buf[9..]` |
| --- | --- | --- | --- |
| `0` | None / Off | `2` | _(none)_ |
| `1` | Colorful Streaming | `3` | `[direction]` (`0=CW`, `1=CCW`) |
| `2` | Breathing | `3 * (count + 1)` | `[count, R0, G0, B0, ...]` (up to 7 colors) |
| `3` | Steady | `5` | `[R, G, B]` |
| `4` | Neon | `2` | _(none)_ |
| `5` | Snake | `2` | _(none)_ |
| `6` | Colorful Steady | `23` (`0x17`) | `R0, G0, B0 .. R6, G6, B6` (7 colors) |
| `7` | Flicker | `8` | `R0, G0, B0, R1, G1, B1` (2 colors) |
| `8` | Stars Twinkle | `2` | _(none)_ |
| `9` | Wave | `2` | _(none)_ |

### 4.6 `cmd 0x09..0x0c` & `0x0f` — Sensor, Debounce, Power & Reset

- `cmd 0x09` (`length = 0x02`): Lift-Off Distance `[lod_mm, 0x00]` where `lod_mm` is `1` (1 mm) or `2` (2 mm).
- `cmd 0x0a` (`length = 0x01`): Key Response / Debounce Time `[ms]` (e.g. `2..20` ms).
- `cmd 0x0b` (`length = 0x02`): Power Manager `[sleep_minutes, light_off_while_move]` (`sleep_minutes` in `1..60`, `light_off_while_move` in `0..1`).
- `cmd 0x0c` (`length = 0x01`): Motion Wake-Up `[enabled]` (`0` or `1`, supported when `M137` wake capability is present).
- `cmd 0x0f` (`length = 0x01`): Restore Factory Defaults `[0xff]`.

### 4.7 `cmd 0x04` — Button Remapping (`length = 0x04`, `buf[7..10]`)

Each modified button sends its own 4-byte command packet:

```text
buf[7] = hw_slot   # 0..5
buf[8] = type
buf[9] = param1
buf[10]= param2
```

**Logical vs Hardware Slot Swap**: Logical UI/profile buttons `[0=Left, 1=Right, 2=Middle, 3=Forward, 4=Backward, 5=DPI]` map to hardware wire slots **`[0, 1, 2, 4, 3, 5]`** (`Forward` = hw slot `4`, `Backward` = hw slot `3`).

Verified `(type, param1, param2)` encodings:
- `(0x00, 0x00, 0x00)`: Disabled
- `(0x10, mask, 0x00)`: Mouse Click (`0x01`=Left, `0x02`=Right, `0x04`=Middle, `0x08`=Backward, `0x10`=Forward)
- `(0x30, delay_ms, repeat)`: Fire Key / Multi-click (`(0x30, 0x32, 0x03)` = Triple Click)
- `(0x40, sub, 0x00)`: DPI / Sensor Action (`0x01`=DPI Loop, `0x02`=DPI+, `0x03`=DPI-)
- `(0x50, sub, 0x00)`: System / Extended shortcut (`0x01..0x0b`)
- `(0x60, 0x00, hid_key)` / `(0x70, mod_mask, hid_key)`: Keyboard key or modifier+key combo
- `(0x80, usage_lo, usage_hi)`: Multimedia Consumer Usage (LE 16-bit, e.g. `0x00cd`=Play/Pause, `0x00e9`=Vol+, `0x00ea`=Vol-, `0x00e2`=Mute, `0x00b5`=Next, `0x00b6`=Prev, `0x00b7`=Stop, `0x0183`=Media, `0x018a`=Mail, `0x0192`=Calc)
- `(0x90, macro_slot, repeat_mode)`: Hardware macro playback
