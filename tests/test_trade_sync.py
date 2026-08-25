"""Public behavior tests for live Native Trade synchronization."""

from unittest.mock import Mock
from copy import deepcopy
import datetime
import threading
import time

import pytest

from sj_sync import PositionSync
from sj_sync.shioaji_compat import AccountType, OrderState, Status, Trade, sj


LIVE_TRADE_SYNC_SUPPORTED = tuple(
    int(part) for part in sj.__version__.split(".")[:2]
) in {(1, 2), (1, 3)}


@pytest.fixture(autouse=True)
def require_live_trade_sync_or_explicit_disabled_test(request):
    """Run live-mutation cases only on supported Shioaji versions."""
    if LIVE_TRADE_SYNC_SUPPORTED:
        return
    if request.node.get_closest_marker("runs_without_live_trade_sync") is None:
        pytest.skip("Live Trade synchronization is supported on Shioaji 1.2/1.3")


def create_native_trade(order_id: str = "order-1", account_id: str = "1234567") -> Mock:
    """Create the Native Trade shape returned by the Shioaji boundary."""
    trade = Mock()
    trade.order.id = order_id
    trade.order.account.broker_id = "9100"
    trade.order.account.account_id = account_id
    trade.order.price = 100.0
    trade.order.quantity = 2
    trade.status.status = Status.PendingSubmit
    trade.status.status_code = ""
    trade.status.msg = ""
    trade.status.order_quantity = 2
    trade.status.deal_quantity = 0
    trade.status.cancel_quantity = 0
    trade.status.deals = []
    return trade


def create_stock_order_event(order_id: str = "order-1") -> dict:
    return {
        "operation": {"op_type": "New", "op_code": "00", "op_msg": ""},
        "order": {
            "id": order_id,
            "seqno": "000001",
            "ordno": "A0001",
            "account": {"broker_id": "9100", "account_id": "1234567"},
            "action": "Buy",
            "price": 100.0,
            "quantity": 2,
            "order_type": "ROD",
            "price_type": "LMT",
            "order_cond": "Cash",
            "order_lot": "Common",
            "custom_field": "",
        },
        "status": {
            "id": order_id,
            "exchange_ts": 1770000000.0,
            "modified_price": 0.0,
            "cancel_quantity": 0,
            "order_quantity": 2,
            "web_id": "137",
        },
        "contract": {"security_type": "STK", "exchange": "TSE", "code": "2330"},
    }


def create_stock_deal_event(order_id: str = "order-1", quantity: int = 1) -> dict:
    return {
        "trade_id": order_id,
        "seqno": "000001",
        "ordno": "A0001",
        "exchange_seq": "deal-1",
        "broker_id": "9100",
        "account_id": "1234567",
        "action": "Buy",
        "code": "2330",
        "order_cond": "Cash",
        "order_lot": "Common",
        "price": 100.0,
        "quantity": quantity,
        "web_id": "137",
        "custom_field": "",
        "ts": 1770000001.0,
    }


def create_futures_order_event(order_id: str = "future-1") -> dict:
    event = create_stock_order_event(order_id)
    event["order"] = {
        "id": order_id,
        "seqno": "000002",
        "ordno": "F0001",
        "account": {
            "account_type": "F",
            "broker_id": "9100",
            "account_id": "7654321",
        },
        "action": "Buy",
        "price": 20000.0,
        "quantity": 1,
        "order_type": "ROD",
        "price_type": "LMT",
        "oc_type": "Auto",
        "market_type": "Day",
        "custom_field": "",
    }
    event["status"]["order_quantity"] = 1
    event["contract"] = {
        "security_type": "FUT",
        "exchange": "TAIFEX",
        "code": "TXF",
        "full_code": "TXFH6",
        "delivery_month": "202608",
        "option_right": "Future",
    }
    return event


def create_futures_deal_event(order_id: str = "future-1") -> dict:
    return {
        "trade_id": order_id,
        "seqno": "000002",
        "ordno": "F0001001",
        "exchange_seq": "future-deal-1",
        "broker_id": "9100",
        "account_id": "7654321",
        "action": "Buy",
        "code": "TXF",
        "full_code": "TXFH6",
        "price": 20000.0,
        "quantity": 1,
        "subaccount": "",
        "security_type": "FUT",
        "delivery_month": "202608",
        "strike_price": 0.0,
        "option_right": "Future",
        "market_type": "Day",
        "combo": False,
        "ts": 1770000002.0,
    }


