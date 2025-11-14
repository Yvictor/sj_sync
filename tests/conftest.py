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
        "code": "2330",
        "action": "Buy",
        "quantity": 2,
        "price": 505.0,
        "order_cond": "Cash",
    }


@pytest.fixture
def sample_sell_deal():
    """Sample stock sell deal event data."""
    return {
        "trade_id": "test456",
        "code": "2330",
        "action": "Sell",
        "quantity": 3,
        "price": 510.0,
        "order_cond": "Cash",
    }


@pytest.fixture
def sample_margin_deal():
    """Sample margin trading deal event."""
    return {
        "trade_id": "test789",
        "code": "2317",
        "action": "Buy",
        "quantity": 2,
        "price": 105.0,
        "order_cond": "MarginTrading",
    }


@pytest.fixture
def sample_short_deal():
    """Sample short selling deal event."""
    return {
        "trade_id": "test101",
        "code": "2454",
        "action": "Sell",
        "quantity": 1,
        "price": 205.0,
        "order_cond": "ShortSelling",
    }


@pytest.fixture
def sample_futures_deal():
    """Sample futures deal event data."""
    return {
        "trade_id": "test_fut",
        "code": "TXFJ4",
        "action": "Buy",
        "quantity": 1,
        "price": 17050.0,
    }
