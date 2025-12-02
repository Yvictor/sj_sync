"""Pytest fixtures for testing PositionSync."""

import pytest
from unittest.mock import Mock
from shioaji.constant import Action, StockOrderCond
from shioaji.account import AccountType
from shioaji.position import StockPosition as SjStockPosition
from shioaji.position import FuturePosition as SjFuturePosition


def create_mock_account(
    broker_id="9100", account_id="1234567", account_type=AccountType.Stock
):
    """Helper to create mock account with required attributes."""
    account = Mock()
    account.broker_id = broker_id
    account.account_id = account_id
    account.account_type = account_type
    return account


@pytest.fixture
def mock_api():
    """Create a mock Shioaji API instance."""
    api = Mock()
    api.set_order_callback = Mock()
    api.list_positions = Mock(return_value=[])
    api.list_accounts = Mock(return_value=[])

    # Mock stock_account with broker_id and account_id
    api.stock_account = create_mock_account()

    # Mock Contracts.Stocks for stock name lookup
    api.Contracts = Mock()
    api.Contracts.Stocks = {}

    return api


@pytest.fixture
def sample_stock_pnl():
    """Sample stock position from list_positions()."""
    pnl = Mock(spec=SjStockPosition)
    pnl.code = "2330"
    pnl.direction = Action.Buy
    pnl.quantity = 10
    pnl.yd_quantity = 10
    pnl.price = 500.0
    pnl.cond = StockOrderCond.Cash
    return pnl


@pytest.fixture
def sample_margin_pnl():
    """Sample margin trading position."""
    pnl = Mock(spec=SjStockPosition)
    pnl.code = "2317"
    pnl.direction = Action.Buy
    pnl.quantity = 5
    pnl.yd_quantity = 5
    pnl.price = 100.0
    pnl.cond = StockOrderCond.MarginTrading
    return pnl


@pytest.fixture
def sample_short_pnl():
    """Sample short selling position."""
    pnl = Mock(spec=SjStockPosition)
    pnl.code = "2454"
    pnl.direction = Action.Sell
    pnl.quantity = 3
    pnl.yd_quantity = 3
    pnl.price = 200.0
    pnl.cond = StockOrderCond.ShortSelling
    return pnl


@pytest.fixture
def sample_futures_pnl():
    """Sample futures position from list_positions()."""
    pnl = Mock(spec=SjFuturePosition)
    pnl.code = "TXFJ4"
    pnl.direction = Action.Buy
    pnl.quantity = 2
    pnl.yd_quantity = 2
    pnl.price = 17000.0
    # Futures don't have cond attribute - using spec to prevent auto-creation
    return pnl


@pytest.fixture
def sample_stock_deal():
    """Sample stock deal event data."""
    return {
        "trade_id": "test123",
        "seqno": "269866",
        "ordno": "IN497",
        "exchange_seq": "669915",
        "broker_id": "9100",
        "account_id": "1234567",
        "action": "Buy",
        "code": "2330",
        "order_cond": "Cash",
        "order_lot": "Common",
        "price": 505.0,
        "quantity": 2,
        "web_id": "137",
        "custom_field": "",
        "ts": 1673577256.354,
    }


@pytest.fixture
def sample_sell_deal():
    """Sample stock sell deal event data."""
    return {
        "trade_id": "test456",
        "seqno": "269867",
        "ordno": "IN498",
        "exchange_seq": "669916",
        "broker_id": "9100",
        "account_id": "1234567",
        "action": "Sell",
        "code": "2330",
        "order_cond": "Cash",
        "order_lot": "Common",
        "price": 510.0,
        "quantity": 3,
        "web_id": "137",
        "custom_field": "",
        "ts": 1673577260.354,
    }


@pytest.fixture
def sample_margin_deal():
    """Sample margin trading deal event."""
    return {
        "trade_id": "test789",
        "seqno": "269868",
        "ordno": "IN499",
        "exchange_seq": "669917",
        "broker_id": "9100",
        "account_id": "1234567",
        "action": "Buy",
        "code": "2317",
        "order_cond": "MarginTrading",
        "order_lot": "Common",
        "price": 105.0,
        "quantity": 2,
        "web_id": "137",
        "custom_field": "",
        "ts": 1673577264.354,
    }


@pytest.fixture
def sample_short_deal():
    """Sample short selling deal event."""
    return {
        "trade_id": "test101",
        "seqno": "269869",
        "ordno": "IN500",
        "exchange_seq": "669918",
        "broker_id": "9100",
        "account_id": "1234567",
        "action": "Sell",
        "code": "2454",
        "order_cond": "ShortSelling",
        "order_lot": "Common",
        "price": 205.0,
        "quantity": 1,
        "web_id": "137",
        "custom_field": "",
        "ts": 1673577268.354,
    }


@pytest.fixture
def sample_futures_deal():
    """Sample futures deal event data."""
    return {
        "trade_id": "test_fut",
        "seqno": "458545",
        "ordno": "tA0deX1O",
        "exchange_seq": "j5006396",
        "broker_id": "9100",
        "account_id": "1234567",
        "action": "Buy",
        "code": "TXF",
        "full_code": "TXFJ4",  # Complete contract code (code + delivery month)
        "price": 17050.0,
        "quantity": 1,
        "subaccount": "",
        "security_type": "FUT",
        "delivery_month": "202401",
        "strike_price": 0.0,
        "option_right": "Future",
        "market_type": "Day",
        "combo": False,
        "ts": 1673270852.0,
    }