def test_list_trades_returns_the_local_native_trade_reference(mock_api):
    native_trade = create_native_trade()
    mock_api.list_trades.return_value = [native_trade]

    sync = PositionSync(mock_api)

    assert sync.list_trades()[0] is native_trade


def test_local_order_is_updated_before_the_user_callback(mock_api):
    native_trade = create_native_trade()
    mock_api.list_trades.return_value = [native_trade]
    sync = PositionSync(mock_api)
    observed_statuses = []
    sync.set_order_callback(
        lambda _state, _data: observed_statuses.append(native_trade.status.status)
    )

    api_callback = mock_api.set_order_callback.call_args.args[0]
    api_callback(OrderState.StockOrder, create_stock_order_event())

    assert observed_statuses == [Status.Submitted]


@pytest.mark.runs_without_live_trade_sync
def test_runtime_callbacks_do_not_poll_list_trades(mock_api):
    native_trade = create_native_trade()
    mock_api.list_trades.return_value = [native_trade]
    PositionSync(mock_api)
    mock_api.list_trades.reset_mock()
    api_callback = mock_api.set_order_callback.call_args.args[0]

    api_callback(OrderState.StockOrder, create_stock_order_event())
    api_callback(OrderState.StockDeal, create_stock_deal_event())

    mock_api.list_trades.assert_not_called()


@pytest.mark.runs_without_live_trade_sync
def test_live_trade_updates_are_disabled_for_shioaji_1_5(mock_api, monkeypatch):
    import sj_sync.position_sync as position_sync_module

    monkeypatch.setattr(position_sync_module.sj, "__version__", "1.5.6")
    snapshot = create_native_trade()
    mock_api.list_trades.return_value = [snapshot]
    sync = PositionSync(mock_api)
    observed = []
    sync.set_order_callback(lambda state, data: observed.append((state, data)))

    api_callback = mock_api.set_order_callback.call_args.args[0]
    event = create_stock_order_event()
    api_callback(OrderState.StockOrder, event)

    assert snapshot.status.status == Status.PendingSubmit
    assert observed == [(OrderState.StockOrder, event)]

    update_event = deepcopy(event)
    update_event["operation"]["op_type"] = "UpdatePrice"
    api_callback(OrderState.StockOrder, update_event)

    assert observed[-1] == (OrderState.StockOrder, update_event)
    sync.close()


@pytest.mark.runs_without_live_trade_sync
def test_disabled_live_sync_delegates_list_trades(mock_api, monkeypatch):
    import sj_sync.position_sync as position_sync_module

    monkeypatch.setattr(position_sync_module.sj, "__version__", "1.5.6")
    first_snapshot = create_native_trade("first")
    second_snapshot = create_native_trade("second")
    mock_api.list_trades.return_value = [first_snapshot]
    sync = PositionSync(mock_api)

    first_result = sync.list_trades()
    mock_api.list_trades.return_value = [second_snapshot]
    second_result = sync.list_trades()

    assert first_result == [first_snapshot]
    assert second_result == [second_snapshot]
    assert first_result is not second_result
    sync.close()


def test_duplicate_deal_is_applied_to_trade_and_position_once(mock_api):
    native_trade = create_native_trade()
    mock_api.list_trades.return_value = [native_trade]
    sync = PositionSync(mock_api)
    api_callback = mock_api.set_order_callback.call_args.args[0]
    deal = create_stock_deal_event()

    api_callback(OrderState.StockDeal, deal)
    api_callback(OrderState.StockDeal, deal)

    assert native_trade.status.deal_quantity == 1
    assert len(native_trade.status.deals) == 1
    assert native_trade.status.deals[0].seq == "deal-1"
    assert native_trade.status.deals[0].price == 100.0
    assert native_trade.status.deals[0].quantity == 1
    assert sync.list_positions()[0].quantity == 1


def test_external_order_becomes_a_sync_owned_native_trade(mock_api):
    mock_api.list_trades.return_value = []
    sync = PositionSync(mock_api)
    api_callback = mock_api.set_order_callback.call_args.args[0]

    api_callback(OrderState.StockOrder, create_stock_order_event("external-1"))

    deadline = time.monotonic() + 2
    trades = sync.list_trades()
    while not trades and time.monotonic() < deadline:
        time.sleep(0.02)
        trades = sync.list_trades()

    assert isinstance(trades[0], Trade)
    assert trades[0].order.id == "external-1"
    sync.close()


