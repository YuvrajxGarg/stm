"""Stem separation with htdemucs in ONNX Runtime.

The network runs on the GPU / Neural Engine where ONNX Runtime can reach it
(CoreML on macOS, DirectML on Windows) and falls back to the CPU otherwise.
A song is cut into overlapping chunks the length the model was trained on
(7.8 s); each chunk's stems are blended back with a triangular cross-fade, the
same overlap-add Demucs uses, so memory stays flat however long the song is.
"""

import os
import sys
import threading

import numpy as np

from . import dsp

SAMPLERATE = 44100
OVERLAP = 0.25


class Cancelled(Exception):
    pass


def model_path():
    """The bundled model, or STM_MODEL to point at another one."""
    env = os.environ.get("STM_MODEL")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    cands = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        cands.append(os.path.join(sys._MEIPASS, "models", "htdemucs.onnx"))
    cands.append(os.path.join(os.path.dirname(here), "models", "htdemucs.onnx"))
    for c in cands:
        if os.path.isfile(c):
            return c
    return cands[-1]


def _providers(device):
    import onnxruntime as ort

    have = set(ort.get_available_providers())
    out = []
    if device in ("auto", "gpu"):
        if "CoreMLExecutionProvider" in have:
            out.append(("CoreMLExecutionProvider", {"ModelFormat": "MLProgram", "MLComputeUnits": "ALL"}))
        if "DmlExecutionProvider" in have:
            out.append(("DmlExecutionProvider", {}))
        if "CUDAExecutionProvider" in have:
            out.append(("CUDAExecutionProvider", {}))
    out.append(("CPUExecutionProvider", {}))
    return out


def device_label(provider):
    return {
        "CoreMLExecutionProvider": "Apple GPU / Neural Engine (CoreML)",
        "DmlExecutionProvider": "GPU (DirectML)",
        "CUDAExecutionProvider": "NVIDIA GPU (CUDA)",
        "CPUExecutionProvider": "CPU",
    }.get(provider, provider)


def chunk_weight(n):
    """Demucs' triangular cross-fade weight for a chunk of n samples."""
    w = np.concatenate([np.arange(1, n // 2 + 1), np.arange(n - n // 2, 0, -1)]).astype(np.float64)
    return w / w.max()


def chunk_offsets(length, segment, overlap=OVERLAP):
    stride = int((1 - overlap) * segment)
    return list(range(0, length, stride))


def padded_chunk(mix, offset, segment):
    """Demucs' TensorChunk.padded: the chunk at offset, centred in `segment` samples
    of real context where the song has it and zeros where it doesn't."""
    total = mix.shape[-1]
    length = min(segment, total - offset)
    delta = segment - length
    start = offset - delta // 2
    end = start + segment
    cs, ce = max(0, start), min(total, end)
    out = np.zeros(mix.shape[:-1] + (segment,), dtype=mix.dtype)
    out[..., cs - start:cs - start + (ce - cs)] = mix[..., cs:ce]
    return out, length, delta // 2


class Separator(object):
    def __init__(self, path=None, device="auto", threads=0):
        import onnxruntime as ort

        self.path = path or model_path()
        if not os.path.isfile(self.path):
            raise FileNotFoundError("Model not found: %s" % self.path)
        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if threads:
            opts.intra_op_num_threads = int(threads)
        provs = _providers(device)
        if any(p[0] == "DmlExecutionProvider" for p in provs):
            opts.enable_mem_pattern = False
            opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = None
        err = None
        # Try the accelerated providers first; a provider that can't compile this
        # graph raises here, and the next one (finally the CPU) takes over.
        for i in range(len(provs)):
            try:
                self.session = ort.InferenceSession(
                    self.path, sess_options=opts,
                    providers=[p[0] for p in provs[i:]], provider_options=[p[1] for p in provs[i:]])
                break
            except Exception as e:  # pragma: no cover - depends on the machine
                err = e
        if self.session is None:
            raise RuntimeError("Couldn't load the model: %s" % err)
        meta = self.session.get_modelmeta().custom_metadata_map
        self.sources = meta.get("stm.sources", "drums,bass,other,vocals").split(",")
        self.samplerate = int(meta.get("stm.samplerate", SAMPLERATE))
        self.segment = int(meta.get("stm.segment", 343980))
        self.nfft = int(meta.get("stm.nfft", 4096))
        self.hop = int(meta.get("stm.hop", 1024))
        self.model_name = meta.get("stm.name", "htdemucs")
        self.provider = self.session.get_providers()[0]
        self._lock = threading.Lock()

    @property
    def device(self):
        return device_label(self.provider)

    def _run_chunk(self, chunk):
        mix = chunk[None].astype(np.float32)
        spec = dsp.spec_in(mix, self.nfft, self.hop)
        with self._lock:
            try:
                spec_o, wave_o = self.session.run(None, {"mix": mix, "spec": spec})
            except Exception:
                if self.provider == "CPUExecutionProvider":
                    raise
                # The accelerator gave up at run time: rebuild on the CPU and carry on.
                import onnxruntime as ort

                self.session = ort.InferenceSession(self.path, providers=["CPUExecutionProvider"])
                self.provider = "CPUExecutionProvider"
                spec_o, wave_o = self.session.run(None, {"mix": mix, "spec": spec})
        out = dsp.spec_out(spec_o, self.hop, self.segment) + wave_o.astype(np.float64)
        return out[0]  # [S, C, segment]

    def separate(self, wav, progress=None, cancel=None):
        """wav: float array [channels, samples] at self.samplerate (stereo).
        Returns {source: float32 [channels, samples]}."""
        wav = np.asarray(wav, dtype=np.float64)
        if wav.ndim != 2:
            raise ValueError("expected [channels, samples]")
        if wav.shape[0] == 1:
            wav = np.repeat(wav, 2, axis=0)
        C, N = wav.shape
        if N == 0:
            raise ValueError("The audio is empty")
        # Normalise the whole song the way demucs.separate does, then undo it at the end.
        ref = wav.mean(0)
        mean, std = ref.mean(), ref.std(ddof=1) + 1e-8
        mix = (wav - mean) / std

        S = len(self.sources)
        out = np.zeros((S, C, N))
        total_w = np.zeros(N)
        weight = chunk_weight(self.segment)
        offsets = chunk_offsets(N, self.segment)
        for i, off in enumerate(offsets):
            if cancel is not None and cancel():
                raise Cancelled()
            chunk, length, trim = padded_chunk(mix, off, self.segment)
            res = self._run_chunk(chunk)[..., trim:trim + length]
            out[..., off:off + length] += weight[:length] * res
            total_w[off:off + length] += weight[:length]
            if progress:
                progress((i + 1) / float(len(offsets)))
        out /= total_w
        out = out * std + mean
        return {name: out[k].astype(np.float32) for k, name in enumerate(self.sources)}


def combine(stems, mode):
    """Turn the model's four stems into what the user asked for.
    mode "4"      -> vocals, drums, bass, other
    mode "2"      -> vocals, instrumental
    mode "<name>" -> just that stem plus everything else as "no_<name>"."""
    if mode == "4":
        order = ["vocals", "drums", "bass", "other"]
        return [(k, stems[k]) for k in order if k in stems] + [(k, v) for k, v in stems.items() if k not in order]
    keep = "vocals" if mode == "2" else mode
    if keep not in stems:
        raise ValueError("Unknown stem: %s" % keep)
    rest = sum(v for k, v in stems.items() if k != keep)
    return [(keep, stems[keep]), ("instrumental" if keep == "vocals" else "no_" + keep, rest)]
