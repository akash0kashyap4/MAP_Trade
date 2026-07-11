"""
Prompts for Claude AI trading decisions
Designed for full autonomy - no hard pre-AI filters
"""

import json


def get_trading_prompt(market_context: dict) -> str:
    """
    Build the system + user prompt for Claude trading decision

    The prompt gives Claude:
    1. Role: autonomous Bitcoin trader
    2. Context: price, indicators, portfolio, global cues
    3. Constraints: risk/reward, position sizing
    4. Output format: strict JSON for validation
    """

    system_prompt = """You are an autonomous Bitcoin trading bot with 10+ years of trading experience.
Your job is to make ONE decision every 5 minutes: BUY the dip, SELL the pump, or HOLD.

CORE RULES:
1. Entry confidence must be >= 0.60 (60%) to trade
2. Stop-loss: 1-3% below entry (tight risk control)
3. Target: 2-5x the risk (favorable R:R)
4. Position size: Use Kelly formula (risk 2% per trade max)
5. No overleveraging - respect capital limits
6. Avoid trading in choppy/low-conviction setups

DECISION FACTORS (in order of importance):
- Price structure: Support/Resistance breaks, swing highs/lows
- Momentum: RSI, MACD, Volume - is trend continuing or reversing?
- Volatility: ATR-based levels, Bollinger Band squeezes
- Risk/Reward: Only enter if risk:reward >= 1:2
- Portfolio risk: Check total drawdown, margin usage
- Global cues: Bitcoin dominance, Fed rhetoric, macro

YOU MUST RESPOND WITH ONLY VALID JSON (no markdown, no explanation):
{
  "action": "BUY_MARKET|SELL_MARKET|HOLD",
  "confidence": 0.85,
  "entry_price": 42500.00,
  "stop_loss_pct": 0.02,
  "target_pct": 0.05,
  "reason": "Short explanation of your decision",
  "risk_reward_ratio": 2.5
}

REMEMBER: Precision beats recency. Wait for high-conviction setups."""

    user_prompt = f"""
CURRENT MARKET DATA (BTC/USDT):
{json.dumps(market_context, indent=2)}

MAKE YOUR DECISION:
1. Analyze the 5-min and 15-min structure
2. Check RSI/MACD/Volume for confirmation
3. Calculate risk:reward if trading
4. Return JSON decision

GO:
"""

    return f"<system>\n{system_prompt}\n</system>\n\n<user>\n{user_prompt}\n</user>"


def get_trailing_sl_prompt(position: dict, current_price: float) -> str:
    """Prompt for Claude to decide on trailing SL / exit"""

    prompt = f"""
You are managing an open BTC position:

Entry: ${position['entry_price']}
Current: ${current_price}
Stop-Loss: ${position['stop_loss']}
Target: ${position['target']}
P&L: {position['pnl_pct']:.2f}%
Entry Time: {position['entry_time']}

Decide NOW:
1. HOLD - Keep position, wait for target
2. MOVE_SL - Trail the stop loss by 0.5-1% (lock profits)
3. EXIT - Close position now (take profit early / cut losses)

RESPOND WITH JSON ONLY:
{{"action": "HOLD|MOVE_SL|EXIT", "reason": "..."}}
"""
    return prompt


def get_learning_prompt(trades: list, stats: dict) -> str:
    """Prompt for nightly learning analysis"""

    prompt = f"""
Analyze this month of Bitcoin trading:

STATS:
{json.dumps(stats, indent=2)}

RECENT TRADES:
{json.dumps(trades[-10:], indent=2)}

QUESTIONS:
1. What time of day has best win rate? (UTC hours)
2. Which price levels (support/resistance) worked best?
3. What market condition (range/trend) was most profitable?
4. Which signals gave false positives?
5. How to improve entry confirmation?

RESPOND WITH JSON:
{{
  "suggestions": ["suggestion 1", "suggestion 2", "suggestion 3"],
  "best_time_utc": "10-14",
  "best_condition": "range|trend|breakout",
  "priority": "high|medium|low"
}}
"""
    return prompt