def test_callback_before_place_order_return_keeps_the_local_reference(mock_api):
    native_trade = create_native_trade("local-race")
    mock_api.list_trades.return_value = []
    sync = PositionSync(mock_api)
    api_callback = mock_api.set_order_callback.call_args.args[0]

    api_callback(OrderState.StockOrder, create_stock_order_event("local-race"))
    mock_api.list_trades.return_value = [native_trade]

    deadline = time.monotonic() + 2
    while (
        native_trade.status.status != Status.Submitted and time.monotonic() < deadline
    ):
        time.sleep(0.02)

    assert sync.list_trades()[0] is native_trade
    sync.close()


def test_deal_before_external_order_is_replayed_into_the_trade(mock_api):
    mock_api.list_trades.return_value = []
    sync = PositionSync(mock_api)
    api_callback = mock_api.set_order_callback.call_args.args[0]

    api_callback(OrderState.StockDeal, create_stock_deal_event("external-deal"))
    api_callback(OrderState.StockOrder, create_stock_order_event("external-deal"))

    deadline = time.monotonic() + 2
    trades = sync.list_trades()
    while not trades and time.monotonic() < deadline:
        time.sleep(0.02)
        trades = sync.list_trades()

    assert trades[0].status.status == Status.PartFilled
    assert trades[0].status.deal_quantity == 1
    assert sync.list_positions()[0].quantity == 1
    sync.close()


def test_user_callback_can_close_sync_from_trade_worker(mock_api):
    mock_api.list_trades.return_value = []
    sync = PositionSync(mock_api)
    closed = threading.Event()

    def close_from_callback(_state, _data):
        sync.close()
        closed.set()

    sync.set_order_callback(close_from_callback)
    api_callback = mock_api.set_order_callback.call_args.args[0]

    api_callback(OrderState.StockOrder, create_stock_order_event("worker-close"))

    assert closed.wait(2)


def test_cancelled_trade_does_not_regress_on_an_older_order_report(mock_api):
    native_trade = create_native_trade()
    mock_api.list_trades.return_value = [native_trade]
    PositionSync(mock_api)
    api_callback = mock_api.set_order_callback.call_args.args[0]
    new_event = create_stock_order_event()
    cancel_event = deepcopy(new_event)
    cancel_event["operation"]["op_type"] = "Cancel"
    cancel_event["status"]["exchange_ts"] += 2
    cancel_event["status"]["cancel_quantity"] = 2

    api_callback(OrderState.StockOrder, new_event)
    api_callback(OrderState.StockOrder, cancel_event)
    stale_event = deepcopy(new_event)
    stale_event["operation"]["op_type"] = "UpdatePrice"
    stale_event["status"]["exchange_ts"] -= 1
    stale_event["status"]["modified_price"] = 99.0
    api_callback(OrderState.StockOrder, stale_event)

    assert native_trade.status.status == Status.Cancelled
    assert native_trade.status.cancel_quantity == 2
    assert native_trade.order.price == 100.0


def test_close_stops_unresolved_order_classification(mock_api):
    mock_api.list_trades.return_value = []
    sync = PositionSync(mock_api)
    observed = []
    sync.set_order_callback(lambda state, data: observed.append((state, data)))
    api_callback = mock_api.set_order_callback.call_args.args[0]

    api_callback(OrderState.StockOrder, create_stock_order_event("closing"))
    sync.close()
    sync.close()

    assert sync.list_trades() == []
    assert observed == []


def test_context_manager_closes_callback_processing(mock_api):
    native_trade = create_native_trade()
    mock_api.list_trades.return_value = [native_trade]

    with PositionSync(mock_api) as sync:
        assert sync.list_trades() == [native_trade]
        api_callback = mock_api.set_order_callback.call_args.args[0]

    api_callback(OrderState.StockOrder, create_stock_order_event())

    assert native_trade.status.status == Status.PendingSubmit


def test_initialization_tracks_trades_after_one_status_reconciliation(mock_api):
    native_trade = create_native_trade("startup")

    def reconcile(*_args, **_kwargs):
        mock_api.list_trades.return_value = [native_trade]

    mock_api.update_status.side_effect = reconcile

    sync = PositionSync(mock_api)

    assert sync.list_trades()[0] is native_trade
    mock_api.update_status.assert_called_once()


