"""Durable-write helpers shared by the data-file writers.

Two guarantees, both aimed at surviving a crash (or `kill -9`) mid-write:

* **Atomic text/YAML writes** (`atomic_write_text`): write the full payload to a
  sibling ``<file>.tmp``, flush + fsync it, then ``os.replace()`` it over the
  target. ``os.replace`` is atomic on POSIX and Windows, so a concurrent reader
  sees either the old file or the new file in full — never a truncated one. If
  the process dies before the replace, the previous good file is untouched.

* **Durable JSONL appends** (`append_jsonl`): append one record, then flush and
  fsync so the line is on disk before the call returns. Appends can't be atomic
  the way a whole-file replace is, but fsync guarantees a committed record isn't
  lost to a power cut, and a single ``write`` of ``json.dumps(...) + "\\n"`` won't
  interleave a partial line under normal (single-writer) use.

Kept dependency-free (stdlib only) so every layer can import it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Optional, Union

_PathLike = Union[str, os.PathLike]


def atomic_write_text(path: _PathLike, text: str, *, encoding: str = "utf-8") -> None:
    """Write ``text`` to ``path`` atomically via a ``<file>.tmp`` + ``os.replace``."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "w", encoding=encoding) as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)


def append_jsonl(
    path: _PathLike,
    record: Any,
    *,
    default: Optional[Callable[[Any], Any]] = None,
) -> None:
    """Append one JSON record as a line to ``path``, fsync'd before returning.

    ``default`` is forwarded to ``json.dumps`` (pass ``str`` to coerce
    non-serialisable values, matching the previous inline call sites).
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=default) + "\n")
        f.flush()
        os.fsync(f.fileno())
