"""BDD step definitions for midday restart scenarios.

This module tests the yd_offset_quantity calculation when the system
restarts during trading hours with existing trades.
"""

import pytest
from pytest_bdd import scenarios, given, when, then, parsers
from unittest.mock import Mock
from shioaji.constant import Action, StockOrderCond, Status
from shioaji.account import AccountType
from shioaji.position import StockPosition as SjStockPostion
from sj_sync.position_sync import PositionSync


# Load feature file
scenarios("../features/midday_restart.feature")


@pytest.fixture
def context():
    """Shared context for BDD scenarios."""
    return {
        "sync": None,
        "account": None,
        "today_trades": [],
        "positions": {},
    }


@pytest.fixture(autouse=True)
def setup_account(context):
    """Setup account before any steps run."""
    # Mock stock account
    account = Mock()
    account.broker_id = "9100"
    account.account_id = "1234567"
    account.account_type = AccountType.Stock

    # Store in context
    context["account"] = account

    # Mock API
    api = Mock()

    # Setup list_accounts
    api.list_accounts = Mock(return_value=[account])

    # Setup list_positions (will be configured by when steps)
    api.list_positions = Mock(return_value=[])

    # Setup update_status and list_trades (will return today_trades from context)
    def mock_update_status(acc=None):
        pass

    def mock_list_trades():
        return context["today_trades"]

    api.update_status = Mock(side_effect=mock_update_status)
    api.list_trades = Mock(side_effect=mock_list_trades)
    api.set_order_callback = Mock()
    api.stock_account = account

    context["api"] = api

    return None


def create_mock_trade(code: str, action: str, quantity: int, order_cond: str, account):
    """Create a mock Trade object."""
    trade = Mock()

    # Mock contract
    trade.contract = Mock()
    trade.contract.code = code
    trade.contract.exchange = "TSE"  # Stock has exchange

    # Mock order
    trade.order = Mock()
    trade.order.action = Action.Buy if action == "Buy" else Action.Sell
    trade.order.order_cond = getattr(StockOrderCond, order_cond)
    trade.order.account = Mock()
    trade.order.account.broker_id = account.broker_id
    trade.order.account.account_id = account.account_id

    # Mock status
    trade.status = Mock()
    trade.status.status = Status.Filled
    trade.status.deal_quantity = quantity
    trade.status.deals = [Mock(price=500.0)]

    return trade


def create_mock_position(
    code: str, direction: str, quantity: int, yd_quantity: int, cond: str
):
    """Create a mock position from list_positions."""
    pos = Mock(spec=SjStockPostion)
    pos.code = code
    pos.direction = Action.Buy if direction == "Buy" else Action.Sell
    pos.quantity = quantity
    pos.yd_quantity = yd_quantity
    pos.cond = getattr(StockOrderCond, cond)
    return pos


# Given steps - Today's trades


@given("今天沒有交易記錄")
def no_trades_today(context):
    """No trades today."""
    context["today_trades"] = []


@given(parsers.parse("今天已有交易記錄：資買 {code:d} 數量 {quantity:d} 張"))
def today_margin_buy_single(context, code, quantity):
    """Single margin buy trade today."""
    account = context["account"]
    trade = create_mock_trade(str(code), "Buy", quantity, "MarginTrading", account)
    context["today_trades"] = [trade]


@given(parsers.parse("今天已有交易記錄：資賣 {code:d} 數量 {quantity:d} 張"))
def today_margin_sell_single(context, code, quantity):
    """Single margin sell trade today."""
    account = context["account"]
    trade = create_mock_trade(str(code), "Sell", quantity, "MarginTrading", account)
    context["today_trades"] = [trade]


@given(parsers.parse("今天已有交易記錄：券買 {code:d} 數量 {quantity:d} 張"))
def today_short_cover_single(context, code, quantity):
    """Single short cover trade today."""
    account = context["account"]
    trade = create_mock_trade(str(code), "Buy", quantity, "ShortSelling", account)
    context["today_trades"] = [trade]


@given(parsers.parse("今天已有交易記錄：券賣 {code:d} 數量 {quantity:d} 張"))
def today_short_sell_single(context, code, quantity):
    """Single short sell trade today."""
    account = context["account"]
    trade = create_mock_trade(str(code), "Sell", quantity, "ShortSelling", account)
    context["today_trades"] = [trade]