def test_manual_reconciliation_replays_a_deferred_deal(mock_api):
    mock_api.list_trades.return_value = []
    sync = PositionSync(mock_api)
    api_callback = mock_api.set_order_callback.call_args.args[0]
    api_callback(OrderState.StockDeal, create_stock_deal_event("reconciled"))
    native_trade = create_native_trade("reconciled")
    mock_api.list_trades.return_value = [native_trade]

    sync.sync_from_api()

    assert native_trade.status.deal_quantity == 1
    assert sync.list_positions()[0].quantity == 1


def test_manual_reconciliation_discards_still_unresolved_orders(mock_api):
    mock_api.list_trades.return_value = []
    sync = PositionSync(mock_api)
    api_callback = mock_api.set_order_callback.call_args.args[0]
    api_callback(OrderState.StockOrder, create_stock_order_event("missing"))

    sync.sync_from_api()
    time.sleep(1.05)

    assert sync.list_trades() == []
    sync.close()


def test_manual_reconciliation_discards_unresolved_deals_and_updates(mock_api):
    mock_api.list_trades.return_value = []
    sync = PositionSync(mock_api)
    observed = []
    sync.set_order_callback(lambda state, data: observed.append((state, data)))
    api_callback = mock_api.set_order_callback.call_args.args[0]
    api_callback(OrderState.StockDeal, create_stock_deal_event("missing-reports"))
    update_event = create_stock_order_event("missing-reports")
    update_event["operation"]["op_type"] = "Cancel"
    api_callback(OrderState.StockOrder, update_event)

    sync.sync_from_api()

    assert sync.list_trades() == []
    assert observed == [
        (OrderState.StockDeal, create_stock_deal_event("missing-reports"))
    ]
    sync.close()


def test_account_reconciliation_keeps_other_accounts_deferred_deals(mock_api):
    mock_api.list_trades.return_value = []
    sync = PositionSync(mock_api)
    api_callback = mock_api.set_order_callback.call_args.args[0]
    api_callback(OrderState.FuturesDeal, create_futures_deal_event("other-account"))

    sync.sync_from_api(account=mock_api.stock_account)
    native_trade = create_native_trade("other-account", account_id="7654321")
    native_trade.order.quantity = 1
    native_trade.status.order_quantity = 1
    mock_api.list_trades.return_value = [native_trade]

    sync.list_trades()

    assert native_trade.status.deal_quantity == 1


def test_cancel_report_waits_for_an_existing_local_trade_reference(mock_api):
    mock_api.list_trades.return_value = []
    sync = PositionSync(mock_api)
    observed = []
    sync.set_order_callback(lambda state, data: observed.append((state, data)))
    api_callback = mock_api.set_order_callback.call_args.args[0]
    cancel_event = create_stock_order_event("late-local")
    cancel_event["operation"]["op_type"] = "Cancel"

    api_callback(OrderState.StockOrder, cancel_event)
    native_trade = create_native_trade("late-local")
    mock_api.list_trades.return_value = [native_trade]
    sync.list_trades()

    assert native_trade.status.status == Status.Cancelled
    assert len(observed) == 1


def test_external_futures_order_and_deal_update_trade_and_position(mock_api):
    from tests.conftest import create_mock_account

    mock_api.futopt_account = create_mock_account("9100", "7654321", AccountType.Future)
    mock_api.list_trades.return_value = []
    sync = PositionSync(mock_api)
    api_callback = mock_api.set_order_callback.call_args.args[0]
    api_callback(OrderState.FuturesOrder, create_futures_order_event())

    deadline = time.monotonic() + 2
    trades = sync.list_trades()
    while not trades and time.monotonic() < deadline:
        time.sleep(0.02)
        trades = sync.list_trades()
    api_callback(OrderState.FuturesDeal, create_futures_deal_event())

    assert trades[0].status.status == Status.Filled
    assert sync.list_positions(account=mock_api.futopt_account)[0].code == "TXFH6"
    sync.close()


