"""Text → embedding, with graceful degradation.

Three backends, selected by :func:`get_embedder`:

  * :class:`OnnxEmbedder`   — real semantic vectors (bge-small) when the model
                              files are present. Needs onnxruntime + tokenizers.
  * :class:`DaemonEmbedder` — socket client for a resident OnnxEmbedder.
  * :class:`HashingEmbedder`— **dependency-free fallback** (numpy only). Hashes
                              word + character-trigram features into a fixed
                              vector so lexically similar texts score higher.
                              No download, no model — usable on first run.

All backends return L2-normalized ``(N, dim)`` float32 with ``dim == 384`` so
the ``.psmem`` format is identical regardless of backend.
"""
from __future__ import annotations

import hashlib
import os
import re
import socket
import struct
from pathlib import Path

import numpy as np

DEFAULT_DIM = 384
DEFAULT_MAX_LEN = 512
_TOKEN_RE = re.compile(r"[a-z0-9]+")


# --------------------------------------------------------------------------- #
# Hashing fallback (numpy only)
# --------------------------------------------------------------------------- #
class HashingEmbedder:
    """Feature-hashing embedder. Lexical, not semantic, but real cosine signal
    with zero dependencies and zero download. The default until a model is
    installed via ``priorstates init --download-model``."""

    backend = "hashing"

    def __init__(self, dim: int = DEFAULT_DIM):
        self.dim = dim

    def _features(self, text: str):
        text = text.lower()
        toks = _TOKEN_RE.findall(text)
        # whole words
        for t in toks:
            yield "w:" + t
        # word bigrams (a little phrase signal)
        for a, b in zip(toks, toks[1:]):
            yield "b:" + a + "_" + b
        # character trigrams over the joined token stream (typo/substring signal)
        joined = " ".join(toks)
        for i in range(len(joined) - 2):
            yield "c:" + joined[i:i + 3]

    def embed(self, texts: list[str], batch: int = 0) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for r, text in enumerate(texts):
            v = out[r]
            for feat in self._features(text):
                h = hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest()
                idx = int.from_bytes(h[:4], "little") % self.dim
                sign = 1.0 if (h[4] & 1) else -1.0
                v[idx] += sign
            n = np.linalg.norm(v)
            if n > 0:
                out[r] = v / n
        return out

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


# --------------------------------------------------------------------------- #
# ONNX (real semantic)
# --------------------------------------------------------------------------- #
class OnnxEmbedder:
    backend = "onnx"

    def __init__(self, model_dir: Path | str, max_len: int = DEFAULT_MAX_LEN):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        model_dir = Path(model_dir)
        onnx_path = model_dir / "onnx" / "model.onnx"
        tok_path = model_dir / "tokenizer.json"
        if not onnx_path.exists() or not tok_path.exists():
            raise FileNotFoundError(f"model not found under {model_dir}")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, (os.cpu_count() or 4) // 2)
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(str(onnx_path), sess_options=opts,
                                            providers=["CPUExecutionProvider"])
        self.tokenizer = Tokenizer.from_file(str(tok_path))
        self.tokenizer.enable_truncation(max_length=max_len)
        self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        self.dim = DEFAULT_DIM
        self.input_names = {i.name for i in self.session.get_inputs()}

    def embed(self, texts: list[str], batch: int = 32) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        out = np.empty((len(texts), self.dim), dtype=np.float32)
        for i in range(0, len(texts), batch):
            chunk = texts[i:i + batch]
            encs = self.tokenizer.encode_batch(chunk)
            ids = np.array([e.ids for e in encs], dtype=np.int64)
            mask = np.array([e.attention_mask for e in encs], dtype=np.int64)
            feed = {"input_ids": ids, "attention_mask": mask}
            if "token_type_ids" in self.input_names:
                feed["token_type_ids"] = np.zeros_like(ids)
            (last_hidden,) = self.session.run(["last_hidden_state"], feed)
            cls = last_hidden[:, 0, :]
            norms = np.linalg.norm(cls, axis=1, keepdims=True) + 1e-12
            out[i:i + len(chunk)] = (cls / norms).astype(np.float32)
        return out

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


# --------------------------------------------------------------------------- #
# Daemon client (resident OnnxEmbedder over AF_UNIX) — same wire as reference.
# --------------------------------------------------------------------------- #
class DaemonEmbedder:
    backend = "daemon"

    def __init__(self, sock_path: Path, timeout_s: float = 30.0):
        self.sock_path = Path(sock_path)
        self.timeout_s = timeout_s
        self.dim = DEFAULT_DIM

    def _readn(self, conn, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise EOFError(f"short read {len(buf)}/{n}")
            buf.extend(chunk)
        return bytes(buf)

    def embed(self, texts: list[str], batch: int = 32) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        out = np.empty((len(texts), self.dim), dtype=np.float32)
        for i in range(0, len(texts), batch):
            chunk = texts[i:i + batch]
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(self.timeout_s)
                s.connect(str(self.sock_path))
                req = bytearray(struct.pack("<I", len(chunk)))
                for t in chunk:
                    b = t.encode("utf-8")
                    req.extend(struct.pack("<I", len(b)))
                    req.extend(b)
                s.sendall(req)
                (status,) = struct.unpack("<I", self._readn(s, 4))
                if status != 0:
                    (ln,) = struct.unpack("<I", self._readn(s, 4))
                    raise RuntimeError(self._readn(s, ln).decode("utf-8", "replace"))
                (dim,) = struct.unpack("<I", self._readn(s, 4))
                raw = self._readn(s, len(chunk) * dim * 4)
                out[i:i + len(chunk)] = np.frombuffer(raw, dtype="<f4").reshape(len(chunk), dim)
        return out

    def embed_one(self, text: str) -> np.ndarray:
        return self.embed([text])[0]


def daemon_sock(config=None) -> Path:
    env = os.environ.get("PRIORSTATES_EMBED_SOCK")
    if env:
        return Path(env)
    # Linux XDG runtime dir when available; otherwise a temp path (macOS has no
    # /run/user, Windows has no os.getuid()). The daemon is optional — if the
    # socket can't be reached, get_embedder() falls back to an in-process model.
    uid = getattr(os, "getuid", lambda: None)()
    if uid is not None and os.path.isdir(f"/run/user/{uid}"):
        return Path(f"/run/user/{uid}/priorstates-embed.sock")
    import tempfile
    return Path(tempfile.gettempdir()) / "priorstates-embed.sock"


def get_embedder(config=None, *, prefer_daemon: bool = True, quiet: bool = True):
    """Return the best available embedder. Falls back to HashingEmbedder when
    no ONNX model is installed (so the system always works)."""
    model_dir = config.model_dir if config is not None else None

    if prefer_daemon and os.environ.get("PRIORSTATES_NO_DAEMON") != "1":
        sp = daemon_sock(config)
        if sp.exists():
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                    probe.settimeout(0.5)
                    probe.connect(str(sp))
                return DaemonEmbedder(sp)
            except OSError:
                pass

    if model_dir is not None and (model_dir / "onnx" / "model.onnx").exists():
        try:
            return OnnxEmbedder(model_dir)
        except Exception as e:  # pragma: no cover
            if not quiet:
                print(f"[priorstates] ONNX load failed ({e}); using hashing fallback")

    if not quiet:
        print("[priorstates] no ONNX model installed — using built-in hashing embedder "
              "(run `priorstates init --download-model` for semantic recall)")
    return HashingEmbedder()
