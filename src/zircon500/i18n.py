"""Minimal bilingual (EN/PL) localization strings and user language preference."""

from __future__ import annotations

import json
import os
from pathlib import Path

SUPPORTED_LANGS: tuple[str, ...] = ("en", "pl")
DEFAULT_LANG = "en"


def _config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "zircon500" / "config.json"


def normalize_lang(lang: str | None) -> str:
    if not lang:
        return DEFAULT_LANG
    cleaned = lang.strip().lower()
    return cleaned if cleaned in SUPPORTED_LANGS else DEFAULT_LANG


def get_saved_lang() -> str:
    env_lang = os.environ.get("ZIRCON500_LANG")
    if env_lang and env_lang.strip().lower() in SUPPORTED_LANGS:
        return env_lang.strip().lower()
    try:
        cfg = _config_path()
        if cfg.is_file():
            data = json.loads(cfg.read_text(encoding="utf-8"))
            val = str(data.get("lang", DEFAULT_LANG)).lower()
            if val in SUPPORTED_LANGS:
                return val
    except (OSError, ValueError):
        pass
    return DEFAULT_LANG


def save_lang(lang: str) -> None:
    norm = normalize_lang(lang)
    try:
        cfg = _config_path()
        cfg.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, str] = {}
        if cfg.is_file():
            try:
                loaded = json.loads(cfg.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    payload = loaded
            except (OSError, ValueError):
                payload = {}
        payload["lang"] = norm
        cfg.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "banner_sub": "Linux USB / 2.4 GHz Configurator",
        "version_sub": "Version {ver}",
        "dry_run_sub": "Preview mode (--dry-run)",
        "steps_sub": "PMW3325 DPI steps (59 hardware levels)",
        "presets_sub": "Button action presets",
        "udev_sub": "udev permissions for /dev/hidraw*",
        "poll_sub": "Live USB Polling Rate Test",
        "iface_table_title": "Detected HID Interfaces",
        "col_path": "Device",
        "col_vidpid": "VID:PID",
        "col_mode": "Connection",
        "col_if": "IF",
        "col_role": "Role",
        "col_perms": "Access",
        "role_ctrl": "Control",
        "role_hid": "Standard HID",
        "no_devices": "No compatible mouse detected",
        "perm_ok": "RW",
        "perm_none": "No RW",
        "status_title": "Device Status",
        "lbl_device": "Interface",
        "lbl_sensor": "Sensor",
        "lbl_fw": "Firmware",
        "lbl_battery": "Battery",
        "lbl_dpi_stage": "DPI Stage",
        "lbl_wake": "Motion Wake",
        "yes": "Supported",
        "no": "Unavailable",
        "charge_charging": "Charging",
        "charge_full": "Full",
        "charge_discharging": "Battery",
        "status_fix": "Run 'zircon500 udev-rules' to grant non-root access.",
        "status_failed": "Could not read mouse status.",
        "quick_title": "CLI Commands",
        "q_tui": "Open interactive menu (keyboard & mouse)",
        "q_dpi": "Set 1..8 DPI stages (e.g. 400 800 1600)",
        "q_rate": "Set USB polling rate (125 / 250 / 500 / 1000 Hz)",
        "q_lod": "Set Lift-Off Distance (1 or 2 mm)",
        "q_deb": "Set click debounce delay (2 ms = lowest lag)",
        "q_btn": "Remap mouse buttons",
        "pkt_preview_title": "Generated HID Frames (not sent)",
        "pkt_tx_title": "Sent HID Frames",
        "err_prefix": "Error:",
        # TUI Chrome
        "tui_subtitle": "Keyboard & mouse configurator",
        "tui_detecting": "Detecting mouse...",
        "tui_connected": "{mode} ({path}) · {sensor} · FW {fw} · Battery {bat}% ({charge})",
        "tui_locked": "Detected: {path} ({mode}) · No RW permission (see Device tab)",
        "tui_missing": "No Genesis Zircon 500 detected — Dry-run preview remains available",
        "btn_refresh": "Refresh [R]",
        "btn_lang": "Lang: EN [L]",
        "btn_dry_on": "Dry-Run: ON [D]",
        "btn_dry_off": "Dry-Run: OFF [D]",
        "btn_hex": "Hex Log [X]",
        "ready_toast": "Ready — choose a section on the left or press 1..5.",
        # Sidebar (5 real hardware categories)
        "nav_dpi": "1  DPI Stages",
        "nav_sensor": "2  Sensor & Lag",
        "nav_buttons": "3  Buttons",
        "nav_power": "4  Power & Reset",
        "nav_device": "5  Device & udev",
        # Tab 1: DPI
        "dpi_title": "DPI Sensitivity Stages",
        "dpi_desc": "Choose how many DPI stages stay active when cycling with the mouse button. You can also enter XxY (e.g. 800x1200) for separate X/Y sensitivity.",
        "dpi_active_lbl": "Active stage",
        "dpi_count_lbl": "Enabled stages",
        "dpi_stage_cell": "Stage {n}",
        "dpi_stage_cell_active": "Stage {n} ● ACTIVE",
        "dpi_stage_cell_off": "Stage {n} (unused)",
        "dpi_select_opt": "Stage {n} — {dpi} DPI",
        "dpi_hw_sync": "Mouse button event: Stage {stage}",
        "dpi_rate_hw_sync": "Mouse switch event: {hz} Hz",
        "dpi_snap_lbl": "Round to nearest supported sensor step (e.g. 6500 -> 6400 DPI)",
        "dpi_apply": "Apply DPI",
        "dpi_defaults": "Reset Fields",
        # Tab 2: Sensor & Lag
        "sensor_title": "Sensor & Input Latency",
        "sensor_rate_lbl": "USB Polling Rate",
        "sensor_rate_hint": "How often the mouse reports motion to your PC. 1000 Hz = fastest 1 ms latency; lower rates save battery.",
        "sensor_lod_lbl": "Lift-Off Distance (LOD)",
        "sensor_lod_hint": "Height where tracking stops when lifting the mouse. 2 mm is factory default; 1 mm stops tracking lower.",
        "sensor_deb_lbl": "Click Debounce (2–20 ms)",
        "sensor_deb_hint": "Click noise filter delay. Use 2 ms for minimum click lag; increase to 4–8 ms only if clicks double-register.",
        "sensor_apply": "Apply Sensor & Latency",
        "sensor_test_btn": "Test Live Hz (2.5s)",
        "sensor_test_hint": "Move the mouse smoothly in circles during the test to measure the real USB polling rate.",
        "sensor_test_running": "Measuring on {path} — move mouse continuously for {sec:.1f}s...",
        "sensor_test_empty": "No movement detected on {path} (0 intervals). Move the mouse while measuring.",
        "sensor_test_result": "Measured ({path}): median {med_hz:.0f} Hz ({med_ms:.2f} ms) · avg {avg_hz:.0f} Hz · {count} pkts",
        # Tab 3: Buttons
        "btn_title": "Button Remapping",
        "btn_slot_lbl": "Physical Button",
        "btn_slot_hint": "Select which physical mouse button you want to customize.",
        "btn_preset_lbl": "Built-in Action",
        "btn_custom_lbl": "Custom Binding (optional)",
        "btn_custom_hint": "Optional custom action (overrides preset). Examples: key:ctrl+c, key:space, fire:50:3.",
        "btn_apply": "Apply Button",
        "btn_clear": "Clear Custom",
        "btn_reset_all": "Restore Default Buttons",
        # Tab 4: Power & Reset
        "pwr_title": "Wireless Power Saving & Profile Reset",
        "pwr_sleep_lbl": "Idle Sleep Timer (1–60 min)",
        "pwr_sleep_hint": "Inactivity duration before 2.4 GHz wireless mode enters sleep (red battery bar LEDs turn off).",
        "pwr_wake_lbl": "Motion Wake-Up",
        "pwr_wake_hint": "Wake the mouse by moving it instead of clicking a button (if supported by firmware).",
        "pwr_apply": "Apply Power Settings",
        "rst_title": "Factory Reset",
        "rst_hint": "Restores default DPI stages, polling rate, and button bindings.",
        "rst_confirm": "Confirm restoring factory mouse profile",
        "rst_apply": "Restore Factory Defaults",
        # Tab 5: Device
        "dev_title": "Detected Devices & Linux Permissions",
        "dev_udev_hint": "If Access shows No RW, run this command once in your terminal to use the program without sudo:",
    },
    "pl": {
        "banner_sub": "Konfigurator USB / 2.4 GHz dla Linux",
        "version_sub": "Wersja {ver}",
        "dry_run_sub": "Tryb podglądu (--dry-run)",
        "steps_sub": "Kroki DPI sensora PMW3325 (59 poziomów)",
        "presets_sub": "Presety akcji przycisków",
        "udev_sub": "Uprawnienia udev dla /dev/hidraw*",
        "poll_sub": "Test częstotliwości raportowania USB (Hz)",
        "iface_table_title": "Wykryte interfejsy HID",
        "col_path": "Urządzenie",
        "col_vidpid": "VID:PID",
        "col_mode": "Połączenie",
        "col_if": "IF",
        "col_role": "Rola",
        "col_perms": "Dostęp",
        "role_ctrl": "Sterowanie",
        "role_hid": "Standardowy HID",
        "no_devices": "Nie wykryto kompatybilnej myszy",
        "perm_ok": "RW",
        "perm_none": "Brak RW",
        "status_title": "Status urządzenia",
        "lbl_device": "Interfejs",
        "lbl_sensor": "Sensor",
        "lbl_fw": "Firmware",
        "lbl_battery": "Bateria",
        "lbl_dpi_stage": "Aktywne DPI",
        "lbl_wake": "Motion Wake",
        "yes": "Wspierane",
        "no": "Niedostępne",
        "charge_charging": "Ładowanie",
        "charge_full": "Pełna",
        "charge_discharging": "Bateria",
        "status_fix": "Uruchom 'zircon500 udev-rules', aby nadać uprawnienia bez roota.",
        "status_failed": "Nie udało się odczytać statusu myszy.",
        "quick_title": "Polecenia CLI",
        "q_tui": "Otwórz interaktywne menu (klawiatura i mysz)",
        "q_dpi": "Ustaw 1..8 progów DPI (np. 400 800 1600)",
        "q_rate": "Ustaw taktowanie USB (125 / 250 / 500 / 1000 Hz)",
        "q_lod": "Ustaw dystans LOD (1 lub 2 mm)",
        "q_deb": "Ustaw opóźnienie debounce (2 ms = najmniejszy lag)",
        "q_btn": "Przypisz funkcje przyciskom myszy",
        "pkt_preview_title": "Wygenerowane ramki HID (niewysłane)",
        "pkt_tx_title": "Wysłane ramki HID",
        "err_prefix": "Błąd:",
        # TUI Chrome
        "tui_subtitle": "Konfigurator myszy",
        "tui_detecting": "Wykrywanie myszy...",
        "tui_connected": "{mode} ({path}) · {sensor} · FW {fw} · Bateria {bat}% ({charge})",
        "tui_locked": "Wykryto: {path} ({mode}) · Brak dostępu RW (zobacz zakładkę Urządzenie)",
        "tui_missing": "Nie wykryto Genesis Zircon 500 — tryb symulacji nadal działa",
        "btn_refresh": "Odśwież [R]",
        "btn_lang": "Język: PL [L]",
        "btn_dry_on": "Symulacja: WŁ [D]",
        "btn_dry_off": "Symulacja: WYŁ [D]",
        "btn_hex": "Log HID [X]",
        "ready_toast": "Gotowe — wybierz kategorię po lewej lub wciśnij 1..5.",
        # Sidebar
        "nav_dpi": "1  Progi DPI",
        "nav_sensor": "2  Sensor & Lag",
        "nav_buttons": "3  Przyciski",
        "nav_power": "4  Zasilanie",
        "nav_device": "5  Urządzenie",
        # Tab 1: DPI
        "dpi_title": "Progi czułości DPI",
        "dpi_desc": "Wybierz, ile progów DPI ma być aktywnych pod przyciskiem zmiany DPI. Możesz też wpisać XxY (np. 800x1200) dla osobnej czułości osi X i Y.",
        "dpi_active_lbl": "Aktywny próg",
        "dpi_count_lbl": "Liczba progów",
        "dpi_stage_cell": "Próg {n}",
        "dpi_stage_cell_active": "Próg {n} ● AKTYWNY",
        "dpi_stage_cell_off": "Próg {n} (wyłączony)",
        "dpi_select_opt": "Próg {n} — {dpi} DPI",
        "dpi_hw_sync": "Przycisk na myszy: Próg {stage}",
        "dpi_rate_hw_sync": "Przełącznik na myszy: {hz} Hz",
        "dpi_snap_lbl": "Zaokrąglaj do najbliższego kroku sensora (np. 6500 -> 6400 DPI)",
        "dpi_apply": "Zastosuj DPI",
        "dpi_defaults": "Domyślne pola",
        # Tab 2: Sensor & Lag
        "sensor_title": "Sensor i opóźnienie (Input Lag)",
        "sensor_rate_lbl": "Polling Rate USB",
        "sensor_rate_hint": "Częstotliwość raportowania ruchu do PC. 1000 Hz = najszybsza reakcja 1 ms; niższe wartości oszczędzają baterię.",
        "sensor_lod_lbl": "Lift-Off Distance (LOD)",
        "sensor_lod_hint": "Wysokość, na której sensor przestaje śledzić ruch po uniesieniu myszy. 2 mm to ustawienie fabryczne; 1 mm jest niższe.",
        "sensor_deb_lbl": "Debounce kliku (2–20 ms)",
        "sensor_deb_hint": "Opóźnienie filtra drgań styków. 2 ms daje najmniejszy input lag kliku; zwiększ do 4–8 ms tylko przy dwukliku.",
        "sensor_apply": "Zastosuj Sensor & Lag",
        "sensor_test_btn": "Zmierz Hz na żywo (2.5s)",
        "sensor_test_hint": "Poruszaj myszą płynnie w kółko podczas testu, aby zmierzyć rzeczywiste taktowanie USB.",
        "sensor_test_running": "Pomiar na {path} — ruszaj myszą bez przerwy przez {sec:.1f}s...",
        "sensor_test_empty": "Brak ruchu na {path} (0 próbek). Poruszaj myszą w trakcie pomiaru.",
        "sensor_test_result": "Wynik ({path}): mediana {med_hz:.0f} Hz ({med_ms:.2f} ms) · śr. {avg_hz:.0f} Hz · {count} pak.",
        # Tab 3: Buttons
        "btn_title": "Mapowanie przycisków myszy",
        "btn_slot_lbl": "Przycisk fizyczny",
        "btn_slot_hint": "Wybierz przycisk myszy, któremu chcesz przypisać nową funkcję.",
        "btn_preset_lbl": "Gotowa akcja",
        "btn_custom_lbl": "Własna akcja (opcjonalnie)",
        "btn_custom_hint": "Opcjonalna własna akcja (nadpisuje gotową). Przykłady: key:ctrl+c, key:space, fire:50:3.",
        "btn_apply": "Zastosuj przycisk",
        "btn_clear": "Wyczyść własną",
        "btn_reset_all": "Przywróć domyślne przyciski",
        # Tab 4: Power & Reset
        "pwr_title": "Oszczędzanie energii 2.4 GHz i reset profilu",
        "pwr_sleep_lbl": "Czas do uśpienia (1–60 min)",
        "pwr_sleep_hint": "Czas bezczynności, po którym mysz bezprzewodowa przechodzi w uśpienie.",
        "pwr_wake_lbl": "Wybudzanie ruchem",
        "pwr_wake_hint": "Wybudza mysz samym ruchem zamiast kliknięcia przycisku (zależnie od wersji firmware).",
        "pwr_apply": "Zastosuj zasilanie",
        "rst_title": "Ustawienia fabryczne",
        "rst_hint": "Przywraca domyślne progi DPI, polling rate oraz przypisania przycisków.",
        "rst_confirm": "Potwierdzam przywrócenie domyślnego profilu myszy",
        "rst_apply": "Przywróć domyślne",
        # Tab 5: Device
        "dev_title": "Wykryte urządzenia i uprawnienia Linux",
        "dev_udev_hint": "Jeśli w kolumnie Dostęp widnieje Brak RW, wykonaj raz poniższe polecenie w terminalu, aby korzystać z programu bez sudo:",
    },
}


def t(key: str, lang: str = DEFAULT_LANG, **kwargs: object) -> str:
    loc = normalize_lang(lang)
    template = STRINGS[loc].get(key) or STRINGS[DEFAULT_LANG].get(key, key)
    return template.format(**kwargs) if kwargs else template
