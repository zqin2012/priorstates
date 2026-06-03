"""mdlab — runnable Markdown, headless.

Parses ``*.mdlab.md`` (or any ``.md``) for fenced blocks, runs the runnable
ones (python/bash/journal/journal-search/prompt), and writes results back into
``<!-- priorstates:result ... -->`` regions. No VSCode, no kernel required (an
in-process Python executor is used; a Jupyter kernel is optional).
"""
from .parser import Block, parse_blocks, RUNNABLE  # noqa: F401
from .runner import run_file, run_block, block_hash  # noqa: F401
