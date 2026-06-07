"""Local 'answer' AI for chat-with-your-memory.

The chat answer is synthesized **on this machine** (where the relay agent runs),
using an AI the user configures in the desktop app — never a key shipped to the
hub. Config lives in `~/.priorstates/ai.json`:

    {"provider": "anthropic|openai|ollama|claude_cli",
     "model": "...", "api_key": "...", "base_url": "...", "command": "claude"}

Providers:
- anthropic / openai : hosted API over stdlib urllib (api_key required).
- ollama            : a local model server (base_url, default localhost:11434).
- claude_cli        : shell out to the Claude Code CLI on this machine (no key).

All stdlib — no extra dependencies.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from pathlib import Path

_DEFAULT_MODELS = {
    "anthropic": "claude-3-5-haiku-latest",
    "openai": "gpt-4o-mini",
    "ollama": "llama3.1",
}
_SYSTEM = ("You answer the user's question using ONLY the memory and journal context "
           "below. Be concise and specific. If the answer isn't in the context, say you "
           "don't have it in memory — don't invent facts.")


def ai_path(cfg) -> Path:
    return Path(cfg.home) / "ai.json"


def load_ai(cfg) -> dict:
    try:
        return json.loads(ai_path(cfg).read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_ai(cfg, data: dict) -> None:
    p = ai_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        tmp.chmod(0o600)                      # holds an API key
    except OSError:
        pass
    os.replace(tmp, p)


def configured(cfg, ai: dict | None = None) -> bool:
    ai = load_ai(cfg) if ai is None else ai
    prov = (ai or {}).get("provider")
    if prov in ("ollama", "claude_cli"):
        return True
    if prov in ("anthropic", "openai"):
        return bool(ai.get("api_key"))
    return False


def build_context(mems: list, jr: list) -> str:
    ctx = "".join(f"## {m.get('name')}\n{m.get('description', '')}\n{m.get('body', '')}\n\n"
                  for m in (mems or [])[:8])
    ctx += "".join(f"## (journal) {j.get('title') or j.get('topic') or j.get('name')}\n{j.get('body', '')}\n\n"
                   for j in (jr or [])[:4])
    return ctx


def _post_json(url: str, payload: dict, headers: dict, timeout: int = 90) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310 (user-configured endpoint)
        return json.loads(r.read().decode("utf-8"))


def answer(cfg, question: str, context: str, ai: dict | None = None) -> str:
    """Synthesize an answer from `context` using the locally configured AI."""
    ai = load_ai(cfg) if ai is None else ai
    prov = (ai or {}).get("provider")
    model = (ai or {}).get("model") or _DEFAULT_MODELS.get(prov, "")
    prompt = f"CONTEXT:\n{context}\n\nQUESTION: {question}"
    if not configured(cfg, ai):
        raise RuntimeError("no AI configured")

    if prov == "anthropic":
        d = _post_json("https://api.anthropic.com/v1/messages",
                       {"model": model, "max_tokens": 1024, "system": _SYSTEM,
                        "messages": [{"role": "user", "content": prompt}]},
                       {"x-api-key": ai["api_key"], "anthropic-version": "2023-06-01"})
        return "".join(b.get("text", "") for b in d.get("content", [])).strip()

    if prov == "openai":
        base = (ai.get("base_url") or "https://api.openai.com").rstrip("/")
        d = _post_json(f"{base}/v1/chat/completions",
                       {"model": model, "messages": [{"role": "system", "content": _SYSTEM},
                                                     {"role": "user", "content": prompt}]},
                       {"Authorization": "Bearer " + ai["api_key"]})
        return (d["choices"][0]["message"]["content"] or "").strip()

    if prov == "ollama":
        base = (ai.get("base_url") or "http://localhost:11434").rstrip("/")
        d = _post_json(f"{base}/api/chat",
                       {"model": model, "stream": False,
                        "messages": [{"role": "system", "content": _SYSTEM},
                                     {"role": "user", "content": prompt}]}, {})
        return (d.get("message", {}).get("content") or "").strip()

    if prov == "claude_cli":
        cmd = (ai.get("command") or "claude").split()
        out = subprocess.run(cmd + ["-p", _SYSTEM + "\n\n" + prompt],
                             capture_output=True, text=True, timeout=120)
        if out.returncode != 0:
            raise RuntimeError((out.stderr or "claude CLI failed").strip()[:300])
        return out.stdout.strip()

    raise RuntimeError(f"unknown AI provider: {prov!r}")
