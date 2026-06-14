# Local AI (private, on-machine answers)

PriorStates synthesizes chat-with-your-memory answers (and any other AI step) **on the
machine where your memory lives** — never by shipping your data or an API key off the
box. The recommended setup is a **local model via [ollama](https://ollama.com)**, so
your content never leaves the box and there's no per-call cost.

## Local-first by default

If a local **ollama** server is running and you haven't configured anything else,
PriorStates **uses it automatically** — no `ai.json` needed. An explicit `ai.json`
always takes precedence (so you can force a cloud provider if you prefer).

Resolution order (`core/ai.py: resolve_ai`):
1. `~/.priorstates/ai.json` if it names a `provider` → use it.
2. else, if `http://localhost:11434` answers → **auto-use ollama** (best installed model,
   preferring `qwen2.5` / `llama3.1` / `mistral` / `gemma` families).
3. else → no AI (recall still works; only the synthesized *answer* is unavailable).

## Set up ollama (one time)

```bash
curl -fsSL https://ollama.com/install.sh | sh      # installs + starts a local service
ollama pull qwen2.5:7b                              # ~4.7 GB; great at structured extraction, fits 8 GB VRAM
```

That's it — PriorStates will auto-detect it. To check what will be used:

```python
from priorstates.core.config import load_config
from priorstates.core import ai
print(ai.resolve_ai(load_config()))     # {'provider': 'ollama', 'model': 'qwen2.5:7b', ...}
```

### Model guidance

| VRAM | Good choice | Notes |
|---|---|---|
| 8 GB | `qwen2.5:7b` | strong at JSON/extraction; the default pick |
| 6 GB | `qwen2.5:3b` / `llama3.2:3b` | ~2x faster, lower recall |
| 12 GB+ | `qwen2.5:14b` | best local recall, slower |

First call after a model is idle loads it into VRAM (~tens of seconds); subsequent calls
are warm (~1–3 s). CPU-only works but is much slower — a small GPU is recommended.

## Explicit config (override the default)

Write `~/.priorstates/ai.json` (the desktop app → Connections → AI does this for you):

```jsonc
// local ollama, a specific model:
{ "provider": "ollama", "model": "qwen2.5:14b", "base_url": "http://localhost:11434" }

// cloud (best quality, but sends content + needs a key):
{ "provider": "anthropic", "model": "claude-3-5-haiku-latest", "api_key": "sk-…" }
{ "provider": "openai",    "model": "gpt-4o-mini",            "api_key": "sk-…" }
{ "provider": "deepseek",  "model": "deepseek-chat",          "api_key": "sk-…" }  // OpenAI-compatible; deepseek-reasoner for the reasoning tier

// shell out to the Claude Code CLI on this machine (no key in config):
{ "provider": "claude_cli", "command": "claude" }
```

`ai.json` is written `0600` (it can hold a key). An area can carry its own `ai.json`
at `~/.priorstates/areas/<area>/ai.json`, so each kind of work can use a different model.

## Privacy

- **ollama / claude_cli:** content stays on the machine.
- **anthropic / openai / deepseek:** the question + retrieved memory context are sent
  to that vendor (DeepSeek's API is hosted in the PRC — keep sensitive corpora local).

For sensitive corpora (corp email, strategy notes), prefer **local ollama** — it's the
default whenever it's available.
