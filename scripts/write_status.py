#!/usr/bin/env python3
"""Write STATUS.txt after a run. Called by cron after paper_run.py."""
import json, sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.paper_trading import load_positions, load_trades, fetch_spy_price

runs_root = Path(__file__).parent.parent / 'runs' / '_screen'
dirs = sorted(d for d in runs_root.iterdir() if d.is_dir()) if runs_root.exists() else []
summary_path = (dirs[-1] / 'summary.json') if dirs else None

dist = Counter()
n_screened = 0
if summary_path and summary_path.exists():
    with open(summary_path) as f:
        data = json.load(f)
    n_screened = data['stats']['screened']
    for r in data['results']:
        if r.get('ok') and r.get('rating') not in ('?', 'ERROR', None):
            dist[r['rating']] += 1

positions = load_positions()
trades = load_trades()
spy = fetch_spy_price() or 0.0

# Unrealised book mark
unrealised_rets = []
for pos in positions.values():
    ep = pos['entry_price']
    # Approximate with entry price only (no live fetch here — keep status write fast)
    unrealised_rets.append(0.0)

n_trades = len(trades)
avg_alpha = sum(t['alpha'] for t in trades) / n_trades if n_trades else 0.0

status = (
    f'Agent ran {date.today()}.\n'
    f'{n_screened} tickers screened.\n'
    f'Distribution: SB={dist["STRONG_BUY"]} B={dist["BUY"]} H={dist["HOLD"]} '
    f'S={dist["SELL"]} SS={dist["STRONG_SELL"]}.\n'
    f'Paper book: {len(positions)} open positions. '
    f'Closed trades: {n_trades}, avg alpha {avg_alpha*100:+.2f}%.\n'
    f'SPY: ${spy:.2f}\n'
)
out = Path(__file__).parent.parent / 'STATUS.txt'
out.write_text(status)
print(status.strip())
