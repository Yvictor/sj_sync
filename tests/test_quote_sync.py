"""Tests for QuoteSync."""

import datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest
from shioaji.constant import ChangeType, QuoteType, TickType
from shioaji.data import Snapshot

from sj_sync.quote_sync import QuoteSync, _datetime_to_ns


# -- Helpers --


def make_contract(code: str) -> Mock:
    contract = Mock()
    contract.code = code
    return contract


def make_tick(code: str, **overrides) -> Mock:
    defaults = dict(
        code=code,
        datetime=datetime.datetime(2026, 5, 4, 10, 43, 42, 920445),
        close=Decimal("600.0"),
        open=Decimal("595.0"),
        high=Decimal("605.0"),
        low=Decimal("590.0"),
        volume=10,
        total_volume=5000,
        amount=Decimal("6000000"),
        total_amount=Decimal("3000000000"),
        tick_type=1,
        avg_price=Decimal("598.5"),
        price_chg=Decimal("5.0"),
        pct_chg=Decimal("0.84"),
        chg_type=2,
        simtrade=0,
    )
    defaults.update(overrides)
    tick = Mock()
    for k, v in defaults.items():
        setattr(tick, k, v)
    return tick


def make_bidask(code: str, **overrides) -> Mock:
    defaults = dict(
        code=code,
        datetime=datetime.datetime(2026, 5, 4, 10, 43, 41, 377377),
        bid_price=[Decimal("599.0"), Decimal("598.0"), Decimal("597.0")],
        bid_volume=[100, 200, 150],
        ask_price=[Decimal("600.0"), Decimal("601.0"), Decimal("602.0")],
        ask_volume=[80, 120, 90],
    )
    defaults.update(overrides)
    bidask = Mock()
    for k, v in defaults.items():
        setattr(bidask, k, v)
    return bidask


@pytest.fixture
def mock_quote_api():
    """Mock Shioaji API with quote-related methods."""
    api = Mock()
    api.quote.subscribe = Mock()
    api.quote.unsubscribe = Mock()
    api.quote.set_on_tick_stk_v1_callback = Mock()
    api.quote.set_on_tick_fop_v1_callback = Mock()
    api.quote.set_on_bidask_stk_v1_callback = Mock()
    api.quote.set_on_bidask_fop_v1_callback = Mock()

    # Contract resolution: Stocks has "2330" and "2317", Futures has "TXFH5"
    stock_2330 = make_contract("2330")
    stock_2317 = make_contract("2317")
    future_txf = make_contract("TXFH5")
    option_txo = make_contract("TXO19500C5")

    stocks_dict = {"2330": stock_2330, "2317": stock_2317}
    futures_dict = {"TXFH5": future_txf}
    options_dict = {"TXO19500C5": option_txo}

    api.Contracts.Stocks = Mock()
    api.Contracts.Stocks.get = Mock(side_effect=lambda c: stocks_dict.get(c))
    api.Contracts.Stocks.__contains__ = Mock(side_effect=lambda c: c in stocks_dict)
    api.Contracts.Stocks.__getitem__ = Mock(side_effect=lambda c: stocks_dict[c])

    api.Contracts.Futures = Mock()
    api.Contracts.Futures.get = Mock(side_effect=lambda c: futures_dict.get(c))
    api.Contracts.Futures.__contains__ = Mock(side_effect=lambda c: c in futures_dict)
    api.Contracts.Futures.__getitem__ = Mock(side_effect=lambda c: futures_dict[c])

    api.Contracts.Options = Mock()
    api.Contracts.Options.get = Mock(side_effect=lambda c: options_dict.get(c))
    api.Contracts.Options.__contains__ = Mock(side_effect=lambda c: c in options_dict)
    api.Contracts.Options.__getitem__ = Mock(side_effect=lambda c: options_dict[c])

    # Default: api.snapshots returns real Snapshot objects
    def mock_snapshots(contracts):
        result = []
        for c in contracts:
            snap = Snapshot()
            snap.code = c.code
            snap.close = 600.0
            snap.open = 595.0
            snap.high = 605.0
            snap.low = 590.0
            result.append(snap)
        return result

    api.snapshots = Mock(side_effect=mock_snapshots)
    return api


# -- TestQuoteSyncInit --


