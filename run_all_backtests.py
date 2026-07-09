import sys, os
sys.stdout.reconfigure(encoding='utf-8')
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from backtest.engine import BacktestEngine

strategies = ['first_candle', 'orb15', 'rsi_reversal', 'ema_trend', 'gap_direction']
results = []

for s in strategies:
    print('\n' + '='*60)
    print('STRATEGY: ' + s)
    print('='*60)
    engine = BacktestEngine(use_ai_brain=False)
    result = engine.run('NIFTY', '2026-05-26', '2026-06-26', {
        'strategy': s,
        'max_trades_per_day': 2,
    })
    results.append(result)
    result.print_report()

print('\n\n' + '='*70)
print('COMPARISON SUMMARY')
print('='*70)
print('{:<35} {:>6} {:>8} {:>10} {:>6}'.format('Strategy', 'Trades', 'WinRate', 'P&L', 'PF'))
print('-'*70)
for r in results:
    print('{:<35} {:>6} {:>7.1f}% {:>10,.0f} {:>6.2f}'.format(
        r.strategy, r.total_trades, r.win_rate, r.total_pnl, r.profit_factor))