@pytest.mark.parametrize(
    ("option_right", "native_right"),
    [("OptionCall", "C"), ("OptionPut", "P")],
)
def test_external_option_order_normalizes_option_right(
    mock_api, option_right, native_right
):
    from tests.conftest import create_mock_account

    mock_api.futopt_account = create_mock_account("9100", "7654321", AccountType.Future)
    mock_api.list_trades.return_value = []
    sync = PositionSync(mock_api)
    event = create_futures_order_event(f"option-{native_right}")
    event["contract"].update(
        {
            "security_type": "OPT",
            "code": "TXO",
            "full_code": f"TXO20000{native_right}6",
            "strike_price": 20000.0,
            "option_right": option_right,
        }
    )

    mock_api.set_order_callback.call_args.args[0](OrderState.FuturesOrder, event)

    deadline = time.monotonic() + 2
    trades = sync.list_trades()
    while not trades and time.monotonic() < deadline:
        time.sleep(0.02)
        trades = sync.list_trades()

    assert trades[0].contract.option_right.value == native_right
    sync.close()


def test_invalid_external_order_is_rejected_without_user_notification(mock_api):
    mock_api.list_trades.return_value = []
    sync = PositionSync(mock_api)
    observed = []
    sync.set_order_callback(lambda state, data: observed.append((state, data)))
    event = create_stock_order_event("invalid-external")
    event["order"]["action"] = "InvalidAction"

    mock_api.set_order_callback.call_args.args[0](OrderState.StockOrder, event)
    time.sleep(1.05)

    assert sync.list_trades() == []
    assert observed == []
    sync.close()


def test_update_price_preserves_original_price_and_records_modified_price(mock_api):
    native_trade = create_native_trade()
    native_trade.status.status = Status.Submitted
    mock_api.list_trades.return_value = [native_trade]
    PositionSync(mock_api)
    api_callback = mock_api.set_order_callback.call_args.args[0]
    event = create_stock_order_event()
    event["operation"]["op_type"] = "UpdatePrice"
    event["order"]["price"] = 100.0
    event["status"]["modified_price"] = 101.0

    api_callback(OrderState.StockOrder, event)

    assert native_trade.order.price == 100.0
    assert native_trade.status.modified_price == 101.0
    assert native_trade.status.status == Status.Submitted


def test_update_quantity_keeps_original_quantity_and_tracks_cancelled_quantity(
    mock_api,
):
    native_trade = create_native_trade()
    native_trade.status.status = Status.PartFilled
    mock_api.list_trades.return_value = [native_trade]
    PositionSync(mock_api)
    api_callback = mock_api.set_order_callback.call_args.args[0]
    event = create_stock_order_event()
    event["operation"]["op_type"] = "UpdateQty"
    event["status"]["cancel_quantity"] = 1
    event["status"]["order_quantity"] = 0

    api_callback(OrderState.StockOrder, event)

    assert native_trade.order.quantity == 2
    assert native_trade.status.cancel_quantity == 1
    assert native_trade.status.status == Status.PartFilled


def test_external_order_reduction_then_cancel_accumulates_cancel_quantity(mock_api):
    mock_api.list_trades.return_value = []
    sync = PositionSync(mock_api)
    api_callback = mock_api.set_order_callback.call_args.args[0]
    new_event = create_stock_order_event("external-reduce-cancel")
    api_callback(OrderState.StockOrder, new_event)

    deadline = time.monotonic() + 2
    trades = sync.list_trades()
    while not trades and time.monotonic() < deadline:
        time.sleep(0.02)
        trades = sync.list_trades()

    update_event = deepcopy(new_event)
    update_event["operation"]["op_type"] = "UpdateQty"
    update_event["status"]["exchange_ts"] += 1
    update_event["status"]["order_quantity"] = 1
    update_event["status"]["cancel_quantity"] = 1
    api_callback(OrderState.StockOrder, update_event)

    cancel_event = deepcopy(new_event)
    cancel_event["operation"]["op_type"] = "Cancel"
    cancel_event["status"]["exchange_ts"] += 2
    cancel_event["status"]["order_quantity"] = 0
    cancel_event["status"]["cancel_quantity"] = 1
    api_callback(OrderState.StockOrder, cancel_event)

    assert trades[0].status.status == Status.Cancelled
    assert trades[0].status.cancel_quantity == 2
    sync.close()


