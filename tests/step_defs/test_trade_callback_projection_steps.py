"""BDD steps for callback-to-Native-Trade field projection."""

from unittest.mock import Mock

import pytest
from pytest_bdd import given, parsers, scenarios, then, when

from sj_sync import PositionSync
from sj_sync.shioaji_compat import OrderState, Status, sj


scenarios("../features/trade_callback_projection.feature")


def _supports_live_trade_sync() -> bool:
    version = tuple(int(part) for part in sj.__version__.split(".")[:2])
    return version in {(1, 2), (1, 3)}


pytestmark = pytest.mark.skipif(
    not _supports_live_trade_sync(),
    reason="Native Trade mutation is supported only on Shioaji 1.2.x/1.3.x",
)


def trade_fields(trade):
    """Return the seven public fields specified by the feature."""
    return {
        "status": str(getattr(trade.status.status, "value", trade.status.status)),
        "price": float(trade.order.price),
        "quantity": int(trade.order.quantity),
        "modified_price": float(trade.status.modified_price),
        "cancel_quantity": int(trade.status.cancel_quantity),
        "deal_quantity": int(trade.status.deal_quantity),
        "deals": len(trade.status.deals or []),
    }


def create_native_trade():
    """Create the Native Trade shape exposed by the Shioaji boundary."""
    trade = Mock()
    trade.order.id = "bdd-order"
    trade.order.account.broker_id = "9100"
    trade.order.account.account_id = "1234567"
    trade.order.price = 100.0
    trade.order.quantity = 2
    trade.status.status = Status.PendingSubmit
    trade.status.status_code = ""
    trade.status.msg = ""
    trade.status.order_quantity = 2
    trade.status.modified_price = 0.0
    trade.status.deal_quantity = 0
    trade.status.cancel_quantity = 0
    trade.status.deals = []
    return trade


def create_order_event(
    context,
    op_type,
    op_code,
    order_price,
    order_quantity,
    modified_price,
    cancel_quantity,
):
    """Create a StockOrder payload matching real Shioaji 1.2/1.3 reports."""
    context["exchange_ts"] += 1
    return {
        "operation": {
            "op_type": op_type,
            "op_code": op_code,
            "op_msg": "" if op_code == "00" else "rejected",
        },
        "order": {
            "id": "bdd-order",
            "seqno": "000001",
            "ordno": "A0001",
            "account": {"broker_id": "9100", "account_id": "1234567"},
            "action": "Buy",
            "price": order_price,
            "quantity": order_quantity,
            "order_type": "ROD",
            "price_type": "LMT",
            "order_cond": "Cash",
            "order_lot": "Common",
            "custom_field": "",
        },
        "status": {
            "id": "bdd-order",
            "exchange_ts": context["exchange_ts"],
            "modified_price": modified_price,
            "cancel_quantity": cancel_quantity,
            "order_quantity": order_quantity if op_type == "New" else 0,
            "web_id": "137",
        },
        "contract": {"security_type": "STK", "exchange": "TSE", "code": "2330"},
    }


def create_deal_event(exchange_seq, price, quantity):
    """Create a StockDeal payload matching real Shioaji reports."""
    return {
        "trade_id": "bdd-order",
        "seqno": "000001",
        "ordno": "A0001",
        "exchange_seq": exchange_seq,
        "broker_id": "9100",
        "account_id": "1234567",
        "action": "Buy",
        "code": "2330",
        "order_cond": "Cash",
        "order_lot": "Common",
        "price": price,
        "quantity": quantity,
        "web_id": "137",
        "custom_field": "",
        "ts": 1770000001.0,
    }


@pytest.fixture
def context():
    """Create a sync around one Local Native Trade and capture user observations."""
    trade = create_native_trade()
    api = Mock()
    api.set_order_callback = Mock()
    api.list_accounts = Mock(return_value=[])
    api.list_positions = Mock(return_value=[])
    api.update_status = Mock()
    api.list_trades = Mock(return_value=[trade])
    api.stock_account = trade.order.account
    api.Contracts = Mock()
    api.Contracts.Stocks = {}
    sync = PositionSync(api)
    observed = []
    sync.set_order_callback(lambda _state, _data: observed.append(trade_fields(trade)))
    test_context = {
        "api": api,
        "sync": sync,
        "trade": trade,
        "observed": observed,
        "exchange_ts": 1770000000.0,
    }
    yield test_context
    sync.close()


