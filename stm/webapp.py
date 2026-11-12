"""Stm's desktop UI: an HTML/CSS interface (stm/ui) in a native window via pywebview.

Uses WebKit on macOS and Edge WebView2 on Windows, so both platforms get the same UI.
"""

import json
import os
import subprocess
import sys
import threading

import numpy as np
import webview
from webview.dom import DOMEventHandler

from . import __version__, audio, core, engine
from .settings import Settings
from .updater import Updater

UI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui")
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    UI_DIR = os.path.join(sys._MEIPASS, "stm", "ui")

BG = "#0b0b0c"
PEAKS = 72


def _human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0


def _clock(sec):
    if sec is None:
        return ""
    sec = int(round(sec))
    return "%d:%02d:%02d" % (sec // 3600, sec // 60 % 60, sec % 60) if sec >= 3600 else "%d:%02d" % (sec // 60, sec % 60)


def peaks(wav, n=PEAKS):
    """A tiny waveform for the list: n values between 0 and 1."""
    mono = np.abs(np.asarray(wav, dtype=np.float32)).mean(axis=0)
    if mono.size < n:
        return [0.0] * n
    cut = mono[: mono.size // n * n].reshape(n, -1)
    v = np.sqrt((cut ** 2).mean(axis=1))
    top = float(v.max()) or 1.0
    return [round(float(x) / top, 3) for x in v]


def _quick_peaks(path):
    """Waveform from a low-rate decode, so it shows up long before the split runs."""
    try:
        return peaks(audio.decode(path, 2000))
    except Exception:
        return None


class Api(object):
    def __init__(self):
        self.window = None
        self.items = {}  # id -> dict
        self.next_id = 1
        self.lock = threading.Lock()
        self.busy = False
        self.stop = False
        self.sep = None
        self.engine_error = None
        self.settings = Settings()
        self.updater = Updater(self.settings, lambda st: self._emit("update", st))

    # ---- helpers ---------------------------------------------------------
    def _emit(self, event, payload):
        if self.window:
            try:
                self.window.evaluate_js("window.App && App.on(%s, %s)" % (json.dumps(event), json.dumps(payload)))
            except Exception:
                pass

    def _public(self, it):
        return {
            "id": it["id"], "name": os.path.basename(it["path"]), "path": it["path"],
            "folder": os.path.dirname(it["path"]), "size": it["size"], "ext": os.path.splitext(it["path"])[1][1:].upper(),
            "duration": _clock(it.get("duration")), "status": it["status"], "error": it.get("error"),
            "progress": it.get("progress", 0), "phase": it.get("phase"), "peaks": it.get("peaks"),
            "out": it.get("out"), "stems": it.get("stems", []), "took": it.get("took"),
        }

    def load_engine(self):
        try:
            self.sep = engine.Separator(device=self.settings.get("device") or "auto")
            self.engine_error = None
        except Exception as e:
            self.sep = None
            self.engine_error = str(e)
        self._emit("engine", self._engine_state())

    def _engine_state(self):
        if self.sep:
            return {"ready": True, "device": self.sep.device, "model": self.sep.model_name}
        return {"ready": False, "error": self.engine_error}

    # ---- called from JS --------------------------------------------------
    def info(self):
        return {"version": __version__, "ffmpeg": bool(audio.find_ffmpeg()), "platform": sys.platform,
                "settings": self.settings.public(), "update": self.updater.state(),
                "engine": self._engine_state(), "home": os.path.expanduser("~")}

    def set_setting(self, key, value):
        if key in ("out_mode", "custom_dir", "open_after", "auto_check", "auto_install", "welcomed",
                   "stems", "format", "device"):
            self.settings.set(key, value)
            if key == "auto_install" and value and self.updater.phase == "available":
                threading.Thread(target=self.updater.stage_newest, daemon=True).start()
            if key == "device" and not self.busy:
                self._emit("engine", {"ready": False, "loading": True})
                threading.Thread(target=self.load_engine, daemon=True).start()
        return self.settings.public()

    def check_updates(self):
        return self.updater.check(manual=True)

    def download_update(self):
        threading.Thread(target=self.updater.stage_newest, daemon=True).start()

    def install_update(self):
        def go():
            if self.updater.install() == "open_page":
                self.open_url(self.updater.state()["page"])
        threading.Thread(target=go, daemon=True).start()

    def open_url(self, url):
        if not url.startswith("https://github.com/"):
            return
        import webbrowser
        webbrowser.open(url)

    def pick_files(self):
        exts = ";".join("*" + e for e in sorted(audio.SUPPORTED_EXTS))
        res = self.window.create_file_dialog(
            webview.FileDialog.OPEN, allow_multiple=True,
            file_types=("Songs and videos (%s)" % exts, "All files (*.*)"))
        if res:
            self.add_paths(list(res))

    def pick_folder(self):
        res = self.window.create_file_dialog(webview.FileDialog.FOLDER)
        if res:
            self.add_paths([res[0] if isinstance(res, (list, tuple)) else res])

    def choose_output(self):
        res = self.window.create_file_dialog(webview.FileDialog.FOLDER)
        if res:
            return res[0] if isinstance(res, (list, tuple)) else res
        return None

    def add_paths(self, paths):
        files = audio.collect_files(paths)
        new = []
        with self.lock:
            known = {it["path"] for it in self.items.values()}
            for p in files:
                if p in known:
                    continue
                known.add(p)
                it = {"id": self.next_id, "path": p, "size": _human(os.path.getsize(p)), "status": "reading"}
                self.items[self.next_id] = it
                self.next_id += 1
                new.append(it)
        if not files:
            self._emit("toast", {"text": "No songs there", "err": True})
        for it in new:
            self._emit("upsert", self._public(it))
        if new:
            threading.Thread(target=self._probe, args=(new,), daemon=True).start()

    def _probe(self, items):
        for it in items:
            dur = audio.probe_duration(it["path"])
            if dur is None:
                it["status"] = "unsupported"
                it["error"] = "No audio in this file"
            else:
                it["duration"] = dur
                if it["status"] == "reading":
                    it["status"] = "ready"
            self._emit("upsert", self._public(it))
            if dur is not None:
                it["peaks"] = _quick_peaks(it["path"])
                self._emit("upsert", self._public(it))

    def remove(self, item_id):
        with self.lock:
            it = self.items.get(int(item_id))
            if it and it["status"] not in ("splitting", "queued"):
                self.items.pop(int(item_id), None)

    def clear(self):
        if not self.busy:
            with self.lock:
                self.items.clear()

    def cancel(self):
        if self.busy:
            self.stop = True

    def split(self, stems, fmt, mode, custom_dir):
        if self.busy or not self.sep:
            return
        todo = [it for it in self.items.values() if it["status"] in ("ready", "failed", "stopped", "done")
                and not (it["status"] == "done" and it.get("mode") == (stems, fmt))]
        if not todo:
            return
        self.busy = True
        self.stop = False
        for it in todo:
            it["status"] = "queued"
            it["progress"] = 0
            it["error"] = None
            self._emit("upsert", self._public(it))
        threading.Thread(target=self._split, args=(todo, stems, fmt, mode, custom_dir), daemon=True).start()

    def _split(self, todo, stems, fmt, mode, custom_dir):
        import time

        ok = 0
        last_dir = None
        self._emit("busy", {"busy": True, "total": len(todo)})
        for i, it in enumerate(todo):
            if self.stop:
                it["status"] = "stopped"
                self._emit("upsert", self._public(it))
                continue
            src = it["path"]
            base = custom_dir if (mode == "custom" and custom_dir) else None
            out_dir = audio.output_dir_for(src, base)
            it["status"] = "splitting"
            it["progress"] = 0
            self._emit("upsert", self._public(it))
            last_sent = [0.0]

            def prog(f, phase, it=it, i=i):
                it["progress"] = f
                it["phase"] = phase
                if f - last_sent[0] >= 0.01 or f >= 1.0:
                    last_sent[0] = f
                    self._emit("row_progress", {"id": it["id"], "progress": f, "phase": phase})
                    self._emit("progress", {"done": i + f, "total": len(todo)})

            t0 = time.time()
            try:
                written = core.split_file(self.sep, src, out_dir, stems, fmt, progress=prog, cancel=lambda: self.stop)
                it["stems"] = [{"name": n, "path": p} for n, p in written]
                it["out"] = out_dir
                it["status"] = "done"
                it["mode"] = (stems, fmt)
                it["took"] = round(time.time() - t0, 1)
                ok += 1
                last_dir = out_dir
            except engine.Cancelled:
                it["status"] = "stopped"
            except Exception as e:
                it["status"] = "failed"
                it["error"] = str(e)
            self._emit("upsert", self._public(it))
        self.busy = False
        self._emit("busy", {"busy": False})
        self._emit("finished", {"ok": ok, "total": len(todo), "dir": last_dir, "stopped": self.stop})
        if ok and last_dir and self.settings.get("open_after"):
            self.reveal(last_dir)

    def reveal(self, path):
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path] if os.path.isfile(path) else ["open", path])
            elif os.name == "nt":
                if os.path.isfile(path):
                    subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
                else:
                    os.startfile(path)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", os.path.dirname(path) if os.path.isfile(path) else path])
        except Exception:
            pass

    def play(self, path):
        """Open a stem in the system's default player."""
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", path])
            elif os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            pass