def test_external_order_cancel_preserves_previous_modified_price(mock_api):
    mock_api.list_trades.return_value = []
    sync = PositionSync(mock_api)
    api_callback = mock_api.set_order_callback.call_args.args[0]
    new_event = create_stock_order_event("external-price-cancel")
    api_callback(OrderState.StockOrder, new_event)

    deadline = time.monotonic() + 2
    trades = sync.list_trades()
    while not trades and time.monotonic() < deadline:
        time.sleep(0.02)
        trades = sync.list_trades()

    update_event = deepcopy(new_event)
    update_event["operation"]["op_type"] = "UpdatePrice"
    update_event["status"]["exchange_ts"] += 1
    update_event["status"]["modified_price"] = 101.0
    api_callback(OrderState.StockOrder, update_event)

    cancel_event = deepcopy(new_event)
    cancel_event["operation"]["op_type"] = "Cancel"
    cancel_event["status"]["exchange_ts"] += 2
    cancel_event["status"]["cancel_quantity"] = 2
    api_callback(OrderState.StockOrder, cancel_event)

    assert trades[0].status.status == Status.Cancelled
    assert trades[0].order.price == 100.0
    assert trades[0].status.modified_price == 101.0
    sync.close()


@pytest.mark.parametrize("op_type", ["UpdatePrice", "UpdateQty", "Cancel"])
def test_failed_order_operation_preserves_existing_trade_state(mock_api, op_type):
    native_trade = create_native_trade()
    native_trade.status.status = Status.Submitted
    native_trade.status.modified_price = 101.0
    original_modified_time = datetime.datetime(
        2026, 8, 25, 9, 30, tzinfo=datetime.timezone(datetime.timedelta(hours=8))
    )
    native_trade.status.modified_time = original_modified_time
    mock_api.list_trades.return_value = [native_trade]
    sync = PositionSync(mock_api)
    event = create_stock_order_event()
    event["operation"].update(
        {"op_type": op_type, "op_code": "E003", "op_msg": "rejected"}
    )
    event["status"]["order_quantity"] = 1
    event["status"]["cancel_quantity"] = 1
    event["status"]["modified_price"] = 0.0

    mock_api.set_order_callback.call_args.args[0](OrderState.StockOrder, event)

    assert native_trade.status.status == Status.Submitted
    assert native_trade.status.order_quantity == 2
    assert native_trade.status.cancel_quantity == 0
    assert native_trade.status.modified_price == 101.0
    assert native_trade.status.modified_time == original_modified_time
    assert native_trade.status.status_code == "E003"
    assert native_trade.status.msg == "rejected"
    sync.close()


def test_last_successful_modified_price_survives_a_failed_update(mock_api):
    native_trade = create_native_trade()
    native_trade.status.status = Status.Submitted
    native_trade.status.modified_price = 0.0
    mock_api.list_trades.return_value = [native_trade]
    sync = PositionSync(mock_api)
    api_callback = mock_api.set_order_callback.call_args.args[0]
    new_event = create_stock_order_event()

    first_update = deepcopy(new_event)
    first_update["operation"]["op_type"] = "UpdatePrice"
    first_update["status"]["exchange_ts"] += 1
    first_update["status"]["modified_price"] = 101.0
    api_callback(OrderState.StockOrder, first_update)

    second_update = deepcopy(new_event)
    second_update["operation"]["op_type"] = "UpdatePrice"
    second_update["status"]["exchange_ts"] += 2
    second_update["status"]["modified_price"] = 102.0
    api_callback(OrderState.StockOrder, second_update)

    failed_update = deepcopy(new_event)
    failed_update["operation"].update(
        {"op_type": "UpdatePrice", "op_code": "E004", "op_msg": "rejected"}
    )
    failed_update["status"]["exchange_ts"] += 3
    failed_update["status"]["modified_price"] = 999.0
    api_callback(OrderState.StockOrder, failed_update)

    assert native_trade.order.price == 100.0
    assert native_trade.status.modified_price == 102.0
    assert native_trade.status.status == Status.Submitted
    assert native_trade.status.status_code == "E004"
    sync.close()


def test_sparse_success_report_preserves_omitted_status_fields(mock_api):
    native_trade = create_native_trade()
    native_trade.status.status = Status.Submitted
    native_trade.status.web_id = "137"
    mock_api.list_trades.return_value = [native_trade]
    sync = PositionSync(mock_api)
    event = create_stock_order_event()
    event["operation"]["op_type"] = "UpdatePrice"
    event["status"]["modified_price"] = 101.0
    event["status"].pop("order_quantity")
    event["status"].pop("web_id")

    mock_api.set_order_callback.call_args.args[0](OrderState.StockOrder, event)

    assert native_trade.status.modified_price == 101.0
    assert native_trade.status.order_quantity == 2
    assert native_trade.status.web_id == "137"
    sync.close()


