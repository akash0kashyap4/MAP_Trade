from __future__ import annotations
from groww.auth import get_groww_client

def place_market_order(trading_symbol: str, quantity: int, transaction_type: str) -> str:
    groww = get_groww_client()
    t_type = groww.TRANSACTION_TYPE_BUY if transaction_type.upper() == 'BUY' else groww.TRANSACTION_TYPE_SELL

    try:
        print(f"[groww.orders] Placing MARKET {transaction_type} order for {trading_symbol}")
        order_id = groww.place_order(
            trading_symbol=trading_symbol,
            quantity=quantity,
            validity=groww.VALIDITY_DAY,
            exchange=groww.EXCHANGE_NSE,
            segment=groww.SEGMENT_FNO,
            product=groww.PRODUCT_MIS,
            order_type=groww.ORDER_TYPE_MARKET,
            transaction_type=t_type
        )
        print(f"[groww.orders] ✅ {transaction_type} order placed for {trading_symbol}. Order ID: {order_id.get('groww_order_id')}")
        return order_id.get('groww_order_id')
    except Exception as e:
        print(f"[groww.orders] ❌ Failed to place {transaction_type} order: {e}")
        raise