@given(parsers.parse("今天已有交易記錄：現股賣 {code:d} 數量 {quantity:d} 張"))
def today_cash_sell_single(context, code, quantity):
    """Single cash sell trade today."""
    account = context["account"]
    trade = create_mock_trade(str(code), "Sell", quantity, "Cash", account)
    context["today_trades"] = [trade]


@given(
    parsers.parse(
        "今天已有交易記錄：資賣 {code:d} 數量 {qty1:d} 張，資買 {code2:d} 數量 {qty2:d} 張"
    )
)
def today_margin_sell_and_buy(context, code, qty1, code2, qty2):
    """Margin sell then buy today."""
    account = context["account"]
    trade1 = create_mock_trade(str(code), "Sell", qty1, "MarginTrading", account)
    trade2 = create_mock_trade(str(code2), "Buy", qty2, "MarginTrading", account)
    context["today_trades"] = [trade1, trade2]


@given(
    parsers.parse(
        "今天已有交易記錄：資買 {code:d} 數量 {qty1:d} 張，券賣 {code2:d} 數量 {qty2:d} 張"
    )
)
def today_margin_buy_and_short_sell(context, code, qty1, code2, qty2):
    """Margin buy and short sell today (day trading)."""
    account = context["account"]
    trade1 = create_mock_trade(str(code), "Buy", qty1, "MarginTrading", account)
    trade2 = create_mock_trade(str(code2), "Sell", qty2, "ShortSelling", account)
    context["today_trades"] = [trade1, trade2]


@given(
    parsers.parse(
        "今天已有交易記錄：資買 {code:d} 數量 {qty1:d} 張，資賣 {code2:d} 數量 {qty2:d} 張"
    )
)
def today_margin_buy_and_sell(context, code, qty1, code2, qty2):
    """Margin buy then sell today."""
    account = context["account"]
    trade1 = create_mock_trade(str(code), "Buy", qty1, "MarginTrading", account)
    trade2 = create_mock_trade(str(code2), "Sell", qty2, "MarginTrading", account)
    context["today_trades"] = [trade1, trade2]


@given(
    parsers.parse(
        "今天已有交易記錄：資買 {code:d} 數量 {qty1:d} 張，資賣 {code2:d} 數量 {qty2:d} 張，資買 {code3:d} 數量 {qty3:d} 張"
    )
)
def today_multiple_trades(context, code, qty1, code2, qty2, code3, qty3):
    """Multiple margin trades today."""
    account = context["account"]
    trade1 = create_mock_trade(str(code), "Buy", qty1, "MarginTrading", account)
    trade2 = create_mock_trade(str(code2), "Sell", qty2, "MarginTrading", account)
    trade3 = create_mock_trade(str(code3), "Buy", qty3, "MarginTrading", account)
    context["today_trades"] = [trade1, trade2, trade3]


# When steps - System initialization with positions


@when(
    parsers.parse(
        "系統初始化並從券商取得部位：資買 {code} 數量 {quantity:d} 張，昨日庫存 {yd_quantity:d} 張"
    )
)
def init_with_margin_position(context, code, quantity, yd_quantity):
    """Initialize system with margin position from broker."""
    api = context["api"]

    # Setup list_positions to return this position
    pos = create_mock_position(code, "Buy", quantity, yd_quantity, "MarginTrading")
    api.list_positions = Mock(return_value=[pos])

    # Create PositionSync (this will call _initialize_positions)
    sync = PositionSync(api)
    context["sync"] = sync


@when(
    parsers.parse(
        "系統初始化並從券商取得部位：券賣 {code} 數量 {quantity:d} 張，昨日庫存 {yd_quantity:d} 張"
    )
)
def init_with_short_position(context, code, quantity, yd_quantity):
    """Initialize system with short position from broker."""
    api = context["api"]

    pos = create_mock_position(code, "Sell", quantity, yd_quantity, "ShortSelling")
    api.list_positions = Mock(return_value=[pos])

    sync = PositionSync(api)
    context["sync"] = sync


@when(
    parsers.parse(
        "系統初始化並從券商取得部位：現股 {code} 數量 {quantity:d} 張，昨日庫存 {yd_quantity:d} 張"
    )
)
def init_with_cash_position(context, code, quantity, yd_quantity):
    """Initialize system with cash position from broker."""
    api = context["api"]

    pos = create_mock_position(code, "Buy", quantity, yd_quantity, "Cash")
    api.list_positions = Mock(return_value=[pos])

    sync = PositionSync(api)
    context["sync"] = sync


