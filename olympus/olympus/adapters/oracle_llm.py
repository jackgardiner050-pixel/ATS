"""Oracle causal-reasoning LLM bridge (Phase 6). RESEARCH-GRADE.

Drives Oracle's existing causal_sweep + thesis rubrics with an LLM to form a real thesis on a
naked ticker. Cost discipline: a CHEAP model does the bulk (triage), the DEEPER model is reserved
for the thesis step; results are cached per (ticker, date); call-count + estimated cost are tracked.

FAIL LOUD: if there is no API key, this raises OracleReasoningUnavailable. It NEVER silently falls
back to a data-only screen and pretends — that is the swallowed-error trap. The LLM client is
injectable so tests prove the path with a mock (no live key, no network).

The firewall (§B): the prompt is built from the bare ticker + PUBLIC context only. No momentum /
screener / discovery signal is ever placed in the prompt.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Optional

from olympus.core import config

CHEAP_MODEL = "claude-haiku-4-5"     # bulk / triage
DEEP_MODEL = "claude-sonnet-4-6"     # reserved for the thesis step only
# Approximate public $/Mtok (input, output) — for COST VISIBILITY only (clearly an estimate).
PRICES = {"claude-haiku-4-5": (1.0, 5.0), "claude-sonnet-4-6": (3.0, 15.0), "claude-opus-4-8": (15.0, 75.0)}
CACHE = config.DATA_DIR / "oracle_llm_cache.json"


class OracleReasoningUnavailable(RuntimeError):
    """Raised when the full Oracle cannot run (no API key, or a malformed/empty LLM result)."""


class CostTracker:
    def __init__(self):
        self.calls = self.in_tok = self.out_tok = 0
        self.usd = 0.0
        self.by_model: dict = {}

    def add(self, model: str, in_tok: int, out_tok: int) -> None:
        self.calls += 1
        self.in_tok += in_tok
        self.out_tok += out_tok
        pi, po = PRICES.get(model, (0.0, 0.0))
        cost = in_tok / 1e6 * pi + out_tok / 1e6 * po
        self.usd += cost
        m = self.by_model.setdefault(model, {"calls": 0, "usd": 0.0})
        m["calls"] += 1
        m["usd"] += cost

    def summary(self) -> dict:
        return {"llm_calls": self.calls, "input_tokens": self.in_tok, "output_tokens": self.out_tok,
                "estimated_usd": round(self.usd, 4),
                "by_model": {k: {"calls": v["calls"], "usd": round(v["usd"], 4)} for k, v in self.by_model.items()},
                "note": "estimated from approximate public per-token prices"}


def have_key() -> bool:
    import os
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def make_client():
    if not have_key():
        raise OracleReasoningUnavailable(
            "ANTHROPIC_API_KEY not set — Oracle causal reasoning is UNAVAILABLE. Refusing to fall "
            "back to a data-only screen and fake a thesis (the swallowed-error trap). Set "
            "ANTHROPIC_API_KEY to enable the full Oracle.")
    try:
        import anthropic
    except ImportError as e:                       # missing SDK is also fail-loud, never a fake
        raise OracleReasoningUnavailable(f"anthropic SDK not installed — Oracle unavailable ({e})") from e
    return anthropic.Anthropic()


def _call(client, model: str, system: str, user: str, max_tokens: int, tracker: Optional[CostTracker]) -> str:
    r = client.messages.create(model=model, max_tokens=max_tokens, system=system,
                               messages=[{"role": "user", "content": user}])
    text = "".join(getattr(b, "text", "") for b in r.content)
    u = getattr(r, "usage", None)
    if tracker is not None and u is not None:
        tracker.add(model, getattr(u, "input_tokens", 0) or 0, getattr(u, "output_tokens", 0) or 0)
    return text


def _cache() -> dict:
    try:
        return json.loads(CACHE.read_text()) if CACHE.exists() else {}
    except Exception:
        return {}


_SCHEMA = ('{"bias":"BUY|HOLD|SELL","conviction":0-100,"causal_thesis":"...",'
           '"evidence_labels":{"claim":"Evidence|Hypothesis|Assumption|Opinion|Unknown"},'
           '"priced_in_view":"...","catalyst":{"desc":"...","when":"...","near_term":true},'
           '"invalidation":{"line":"...","by_when":"..."},'
           '"overlap":{"is_more_ai":false,"diversifying":true,"text":"..."},'
           '"pillars":[{"pillar":"...","expectation":"..."}],"disconfirming_evidence":["..."],'
           '"target":"...","stop_exit":"...","horizon":"6-12 months","right_but_early_risk":"LOW|MED|HIGH"}')


def causal_thesis(ticker: str, public_ctx: str, *, client, tracker: Optional[CostTracker] = None,
                  cheap_model: str = CHEAP_MODEL, deep_model: str = DEEP_MODEL,
                  causal_sweep: str = "", thesis_rubric: str = "", use_cache: bool = True) -> dict:
    key = f"{ticker}:{date.today().isoformat()}"
    cache = _cache() if use_cache else {}
    if use_cache and key in cache:
        return cache[key]

    # 1. CHEAP triage (the bulk) — one-line non-consensus angle, no screener signal.
    triage = _call(client, cheap_model,
                   "You are Oracle's triage. In ONE sentence give the most plausible NON-CONSENSUS angle "
                   "for this name from the public context, or 'no angle'. You receive NO momentum/screener signal.",
                   f"Ticker: {ticker}\nPublic context:\n{public_ctx}", 200, tracker)

    # 2. DEEP thesis (only the thesis step uses the deeper model).
    system = ("You are Oracle, a causal-reasoning equity analyst (paper/advisory, research-grade). Follow the "
              "causal-sweep and thesis rubrics below. Reason ONLY from the public context — you did NOT receive any "
              "momentum/screener/discovery signal; form your own thesis. Down-weight consensus / already-priced "
              "ideas. A BUY or SELL needs real conviction + a falsifiable invalidation line + a near-term catalyst "
              "(no 'right but early'). Label each claim Evidence/Hypothesis/Assumption/Opinion/Unknown. Output ONLY a "
              "single valid JSON object — no markdown fences, no prose before or after, all strings on one line.")
    user = (f"RUBRICS:\n--- causal_sweep ---\n{causal_sweep[:3000]}\n--- thesis ---\n{thesis_rubric[:3000]}\n\n"
            f"TICKER: {ticker}\nTRIAGE ANGLE: {triage}\nPUBLIC CONTEXT:\n{public_ctx}\n\n"
            f"Return JSON exactly in this shape (keep it compact):\n{_SCHEMA}")
    raw = _call(client, deep_model, system, user, 2500, tracker)
    j = _parse(raw)
    if use_cache:
        cache[key] = j
        CACHE.write_text(json.dumps(cache, indent=2))
    return j


_GROWTH_SCHEMA = ('{"bias":"BUY|HOLD|SELL","conviction":0-100,"causal_thesis":"...",'
                  '"growth_durability":"durable|peaking|hype","growth_trend":"accelerating|steady|decelerating",'
                  '"quality":"high|medium|low","momentum_state":"confirming|neutral|rolling_over",'
                  '"bottleneck_angle":"...","evidence_labels":{"claim":"Evidence|Hypothesis|Assumption|Opinion|Unknown"},'
                  '"invalidation":{"line":"...","by_when":"..."},"target":"...","horizon":"6-12 months"}')


def growth_thesis(ticker: str, public_ctx: str, *, role: str = "leader", theme: str = "",
                  enabler: str = "", stage: str = "mid", client, tracker: Optional[CostTracker] = None,
                  cheap_model: str = CHEAP_MODEL, deep_model: str = DEEP_MODEL, use_cache: bool = True) -> dict:
    """GROWTH-mode thesis (v2). Consensus is FINE — conviction is durable/accelerating growth +
    quality + momentum + the bottleneck angle. The veto is NOT 'is it priced in' but 'is the growth
    REAL and DURABLE, or hype/peaking?'. CHEAP triage + DEEP thesis. Firewall: public context only."""
    key = f"growth:{ticker}:{role}:{date.today().isoformat()}"
    cache = _cache() if use_cache else {}
    if use_cache and key in cache:
        return cache[key]

    role_hint = (f"This name is tagged a SECOND-ORDER / BOTTLENECK enabler ({enabler}) in the '{theme}' "
                 f"value chain — judge whether it is a genuine at-scale / new-enabling-tech bottleneck."
                 if role == "bottleneck" else
                 f"This name is tagged an obvious LEADER in the '{theme}' theme — consensus leadership is "
                 f"FINE; judge the durability of its growth.")

    triage = _call(client, cheap_model,
                   "You are Oracle's GROWTH triage. In ONE sentence give the core growth+bottleneck angle "
                   "for this name from the public context (durable growth? key enabler?), or 'no angle'. "
                   "Consensus is fine — you receive NO momentum/screener signal.",
                   f"Ticker: {ticker} (role={role}, theme={theme})\n{role_hint}\nPublic context:\n{public_ctx}",
                   200, tracker)

    system = ("You are Oracle in GROWTH mode (paper/advisory, research-grade). Build conviction from "
              "DURABLE or ACCELERATING growth + quality (margins/returns/balance sheet) + confirming "
              "momentum + the bottleneck angle. CONSENSUS IS FINE — do NOT penalise a name for being "
              "well-owned or near its target; the question is NOT 'is it priced in' but 'is the growth "
              "REAL and DURABLE, or hype / peaking?'. Down-weight conviction hard if growth is peaking, "
              "hype-driven, or decelerating, or if momentum is rolling over. A BUY needs durable growth + "
              "a FALSIFIABLE invalidation line (growth-decel or momentum-break). Label each claim "
              "Evidence/Hypothesis/Assumption/Opinion/Unknown. Output ONLY a single valid JSON object — "
              "no markdown fences, no prose, all strings on one line.")
    user = (f"TICKER: {ticker}\nROLE: {role} · THEME: {theme} · STAGE: {stage}\n{role_hint}\n"
            f"GROWTH+BOTTLENECK ANGLE (triage): {triage}\nPUBLIC CONTEXT:\n{public_ctx}\n\n"
            f"Return JSON exactly in this shape (compact):\n{_GROWTH_SCHEMA}")
    raw = _call(client, deep_model, system, user, 2500, tracker)
    j = _parse(raw)
    if use_cache:
        cache[key] = j
        CACHE.write_text(json.dumps(cache, indent=2))
    return j


def _parse(raw: str) -> dict:
    """Extract the first balanced JSON object (respecting strings/escapes); fail loud, never fake."""
    import re
    t = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)   # strip a markdown fence if present
    if fence:
        t = fence.group(1).strip()
    start = t.find("{")
    if start < 0:
        raise OracleReasoningUnavailable(f"Oracle thesis returned non-JSON (cannot fake): {raw[:120]!r}")
    depth = 0; in_str = False; esc = False
    for i in range(start, len(t)):
        ch = t[i]
        if esc:
            esc = False; continue
        if ch == "\\":
            esc = True; continue
        if ch == '"':
            in_str = not in_str; continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(t[start:i + 1])
                except Exception as e:
                    raise OracleReasoningUnavailable(f"Oracle thesis JSON invalid (cannot fake): {e}") from e
    raise OracleReasoningUnavailable("Oracle thesis JSON was not balanced (cannot fake)")
