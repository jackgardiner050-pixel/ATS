"""Shared helpers for scripts/ — logging prefix, nothing else.

The goal is a uniform, greppable log format across every CLI entry point:

    [2026-07-05T14:03:11] [run_universe] Screening universe: 147 tickers ...

without restructuring any script's logic. A script opts in with two lines placed
after its sys.path bootstrap:

    from scripts._common import get_print
    print = get_print(__file__)          # noqa: A001 — intentional module-level shadow

`get_print` returns a drop-in replacement for the builtin `print` (same
signature: *args, sep, end, file, flush). It prefixes each *output line* — the
prefix is emitted only at the start of a line, so multi-call progress output
such as `print("AGX...", end=" ")` followed by `print("STRONG_BUY")` still
renders as a single prefixed line rather than two half-lines.

Import note: `scripts` is an implicit namespace package, so `from scripts._common
import get_print` resolves whenever the repo root is on sys.path — which every
entry point already arranges via `sys.path.insert(0, <repo root>)`.
"""
from __future__ import annotations

import builtins
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable


def iso_now() -> str:
    """Local ISO-8601 timestamp to the second (no microseconds)."""
    return datetime.now().replace(microsecond=0).isoformat()


def script_name(script_file: str) -> str:
    """Derive the log label from a script's __file__ (basename without .py)."""
    return Path(script_file).stem


def log_prefix(name: str) -> str:
    return f"[{iso_now()}] [{name}] "


def get_print(script_file: str) -> Callable[..., None]:
    """Return a builtin-`print`-compatible callable that prefixes each line.

    Assign it to the module global `print` at the top of a script to prefix all
    of that script's output. State (whether we are mid-line) is captured per
    returned callable, so interleaved `end=`-continuation prints stay on one
    visual line with a single prefix.
    """
    name = script_name(script_file)
    real_print = builtins.print
    state = {"at_line_start": True}

    def _print(*args, sep: str = " ", end: str = "\n", file=None, flush: bool = False) -> None:
        stream = file if file is not None else sys.stdout
        text = sep.join(str(a) for a in args) + end
        prefix = log_prefix(name)
        out: list[str] = []
        for ch in text:
            if state["at_line_start"] and ch != "\n":
                out.append(prefix)
                state["at_line_start"] = False
            out.append(ch)
            if ch == "\n":
                state["at_line_start"] = True
        real_print("".join(out), sep="", end="", file=stream, flush=flush)

    return _print
