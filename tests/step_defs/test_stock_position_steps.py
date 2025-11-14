"""BDD step definitions for stock position tracking.

This module contains pytest-bdd step definitions for testing Taiwan stock
margin trading and day trading offset rules.
"""

import pytest
from pytest_bdd import scenarios, given, when, then, parsers
from unittest.mock import Mock
from shioaji.constant import Action, StockOrderCond, OrderState
from shioaji.account import AccountType
from sj_sync.position_sync import PositionSync


# Load all feature files
scenarios("../features/day_trading.feature")
scenarios("../features/margin_trading.feature")
scenarios("../features/mixed_scenarios.feature")


@pytest.fixture
def context():
    """Shared context for BDD scenarios."""
    return {
        "sync": None,
        "account": None,
        "positions": {},
    }


@pytest.fixture
def position_sync(context):
    """Create PositionSync instance for testing."""
    # Mock API
    api = Mock()
    api.set_order_callback = Mock()
    api.list_positions = Mock(return_value=[])
    api.list_accounts = Mock(return_value=[])

    # Mock stock account
    account = Mock()
    account.broker_id = "9100"
    account.account_id = "1234567"
    account.account_type = AccountType.Stock
    api.stock_account = account

    # Create PositionSync
    sync = PositionSync(api)

    # Store in context
    context["sync"] = sync
    context["account"] = account

    return sync


def create_deal(code: str, action: str, quantity: int, order_cond: str, account):
    """Helper to create deal event data."""
    return {
        "code": code,
        "action": action,
        "quantity": quantity,
        "price": 500.0,  # Price doesn't affect offset logic
        "order_cond": order_cond,
        "account": {
            "broker_id": account.broker_id,
            "account_id": account.account_id,
        },
    }


def get_position(sync: PositionSync, account, code: str, cond: StockOrderCond):
    """Helper to get position."""
    account_key = f"{account.broker_id}{account.account_id}"
    key = (code, cond)
    positions = sync._stock_positions.get(account_key, {})
    return positions.get(key)


# Given steps


@given("我沒有任何庫存", target_fixture="initial_position")
def no_position(position_sync):
    """Start with no positions."""
    return None


@given(
    parsers.parse("我有昨日資買庫存 {code} 數量 {quantity:d} 張"),
    target_fixture="initial_position",
)
def yesterday_margin_position(position_sync, context, code, quantity):
    """Set up yesterday's margin trading position."""
    sync = context["sync"]
    account = context["account"]

    # Create a deal to establish yesterday's position
    deal = create_deal(code, "Buy", quantity, "MarginTrading", account)
    sync.on_order_deal_event(OrderState.StockDeal, deal)

    # Manually set yd_quantity to simulate yesterday's position
    account_key = f"{account.broker_id}{account.account_id}"
    key = (code, StockOrderCond.MarginTrading)
    position = sync._stock_positions[account_key][key]
    position.yd_quantity = quantity

    return position


@given(
    parsers.parse("我有昨日券賣庫存 {code} 數量 {quantity:d} 張"),
    target_fixture="initial_position",
)
def yesterday_short_position(position_sync, context, code, quantity):
    """Set up yesterday's short selling position."""
    sync = context["sync"]
    account = context["account"]

    # Create a deal to establish yesterday's position
    deal = create_deal(code, "Sell", quantity, "ShortSelling", account)
    sync.on_order_deal_event(OrderState.StockDeal, deal)

    # Manually set yd_quantity to simulate yesterday's position
    account_key = f"{account.broker_id}{account.account_id}"
    key = (code, StockOrderCond.ShortSelling)
    position = sync._stock_positions[account_key][key]
    position.yd_quantity = quantity

    return position


# When steps - Trading actions


@when(parsers.parse("我資買 {code} 數量 {quantity:d} 張"))
def margin_buy(position_sync, context, code, quantity):
    """Execute margin trading buy."""
    sync = context["sync"]
    account = context["account"]
    deal = create_deal(code, "Buy", quantity, "MarginTrading", account)
    sync.on_order_deal_event(OrderState.StockDeal, deal)


@when(parsers.parse("我資賣 {code} 數量 {quantity:d} 張"))
def margin_sell(position_sync, context, code, quantity):
    """Execute margin trading sell (to close margin position)."""
    sync = context["sync"]
    account = context["account"]
    deal = create_deal(code, "Sell", quantity, "MarginTrading", account)
    sync.on_order_deal_event(OrderState.StockDeal, deal)


@when(parsers.parse("我券賣 {code} 數量 {quantity:d} 張"))
def short_sell(position_sync, context, code, quantity):
    """Execute short selling."""
    sync = context["sync"]
    account = context["account"]
    deal = create_deal(code, "Sell", quantity, "ShortSelling", account)
    sync.on_order_deal_event(OrderState.StockDeal, deal)


@when(parsers.parse("我券買 {code} 數量 {quantity:d} 張"))
def short_cover(position_sync, context, code, quantity):
    """Execute short covering (buy to close short position)."""
    sync = context["sync"]
    account = context["account"]
    deal = create_deal(code, "Buy", quantity, "ShortSelling", account)
    sync.on_order_deal_event(OrderState.StockDeal, deal)


