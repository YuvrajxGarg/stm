"""Export Demucs htdemucs to ONNX for Stm.

    pip install torch demucs onnx onnxruntime
    python tools/export_onnx.py                      # official htdemucs weights -> models/htdemucs.onnx
    python tools/export_onnx.py --random -o x.onnx   # untrained network with the same shape (tests only)

htdemucs runs an STFT and an inverse STFT around its network. Those use complex
tensors, which ONNX and the CoreML / DirectML execution providers handle badly,
so they're kept out of the graph. Stm does them in numpy (stm/dsp.py) and the
exported graph only contains the network itself:

    inputs   mix   float32 [1, 2, L]          one chunk of stereo audio, L = model.segment * 44100
             spec  float32 [1, 4, 2048, T]    STFT of the chunk, real/imag stacked as channels
    outputs  spec_out  float32 [1, S, 4, 2048, T]   per-source spectrogram (real/imag channels)
             wave_out  float32 [1, S, 2, L]         per-source waveform from the time branch

The final stem is istft(spec_out) + wave_out, exactly as HTDemucs.forward does.
"""

import argparse
import hashlib
import json
import os
import sys

import torch
from torch import nn


class Core(nn.Module):
    """HTDemucs.forward without the STFT / iSTFT at either end."""

    def __init__(self, m):
        super().__init__()
        self.m = m

    def forward(self, mix, mag):
        m = self.m
        x = mag
        B, C, Fq, T = x.shape
        mean = x.mean(dim=(1, 2, 3), keepdim=True)
        std = x.std(dim=(1, 2, 3), keepdim=True)
        x = (x - mean) / (1e-5 + std)

        xt = mix
        meant = xt.mean(dim=(1, 2), keepdim=True)
        stdt = xt.std(dim=(1, 2), keepdim=True)
        xt = (xt - meant) / (1e-5 + stdt)

        saved, saved_t, lengths, lengths_t = [], [], [], []
        for idx, encode in enumerate(m.encoder):
            lengths.append(x.shape[-1])
            inject = None
            if idx < len(m.tencoder):
                lengths_t.append(xt.shape[-1])
                tenc = m.tencoder[idx]
                xt = tenc(xt)
                if not tenc.empty:
                    saved_t.append(xt)
                else:
                    inject = xt
            x = encode(x, inject)
            if idx == 0 and m.freq_emb is not None:
                frs = torch.arange(x.shape[-2], device=x.device)
                emb = m.freq_emb(frs).t()[None, :, :, None].expand_as(x)
                x = x + m.freq_emb_scale * emb
            saved.append(x)

        if m.crosstransformer:
            if m.bottom_channels:
                b, c, f, t = x.shape
                x = x.reshape(b, c, f * t)
                x = m.channel_upsampler(x)
                x = x.reshape(b, -1, f, t)
                xt = m.channel_upsampler_t(xt)
            x, xt = m.crosstransformer(x, xt)
            if m.bottom_channels:
                b, c, f, t = x.shape
                x = x.reshape(b, c, f * t)
                x = m.channel_downsampler(x)
                x = x.reshape(b, -1, f, t)
                xt = m.channel_downsampler_t(xt)

        for idx, decode in enumerate(m.decoder):
            skip = saved.pop(-1)
            x, pre = decode(x, skip, lengths.pop(-1))
            offset = m.depth - len(m.tdecoder)
            if idx >= offset:
                tdec = m.tdecoder[idx - offset]
                length_t = lengths_t.pop(-1)
                if tdec.empty:
                    pre = pre[:, :, 0]
                    xt, _ = tdec(pre, None, length_t)
                else:
                    skip = saved_t.pop(-1)
                    xt, _ = tdec(xt, skip, length_t)

        S = len(m.sources)
        x = x.view(B, S, -1, Fq, T)
        x = x * std[:, None] + mean[:, None]
        xt = xt.view(B, S, -1, mix.shape[-1])
        xt = xt * stdt[:, None] + meant[:, None]
        return x, xt


def load(random_init):
    if random_init:
        from demucs.htdemucs import HTDemucs

        torch.manual_seed(0)
        m = HTDemucs(sources=["drums", "bass", "other", "vocals"], segment=7.8)
        return m.eval()
    from demucs.pretrained import get_model

    bag = get_model("htdemucs")
    m = bag.models[0] if hasattr(bag, "models") else bag
    return m.eval()


def segment_samples(m):
    return int(m.segment * m.samplerate)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("-o", "--output", default=os.path.join("models", "htdemucs.onnx"))
    p.add_argument("--random", action="store_true", help="untrained weights (for tests, no download)")
    p.add_argument("--opset", type=int, default=17)
    args = p.parse_args(argv)

    m = load(args.random)
    L = segment_samples(m)
    hl = m.hop_length
    T = -(-L // hl)
    core = Core(m).eval()
    mix = torch.randn(1, m.audio_channels, L) * 0.1
    mag = torch.randn(1, m.audio_channels * 2, m.nfft // 2, T)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    # The fused attention kernel PyTorch picks in eval mode has no ONNX equivalent.
    torch.backends.mha.set_fastpath_enabled(False)
    with torch.no_grad():
        torch.onnx.export(
            core, (mix, mag), args.output,
            input_names=["mix", "spec"], output_names=["spec_out", "wave_out"],
            opset_version=args.opset, do_constant_folding=True, dynamo=False,
        )

    import onnx

    model = onnx.load(args.output)
    meta = {
        "sources": ",".join(m.sources), "samplerate": str(m.samplerate), "segment": str(L),
        "nfft": str(m.nfft), "hop": str(hl), "channels": str(m.audio_channels),
        "name": "htdemucs-random" if args.random else "htdemucs",
    }
    del model.metadata_props[:]
    for k, v in meta.items():
        e = model.metadata_props.add()
        e.key, e.value = "stm." + k, v
    onnx.save(model, args.output)

    h = hashlib.sha256()
    with open(args.output, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    print(json.dumps({"path": args.output, "sha256": h.hexdigest(), "bytes": os.path.getsize(args.output), **meta}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
