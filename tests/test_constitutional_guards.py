"""CI enforcement of the hard constitutional rules from SYSTEM_AUDIT_2026-05-25.md §1.

THESE TESTS ARE THE ENFORCEMENT MECHANISM. They replace the by-hand §1 audit with
something CI runs every time. They must NEVER be skipped, xfailed, or weakened to
make a change pass — a failure here means a hard rule (no broker integration, no
real orders, swing-bot ringfence, locked configs) has been breached, and the change
must be fixed, not the test. Diagnostic/read-only: they inspect the tree, never edit it.
"""
import ast
import subprocess
import sys
from pathlib import Path

import re
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.governance.constitution import _validate_hard_booleans  # reuse the real validator

# Broker / live-trading libraries that must never appear anywhere in this repo.
BROKER_LIBS = {
    "trading212", "alpaca", "ib_insync", "ibapi", "schwab", "robin_stocks", "ccxt",
}

AGENT_CODE_DIRS = ["src", "scripts"]
SWINGBOT_CODE_DIRS = ["swing-bot/src", "swing-bot/scripts"]
REQUIREMENTS_FILES = ["requirements.txt", "swing-bot/requirements.txt"]


def _py_files(*rel_dirs) -> list[Path]:
    files: list[Path] = []
    for rel in rel_dirs:
        d = ROOT / rel
        if d.exists():
            files.extend(p for p in d.rglob("*.py") if "__pycache__" not in p.parts)
    return files


def _imported_names(path: Path) -> list[str]:
    """Every dotted module name imported by a file (AST-based)."""
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


# ─── 1. No broker libraries anywhere ─────────────────────────────────────────

def test_no_broker_library_imports():
    offenders = []
    for path in _py_files(*AGENT_CODE_DIRS, *SWINGBOT_CODE_DIRS):
        for mod in _imported_names(path):
            top = mod.split(".")[0]
            if top in BROKER_LIBS or any(lib in mod for lib in BROKER_LIBS):
                offenders.append(f"{path.relative_to(ROOT)}: imports {mod}")
    assert not offenders, "broker library import(s) found:\n" + "\n".join(offenders)


def test_no_broker_library_in_requirements():
    offenders = []
    for rel in REQUIREMENTS_FILES:
        p = ROOT / rel
        if not p.exists():
            continue
        for line in p.read_text().splitlines():
            name = line.strip().split("#")[0].strip().lower()
            token = name.replace("_", "").replace("-", "")
            for lib in BROKER_LIBS:
                if token.startswith(lib.replace("_", "")):
                    offenders.append(f"{rel}: {line.strip()}")
    assert not offenders, "broker library in requirements:\n" + "\n".join(offenders)


# ─── 2. swing-bot ↔ agent ringfence (no cross-imports either direction) ──────

def _module_names(rel_dir: str) -> set[str]:
    d = ROOT / rel_dir
    if not d.exists():
        return set()
    return {p.stem for p in d.iterdir() if p.suffix == ".py"} | {
        p.name for p in d.iterdir() if p.is_dir() and p.name != "__pycache__"}


def test_swingbot_and_agent_are_ringfenced():
    agent_mods = _module_names("src")
    swing_mods = _module_names("swing-bot/src")
    offenders = []

    # agent code must not reach into swing-bot
    for path in _py_files(*AGENT_CODE_DIRS):
        for mod in _imported_names(path):
            if "swing" in mod.lower():
                offenders.append(f"{path.relative_to(ROOT)} → {mod} (agent imports swing-bot)")
            seg = mod.split(".")
            if seg[0] == "src" and len(seg) > 1 and seg[1] in (swing_mods - agent_mods):
                offenders.append(f"{path.relative_to(ROOT)} → {mod} (agent imports swing-bot module)")

    # swing-bot code must not reach into the agent's src
    for path in _py_files("swing-bot/src", "swing-bot/scripts"):
        for mod in _imported_names(path):
            seg = mod.split(".")
            if seg[0] == "src" and len(seg) > 1 and seg[1] in (agent_mods - swing_mods):
                offenders.append(f"{path.relative_to(ROOT)} → {mod} (swing-bot imports agent module)")

    assert not offenders, "ringfence breach:\n" + "\n".join(offenders)


# ─── 2b. Phaethon (LLM idea-generator) firewall ──────────────────────────────

