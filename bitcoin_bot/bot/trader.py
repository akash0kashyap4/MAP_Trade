"""
Live Trading Engine
Handles entry, exit, trailing stops, and position management
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class LiveTrader:
    """Main trading loop coordinator"""

    def __init__(self, exchange, db, ai_agent, config: Dict):
        self.exchange = exchange
        self.db = db
        self.ai_agent = ai_agent
        self.config = config
        self.positions: List[Dict] = []
        self.portfolio_value = 0
        self.daily_pnl = 0

    async def get_ai_decision(self, market_data: Dict) -> Optional[Dict]:
        """Query Claude for trading decision"""
        try:
            # Build context for Claude
            context = {
                "market": market_data,
                "positions": self.positions,
                "portfolio_value": self.portfolio_value,
                "daily_pnl": self.daily_pnl,
            }

            decision = await self.ai_agent.get_trading_decision(context)
            return decision

        except Exception as e:
            logger.error(f"AI decision error: {e}")
            return None

    async def execute_trade(self, decision: Dict) -> bool:
        """Execute trade based on Claude decision"""
        try:
            action = decision.get("action")
            pair = self.config["pairs"][0]

            if action == "BUY_MARKET":
                return await self._buy(decision, pair)
            elif action == "SELL_MARKET":
                return await self._sell(decision, pair)

            return False

        except Exception as e:
            logger.error(f"Trade execution error: {e}")
            return False

    async def _buy(self, decision: Dict, pair: str) -> bool:
        """Execute BUY order"""
        try:
            quantity = self.config["base_order_size"]
            order = await self.exchange.place_market_order(pair, "BUY", quantity)

            if order:
                # Create position tracking
                position = {
                    "pair": pair,
                    "side": "BUY",
                    "entry_price": float(order.get("fills")[0]["price"]),
                    "quantity": quantity,
                    "stop_loss": decision.get("stop_loss_pct"),
                    "target": decision.get("target_pct"),
                    "entry_time": datetime.utcnow().isoformat(),
                    "status": "OPEN",
                }
                self.positions.append(position)
                logger.info(f"✓ BUY position opened: {position}")
                return True

            return False

        except Exception as e:
            logger.error(f"Buy execution error: {e}")
            return False

    async def _sell(self, decision: Dict, pair: str) -> bool:
        """Execute SELL order (close position or short)"""
        try:
            if self.positions:
                # Close existing position
                position = self.positions[0]
                quantity = position["quantity"]

                order = await self.exchange.place_market_order(pair, "SELL", quantity)

                if order:
                    exit_price = float(order.get("fills")[0]["price"])
                    pnl = (exit_price - position["entry_price"]) * quantity

                    # Update position
                    position["exit_price"] = exit_price
                    position["pnl"] = pnl
                    position["status"] = "CLOSED"

                    # Log trade
                    await self.db.log_trade(position)
                    self.positions.remove(position)
                    self.daily_pnl += pnl

                    logger.info(f"✓ Position closed: P&L = ${pnl:.2f}")
                    return True

            return False

        except Exception as e:
            logger.error(f"Sell execution error: {e}")
            return False

    async def check_trailing_stops(self):
        """Check all positions for SL/target/trail opportunities"""
        try:
            # Get current prices
            market_data = await self.exchange.get_market_data(
                self.config["pairs"][0]
            )
            current_price = market_data.get("current_price")

            for position in self.positions:
                if current_price:
                    # Ask Claude for trailing decision
                    action = await self.ai_agent.check_trailing_sl(
                        position, current_price
                    )

                    if action == "EXIT":
                        await self._exit_position(position, current_price)
                    elif action == "MOVE_SL":
                        await self._move_stop_loss(position, current_price)

        except Exception as e:
            logger.error(f"Trailing stop check error: {e}")

    async def _exit_position(self, position: Dict, current_price: float):
        """Exit a position at current price"""
        try:
            pair = position["pair"]
            quantity = position["quantity"]

            order = await self.exchange.place_market_order(pair, "SELL", quantity)

            if order:
                exit_price = float(order.get("fills")[0]["price"])
                pnl = (exit_price - position["entry_price"]) * quantity

                position["exit_price"] = exit_price
                position["pnl"] = pnl
                position["status"] = "CLOSED"

                await self.db.log_trade(position)
                self.positions.remove(position)
                self.daily_pnl += pnl

                logger.info(f"✓ Position exited: P&L = ${pnl:.2f}")

        except Exception as e:
            logger.error(f"Exit position error: {e}")

    async def _move_stop_loss(self, position: Dict, current_price: float):
        """Trail the stop loss by 0.5-1%"""
        try:
            # Calculate new SL (lock in profits)
            new_sl = current_price * 0.995  # Trail by 0.5%
            position["stop_loss"] = new_sl
            logger.info(f"✓ Stop loss moved to ${new_sl:.2f}")

        except Exception as e:
            logger.error(f"Move SL error: {e}")

    async def square_off_all(self):
        """Close all positions at EOD"""
        try:
            logger.info("🌙 EOD square-off starting...")

            market_data = await self.exchange.get_market_data(
                self.config["pairs"][0]
            )
            current_price = market_data.get("current_price")

            for position in self.positions[:]:
                await self._exit_position(position, current_price)

            logger.info(f"✅ EOD complete. Daily P&L: ${self.daily_pnl:.2f}")

        except Exception as e:
            logger.error(f"Square-off error: {e}")

    async def close(self):
        """Cleanup trader"""
        await self.square_off_all()
