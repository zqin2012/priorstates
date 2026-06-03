"""Binary ``.psmem`` format primitives (header, IndexEntry).

Ported byte-for-byte from the reference ``.cmem`` format (magic changed
``CMEM``→``PMEM``; type codes generalized). Layout is documented in
docs/DATA_MODEL.md. If you change a struct here, bump ``VERSION``.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"PMEM"
VERSION = 1
PAGE = 4096

# Header (128 bytes): <  4s magic, H version, H flags, I n_entries, I dim,
#   I embed_dtype, I reserved0, Q embed_offset, Q index_offset,
#   Q strings_offset, Q strings_len, Q bodies_offset, Q bodies_len,
#   Q created_unix_ns, 48s reserved
HEADER_STRUCT = struct.Struct("<4sHHIIII QQ QQ QQ Q 48s")
HEADER_SIZE = 128
assert HEADER_STRUCT.size == HEADER_SIZE, HEADER_STRUCT.size

# IndexEntry (64 bytes).
ENTRY_STRUCT = struct.Struct("<IIII IIII B3s ff I 16s")
ENTRY_SIZE = 64
assert ENTRY_STRUCT.size == ENTRY_SIZE, ENTRY_STRUCT.size

DTYPE_F16 = 1
DTYPE_F32 = 2

FLAG_EMBED_NORMALIZED = 1 << 0
FLAG_PINNED = 1 << 0  # IndexEntry.flags

# Core type codes are stable; plugin-defined types should use codes >= 64.
TYPE_CODES = {
    "other": 0,
    "user": 1,
    "preference": 2,
    "project": 3,
    "reference": 4,
    "note": 5,
    # ingested sources
    "journal": 6,
    "doc": 7,
}
TYPE_NAMES = {v: k for k, v in TYPE_CODES.items()}


@dataclass(slots=True)
class Header:
    magic: bytes = MAGIC
    version: int = VERSION
    flags: int = FLAG_EMBED_NORMALIZED
    n_entries: int = 0
    dim: int = 0
    embed_dtype: int = DTYPE_F16
    embed_offset: int = 0
    index_offset: int = 0
    strings_offset: int = 0
    strings_len: int = 0
    bodies_offset: int = 0
    bodies_len: int = 0
    created_unix_ns: int = 0

    def pack(self) -> bytes:
        return HEADER_STRUCT.pack(
            self.magic, self.version, self.flags,
            self.n_entries, self.dim, self.embed_dtype, 0,
            self.embed_offset, self.index_offset,
            self.strings_offset, self.strings_len,
            self.bodies_offset, self.bodies_len,
            self.created_unix_ns, b"",
        )

    @classmethod
    def unpack(cls, buf: bytes) -> "Header":
        (magic, version, flags, n_entries, dim, embed_dtype, _r0,
         embed_offset, index_offset, strings_offset, strings_len,
         bodies_offset, bodies_len, created_unix_ns, _r) = HEADER_STRUCT.unpack(buf[:HEADER_SIZE])
        if magic != MAGIC:
            raise ValueError(f"bad magic: {magic!r}")
        if version != VERSION:
            raise ValueError(f"unsupported version {version}; this build reads v{VERSION}")
        return cls(magic=magic, version=version, flags=flags, n_entries=n_entries,
                   dim=dim, embed_dtype=embed_dtype, embed_offset=embed_offset,
                   index_offset=index_offset, strings_offset=strings_offset,
                   strings_len=strings_len, bodies_offset=bodies_offset,
                   bodies_len=bodies_len, created_unix_ns=created_unix_ns)


@dataclass(slots=True)
class IndexEntry:
    name_off: int = 0
    name_len: int = 0
    desc_off: int = 0
    desc_len: int = 0
    body_off: int = 0
    body_len: int = 0
    src_path_off: int = 0
    src_path_len: int = 0
    type_code: int = 0
    ctime_unix: float = 0.0
    mtime_unix: float = 0.0
    flags: int = 0
    name_hash: bytes = b"\x00" * 16

    def pack(self) -> bytes:
        return ENTRY_STRUCT.pack(
            self.name_off, self.name_len, self.desc_off, self.desc_len,
            self.body_off, self.body_len, self.src_path_off, self.src_path_len,
            self.type_code, b"\x00\x00\x00",
            self.ctime_unix, self.mtime_unix, self.flags, self.name_hash,
        )

    @classmethod
    def unpack_from(cls, buf, offset: int) -> "IndexEntry":
        (name_off, name_len, desc_off, desc_len, body_off, body_len,
         src_path_off, src_path_len, type_code, _pad,
         ctime_unix, mtime_unix, flags, name_hash) = ENTRY_STRUCT.unpack_from(buf, offset)
        return cls(name_off=name_off, name_len=name_len, desc_off=desc_off,
                   desc_len=desc_len, body_off=body_off, body_len=body_len,
                   src_path_off=src_path_off, src_path_len=src_path_len,
                   type_code=type_code, ctime_unix=ctime_unix, mtime_unix=mtime_unix,
                   flags=flags, name_hash=name_hash)


def align_up(n: int, to: int = PAGE) -> int:
    return (n + to - 1) & ~(to - 1)
