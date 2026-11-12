"""Small JSON settings store in the per-user app data folder."""

import json
import os
import sys
import threading

APP_NAME = "Stm"

DEFAULTS = {
    "out_mode": "beside",        # "beside" -> "<song> (stems)" next to each song, "custom" -> inside custom_dir
    "custom_dir": None,
    "open_after": False,         # open the output folder when a batch finishes
    "auto_check": True,          # check GitHub Releases for updates
    "auto_install": True,        # download in the background, install on quit
    "welcomed": False,
    "stems": "4",                # "4" or "2" (vocals + instrumental)
    "format": "wav",             # wav, flac or mp3
    "device": "auto",            # auto (GPU / Neural Engine when possible) or cpu
    "staged_version": None,
    "last_checked": None,
    "notified_version": None,
}


def app_data_dir():
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    d = os.path.join(base, APP_NAME)
    os.makedirs(d, exist_ok=True)
    return d


class Settings(object):
    def __init__(self, path=None):
        self.path = path or os.path.join(app_data_dir(), "settings.json")
        self.lock = threading.Lock()
        self.data = dict(DEFAULTS)
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.data.update(json.load(f))
        except (OSError, ValueError):
            pass

    def get(self, key):
        return self.data.get(key, DEFAULTS.get(key))

    def set(self, key, value):
        with self.lock:
            self.data[key] = value
            tmp = self.path + ".tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, indent=2)
                os.replace(tmp, self.path)
            except OSError:
                pass

    def public(self):
        return {k: self.data.get(k) for k in ("out_mode", "custom_dir", "open_after", "auto_check", "auto_install", "welcomed",
                                               "stems", "format", "device")}
