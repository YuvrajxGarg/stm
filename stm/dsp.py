"""The STFT / iSTFT that htdemucs wraps around its network, in numpy.

These reproduce torch.stft / torch.istft with the settings Demucs uses
(Hann window, normalized=True, center=True, reflect padding) and the extra
padding and trimming in HTDemucs._spec / _ispec, so the ONNX graph can stay
free of complex numbers. tests/test_engine.py checks them against PyTorch.
"""

import numpy as np


def _hann(n):
    # torch.hann_window is periodic by default.
    return (0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(n) / n)).astype(np.float64)


def stft(x, n_fft, hop):
    """x: [..., L] float -> complex [..., n_fft//2 + 1, frames] (torch.stft, normalized, center)."""
    pad = n_fft // 2
    x = np.pad(x, [(0, 0)] * (x.ndim - 1) + [(pad, pad)], mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(x, n_fft, axis=-1)[..., ::hop, :]
    spec = np.fft.rfft(frames * _hann(n_fft), axis=-1) / np.sqrt(n_fft)
    return np.swapaxes(spec, -1, -2)


def istft(z, hop, length):
    """z: complex [..., freqs, frames] -> [..., length] (torch.istft, normalized, center)."""
    n_fft = 2 * z.shape[-2] - 2
    if n_fft % hop:
        raise ValueError("hop must divide n_fft")
    k = n_fft // hop
    win = _hann(n_fft)
    frames = np.fft.irfft(np.swapaxes(z, -1, -2), n=n_fft, axis=-1) * np.sqrt(n_fft) * win
    *lead, n, _ = frames.shape
    blocks = frames.reshape(*lead, n, k, hop)
    out = np.zeros((*lead, n + k - 1, hop))
    env = np.zeros((n + k - 1, hop))
    wsq = (win ** 2).reshape(k, hop)
    for j in range(k):
        out[..., j:j + n, :] += blocks[..., j, :]
        env[j:j + n] += wsq[j]
    out = out.reshape(*lead, -1)
    env = env.reshape(-1)
    start = n_fft // 2
    out = out[..., start:start + length]
    env = env[start:start + length]
    if out.shape[-1] < length:
        raise ValueError("not enough frames for the requested length")
    return out / np.where(env > 1e-11, env, 1.0)


def spec_in(mix, n_fft, hop):
    """HTDemucs._spec + _magnitude (cac): mix [B, C, L] -> float32 [B, C*2, n_fft//2, T]."""
    L = mix.shape[-1]
    le = -(-L // hop)
    pad = hop // 2 * 3
    x = np.pad(mix, [(0, 0)] * (mix.ndim - 1) + [(pad, pad + le * hop - L)], mode="reflect")
    z = stft(x, n_fft, hop)[..., :-1, :]
    z = z[..., 2:2 + le]
    B, C, Fr, T = z.shape
    m = np.stack([z.real, z.imag], axis=2)  # [B, C, 2, Fr, T]
    return m.reshape(B, C * 2, Fr, T).astype(np.float32)


def spec_out(m, hop, length):
    """HTDemucs._mask (cac) + _ispec: [B, S, C*2, Fr, T] -> [B, S, C, length]."""
    B, S, C2, Fr, T = m.shape
    m = m.astype(np.float64).reshape(B, S, C2 // 2, 2, Fr, T)
    z = m[:, :, :, 0] + 1j * m[:, :, :, 1]
    z = np.pad(z, [(0, 0)] * 3 + [(0, 1), (2, 2)])
    pad = hop // 2 * 3
    le = hop * -(-length // hop) + 2 * pad
    x = istft(z, hop, le)
    return x[..., pad:pad + length]