@when(
    parsers.parse(
        "券賣部位：券賣 {code} 數量 {quantity:d} 張，昨日庫存 {yd_quantity:d} 張"
    )
)
def add_short_position(context, code, quantity, yd_quantity):
    """Add short selling position (for multi-position scenarios)."""
    api = context["api"]

    # Get existing positions and add new one
    existing_positions = api.list_positions.return_value
    pos = create_mock_position(code, "Sell", quantity, yd_quantity, "ShortSelling")
    api.list_positions = Mock(return_value=existing_positions + [pos])

    # Re-initialize
    sync = PositionSync(api)
    context["sync"] = sync


# Then steps - Assertions


def get_position(sync, account, code: str, cond: StockOrderCond):
    """Helper to get position."""
    account_key = f"{account.broker_id}{account.account_id}"
    key = (code, cond)
    positions = sync._stock_positions.get(account_key, {})
    return positions.get(key)


@then(
    parsers.parse(
        "資買庫存應為 {expected_qty:d} 張，昨日庫存為 {expected_yd:d} 張，昨日已抵銷 {expected_offset:d} 張"
    )
)
def check_margin_position_with_offset(
    context, expected_qty, expected_yd, expected_offset
):
    """Check margin position with yd_offset."""
    sync = context["sync"]
    account = context["account"]
    position = get_position(sync, account, "2330", StockOrderCond.MarginTrading)

    assert position is not None, "資買庫存應該存在"
    assert position.quantity == expected_qty, (
        f"資買庫存應為 {expected_qty} 張，實際為 {position.quantity} 張"
    )
    assert position.yd_quantity == expected_yd, (
        f"昨日庫存應為 {expected_yd} 張，實際為 {position.yd_quantity} 張"
    )
    assert position.yd_offset_quantity == expected_offset, (
        f"昨日已抵銷應為 {expected_offset} 張，實際為 {position.yd_offset_quantity} 張"
    )


@then(
    parsers.parse(
        "券賣庫存應為 {expected_qty:d} 張，昨日庫存為 {expected_yd:d} 張，昨日已抵銷 {expected_offset:d} 張"
    )
)
def check_short_position_with_offset(
    context, expected_qty, expected_yd, expected_offset
):
    """Check short position with yd_offset."""
    sync = context["sync"]
    account = context["account"]
    position = get_position(sync, account, "2330", StockOrderCond.ShortSelling)

    assert position is not None, "券賣庫存應該存在"
    assert position.quantity == expected_qty, (
        f"券賣庫存應為 {expected_qty} 張，實際為 {position.quantity} 張"
    )
    assert position.yd_quantity == expected_yd, (
        f"昨日庫存應為 {expected_yd} 張，實際為 {position.yd_quantity} 張"
    )
    assert position.yd_offset_quantity == expected_offset, (
        f"昨日已抵銷應為 {expected_offset} 張，實際為 {position.yd_offset_quantity} 張"
    )


@then(parsers.parse("券賣庫存應為 {expected_qty:d} 張，昨日庫存為 {expected_yd:d} 張"))
def check_short_position_simple(context, expected_qty, expected_yd):
    """Check short position without offset check."""
    sync = context["sync"]
    account = context["account"]
    position = get_position(sync, account, "2330", StockOrderCond.ShortSelling)

    assert position is not None, "券賣庫存應該存在"
    assert position.quantity == expected_qty, (
        f"券賣庫存應為 {expected_qty} 張，實際為 {position.quantity} 張"
    )
    assert position.yd_quantity == expected_yd, (
        f"昨日庫存應為 {expected_yd} 張，實際為 {position.yd_quantity} 張"
    )


@then(parsers.parse("現股庫存應為 {expected_qty:d} 張，昨日庫存為 {expected_yd:d} 張"))
def check_cash_position(context, expected_qty, expected_yd):
    """Check cash position."""
    sync = context["sync"]
    account = context["account"]
    position = get_position(sync, account, "2330", StockOrderCond.Cash)

    assert position is not None, "現股庫存應該存在"
    assert position.quantity == expected_qty, (
        f"現股庫存應為 {expected_qty} 張，實際為 {position.quantity} 張"
    )
    assert position.yd_quantity == expected_yd, (
        f"昨日庫存應為 {expected_yd} 張，實際為 {position.yd_quantity} 張"
    )