# Live P&L / fills artifacts an LLM agent must never see (NO_LIVE_PNL_LEARNING).
LIVE_PNL_ARTIFACTS = ["fills.jsonl", "data/live/", "realized_pnl", "live_pnl", "book.json"]


def test_phaethon_does_not_import_engine_or_signals():
    """src/phaethon must not reach into the rating engine or signals (isolation)."""
    offenders = []
    for path in _py_files("src/phaethon"):
        for mod in _imported_names(path):
            seg = mod.split(".")
            if seg[:2] in (["src", "engine"], ["src", "signals"]):
                offenders.append(f"{path.relative_to(ROOT)} → {mod}")
    assert not offenders, "phaethon imports engine/signals:\n" + "\n".join(offenders)


def test_phaethon_no_live_pnl_read_in_prompt_paths():
    """CRITICAL NO_LIVE_PNL_LEARNING firewall: no code under src/phaethon reads a live
    P&L / fills artifact. The Phaethon generator is an LLM agent — if a live-outcome file
    reached any prompt-construction path it would learn from realized P&L. src/phaethon
    only renders already-computed *public* scorecard state; it must never open live P&L.
    (Note: book.json here is the trader's holdings-state input read by the frozen render;
    it is the public book snapshot, but we still forbid live *fills/pnl* artifacts.)"""
    offenders = []
    for path in _py_files("src/phaethon"):
        text = path.read_text()
        for token in ("fills.jsonl", "data/live/", "realized_pnl", "live_pnl", "/pnl"):
            if token in text:
                offenders.append(f"{path.relative_to(ROOT)} references {token}")
    assert not offenders, "phaethon touches live P&L artifacts:\n" + "\n".join(offenders)


# ─── 2c. Phaethon LEARNING mechanism firewall (OUTCOME_LEARNING_VIA_BOUNDARY_ONLY) ──

# Human-side learning machinery — must be unreachable from any code that builds what
# Phaethon actually sees. (journal is the human-side source these read.)
LEARNING_MODULES = {"review_trigger", "lessons_ledger", "prediction_resolution",
                    "learning_kill_switch", "journal", "stage0_bridge"}
# Phaethon-facing output / would-be context-builder modules.
PHAETHON_FACING = {"publish", "scorecard", "governance", "schema", "ledger"}


def _phaethon_import_graph():
    graph = {}
    for path in _py_files("src/phaethon"):
        deps = set()
        for name in _imported_names(path):
            parts = name.split(".")
            if parts[:2] == ["src", "phaethon"] and len(parts) >= 3:
                deps.add(parts[2])
        graph[path.stem] = deps
    return graph


def test_learning_modules_unreachable_from_phaethon_facing_code():
    """AST/import-graph: no Phaethon-facing (or future context-builder) module can reach
    any learning module — the outcome-learning channel never touches live context."""
    graph = _phaethon_import_graph()
    facing = {m for m in graph if m in PHAETHON_FACING
              or any(k in m for k in ("evidence", "context", "prompt"))}
    reachable, stack = set(), list(facing)
    while stack:
        for d in graph.get(stack.pop(), ()):
            if d not in reachable:
                reachable.add(d); stack.append(d)
    breach = reachable & LEARNING_MODULES
    assert not breach, f"Phaethon-facing code can reach learning modules: {sorted(breach)}"


def test_phaethon_facing_never_reads_registry_state():
    """B-22 / §G-6 one-way bridge: the Phaethon → Stage-0 extractor writes registration
    *candidates* out; NOTHING that builds what Phaethon sees may read registry state, a
    Stage result, retired.yaml, or the candidates directory back in. Scanned on the
    Phaethon-facing modules only (stage0_bridge itself legitimately writes candidates;
    journal legitimately imports the hash-chain primitives)."""
    readback_tokens = ("stage0_candidates", "registry.yaml", "retired.yaml",
                       "load_registry", "load_registry_raw", "Stage1Result",
                       "stage_result", "queue_priority", "correction_m")
    offenders = []
    for name in PHAETHON_FACING:
        p = ROOT / "src" / "phaethon" / f"{name}.py"
        if not p.exists():
            continue
        text = p.read_text()
        for tok in readback_tokens:
            if tok in text:
                offenders.append(f"{name}.py references registry-state token {tok!r}")
    assert not offenders, ("Phaethon-facing code reads registry state (breaks the one-way "
                           "Stage-0 bridge):\n" + "\n".join(offenders))