# ---- native window chrome -------------------------------------------------

def _style_mac(window):
    """Dark, transparent title bar with content running underneath (like Dwn and Tag)."""
    try:
        import AppKit
        from PyObjCTools import AppHelper

        def apply():
            w = window.native
            w.setStyleMask_(w.styleMask() | AppKit.NSWindowStyleMaskFullSizeContentView)
            w.setTitlebarAppearsTransparent_(True)
            w.setTitleVisibility_(AppKit.NSWindowTitleHidden)
            w.setAppearance_(AppKit.NSAppearance.appearanceNamed_(AppKit.NSAppearanceNameDarkAqua))
            w.setBackgroundColor_(AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(0.043, 0.043, 0.047, 1.0))
            w.setMovableByWindowBackground_(False)
            try:
                w.contentView().superview().subviews().lastObject().setBackgroundColor_(AppKit.NSColor.clearColor())
            except Exception:
                pass
            if hasattr(w, "setToolbarStyle_"):
                w.setToolbarStyle_(AppKit.NSWindowToolbarStyleUnifiedCompact)

        AppHelper.callAfter(apply)
    except Exception:
        pass


def _style_windows(window):
    """Dark title bar on Windows 10/11; caption colour matches the app on Windows 11."""
    try:
        import ctypes

        hwnd = window.native.Handle.ToInt32()
        dwm = ctypes.windll.dwmapi
        on = ctypes.c_int(1)
        for attr in (20, 19):
            if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), 4) == 0:
                break
        caption = ctypes.c_int(0x000C0B0B)
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), 4)
    except Exception:
        pass


def main():
    api = Api()
    webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True
    window = webview.create_window(
        "Stm", url=os.path.join(UI_DIR, "index.html"), js_api=api,
        width=1120, height=720, min_size=(880, 580), background_color=BG, easy_drag=False,
    )
    api.window = window

    def on_drop(e):
        files = (e.get("dataTransfer") or {}).get("files") or []
        paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
        if paths:
            api.add_paths(paths)

    def on_loaded():
        try:
            window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)
        except Exception:
            pass
        threading.Thread(target=api.load_engine, daemon=True).start()

    def quit_for_install():
        try:
            window.destroy()
        finally:
            threading.Timer(3.0, lambda: os._exit(0)).start()

    api.updater.on_quit_for_install = quit_for_install
    window.events.closing += lambda: api.updater.install_on_quit()
    window.events.loaded += lambda: api.updater.start()

    if sys.platform == "darwin":
        window.events.before_show += lambda: _style_mac(window)
    elif os.name == "nt":
        window.events.shown += lambda: _style_windows(window)
    window.events.loaded += on_loaded
    webview.start(debug=bool(os.environ.get("STM_DEBUG")))


if __name__ == "__main__":
    main()
