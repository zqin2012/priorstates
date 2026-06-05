"""Read path: mmap a ``.psmem`` file and run top-k cosine queries.

Ported from the reference store. Zero-copy numpy views over the embeddings
and index sections; a query is one embed + one dot product + one argpartition.
"""
from __future__ import annotations

import mmap
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .format import (
    DTYPE_F16, DTYPE_F32, ENTRY_SIZE, FLAG_PINNED, HEADER_SIZE,
    Header, IndexEntry, TYPE_CODES, TYPE_NAMES,
)


@dataclass(slots=True)
class Hit:
    name: str
    description: str
    body: str
    type: str
    src_path: str
    score: float
    rank: int
    pinned: bool = False


class MemoryStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._f = open(self.path, "rb")
        # mmap normally; fall back to reading into RAM on filesystems that don't
        # support mmap (some network filesystems). The .psmem is small, so this is
        # cheap and harmless.
        try:
            # access=ACCESS_READ is portable (Windows + POSIX); the prot= form is
            # POSIX-only and raises AttributeError on Windows (no mmap.PROT_READ).
            self._mm = mmap.mmap(self._f.fileno(), 0, access=mmap.ACCESS_READ)
            self._is_mmap = True
        except (OSError, ValueError):
            self._mm = self._f.read()
            self._is_mmap = False
        self.header = Header.unpack(bytes(self._mm[:HEADER_SIZE]))
        h = self.header
        np_dtype = {DTYPE_F16: np.float16, DTYPE_F32: np.float32}.get(h.embed_dtype)
        if np_dtype is None:
            raise ValueError(f"unsupported embed_dtype {h.embed_dtype}")
        self.embeddings = np.frombuffer(
            self._mm, dtype=np_dtype, count=h.n_entries * h.dim, offset=h.embed_offset,
        ).reshape(h.n_entries, h.dim)
        self._entries_buf = memoryview(self._mm)[h.index_offset:h.index_offset + h.n_entries * ENTRY_SIZE]
        self._strings = memoryview(self._mm)[h.strings_offset:h.strings_offset + h.strings_len]
        self._bodies = memoryview(self._mm)[h.bodies_offset:h.bodies_offset + h.bodies_len]

    def close(self) -> None:
        self.embeddings = None
        self._entries_buf = None
        self._strings = None
        self._bodies = None
        if self._is_mmap:
            self._mm.close()
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    @property
    def n(self) -> int:
        return self.header.n_entries

    def _entry(self, i: int) -> IndexEntry:
        return IndexEntry.unpack_from(self._entries_buf, i * ENTRY_SIZE)

    def _str(self, off: int, ln: int) -> str:
        return bytes(self._strings[off:off + ln]).decode("utf-8", errors="replace")

    def _body(self, off: int, ln: int) -> str:
        return bytes(self._bodies[off:off + ln]).decode("utf-8", errors="replace")

    def hit_from_entry(self, i: int, score: float, rank: int, *, with_body: bool = True) -> Hit:
        e = self._entry(i)
        return Hit(
            name=self._str(e.name_off, e.name_len),
            description=self._str(e.desc_off, e.desc_len),
            body=self._body(e.body_off, e.body_len) if with_body else "",
            type=TYPE_NAMES.get(e.type_code, "other"),
            src_path=self._str(e.src_path_off, e.src_path_len),
            score=float(score), rank=rank, pinned=bool(e.flags & FLAG_PINNED),
        )

    def list_pinned(self, *, with_body: bool = True) -> list[Hit]:
        out: list[Hit] = []
        for i in range(self.n):
            if self._entry(i).flags & FLAG_PINNED:
                out.append(self.hit_from_entry(i, 1.0, len(out), with_body=with_body))
        return out

    def search(self, query_vec: np.ndarray, k: int = 5, *,
               type_filter: str | None = None, with_body: bool = True) -> list[Hit]:
        if query_vec.shape != (self.header.dim,):
            raise ValueError(f"query_vec shape {query_vec.shape} != ({self.header.dim},)")
        q = query_vec.astype(np.float32)
        scores = self.embeddings.astype(np.float32) @ q  # embeddings normalized → cosine
        if type_filter:
            code = TYPE_CODES.get(type_filter)
            if code is None:
                raise ValueError(f"bad type_filter {type_filter}")
            keep = np.fromiter((self._entry(i).type_code == code for i in range(self.n)),
                               dtype=bool, count=self.n)
            scores = np.where(keep, scores, -np.inf)
        k = min(k, self.n)
        if k <= 0:
            return []
        top = np.argpartition(-scores, k - 1)[:k]
        top = top[np.argsort(-scores[top])]
        return [self.hit_from_entry(int(i), scores[i], rank, with_body=with_body)
                for rank, i in enumerate(top)]

    def get_by_name(self, name: str) -> Hit | None:
        for i in range(self.n):
            e = self._entry(i)
            if self._str(e.name_off, e.name_len) == name:
                return self.hit_from_entry(i, 1.0, 0)
        return None

    def iter_entries(self):
        for i in range(self.n):
            yield i, self._entry(i)