@when(parsers.parse("我現股買 {code} 數量 {quantity:d} 張"))
def cash_buy(position_sync, context, code, quantity):
    """Execute cash buy."""
    sync = context["sync"]
    account = context["account"]
    deal = create_deal(code, "Buy", quantity, "Cash", account)
    sync.on_order_deal_event(OrderState.StockDeal, deal)


@when(parsers.parse("我現股賣 {code} 數量 {quantity:d} 張"))
def cash_sell(position_sync, context, code, quantity):
    """Execute cash sell."""
    sync = context["sync"]
    account = context["account"]
    deal = create_deal(code, "Sell", quantity, "Cash", account)
    sync.on_order_deal_event(OrderState.StockDeal, deal)


# Then steps - Assertions


@then(
    parsers.parse(
        "資買庫存應為 {expected_qty:d} 張，昨日庫存為 {expected_yd:d} 張，昨日已抵銷 {expected_offset:d} 張"
    )
)
def check_margin_position_with_yd_offset(
    position_sync, context, expected_qty, expected_yd, expected_offset
):
    """Check margin trading position quantity, yesterday's quantity and offset."""
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


@then(parsers.parse("資買庫存應為 {expected_qty:d} 張，昨日庫存為 {expected_yd:d} 張"))
def check_margin_position_with_yd(position_sync, context, expected_qty, expected_yd):
    """Check margin trading position quantity and yesterday's quantity (without offset check)."""
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


@then(parsers.parse("資買庫存應為 {expected_qty:d} 張（完全抵銷）"))
@then(parsers.parse("資買庫存應為 {expected_qty:d} 張（當沖抵銷）"))
@then(parsers.parse("資買庫存應為 {expected_qty:d} 張"))
def check_margin_position(position_sync, context, expected_qty):
    """Check margin trading position quantity."""
    sync = context["sync"]
    account = context["account"]
    position = get_position(sync, account, "2330", StockOrderCond.MarginTrading)

    if expected_qty == 0:
        assert position is None, f"資買庫存應為 0 (已移除)，但仍存在: {position}"
    else:
        assert position is not None, "資買庫存應該存在"
        assert position.quantity == expected_qty, (
            f"資買庫存應為 {expected_qty} 張，實際為 {position.quantity} 張"
        )


@then(
    parsers.parse(
        "券賣庫存應為 {expected_qty:d} 張，昨日庫存為 {expected_yd:d} 張，昨日已抵銷 {expected_offset:d} 張"
    )
)
def check_short_position_with_yd_offset(
    position_sync, context, expected_qty, expected_yd, expected_offset
):
    """Check short selling position quantity, yesterday's quantity and offset."""
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
def check_short_position_with_yd(position_sync, context, expected_qty, expected_yd):
    """Check short selling position quantity and yesterday's quantity (without offset check)."""
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


@then(parsers.parse("券賣庫存應為 {expected_qty:d} 張（完全抵銷）"))
@then(parsers.parse("券賣庫存應為 {expected_qty:d} 張（當沖抵銷）"))
@then(parsers.parse("券賣庫存應為 {expected_qty:d} 張"))
def check_short_position(position_sync, context, expected_qty):
    """Check short selling position quantity."""
    sync = context["sync"]
    account = context["account"]
    position = get_position(sync, account, "2330", StockOrderCond.ShortSelling)

    if expected_qty == 0:
        assert position is None, f"券賣庫存應為 0 (已移除)，但仍存在: {position}"
    else:
        assert position is not None, "券賣庫存應該存在"
        assert position.quantity == expected_qty, (
            f"券賣庫存應為 {expected_qty} 張，實際為 {position.quantity} 張"
        )


@then(parsers.parse("現股庫存應為 {expected_qty:d} 張，昨日庫存為 {expected_yd:d} 張"))
def check_cash_position_with_yd(position_sync, context, expected_qty, expected_yd):
    """Check cash position quantity and yesterday's quantity."""
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


@then(parsers.parse("現股庫存應為 {expected_qty:d} 張（完全抵銷）"))
@then(parsers.parse("現股庫存應為 {expected_qty:d} 張（當沖抵銷）"))
@then(parsers.parse("現股庫存應為 {expected_qty:d} 張"))
def check_cash_position(position_sync, context, expected_qty):
    """Check cash position quantity."""
    sync = context["sync"]
    account = context["account"]
    position = get_position(sync, account, "2330", StockOrderCond.Cash)

    if expected_qty == 0:
        assert position is None, f"現股庫存應為 0 (已移除)，但仍存在: {position}"
    else:
        assert position is not None, "現股庫存應該存在"
        assert position.quantity == expected_qty, (
            f"現股庫存應為 {expected_qty} 張，實際為 {position.quantity} 張"
        )


@then(parsers.parse("現股賣出庫存應為 {expected_qty:d} 張"))
def check_cash_sell_position(position_sync, context, expected_qty):
    """Check cash sell position (short without margin)."""
    sync = context["sync"]
    account = context["account"]
    position = get_position(sync, account, "2330", StockOrderCond.Cash)

    if expected_qty == 0:
        assert position is None, f"現股賣出庫存應為 0 (已移除)，但仍存在: {position}"
    else:
        assert position is not None, "現股賣出庫存應該存在"
        assert position.quantity == expected_qty, (
            f"現股賣出庫存應為 {expected_qty} 張，實際為 {position.quantity} 張"
        )
        assert position.direction == Action.Sell, "現股賣出庫存方向應為 Sell"