class TestQuoteSyncInit:
    def test_registers_all_four_callbacks(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        mock_quote_api.quote.set_on_tick_stk_v1_callback.assert_called_once_with(
            qs._on_tick_stk
        )
        mock_quote_api.quote.set_on_tick_fop_v1_callback.assert_called_once_with(
            qs._on_tick_fop
        )
        mock_quote_api.quote.set_on_bidask_stk_v1_callback.assert_called_once_with(
            qs._on_bidask_stk
        )
        mock_quote_api.quote.set_on_bidask_fop_v1_callback.assert_called_once_with(
            qs._on_bidask_fop
        )

    def test_empty_initial_state(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        assert qs._snapshots == {}
        assert qs._contracts == {}
        assert qs._subscribed == {}
        assert qs.snapshots() == []

    def test_no_user_callbacks_initially(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        assert qs._user_tick_stk_callback is None
        assert qs._user_tick_fop_callback is None
        assert qs._user_bidask_stk_callback is None
        assert qs._user_bidask_fop_callback is None


# -- TestQuoteSyncSubscribe --


class TestQuoteSyncSubscribe:
    def test_subscribe_fetches_initial_snapshots(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        mock_quote_api.snapshots.assert_called_once()
        snap = qs.snapshots(["2330"])[0]
        assert snap is not None
        assert snap.code == "2330"

    def test_subscribe_calls_api_quote_subscribe(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        contract = mock_quote_api.Contracts.Stocks.get("2330")
        mock_quote_api.quote.subscribe.assert_called_once_with(
            contract, quote_type=QuoteType.Tick
        )

    def test_subscribe_multiple_codes(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330", "2317"])
        assert len(qs.snapshots()) == 2
        assert mock_quote_api.quote.subscribe.call_count == 2

    def test_subscribe_with_contracts(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        contract = make_contract("2330")
        qs.subscribe(contracts=[contract])
        assert len(qs.snapshots(["2330"])) == 1

    def test_subscribe_with_both_codes_and_contracts(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        contract = make_contract("CUSTOM")
        # Need to make api.snapshots handle this too
        mock_quote_api.snapshots.side_effect = lambda cs: [Snapshot() for _ in cs]
        qs.subscribe(codes=["2330"], contracts=[contract])
        assert mock_quote_api.quote.subscribe.call_count == 2

    def test_subscribe_no_args_raises(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        with pytest.raises(ValueError, match="Must provide either"):
            qs.subscribe()

    def test_skip_existing_codes_no_duplicate_snapshot_fetch(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        mock_quote_api.snapshots.reset_mock()
        # Subscribe again with same code + new type
        qs.subscribe(codes=["2330"], quote_type=[QuoteType.BidAsk])
        # Should NOT call api.snapshots again for existing code
        mock_quote_api.snapshots.assert_not_called()

    def test_delta_subscribe_adds_bidask_to_tick(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"], quote_type=[QuoteType.Tick])
        mock_quote_api.quote.subscribe.reset_mock()
        qs.subscribe(codes=["2330"], quote_type=[QuoteType.BidAsk])
        # Only BidAsk should be subscribed (Tick already active)
        mock_quote_api.quote.subscribe.assert_called_once()
        call_args = mock_quote_api.quote.subscribe.call_args
        assert call_args[1]["quote_type"] == QuoteType.BidAsk

    def test_duplicate_subscribe_same_type_no_extra_call(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"], quote_type=[QuoteType.Tick])
        mock_quote_api.quote.subscribe.reset_mock()
        qs.subscribe(codes=["2330"], quote_type=[QuoteType.Tick])
        mock_quote_api.quote.subscribe.assert_not_called()

    def test_resolve_futures_contract(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["TXFH5"])
        assert len(qs.snapshots(["TXFH5"])) == 1

    def test_resolve_options_contract(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["TXO19500C5"])
        assert len(qs.snapshots(["TXO19500C5"])) == 1

    def test_unresolvable_code_raises(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        with pytest.raises(ValueError, match="Cannot resolve"):
            qs.subscribe(codes=["INVALID"])

    def test_snapshots_failure_logs_warning_continues(self, mock_quote_api):
        mock_quote_api.snapshots.side_effect = Exception("API error")
        qs = QuoteSync(mock_quote_api)
        # Should not raise
        qs.subscribe(codes=["2330"])
        # Snapshot should exist (empty) and subscription should proceed
        assert len(qs.snapshots(["2330"])) == 1
        mock_quote_api.quote.subscribe.assert_called_once()

    def test_subscribe_tick_and_bidask_together(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(
            codes=["2330"],
            quote_type=[QuoteType.Tick, QuoteType.BidAsk],
        )
        assert mock_quote_api.quote.subscribe.call_count == 2
        assert qs._subscribed["2330"] == {QuoteType.Tick, QuoteType.BidAsk}


# -- TestQuoteSyncUnsubscribe --


class TestQuoteSyncUnsubscribe:
    def test_full_unsubscribe_removes_all(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(
            codes=["2330"],
            quote_type=[QuoteType.Tick, QuoteType.BidAsk],
        )
        qs.unsubscribe(["2330"])
        assert "2330" not in qs._subscribed
        assert "2330" not in qs._snapshots
        assert "2330" not in qs._contracts
        assert mock_quote_api.quote.unsubscribe.call_count == 2

    def test_partial_unsubscribe_keeps_tick(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(
            codes=["2330"],
            quote_type=[QuoteType.Tick, QuoteType.BidAsk],
        )
        qs.unsubscribe(["2330"], quote_type=[QuoteType.BidAsk])
        assert "2330" in qs._subscribed
        assert qs._subscribed["2330"] == {QuoteType.Tick}
        assert len(qs.snapshots(["2330"])) == 1
        mock_quote_api.quote.unsubscribe.assert_called_once()

    def test_unsubscribe_unknown_code_no_error(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.unsubscribe(["UNKNOWN"])  # should not raise
        mock_quote_api.quote.unsubscribe.assert_not_called()

    def test_unsubscribe_type_not_subscribed(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"], quote_type=[QuoteType.Tick])
        qs.unsubscribe(["2330"], quote_type=[QuoteType.BidAsk])
        # BidAsk was never subscribed, so no unsubscribe call
        mock_quote_api.quote.unsubscribe.assert_not_called()
        # Tick should still be active
        assert qs._subscribed["2330"] == {QuoteType.Tick}


# -- TestQuoteSyncSnapshots --


class TestQuoteSyncSnapshots:
    def test_snapshots_all(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330", "2317"])
        result = qs.snapshots()
        assert len(result) == 2

    def test_snapshots_filtered_preserves_order(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330", "2317"])
        result = qs.snapshots(["2317", "2330"])
        assert result[0].code == "2317"
        assert result[1].code == "2330"

    def test_snapshots_filtered_skips_missing(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        result = qs.snapshots(["2330", "MISSING"])
        assert len(result) == 1

    def test_snapshots_single_code(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        result = qs.snapshots(["2330"])
        assert len(result) == 1
        assert isinstance(result[0], Snapshot)

    def test_snapshots_missing_returns_empty(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        assert qs.snapshots(["9999"]) == []

    def test_snapshots_filtered_by_contracts(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330", "2317"])
        contract = make_contract("2330")
        result = qs.snapshots([contract])
        assert len(result) == 1
        assert result[0].code == "2330"

    def test_snapshots_filtered_by_contracts_preserves_order(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330", "2317"])
        c1 = make_contract("2317")
        c2 = make_contract("2330")
        result = qs.snapshots([c1, c2])
        assert len(result) == 2
        assert result[0].code == "2317"
        assert result[1].code == "2330"

    def test_snapshots_returns_live_references(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        snap1 = qs.snapshots(["2330"])[0]
        snap2 = qs.snapshots(["2330"])[0]
        assert snap1 is snap2  # same object


# -- TestQuoteSyncTickCallbacks --


class TestQuoteSyncTickCallbacks:
    def test_tick_stk_updates_snapshot(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        tick = make_tick("2330", close=Decimal("610.0"), high=Decimal("615.0"))
        qs._on_tick_stk("TSE", tick)
        snap = qs.snapshots(["2330"])[0]
        assert snap.close == 610.0
        assert snap.high == 615.0

    def test_tick_stk_all_fields(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        tick = make_tick("2330")
        qs._on_tick_stk("TSE", tick)
        snap = qs.snapshots(["2330"])[0]
        assert snap.close == 600.0
        assert snap.open == 595.0
        assert snap.high == 605.0
        assert snap.low == 590.0
        assert snap.volume == 10
        assert snap.total_volume == 5000
        assert snap.amount == 6000000
        assert snap.total_amount == 3000000000
        assert snap.tick_type == TickType.Buy
        assert snap.average_price == 598.5
        assert snap.change_price == 5.0
        assert snap.change_rate == 0.84
        assert snap.change_type == ChangeType.Up

    def test_tick_fop_updates_snapshot(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["TXFH5"])
        tick = make_tick("TXFH5", close=Decimal("20000.0"))
        qs._on_tick_fop("TAIFEX", tick)
        snap = qs.snapshots(["TXFH5"])[0]
        assert snap.close == 20000.0

    def test_tick_ignores_unsubscribed_code(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        tick = make_tick("9999")
        # Should not raise
        qs._on_tick_stk("TSE", tick)

    def test_tick_stk_chains_user_callback(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        user_cb = Mock()
        qs.set_on_tick_stk_callback(user_cb)
        tick = make_tick("2330")
        qs._on_tick_stk("TSE", tick)
        user_cb.assert_called_once_with("TSE", tick)

    def test_tick_fop_chains_user_callback(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["TXFH5"])
        user_cb = Mock()
        qs.set_on_tick_fop_callback(user_cb)
        tick = make_tick("TXFH5")
        qs._on_tick_fop("TAIFEX", tick)
        user_cb.assert_called_once_with("TAIFEX", tick)

    def test_user_callback_exception_logged_internal_still_works(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        user_cb = Mock(side_effect=Exception("user error"))
        qs.set_on_tick_stk_callback(user_cb)
        tick = make_tick("2330", close=Decimal("999.0"))
        qs._on_tick_stk("TSE", tick)
        # Internal update should still have happened
        assert qs.snapshots(["2330"])[0].close == 999.0

    def test_malformed_tick_stk_caught(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        tick = Mock()
        tick.code = "2330"
        tick.simtrade = 0
        del tick.close
        qs._on_tick_stk("TSE", tick)

    def test_malformed_tick_fop_caught(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["TXFH5"])
        tick = Mock()
        tick.code = "TXFH5"
        tick.simtrade = 0
        del tick.close
        qs._on_tick_fop("TAIFEX", tick)

    def test_tick_fop_user_callback_exception_logged(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["TXFH5"])
        user_cb = Mock(side_effect=Exception("user error"))
        qs.set_on_tick_fop_callback(user_cb)
        tick = make_tick("TXFH5")
        qs._on_tick_fop("TAIFEX", tick)
        assert qs.snapshots(["TXFH5"])[0].close == 600.0

    def test_tick_stk_simtrade_skipped(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        original_snap = qs.snapshots(["2330"])[0]
        original_close = original_snap.close
        original_change_rate = original_snap.change_rate
        tick = make_tick(
            "2330", simtrade=1, close=Decimal("999.0"), pct_chg=Decimal("9.99")
        )
        qs._on_tick_stk("TSE", tick)
        snap = qs.snapshots(["2330"])[0]
        assert snap.close == original_close
        assert snap.change_rate == original_change_rate

    def test_tick_fop_simtrade_skipped(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["TXFH5"])
        original_snap = qs.snapshots(["TXFH5"])[0]
        original_close = original_snap.close
        tick = make_tick("TXFH5", simtrade=1, close=Decimal("99999.0"))
        qs._on_tick_fop("TAIFEX", tick)
        snap = qs.snapshots(["TXFH5"])[0]
        assert snap.close == original_close

    def test_tick_stk_simtrade_user_callback_still_called(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        user_cb = Mock()
        qs.set_on_tick_stk_callback(user_cb)
        tick = make_tick("2330", simtrade=1)
        qs._on_tick_stk("TSE", tick)
        user_cb.assert_called_once_with("TSE", tick)

    def test_tick_fop_simtrade_user_callback_still_called(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["TXFH5"])
        user_cb = Mock()
        qs.set_on_tick_fop_callback(user_cb)
        tick = make_tick("TXFH5", simtrade=1)
        qs._on_tick_fop("TAIFEX", tick)
        user_cb.assert_called_once_with("TAIFEX", tick)

    def test_tick_stk_simtrade_user_callback_exception_logged(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        user_cb = Mock(side_effect=Exception("user error"))
        qs.set_on_tick_stk_callback(user_cb)
        tick = make_tick("2330", simtrade=1)
        qs._on_tick_stk("TSE", tick)
        # Should not propagate
        user_cb.assert_called_once_with("TSE", tick)

    def test_tick_fop_simtrade_user_callback_exception_logged(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["TXFH5"])
        user_cb = Mock(side_effect=Exception("user error"))
        qs.set_on_tick_fop_callback(user_cb)
        tick = make_tick("TXFH5", simtrade=1)
        qs._on_tick_fop("TAIFEX", tick)
        # Should not propagate
        user_cb.assert_called_once_with("TAIFEX", tick)

    def test_tick_stk_non_simtrade_updates_normally(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        tick = make_tick(
            "2330", simtrade=0, close=Decimal("650.0"), pct_chg=Decimal("1.5")
        )
        qs._on_tick_stk("TSE", tick)
        snap = qs.snapshots(["2330"])[0]
        assert snap.close == 650.0
        assert snap.change_rate == 1.5


# -- TestQuoteSyncBidAskCallbacks --


class TestQuoteSyncBidAskCallbacks:
    def test_bidask_stk_updates_best_bid_ask(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        bidask = make_bidask("2330")
        qs._on_bidask_stk("TSE", bidask)
        snap = qs.snapshots(["2330"])[0]
        assert snap.buy_price == 599.0
        assert snap.buy_volume == 100
        assert snap.sell_price == 600.0
        assert snap.sell_volume == 80

    def test_bidask_fop_updates_best_bid_ask(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["TXFH5"])
        bidask = make_bidask("TXFH5")
        qs._on_bidask_fop("TAIFEX", bidask)
        snap = qs.snapshots(["TXFH5"])[0]
        assert snap.buy_price == 599.0
        assert snap.sell_price == 600.0

    def test_bidask_empty_bid_price_no_crash(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        bidask = make_bidask("2330", bid_price=[], ask_price=[])
        qs._on_bidask_stk("TSE", bidask)
        # Should not crash; original values preserved

    def test_bidask_ignores_unsubscribed_code(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        bidask = make_bidask("9999")
        qs._on_bidask_stk("TSE", bidask)  # should not raise

    def test_bidask_stk_chains_user_callback(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        user_cb = Mock()
        qs.set_on_bidask_stk_callback(user_cb)
        bidask = make_bidask("2330")
        qs._on_bidask_stk("TSE", bidask)
        user_cb.assert_called_once_with("TSE", bidask)

    def test_bidask_fop_chains_user_callback(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["TXFH5"])
        user_cb = Mock()
        qs.set_on_bidask_fop_callback(user_cb)
        bidask = make_bidask("TXFH5")
        qs._on_bidask_fop("TAIFEX", bidask)
        user_cb.assert_called_once_with("TAIFEX", bidask)

    def test_bidask_stk_user_callback_exception_logged(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        user_cb = Mock(side_effect=Exception("user error"))
        qs.set_on_bidask_stk_callback(user_cb)
        bidask = make_bidask("2330")
        qs._on_bidask_stk("TSE", bidask)
        assert qs.snapshots(["2330"])[0].buy_price == 599.0

    def test_bidask_fop_user_callback_exception_logged(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["TXFH5"])
        user_cb = Mock(side_effect=Exception("user error"))
        qs.set_on_bidask_fop_callback(user_cb)
        bidask = make_bidask("TXFH5")
        qs._on_bidask_fop("TAIFEX", bidask)
        assert qs.snapshots(["TXFH5"])[0].buy_price == 599.0

    def test_malformed_bidask_stk_caught(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        bidask = Mock()
        bidask.code = "2330"
        del bidask.bid_price
        qs._on_bidask_stk("TSE", bidask)

    def test_malformed_bidask_fop_caught(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["TXFH5"])
        bidask = Mock()
        bidask.code = "TXFH5"
        del bidask.bid_price
        qs._on_bidask_fop("TAIFEX", bidask)


# -- TestSnapshotTsAlignment --


class TestDatetimeToNs:
    """Verify _datetime_to_ns mirrors shioaji's Snapshot.ts encoding exactly.

    Shioaji encodes Snapshot.ts by treating the TPE wall-clock components
    (year/month/day/hour/min/sec/usec) as if they were UTC seconds, then
    multiplying by 1e9. So input wall-clock numbers and the encoded ns digits
    line up numerically (the "8h offset" is by design — that's the quirk).
    Reference values below come from live api.snapshots() captures.
    """

    def test_known_value_matches_live_snapshot_encoding(self):
        # Captured live: tick.datetime (TPE wall clock) 2026-05-04 10:43:36.672775
        # was paired with Snapshot.ts = 1777891416672775000.
        d = datetime.datetime(2026, 5, 4, 10, 43, 36, 672775)
        assert _datetime_to_ns(d) == 1_777_891_416_672_775_000

    def test_microsecond_precision_preserved(self):
        # Float path int(d.timestamp() * 1e9) loses ns on microsecond inputs;
        # this regression locks in the integer-only result.
        d = datetime.datetime(2026, 5, 4, 10, 43, 42, 920445)
        assert _datetime_to_ns(d) == 1_777_891_422_920_445_000

    def test_zero_microseconds(self):
        d = datetime.datetime(2026, 5, 4, 0, 0, 0, 0)
        assert _datetime_to_ns(d) == 1_777_852_800_000_000_000

    def test_ignores_tzinfo(self):
        # Encoding mirrors shioaji: tzinfo is ignored, only wall-clock fields
        # matter. A naive value and the same value tagged with a non-UTC tz
        # must produce identical ns.
        naive = datetime.datetime(2026, 5, 4, 10, 43, 42, 920445)
        aware = naive.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
        assert _datetime_to_ns(naive) == _datetime_to_ns(aware)


class TestSnapshotTsUpdates:
    """Streaming callbacks must update snap.ts to mirror shioaji's encoding."""

    def test_tick_stk_updates_ts(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        tick = make_tick(
            "2330",
            datetime=datetime.datetime(2026, 5, 4, 10, 43, 36, 520445),
        )
        qs._on_tick_stk("TSE", tick)
        assert qs.snapshots(["2330"])[0].ts == 1_777_891_416_520_445_000

    def test_tick_fop_updates_ts(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["TXFH5"])
        tick = make_tick(
            "TXFH5",
            datetime=datetime.datetime(2026, 5, 4, 10, 43, 36, 520445),
        )
        qs._on_tick_fop("TAIFEX", tick)
        assert qs.snapshots(["TXFH5"])[0].ts == 1_777_891_416_520_445_000

    def test_bidask_stk_does_not_update_ts(self, mock_quote_api):
        # Native Snapshot.ts only advances on deal ticks; bid/ask updates
        # do not touch ts. Mirror that exactly.
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        baseline_ts = qs.snapshots(["2330"])[0].ts
        bidask = make_bidask(
            "2330",
            datetime=datetime.datetime(2026, 5, 4, 10, 43, 36, 520445),
        )
        qs._on_bidask_stk("TSE", bidask)
        assert qs.snapshots(["2330"])[0].ts == baseline_ts

    def test_bidask_fop_does_not_update_ts(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["TXFH5"])
        baseline_ts = qs.snapshots(["TXFH5"])[0].ts
        bidask = make_bidask(
            "TXFH5",
            datetime=datetime.datetime(2026, 5, 4, 10, 43, 36, 520445),
        )
        qs._on_bidask_fop("TAIFEX", bidask)
        assert qs.snapshots(["TXFH5"])[0].ts == baseline_ts

    def test_bidask_after_tick_keeps_tick_ts(self, mock_quote_api):
        # If a tick set ts, a subsequent bidask must NOT overwrite it.
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        tick = make_tick(
            "2330",
            datetime=datetime.datetime(2026, 5, 4, 10, 43, 36, 520445),
        )
        qs._on_tick_stk("TSE", tick)
        ts_after_tick = qs.snapshots(["2330"])[0].ts

        bidask = make_bidask(
            "2330",
            datetime=datetime.datetime(2026, 5, 4, 10, 50, 0, 0),
        )
        qs._on_bidask_stk("TSE", bidask)
        assert qs.snapshots(["2330"])[0].ts == ts_after_tick

    def test_tick_stk_simtrade_does_not_update_ts(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        baseline = make_tick(
            "2330",
            datetime=datetime.datetime(2026, 5, 4, 10, 43, 36, 520445),
        )
        qs._on_tick_stk("TSE", baseline)
        baseline_ts = qs.snapshots(["2330"])[0].ts

        sim = make_tick(
            "2330",
            datetime=datetime.datetime(2026, 5, 4, 11, 0, 0, 0),
            simtrade=1,
        )
        qs._on_tick_stk("TSE", sim)
        assert qs.snapshots(["2330"])[0].ts == baseline_ts

    def test_tick_fop_simtrade_does_not_update_ts(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["TXFH5"])
        baseline = make_tick(
            "TXFH5",
            datetime=datetime.datetime(2026, 5, 4, 10, 43, 36, 520445),
        )
        qs._on_tick_fop("TAIFEX", baseline)
        baseline_ts = qs.snapshots(["TXFH5"])[0].ts

        sim = make_tick(
            "TXFH5",
            datetime=datetime.datetime(2026, 5, 4, 11, 0, 0, 0),
            simtrade=1,
        )
        qs._on_tick_fop("TAIFEX", sim)
        assert qs.snapshots(["TXFH5"])[0].ts == baseline_ts
