"""Checks the exported ONNX model + Stm's numpy pipeline against PyTorch Demucs.

Needs torch and demucs, so it's skipped in a normal test run. CI runs it right
after exporting the model:

    STM_MODEL=models/htdemucs.onnx python -m unittest tests.test_against_torch
    STM_MODEL=x.onnx STM_RANDOM=1 ...   # an export made with --random
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))

try:
    import torch
    from demucs.apply import apply_model
except ImportError:
    torch = None

MODEL = os.environ.get("STM_MODEL", "")


@unittest.skipUnless(torch is not None and os.path.isfile(MODEL), "needs torch, demucs and STM_MODEL")
class AgainstTorch(unittest.TestCase):
    def test_same_stems_as_demucs(self):
        import export_onnx
        from stm import engine

        torch.backends.mha.set_fastpath_enabled(False)
        model = export_onnx.load(bool(os.environ.get("STM_RANDOM")))
        sep = engine.Separator(MODEL, device="cpu")
        self.assertEqual(sep.sources, list(model.sources))

        # 19.3 s: two full chunks and a short tail, with overlaps between them.
        rng = np.random.default_rng(0)
        sr = 44100
        t = np.arange(int(sr * 19.3)) / sr
        wav = np.stack([np.sin(2 * np.pi * 220 * t) * (t % 0.5 < 0.1) + 0.3 * rng.standard_normal(t.size),
                        np.sin(2 * np.pi * 55 * t) + 0.2 * np.sin(2 * np.pi * 880 * t) + 0.3 * rng.standard_normal(t.size)]) * 0.3
        ours = sep.separate(wav)

        x = torch.tensor(wav, dtype=torch.float32)
        ref = x.mean(0)
        mean, std = ref.mean(), ref.std() + 1e-8
        with torch.no_grad():
            theirs = apply_model(model, ((x - mean) / std)[None], shifts=0, split=True, overlap=0.25)[0] * std + mean
        for k, name in enumerate(model.sources):
            a, b = ours[name], theirs[k].numpy()
            err = np.abs(a - b).max()
            print("%-7s max diff %.2e  (stem rms %.3f)" % (name, err, np.sqrt((b ** 2).mean())))
            self.assertLess(err, 2e-3, name)


if __name__ == "__main__":
    unittest.main()
