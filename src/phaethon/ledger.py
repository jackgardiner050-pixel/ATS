"""Phaethon cash-ledger reconstruction — the fix for arm B's cash-accounting bug.

DIAGNOSIS (see docs/PHAETHON_ARM_B_LEDGER_MEMO.md): the trader sizes each buy as a
target %-of-NAV weight and debits cash on the fill, but never caps cumulative buys
against *remaining available cash*. Arm B's 06-24 batch reached ~100% invested; the
06-29 rebalance then added 5 more positions sized against full NAV, funded by driving
cash negative → 138% gross exposure, cash_pct −38%.

THE FIX (this module, scorecard-layer — the trader strategy is FROZEN and untouched):
process fills in order and REJECT any buy that would breach available cash, so cash
never goes below 0 and gross exposure stays ≤ 100%. This is the "reject/flag an order
that would breach available cash rather than silently proceeding" remedy.
"""
from __future__ import annotations


def reconstruct_ledger(starting_cash: float, buys: list[dict]) -> dict:
    """Replay buys in order with a hard available-cash cap. Returns
    {cash, accepted, rejected}. A buy whose cost exceeds current cash is REJECTED
    (flagged) — not silently executed into negative cash.

    Each buy: {ticker, shares, price, ...(extra keys preserved)}.
    """
    cash = float(starting_cash)
    accepted: list[dict] = []
    rejected: list[dict] = []
    for b in buys:
        cost = b["shares"] * b["price"]
        if cost > cash + 1e-9:
            rejected.append({**b, "reject_reason":
                             f"would breach cash: cost {cost:.2f} > available {cash:.2f}"})
            continue
        cash -= cost
        accepted.append(b)
    return {"cash": round(cash, 2), "accepted": accepted, "rejected": rejected}


def restate_book(book: dict, starting_cash: float | None = None) -> tuple[dict, list[dict]]:
    """Rebuild a book with the cash-cap fix applied. Orders the holdings by entry_date
    (then original order — a stable proxy for fill order), replays with the cap, and
    returns (corrected_book, rejected_holdings). corrected_book has cash ≥ 0 and total
    invested ≤ starting capital → gross exposure ≤ 100%.

    starting_cash defaults to the implied initial capital = book.cash + Σ(shares·entry).
    """
    items = list(book["holdings"].items())
    buys = []
    for i, (t, h) in enumerate(items):
        price = h.get("entry_price") or h.get("cost_basis") or 0
        buys.append({"ticker": t, "shares": h["shares"], "price": price,
                     "entry_date": h.get("entry_date") or "", "_i": i, "_h": h})
    if starting_cash is None:
        starting_cash = round(book.get("cash", 0) + sum(b["shares"] * b["price"] for b in buys), 2)

    buys.sort(key=lambda b: (b["entry_date"], b["_i"]))
    led = reconstruct_ledger(starting_cash, buys)

    corrected = {**{k: v for k, v in book.items() if k != "holdings"},
                 "cash": led["cash"],
                 "holdings": {b["ticker"]: b["_h"] for b in led["accepted"]}}
    rejected = [{"ticker": b["ticker"], "entry_notional": round(b["shares"] * b["price"], 2),
                 "reason": b["reject_reason"]} for b in led["rejected"]]
    return corrected, rejected
