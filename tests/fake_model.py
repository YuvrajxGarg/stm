"""A tiny stand-in for htdemucs with the same inputs, outputs and metadata.

Every source gets a quarter of the mix's spectrogram and nothing from the time
branch, so the four stems must add back up to the input exactly. That checks
the whole pipeline (STFT, chunking, overlap-add, iSTFT, file I/O) without the
real 80 MB model or PyTorch.
"""
import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

SOURCES = ["drums", "bass", "other", "vocals"]


def build(path, segment=44100, nfft=4096, hop=1024):
    T = -(-segment // hop)
    S = len(SOURCES)
    mix = helper.make_tensor_value_info("mix", TensorProto.FLOAT, [1, 2, segment])
    spec = helper.make_tensor_value_info("spec", TensorProto.FLOAT, [1, 4, nfft // 2, T])
    spec_out = helper.make_tensor_value_info("spec_out", TensorProto.FLOAT, [1, S, 4, nfft // 2, T])
    wave_out = helper.make_tensor_value_info("wave_out", TensorProto.FLOAT, [1, S, 2, segment])
    inits = [
        numpy_helper.from_array(np.array([1], dtype=np.int64), "ax1"),
        numpy_helper.from_array(np.array([1, S, 4, nfft // 2, T], dtype=np.int64), "shape_s"),
        numpy_helper.from_array(np.array([1, S, 2, segment], dtype=np.int64), "shape_w"),
        numpy_helper.from_array(np.array(1.0 / S, dtype=np.float32), "share"),
        numpy_helper.from_array(np.array(0.0, dtype=np.float32), "zero"),
    ]
    nodes = [
        helper.make_node("Unsqueeze", ["spec", "ax1"], ["s1"]),
        helper.make_node("Mul", ["s1", "share"], ["s2"]),
        helper.make_node("Expand", ["s2", "shape_s"], ["spec_out"]),
        helper.make_node("Unsqueeze", ["mix", "ax1"], ["m1"]),
        helper.make_node("Mul", ["m1", "zero"], ["m2"]),
        helper.make_node("Expand", ["m2", "shape_w"], ["wave_out"]),
    ]
    graph = helper.make_graph(nodes, "fake_htdemucs", [mix, spec], [spec_out, wave_out], inits)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8
    for k, v in {"sources": ",".join(SOURCES), "samplerate": "44100", "segment": str(segment),
                 "nfft": str(nfft), "hop": str(hop), "channels": "2", "name": "fake"}.items():
        e = model.metadata_props.add()
        e.key, e.value = "stm." + k, v
    onnx.checker.check_model(model)
    onnx.save(model, path)
    return path
