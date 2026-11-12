"""Split one song into stems: decode -> separate -> write. Shared by the CLI and the window."""

import os

from . import audio, engine

MODES = ("4", "2", "vocals", "drums", "bass", "other")


def split_file(sep, src, out_dir=None, mode="4", fmt="wav", progress=None, cancel=None):
    """Writes the stems for `src` into out_dir (default "<song> (stems)" beside it).
    progress(fraction, phase) is called along the way. Returns [(stem name, path)]."""
    if mode not in MODES:
        raise ValueError("stems must be one of: " + ", ".join(MODES))
    if fmt not in audio.FORMATS:
        raise ValueError("format must be one of: " + ", ".join(audio.FORMATS))

    def tell(f, phase):
        if progress:
            progress(max(0.0, min(1.0, f)), phase)

    tell(0.0, "reading")
    wav = audio.decode(src, sep.samplerate)
    if wav.shape[-1] < sep.samplerate // 10:
        raise ValueError("The song is too short")
    tell(0.03, "splitting")
    stems = sep.separate(wav, progress=lambda f: tell(0.03 + 0.92 * f, "splitting"), cancel=cancel)
    out_dir = out_dir or audio.output_dir_for(src)
    os.makedirs(out_dir, exist_ok=True)
    parts = engine.combine(stems, mode)
    written = []
    for i, (name, data) in enumerate(parts):
        if cancel is not None and cancel():
            raise engine.Cancelled()
        tell(0.95 + 0.05 * i / len(parts), "saving")
        path = os.path.join(out_dir, "%s.%s" % (name, fmt))
        audio.encode(path, data, sep.samplerate, fmt)
        written.append((name, path))
    tell(1.0, "done")
    return written
