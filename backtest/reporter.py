from __future__ import annotations
import csv
from colorama import Fore, Style


def print_backtest_report(result) -> None:
    sep = "=" * 70
    print(f"\n{Fore.CYAN}{sep}")
    print(f"  RAGI BACKTEST REPORT  --  {result.instrument}  {result.start_date} -> {result.end_date}")
    print(f"{sep}{Style.RESET_ALL}")

    def _row(label, value, color=Fore.WHITE):
        print(f"  {Fore.YELLOW}{label:<30}{color}{value}{Style.RESET_ALL}")

    _row("Total Trades",    result.total_trades)
    _row("Wins",            result.wins,      Fore.GREEN)
    _row("Losses",          result.losses,    Fore.RED)
    _row("Win Rate",        f"{result.win_rate:.1f}%",
         Fore.GREEN if result.win_rate >= 50 else Fore.RED)
    _row("Total P&L",       f"₹{result.total_pnl:,.0f}",
         Fore.GREEN if result.total_pnl >= 0 else Fore.RED)
    _row("SL Hits",         result.sl_hits)
    _row("Target Hits",     result.tgt_hits)
    _row("EOD Exits",       result.eod_exits)
    _row("Profit Factor",   f"{result.profit_factor:.2f}",
         Fore.GREEN if result.profit_factor >= 1 else Fore.RED)
    _row("Sharpe Ratio",    f"{result.sharpe_ratio:.2f}")
    _row("Max Drawdown",    f"₹{result.max_drawdown:,.0f}  ({result.max_drawdown_pct:.1f}%)", Fore.RED)
    if result.best_day:
        _row("Best Day",    f"{result.best_day[0]}  ₹{result.best_day[1]:,.0f}", Fore.GREEN)
    if result.worst_day:
        _row("Worst Day",   f"{result.worst_day[0]}  ₹{result.worst_day[1]:,.0f}", Fore.RED)

    print(f"\n{Fore.CYAN}  Win Rate by Day of Week:{Style.RESET_ALL}")
    for day, wr in result.win_rate_by_day_of_week.items():
        bar = "#" * int(wr / 5)
        print(f"    {day:<12} {wr:>5.1f}%  {Fore.GREEN}{bar}{Style.RESET_ALL}")

    if result.win_rate_by_hour:
        print(f"\n{Fore.CYAN}  Win Rate by Entry Hour:{Style.RESET_ALL}")
        for hr, wr in sorted(result.win_rate_by_hour.items()):
            bar = "#" * int(wr / 5)
            print(f"    {hr}:xx        {wr:>5.1f}%  {Fore.GREEN}{bar}{Style.RESET_ALL}")

    print(f"\n{Fore.CYAN}{sep}{Style.RESET_ALL}\n")


def export_to_csv(result, filename: str) -> None:
    if not result.trades:
        print("[reporter] No trades to export.")
        return
    fieldnames = list(result.trades[0].keys())
    with open(filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(result.trades)
    print(f"[reporter] Exported {len(result.trades)} trades -> {filename}")