@given(
    "Shioaji 1.2 或 1.3 的 Local Native Trade 初始狀態為 PendingSubmit，委託價 100.0，原始委託量 2"
)
def initial_local_native_trade(context):
    """Expose the fixture's initial public Trade state."""
    assert trade_fields(context["trade"]) == {
        "status": "PendingSubmit",
        "price": 100.0,
        "quantity": 2,
        "modified_price": 0.0,
        "cancel_quantity": 0,
        "deal_quantity": 0,
        "deals": 0,
    }


@given("已收到 New 成功回報")
def accepted_new_order(context):
    """Move the Local Trade to Submitted through the public callback."""
    event = create_order_event(context, "New", "00", 100.0, 2, 0.0, 0)
    context["api"].set_order_callback.call_args.args[0](OrderState.StockOrder, event)


@when(
    parsers.parse(
        "收到 {op_type} 委託回報，op_code {op_code}，order.price {order_price:f}，order.quantity {order_quantity:d}，modified_price {modified_price:f}，cancel_quantity {cancel_quantity:d}"
    )
)
def receive_order_report(
    context,
    op_type,
    op_code,
    order_price,
    order_quantity,
    modified_price,
    cancel_quantity,
):
    """Deliver an order report through Shioaji's registered callback."""
    event = create_order_event(
        context,
        op_type,
        op_code,
        order_price,
        order_quantity,
        modified_price,
        cancel_quantity,
    )
    context["api"].set_order_callback.call_args.args[0](OrderState.StockOrder, event)


@when(
    parsers.parse(
        "收到成交回報 exchange_seq {exchange_seq}，price {price:f}，quantity {quantity:d}"
    )
)
def receive_deal_report(context, exchange_seq, price, quantity):
    """Deliver a unique deal report through Shioaji's registered callback."""
    event = create_deal_event(exchange_seq, price, quantity)
    context["api"].set_order_callback.call_args.args[0](OrderState.StockDeal, event)


@when(
    parsers.parse(
        "再次收到相同成交回報 exchange_seq {exchange_seq}，price {price:f}，quantity {quantity:d}"
    )
)
def receive_duplicate_deal_report(context, exchange_seq, price, quantity):
    """Deliver the exact same deal identity a second time."""
    receive_deal_report(context, exchange_seq, price, quantity)


def expected_fields(
    status,
    price,
    quantity,
    modified_price,
    cancel_quantity,
    deal_quantity,
    deals,
):
    return {
        "status": status,
        "price": price,
        "quantity": quantity,
        "modified_price": modified_price,
        "cancel_quantity": cancel_quantity,
        "deal_quantity": deal_quantity,
        "deals": deals,
    }


@then(
    parsers.parse(
        "Trade 七個欄位應為 status {status}、order.price {price:f}、order.quantity {quantity:d}、modified_price {modified_price:f}、cancel_quantity {cancel_quantity:d}、deal_quantity {deal_quantity:d}、deals {deals:d} 筆"
    )
)
def assert_trade_fields(
    context,
    status,
    price,
    quantity,
    modified_price,
    cancel_quantity,
    deal_quantity,
    deals,
):
    """Assert every required Trade field as one coherent public state."""
    assert trade_fields(context["trade"]) == expected_fields(
        status,
        price,
        quantity,
        modified_price,
        cancel_quantity,
        deal_quantity,
        deals,
    )


@then(
    parsers.parse(
        "使用者 callback 觀察到 status {status}、order.price {price:f}、order.quantity {quantity:d}、modified_price {modified_price:f}、cancel_quantity {cancel_quantity:d}、deal_quantity {deal_quantity:d}、deals {deals:d} 筆"
    )
)
def assert_user_callback_fields(
    context,
    status,
    price,
    quantity,
    modified_price,
    cancel_quantity,
    deal_quantity,
    deals,
):
    """Assert Trade projection completed before the user callback."""
    assert context["observed"][-1] == expected_fields(
        status,
        price,
        quantity,
        modified_price,
        cancel_quantity,
        deal_quantity,
        deals,
    )


@then(parsers.parse("Trade status_code 應為 {status_code}，msg 應為 {message}"))
def assert_status_error(context, status_code, message):
    """Assert operation result metadata without inspecting internals."""
    trade = context["trade"]
    assert trade.status.status_code == status_code
    assert trade.status.msg == message


@then(
    parsers.parse(
        "第 {index:d} 筆 deal 應為 exchange_seq {exchange_seq}、price {price:f}、quantity {quantity:d}"
    )
)
def assert_deal(context, index, exchange_seq, price, quantity):
    """Assert the Native Deal appended from exchange report fields."""
    deal = context["trade"].status.deals[index - 1]
    assert str(deal.seq) == exchange_seq
    assert float(deal.price) == price
    assert int(deal.quantity) == quantity
