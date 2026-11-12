"""Reading songs and writing stems through ffmpeg (bundled via imageio-ffmpeg)."""

import os
import re
import shutil
import subprocess
import sys

import numpy as np

AUDIO_EXTS = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".aif", ".aiff", ".wma", ".alac"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
SUPPORTED_EXTS = AUDIO_EXTS | VIDEO_EXTS
FORMATS = ("wav", "flac", "mp3")
OUT_SUFFIX = " (stems)"

_NO_WINDOW = {"creationflags": 0x08000000} if os.name == "nt" else {}


def find_ffmpeg():
    """Locate an ffmpeg binary: env var, bundled copy, PATH, then imageio-ffmpeg."""
    env = os.environ.get("STM_FFMPEG")
    if env and os.path.isfile(env):
        return env
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    bases = []
    if getattr(sys, "frozen", False):
        bases.append(getattr(sys, "_MEIPASS", ""))
        bases.append(os.path.dirname(sys.executable))
    for base in bases:
        cand = os.path.join(base, exe)
        if base and os.path.isfile(cand):
            return cand
    found = shutil.which("ffmpeg")
    if found:
        return found
    for extra in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if os.path.isfile(extra):
            return extra
    try:
        import imageio_ffmpeg  # type: ignore

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def _ffmpeg():
    ff = find_ffmpeg()
    if not ff:
        raise RuntimeError("ffmpeg wasn't found")
    return ff


def probe_duration(path):
    """Seconds of audio, or None. Reads ffmpeg's header line, so it's quick."""
    try:
        r = subprocess.run([_ffmpeg(), "-hide_banner", "-i", path], stdout=subprocess.DEVNULL,
                           stderr=subprocess.PIPE, timeout=30, **_NO_WINDOW)
        err = r.stderr.decode("utf-8", "replace")
        if "Audio:" not in err:
            return None
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
        if m:
            return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:
        pass
    return None


def decode(path, samplerate=44100):
    """Any audio (or a video's soundtrack) -> float32 [2, samples] at `samplerate`."""
    cmd = [_ffmpeg(), "-v", "error", "-nostdin", "-i", path, "-map", "0:a:0", "-vn",
           "-ac", "2", "-ar", str(samplerate), "-f", "f32le", "-acodec", "pcm_f32le", "-"]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_NO_WINDOW)
    if r.returncode != 0 or not r.stdout:
        msg = r.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError("Couldn't read the audio" + (": " + msg[-1] if msg else ""))
    data = np.frombuffer(r.stdout, dtype="<f4")
    return data.reshape(-1, 2).T.copy()


def encode(path, wav, samplerate=44100, fmt="wav"):
    """float [channels, samples] -> file. WAV and FLAC are 24-bit, MP3 is 320 kbps."""
    codec = {"wav": ["-c:a", "pcm_s24le"], "flac": ["-c:a", "flac", "-sample_fmt", "s32"],
             "mp3": ["-c:a", "libmp3lame", "-b:a", "320k"]}[fmt]
    wav = np.asarray(wav, dtype="<f4")
    tmp = path + ".part"
    cmd = [_ffmpeg(), "-v", "error", "-nostdin", "-y", "-f", "f32le", "-ar", str(samplerate),
           "-ac", str(wav.shape[0]), "-i", "-"] + codec + ["-f", {"wav": "wav", "flac": "flac", "mp3": "mp3"}[fmt], tmp]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, **_NO_WINDOW)
    _, err = p.communicate(np.clip(wav, -1.0, 1.0).T.tobytes())
    if p.returncode != 0:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise RuntimeError("Couldn't write %s: %s" % (os.path.basename(path), err.decode("utf-8", "replace").strip()))
    os.replace(tmp, path)
    return path


def output_dir_for(src, base_dir=None):
    """Where a song's stems go: "<song> (stems)" beside the song, or inside base_dir."""
    name = os.path.splitext(os.path.basename(src))[0] + OUT_SUFFIX
    return os.path.join(base_dir or os.path.dirname(os.path.abspath(src)), name)


def collect_files(paths, recursive=True):
    """Expand files/folders into a list of songs (and videos with a soundtrack)."""
    result = []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = sorted(d for d in dirs if not d.endswith(OUT_SUFFIX) and not d.startswith("."))
                for fn in sorted(files):
                    if os.path.splitext(fn)[1].lower() in SUPPORTED_EXTS and not fn.startswith("."):
                        result.append(os.path.join(root, fn))
                if not recursive:
                    break
        elif os.path.isfile(p):
            result.append(p)
    return result
