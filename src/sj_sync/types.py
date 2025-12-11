"""Type definitions for sj_sync."""

from typing import TypedDict


class StockDeal(TypedDict):
    """Stock deal event data structure.

    Based on: https://sinotrade.github.io/zh/tutor/order/order_deal_event/stocks/
    """

    trade_id: str
    seqno: str
    ordno: str
    exchange_seq: str
    broker_id: str
    account_id: str
    action: str
    code: str
    order_cond: str
    order_lot: str
    price: float
    quantity: int
    web_id: str
    custom_field: str
    ts: float


class FuturesDeal(TypedDict):
    """Futures/Options deal event data structure.

    Based on: https://sinotrade.github.io/zh/tutor/order/order_deal_event/futures/
    """

    trade_id: str
    seqno: str
    ordno: str
    exchange_seq: str
    broker_id: str
    account_id: str
    action: str
    code: str
    price: float
    quantity: int
    subaccount: str
    security_type: str
    delivery_month: str
    strike_price: float
    option_right: str
    market_type: str
    combo: bool
    ts: float
    full_code: str  # Complete contract code (not in official doc but used in practice)