def test_stage0_bridge_is_one_way_and_not_phaethon_facing():
    """stage0_bridge must not import anything Phaethon-facing (it is human-side output,
    like journal), and must not import a registry-STATE reader."""
    p = ROOT / "src" / "phaethon" / "stage0_bridge.py"
    assert p.exists(), "src/phaethon/stage0_bridge.py missing (B-22)"
    imported = set(_imported_names(p))
    facing_hit = {m for m in imported
                  if m.split(".")[:2] == ["src", "phaethon"]
                  and m.split(".")[-1] in PHAETHON_FACING}
    assert not facing_hit, f"stage0_bridge imports Phaethon-facing modules: {sorted(facing_hit)}"
    state_readers = {"load_registry", "load_registry_raw", "load_registry_resolved",
                     "queue", "registry_stats"}
    text = p.read_text()
    assert not (state_readers & set(re.findall(r"\b\w+\b", text))), \
        "stage0_bridge references a registry-state reader — the bridge is write-only"


def test_learning_modules_write_only_human_side():
    """The ledger/report never write into docs/data (the dashboard/panel Phaethon-facing
    path) or an evidence pack — only data/phaethon + runs/phaethon (human-side)."""
    for name in LEARNING_MODULES:
        p = ROOT / "src" / "phaethon" / f"{name}.py"
        if p.exists():
            text = p.read_text()
            assert "docs/data" not in text, f"{name} writes to a Phaethon-facing path (docs/data)"
            assert "evidence_pack" not in text, f"{name} references evidence_pack"


# ─── 2d. Live-pilot guard layer firewall ─────────────────────────────────────

def test_live_layer_no_broker_and_no_decision_math():
    """src/live holds NO broker libraries and imports NO decision math (engine/signals)
    — it only guards; it must not touch the rating/signal machinery."""
    offenders = []
    for path in _py_files("src/live"):
        for mod in _imported_names(path):
            top = mod.split(".")[0]
            if top in BROKER_LIBS or any(lib in mod for lib in BROKER_LIBS):
                offenders.append(f"{path.relative_to(ROOT)}: broker import {mod}")
            if mod.split(".")[:2] in (["src", "engine"], ["src", "signals"]):
                offenders.append(f"{path.relative_to(ROOT)}: imports decision math {mod}")
    assert not offenders, "live-layer guard breach:\n" + "\n".join(offenders)


# ─── 3. deploy.sh trading-droplet guards ─────────────────────────────────────

def test_deploy_sh_has_both_trading_guards():
    text = (ROOT / "scripts" / "deploy.sh").read_text()
    assert '"${DROPLET_HOST}" == *"trading"*' in text, "missing DROPLET_HOST trading guard"
    assert '"${REMOTE_HOSTNAME}" == *"trading"*' in text, "missing REMOTE_HOSTNAME trading guard"


# ─── 4. constitution hard booleans all True ──────────────────────────────────

def test_constitution_hard_booleans_all_true():
    cfg = yaml.safe_load((ROOT / "config" / "constitution.yaml").read_text())
    _validate_hard_booleans(cfg)   # raises ConstitutionalViolation if any is not True


# ─── 5. swing-bot place_real_order still raises (import in isolation) ─────────

def test_swingbot_place_real_order_raises():
    code = (
        "import sys; sys.path.insert(0, 'swing-bot')\n"
        "from src.paper_executor import place_real_order\n"
        "try:\n"
        "    place_real_order('AAPL', 1, 1)\n"
        "    print('NO_RAISE')\n"
        "except RuntimeError:\n"
        "    print('RAISED')\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                         capture_output=True, text=True)
    assert "RAISED" in out.stdout, f"place_real_order did not raise: {out.stdout}{out.stderr}"


# ─── 6. locked configs report locked: true ───────────────────────────────────

def test_locked_configs_report_locked_true():
    for rel in ["gaia/rules.yaml", "config/protocol_lock.yaml"]:
        cfg = yaml.safe_load((ROOT / rel).read_text())
        assert cfg.get("locked") is True, f"{rel} is not locked: true"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("All constitutional guards passed.")