def test_duplicate_quantity_and_cancel_reports_do_not_double_count(mock_api):
    native_trade = create_native_trade()
    native_trade.status.status = Status.Submitted
    mock_api.list_trades.return_value = [native_trade]
    sync = PositionSync(mock_api)
    api_callback = mock_api.set_order_callback.call_args.args[0]
    new_event = create_stock_order_event()

    update_event = deepcopy(new_event)
    update_event["operation"]["op_type"] = "UpdateQty"
    update_event["status"]["exchange_ts"] += 1
    update_event["status"]["order_quantity"] = 1
    update_event["status"]["cancel_quantity"] = 1
    api_callback(OrderState.StockOrder, update_event)
    api_callback(OrderState.StockOrder, update_event)

    cancel_event = deepcopy(new_event)
    cancel_event["operation"]["op_type"] = "Cancel"
    cancel_event["status"]["exchange_ts"] += 2
    cancel_event["status"]["order_quantity"] = 0
    cancel_event["status"]["cancel_quantity"] = 1
    api_callback(OrderState.StockOrder, cancel_event)
    api_callback(OrderState.StockOrder, cancel_event)

    assert native_trade.status.status == Status.Cancelled
    assert native_trade.status.cancel_quantity == 2
    sync.close()


def test_partial_fill_reduction_and_cancel_account_for_original_quantity(mock_api):
    native_trade = create_native_trade()
    native_trade.order.quantity = 4
    native_trade.status.order_quantity = 4
    native_trade.status.status = Status.Submitted
    mock_api.list_trades.return_value = [native_trade]
    sync = PositionSync(mock_api)
    api_callback = mock_api.set_order_callback.call_args.args[0]

    api_callback(OrderState.StockDeal, create_stock_deal_event(quantity=1))

    update_event = create_stock_order_event()
    update_event["operation"]["op_type"] = "UpdateQty"
    update_event["status"]["exchange_ts"] += 1
    update_event["status"]["order_quantity"] = 2
    update_event["status"]["cancel_quantity"] = 1
    api_callback(OrderState.StockOrder, update_event)

    cancel_event = create_stock_order_event()
    cancel_event["operation"]["op_type"] = "Cancel"
    cancel_event["status"]["exchange_ts"] += 2
    cancel_event["status"]["order_quantity"] = 0
    cancel_event["status"]["cancel_quantity"] = 2
    api_callback(OrderState.StockOrder, cancel_event)

    assert native_trade.status.status == Status.Cancelled
    assert native_trade.status.deal_quantity == 1
    assert native_trade.status.cancel_quantity == 3
    assert (
        native_trade.status.deal_quantity + native_trade.status.cancel_quantity
        == native_trade.order.quantity
    )
    sync.close()


def test_combo_deal_does_not_project_into_trade(mock_api):
    mock_api.list_trades.return_value = []
    sync = PositionSync(mock_api)
    observed = []
    sync.set_order_callback(lambda state, data: observed.append((state, data)))
    api_callback = mock_api.set_order_callback.call_args.args[0]
    event = create_futures_deal_event("combo-order")
    event["combo"] = True

    api_callback(OrderState.FuturesDeal, event)
    native_trade = create_native_trade("combo-order", account_id="7654321")
    mock_api.list_trades.return_value = [native_trade]
    sync.list_trades()

    assert native_trade.status.deal_quantity == 0
    assert observed == [(OrderState.FuturesDeal, event)]


def test_older_deal_does_not_regress_a_cancelled_trade(mock_api):
    native_trade = create_native_trade()
    mock_api.list_trades.return_value = [native_trade]
    PositionSync(mock_api)
    api_callback = mock_api.set_order_callback.call_args.args[0]
    cancel_event = create_stock_order_event()
    cancel_event["operation"]["op_type"] = "Cancel"
    cancel_event["status"]["exchange_ts"] = 1770000002.0

    api_callback(OrderState.StockOrder, cancel_event)
    api_callback(OrderState.StockDeal, create_stock_deal_event())

    assert native_trade.status.status == Status.Cancelled
    assert native_trade.status.deal_quantity == 1
