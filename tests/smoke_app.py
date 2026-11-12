"""Smoke-test a built app with the real bundled model: make a short song with ffmpeg,
run the app's CLI on it, and check four stems of the right length come out.
    python tests/smoke_app.py <path to Stm executable>
"""
import os
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stm import audio  # noqa: E402

exe = sys.argv[1]
d = tempfile.mkdtemp()
ff = audio.find_ffmpeg()
src = os.path.join(d, "smoke song.mp3")
# 12 s: a bass line, a hi-hat-ish noise burst and a "voice" tone, so every stem gets something.
subprocess.check_call([ff, "-v", "error", "-y",
                       "-f", "lavfi", "-i", "sine=f=55:d=12",
                       "-f", "lavfi", "-i", "anoisesrc=d=12:a=0.2,volume='if(lt(mod(t,0.5),0.05),1,0)':eval=frame",
                       "-f", "lavfi", "-i", "sine=f=440:d=12,vibrato=f=5:d=0.5",
                       "-filter_complex", "amix=inputs=3,aformat=channel_layouts=stereo", src])

# `info` loads the model on the default device (CoreML / DirectML), proving it compiles there.
info_env = {k: v for k, v in os.environ.items() if k != "STM_DEVICE"}
r = subprocess.run([exe, "info"], capture_output=True, text=True, timeout=900, env=info_env)
print(r.stdout, r.stderr)
assert r.returncode == 0 and "htdemucs" in r.stdout, "info failed (exit %s)" % r.returncode

env = dict(os.environ)
env.pop("STM_FFMPEG", None)
env.pop("STM_MODEL", None)
env["PATH"] = os.pathsep.join(p for p in env.get("PATH", "").split(os.pathsep) if "ffmpeg" not in p.lower())
# CI runners have no real GPU (DirectML would fall back to a software renderer), so
# the release workflow may set STM_DEVICE=cpu for the split itself.
out = os.path.join(d, "out")
t0 = time.time()
r = subprocess.run([exe, "split", src, "-o", out], timeout=1800, env=env, capture_output=True, text=True)
print(r.stdout, r.stderr)
stems = os.path.join(out, "smoke song (stems)")
for name in ("vocals", "drums", "bass", "other"):
    p = os.path.join(stems, name + ".wav")
    assert os.path.isfile(p), "missing %s (exit %s)" % (name, r.returncode)
    dur = audio.probe_duration(p)
    assert dur and abs(dur - 12.0) < 0.1, "%s is %s s long" % (name, dur)
print("smoke test passed: %s split the song in %.1fs" % (exe, time.time() - t0))
