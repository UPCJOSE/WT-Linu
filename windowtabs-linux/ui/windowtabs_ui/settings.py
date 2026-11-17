"""Ajustes de la interfaz. Se guardan en ~/.config/windowtabs/settings.json
y se mandan al script de KWin cada vez que éste avisa un cambio."""
import json
import os
from pathlib import Path

DEFAULTS = {
    # lo que usa el script de KWin
    "autoGroupEnabled": True,
    "autoGroupApps": [],
    "hideInactive": False,
    "showOSD": True,
    "barHeight": 32,
    "barPosition": "titlebar",   # titlebar | top | bottom
    "insetLeft": 30,             # espacio libre a la izquierda del titlebar (icono)
    "insetRight": 96,            # espacio libre a la derecha (botones de la ventana)
    # lo que usa solo la interfaz
    "settingsVersion": 2,
    "tabOffset": 0,              # cuánto se desliza la tira de pestañas sobre el titlebar
    "tabMaxWidth": 220,
    "cornerRadius": 8,
    "showIcons": True,
    "closeButton": "hover",      # hover | always | never
    "theme": "system",           # system | light | dark
}


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base)


def settings_path() -> Path:
    return config_dir() / "windowtabs" / "settings.json"


def autostart_path() -> Path:
    return config_dir() / "autostart" / "windowtabs-ui.desktop"


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        with open(settings_path(), encoding="utf-8") as f:
            saved = json.load(f)
        for k, v in saved.items():
            if k in DEFAULTS:
                data[k] = v
        if int(saved.get("settingsVersion", 1)) < 2:
            # ajustes de la v0.2: pasar al nuevo modo (pestañas sobre el titlebar)
            data["barPosition"] = DEFAULTS["barPosition"]
            data["settingsVersion"] = 2
    except (OSError, ValueError):
        pass
    return data


def save(data: dict) -> None:
    p = settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def autostart_enabled() -> bool:
    return autostart_path().exists()


def set_autostart(enabled: bool, exec_cmd: str) -> None:
    p = autostart_path()
    if enabled:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            "[Desktop Entry]\nType=Application\nName=WindowTabs Linux\n"
            f"Exec={exec_cmd}\nIcon=window-duplicate\n"
            "X-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )
    else:
        try:
            p.unlink()
        except OSError:
            pass
