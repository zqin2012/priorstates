"""Publisher identity + manifest signatures (the seed of hub reputation).

A `.pspack` manifest already commits to all content via per-file sha256.
Signing the manifest therefore authenticates the whole bundle: `install` can show
"signed by <handle>" (and warn loudly if a signature is present but invalid).

Ed25519 via the optional `cryptography` package (the `sign` extra). Everything
degrades gracefully: with the library absent you simply can't sign, and unsigned
bundles import exactly as before; a *signed* bundle on a machine without the
library reports "unverified (install the `sign` extra)" rather than failing.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

ALG = "ed25519"


def _crypto():
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ed25519
        return serialization, ed25519
    except Exception:
        return None, None


def available() -> bool:
    return _crypto()[0] is not None


def canonical_payload(manifest: dict) -> bytes:
    """Deterministic bytes signed/verified — the manifest minus its signature."""
    m = {k: v for k, v in manifest.items() if k != "signature"}
    return json.dumps(m, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _fingerprint(pub_b64: str) -> str:
    import hashlib
    return hashlib.sha256(pub_b64.encode()).hexdigest()[:16]


def identity_dir(config) -> Path:
    return config.home / "identity"


def load_or_create_identity(config, *, handle: str | None = None, create: bool = True) -> dict | None:
    """Return this machine's publisher identity, creating a keypair on first use.

    Returns ``{handle, pubkey, fingerprint}`` (private key stays on disk, mode
    600) or ``None`` if `cryptography` is unavailable.
    """
    serialization, ed25519 = _crypto()
    if serialization is None:
        return None
    d = identity_dir(config)
    priv_p, pub_p, handle_p = d / "ed25519.key", d / "ed25519.pub", d / "handle"
    if not priv_p.exists():
        if not create:
            return None
        d.mkdir(parents=True, exist_ok=True)
        key = ed25519.Ed25519PrivateKey.generate()
        priv_p.write_bytes(key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption()))
        try:
            priv_p.chmod(0o600)
        except OSError:
            pass
        pub_b = key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
        pub_p.write_text(base64.b64encode(pub_b).decode())
    if handle and not handle_p.exists():
        handle_p.write_text(handle.strip())
    pub_b64 = pub_p.read_text().strip()
    return {"handle": (handle_p.read_text().strip() if handle_p.exists() else (handle or "anonymous")),
            "pubkey": pub_b64, "fingerprint": _fingerprint(pub_b64)}


def set_handle(config, handle: str) -> None:
    (identity_dir(config) / "handle").write_text(handle.strip())


def sign_manifest(config, manifest: dict) -> dict | None:
    """Return a ``signature`` dict for `manifest`, or None if signing is impossible."""
    serialization, ed25519 = _crypto()
    if serialization is None:
        return None
    ident = load_or_create_identity(config)
    if ident is None:
        return None
    priv_raw = (identity_dir(config) / "ed25519.key").read_bytes()
    key = ed25519.Ed25519PrivateKey.from_private_bytes(priv_raw)
    sig = key.sign(canonical_payload(manifest))
    return {"alg": ALG, "handle": ident["handle"], "pubkey": ident["pubkey"],
            "fingerprint": ident["fingerprint"], "value": base64.b64encode(sig).decode()}


def verify_manifest(manifest: dict) -> tuple[str, str]:
    """Return ``(status, who)`` where status ∈ {unsigned, valid, invalid, unverified}.

    - unsigned   — no signature present.
    - valid      — signature verifies against its embedded pubkey.
    - invalid    — signature present but does NOT verify (tampered / wrong key).
    - unverified — signature present but `cryptography` isn't installed here.
    """
    sig = manifest.get("signature")
    if not sig:
        return "unsigned", ""
    who = f"{sig.get('handle', 'anonymous')} ({sig.get('fingerprint', '?')})"
    serialization, ed25519 = _crypto()
    if serialization is None:
        return "unverified", who
    try:
        pub = ed25519.Ed25519PublicKey.from_public_bytes(base64.b64decode(sig["pubkey"]))
        pub.verify(base64.b64decode(sig["value"]), canonical_payload(manifest))
        return "valid", who
    except Exception:
        return "invalid", who
