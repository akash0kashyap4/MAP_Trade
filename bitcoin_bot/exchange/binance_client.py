"""
Binance Exchange Client
REST API + WebSocket integration for trading and market data
"""

import logging
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from binance.client import Client
from binance.websockets import BinanceSocketManager
import asyncio

logger = logging.getLogger(__name__)


class BinanceClient:
    """Wrapper around Binance API"""

    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.client = None
        self.bsm = None
        self.socket_connected = False

    async def connect(self):
        """Initialize Binance client connection"""
        try:
            self.client = Client(
                api_key=self.api_key,
                api_secret=self.api_secret,
                testnet=self.testnet,
            )

            # Test connection
            info = self.client.get_account()
            logger.info(f"✓ Connected to Binance: {info['commissionRates']}")

            # Initialize WebSocket
            self.bsm = BinanceSocketManager(self.client)
            self.socket_connected = True

        except Exception as e:
            logger.error(f"Binance connection failed: {e}")
            raise

    async def disconnect(self):
        """Close connections"""
        if self.bsm:
            await self.bsm.close_connection()
        self.socket_connected = False
        logger.info("Binance disconnected")

    async def get_market_data(self, pair: str) -> Dict:
        """Fetch current market data for a trading pair"""
        try:
            # Get klines (candlestick data)
            klines = self.client.get_klines(
                symbol=pair,
                interval="5m",  # 5-min candles
                limit=60,  # Last 60 candles = 5 hours
            )

            # Get ticker
            ticker = self.client.get_symbol_info(pair)
            ticker_price = self.client.get_symbol_ticker(symbol=pair)

            # Get order book
            order_book = self.client.get_order_book(symbol=pair, limit=20)

            # Structure the data
            candles = [
                {
                    "time": int(k[0]) / 1000,
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[7]),
                }
                for k in klines
            ]

            return {
                "pair": pair,
                "timestamp": datetime.utcnow().isoformat(),
                "current_price": float(ticker_price["price"]),
                "bid": float(order_book["bids"][0][0]) if order_book["bids"] else 0,
                "ask": float(order_book["asks"][0][0]) if order_book["asks"] else 0,
                "candles": candles,  # Last 60 x 5m = 5 hours history
                "24h_volume": float(ticker_price.get("volume", 0)),
            }

        except Exception as e:
            logger.error(f"Market data fetch error: {e}")
            return {}

    async def place_market_order(
        self, pair: str, side: str, quantity: float
    ) -> Optional[Dict]:
        """
        Place market order (BUY or SELL)

        Args:
            pair: Trading pair (e.g., "BTCUSDT")
            side: "BUY" or "SELL"
            quantity: Amount to buy/sell

        Returns:
            Order response dict
        """
        try:
            order = self.client.order_market(
                symbol=pair,
                side=side,
                quantity=quantity,
            )

            logger.info(f"✓ {side} order placed: {quantity} {pair} @ {order}")
            return order

        except Exception as e:
            logger.error(f"Order placement error: {e}")
            return None

    async def place_limit_order(
        self, pair: str, side: str, quantity: float, price: float
    ) -> Optional[Dict]:
        """Place limit order"""
        try:
            order = self.client.order_limit(
                symbol=pair,
                side=side,
                quantity=quantity,
                price=price,
            )
            logger.info(f"✓ Limit {side} order: {quantity} @ {price}")
            return order
        except Exception as e:
            logger.error(f"Limit order error: {e}")
            return None

    async def get_open_orders(self, pair: str) -> List[Dict]:
        """Get all open orders for a pair"""
        try:
            orders = self.client.get_open_orders(symbol=pair)
            return orders
        except Exception as e:
            logger.error(f"Get open orders error: {e}")
            return []

    async def cancel_order(self, pair: str, order_id: int) -> Optional[Dict]:
        """Cancel an order"""
        try:
            result = self.client.cancel_order(symbol=pair, orderId=order_id)
            logger.info(f"✓ Order cancelled: {order_id}")
            return result
        except Exception as e:
            logger.error(f"Cancel order error: {e}")
            return None

    async def get_account_balance(self) -> Dict:
        """Get current account balances"""
        try:
            account = self.client.get_account()
            balances = {}

            for asset in account["balances"]:
                if float(asset["free"]) > 0 or float(asset["locked"]) > 0:
                    balances[asset["asset"]] = {
                        "free": float(asset["free"]),
                        "locked": float(asset["locked"]),
                        "total": float(asset["free"]) + float(asset["locked"]),
                    }

            return balances
        except Exception as e:
            logger.error(f"Get balance error: {e}")
            return {}

    async def get_trade_history(self, pair: str, limit: int = 50) -> List[Dict]:
        """Get recent trades for a pair"""
        try:
            trades = self.client.get_my_trades(symbol=pair, limit=limit)
            return trades
        except Exception as e:
            logger.error(f"Trade history error: {e}")
            return []

    async def stream_kline(self, pair: str, interval: str, callback):
        """Stream kline (candlestick) updates"""
        if not self.bsm:
            logger.error("WebSocket not initialized")
            return

        try:
            async with self.bsm.multiplex_socket(
                [f"{pair.lower()}@kline_{interval}"]
            ) as ms:
                while True:
                    msg = await ms.recv()
                    await callback(msg)
        except Exception as e:
            logger.error(f"Kline stream error: {e}")

    async def stream_ticker(self, pair: str, callback):
        """Stream ticker updates"""
        if not self.bsm:
            logger.error("WebSocket not initialized")
            return

        try:
            async with self.bsm.multiplex_socket(
                [f"{pair.lower()}@ticker"]
            ) as ms:
                while True:
                    msg = await ms.recv()
                    await callback(msg)
        except Exception as e:
            logger.error(f"Ticker stream error: {e}")
