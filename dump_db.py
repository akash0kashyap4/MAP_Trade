import sqlite3

db = sqlite3.connect('trading_bot.db')
db.row_factory = sqlite3.Row

trades = db.execute('SELECT * FROM trades ORDER BY entry_time').fetchall()
print(f'=== TRADES ({len(trades)} total) ===')
for t in trades:
    t = dict(t)
    etime = str(t.get('entry_time') or '')[:16]
    print(f"  {etime} | {t.get('instrument')} | {t.get('action')} | strike={t.get('strike')} | entry={t.get('entry_price')} | exit={t.get('exit_price')} | pnl={t.get('pnl_final')} | reason={t.get('exit_reason')} | conf={t.get('confidence')}")

total_sigs = db.execute('SELECT COUNT(*) FROM signals').fetchone()[0]
sigs = db.execute('SELECT * FROM signals ORDER BY timestamp DESC LIMIT 30').fetchall()
print(f'\n=== SIGNALS ({total_sigs} total, last 30) ===')
for s in sigs:
    s = dict(s)
    ts = str(s.get('timestamp') or '')[:16]
    reason = str(s.get('reason') or '')[:100]
    print(f"  {ts} | {s.get('instrument')} | {s.get('action')} | conf={s.get('confidence')} | {reason}")

total_rules = db.execute('SELECT COUNT(*) FROM learning_rules').fetchone()[0]
rules_rows = db.execute('SELECT * FROM learning_rules ORDER BY updated_at DESC LIMIT 3').fetchall()
print(f'\n=== LEARNING RULES ({total_rules} versions) ===')
for r in rules_rows:
    r = dict(r)
    ts = str(r.get('updated_at') or '')[:16]
    print(f"  {ts} | win_rate={r.get('win_rate')} | sharpe={r.get('sharpe')}")
    print(f"  Rules: {str(r.get('rules'))[:600]}")

total_bt = db.execute('SELECT COUNT(*) FROM backtest_runs').fetchone()[0]
bt_rows = db.execute('SELECT * FROM backtest_runs ORDER BY run_at DESC LIMIT 5').fetchall()
print(f'\n=== BACKTEST RUNS ({total_bt} total) ===')
for b in bt_rows:
    b = dict(b)
    ts = str(b.get('run_at') or '')[:16]
    cfg = str(b.get('config') or '')[:200]
    print(f"  {ts} | trades={b.get('total_trades')} | win_rate={b.get('win_rate')} | pf={b.get('profit_factor')} | sharpe={b.get('sharpe')}")
    print(f"  Config: {cfg}")

db.close()
