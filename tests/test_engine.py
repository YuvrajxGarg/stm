import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stm import audio, cli, core, dsp, engine  # noqa: E402

try:
    import fake_model
except ImportError:  # onnx isn't installed
    fake_model = None

SR = 44100
# htdemucs' spectrogram drops two frames at each end of a chunk (HTDemucs._spec), so
# the first and last ~0.1 s of a song only come back through the time branch. The
# fake model has no time branch, so compare away from the song's ends.
EDGE = 6000


def inner(a):
    return a[..., EDGE:-EDGE]


def song(seconds, sr=SR, seed=0):
    """Two tones, one gated, plus soft noise. Band-limited, because the model drops
    the very top STFT bin (Nyquist), so content there can't come back out."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * sr)) / sr
    noise = np.convolve(rng.standard_normal(t.size + 7), np.ones(8) / 8, mode="valid")
    left = 0.3 * np.sin(2 * np.pi * 110 * t) + 0.1 * noise
    right = 0.3 * np.sin(2 * np.pi * 440 * t) * (t % 0.5 < 0.25) + 0.1 * noise[::-1]
    return np.stack([left, right])


class DspTests(unittest.TestCase):
    def test_stft_istft_round_trip(self):
        x = np.random.default_rng(1).standard_normal((2, 30000))
        y = dsp.istft(dsp.stft(x, 4096, 1024), 1024, x.shape[-1])
        self.assertLess(np.abs(x - y).max(), 1e-9)

    def test_stft_matches_rfft_of_a_frame(self):
        x = np.random.default_rng(2).standard_normal(20000)
        z = dsp.stft(x, 4096, 1024)
        padded = np.pad(x, 2048, mode="reflect")
        win = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(4096) / 4096)
        ref = np.fft.rfft(padded[3 * 1024:3 * 1024 + 4096] * win) / 64.0
        self.assertLess(np.abs(z[:, 3] - ref).max(), 1e-9)

    def test_model_spec_round_trip(self):
        # spec_in followed by spec_out (one "source" holding the whole spectrogram) gives the mix back.
        x = song(343980 / SR)[None]
        m = dsp.spec_in(x, 4096, 1024)
        self.assertEqual(m.shape, (1, 4, 2048, 336))
        y = dsp.spec_out(m[:, None].astype(np.float64), 1024, x.shape[-1])
        # The top frequency bin is dropped by the model, so allow its small share of the energy.
        self.assertLess(np.abs(inner(x - y[:, 0])).max(), 1e-4)


class ChunkTests(unittest.TestCase):
    def test_offsets_cover_the_song_with_overlap(self):
        seg = 1000
        for n in (1, 999, 1000, 1001, 5333):
            offs = engine.chunk_offsets(n, seg)
            covered = np.zeros(n)
            for o in offs:
                covered[o:o + seg] += 1
            self.assertTrue((covered > 0).all())

    def test_padded_chunk_centres_short_tails(self):
        mix = np.arange(10, dtype=float)[None]
        out, length, trim = engine.padded_chunk(mix, 6, 8)
        self.assertEqual(length, 4)
        self.assertEqual(out.shape, (1, 8))
        np.testing.assert_array_equal(out[0, trim:trim + length], [6, 7, 8, 9])
        np.testing.assert_array_equal(out[0, :trim], [4, 5])

    def test_weight_is_a_triangle(self):
        w = engine.chunk_weight(10)
        self.assertEqual(w.max(), 1.0)
        self.assertTrue((w > 0).all())
        np.testing.assert_allclose(w, w[::-1])

    def test_combine(self):
        st = {k: np.full((2, 4), i + 1.0) for i, k in enumerate(["drums", "bass", "other", "vocals"])}
        names = [n for n, _ in engine.combine(st, "4")]
        self.assertEqual(names, ["vocals", "drums", "bass", "other"])
        two = dict(engine.combine(st, "2"))
        np.testing.assert_array_equal(two["instrumental"], np.full((2, 4), 6.0))
        drums = dict(engine.combine(st, "drums"))
        self.assertIn("no_drums", drums)
        np.testing.assert_array_equal(drums["no_drums"], np.full((2, 4), 9.0))


@unittest.skipUnless(audio.find_ffmpeg(), "needs ffmpeg")
class AudioTests(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def test_wav_round_trip_is_24_bit_accurate(self):
        x = song(1.0).astype(np.float32)
        p = audio.encode(os.path.join(self.d, "a.wav"), x)
        y = audio.decode(p)
        self.assertEqual(y.shape, x.shape)
        self.assertLess(np.abs(x - y).max(), 1e-6)

    def test_flac_and_mp3(self):
        x = song(1.0).astype(np.float32)
        for fmt in ("flac", "mp3"):
            p = audio.encode(os.path.join(self.d, "a." + fmt), x, fmt=fmt)
            self.assertGreater(os.path.getsize(p), 1000)
            self.assertAlmostEqual(audio.probe_duration(p), 1.0, delta=0.08)

    def test_mono_and_video_inputs(self):
        ff = audio.find_ffmpeg()
        mono = os.path.join(self.d, "mono.wav")
        subprocess.check_call([ff, "-v", "error", "-f", "lavfi", "-i", "sine=f=300:d=1", mono])
        self.assertEqual(audio.decode(mono).shape[0], 2)
        vid = os.path.join(self.d, "clip.mp4")
        subprocess.check_call([ff, "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=1",
                               "-f", "lavfi", "-i", "sine=f=300:d=1", "-c:v", "mpeg4", "-c:a", "aac", "-shortest", vid])
        self.assertEqual(audio.decode(vid).shape[0], 2)
        silent = os.path.join(self.d, "silent.mp4")
        subprocess.check_call([ff, "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=1",
                               "-c:v", "mpeg4", silent])
        self.assertIsNone(audio.probe_duration(silent))
        with self.assertRaises(RuntimeError):
            audio.decode(silent)

    def test_collect_skips_stem_folders(self):
        os.makedirs(os.path.join(self.d, "Song (stems)"))
        for name in ("Song.mp3", "notes.txt", os.path.join("Song (stems)", "vocals.wav")):
            open(os.path.join(self.d, name), "wb").close()
        self.assertEqual([os.path.basename(p) for p in audio.collect_files([self.d])], ["Song.mp3"])
        self.assertEqual(audio.output_dir_for("/m/Song.mp3"), os.path.join("/m", "Song (stems)"))


@unittest.skipUnless(fake_model and audio.find_ffmpeg(), "needs onnx and ffmpeg")
class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.model = fake_model.build(os.path.join(cls.d, "fake.onnx"))
        cls.sep = engine.Separator(cls.model, device="cpu")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.d, ignore_errors=True)

    def test_stems_add_back_up_to_the_song(self):
        # 3.3 s against 1 s chunks: several overlaps plus a short tail.
        x = song(3.3)
        seen = []
        stems = self.sep.separate(x, progress=seen.append)
        self.assertEqual(sorted(stems), ["bass", "drums", "other", "vocals"])
        total = sum(stems.values())
        self.assertEqual(total.shape, x.shape)
        self.assertLess(np.abs(inner(total - x)).max(), 1e-2)
        self.assertLess(np.sqrt((inner(total - x) ** 2).mean()), 2e-3)
        self.assertEqual(seen[-1], 1.0)

    def test_shorter_than_one_chunk(self):
        x = song(0.4)
        total = sum(self.sep.separate(x).values())
        self.assertEqual(total.shape, x.shape)
        self.assertLess(np.abs(inner(total - x)).max(), 1e-2)
        self.assertLess(np.sqrt((inner(total - x) ** 2).mean()), 2e-3)

    def test_cancel(self):
        with self.assertRaises(engine.Cancelled):
            self.sep.separate(song(3.0), cancel=lambda: True)

    def test_split_file_and_cli(self):
        src = os.path.join(self.d, "My Song.wav")
        audio.encode(src, song(2.5).astype(np.float32))
        written = core.split_file(self.sep, src, mode="2", fmt="flac")
        self.assertEqual([n for n, _ in written], ["vocals", "instrumental"])
        for _, p in written:
            self.assertTrue(p.startswith(os.path.join(self.d, "My Song (stems)")))
            self.assertAlmostEqual(audio.probe_duration(p), 2.5, delta=0.05)
        out = os.path.join(self.d, "cli-out")
        rc = cli.main(["split", src, "-o", out, "--model", self.model, "--device", "cpu"])
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(os.listdir(os.path.join(out, "My Song (stems)"))),
                         ["bass.wav", "drums.wav", "other.wav", "vocals.wav"])
        mix = audio.decode(src)
        total = sum(audio.decode(os.path.join(out, "My Song (stems)", n + ".wav")) for n in ("bass", "drums", "other", "vocals"))
        self.assertLess(np.abs(inner(total - mix)).max(), 1e-2)


if __name__ == "__main__":
    unittest.main()
