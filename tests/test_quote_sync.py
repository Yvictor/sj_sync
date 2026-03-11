"""Tests for QuoteSync."""

from decimal import Decimal
from unittest.mock import Mock

import pytest
from shioaji.constant import QuoteType
from shioaji.data import Snapshot

from sj_sync.quote_sync import QuoteSync


# -- Helpers --


def make_contract(code: str) -> Mock:
    contract = Mock()
    contract.code = code
    return contract


def make_tick(code: str, **overrides) -> Mock:
    defaults = dict(
        code=code,
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
    )
    defaults.update(overrides)
    tick = Mock()
    for k, v in defaults.items():
        setattr(tick, k, v)
    return tick


def make_bidask(code: str, **overrides) -> Mock:
    defaults = dict(
        code=code,
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
        assert snap.tick_type == 1
        assert snap.average_price == 598.5
        assert snap.change_price == 5.0
        assert snap.change_rate == 0.84
        assert snap.change_type == 2

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

    def test_malformed_tick_caught(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        tick = Mock()
        tick.code = "2330"
        # Missing attributes will cause AttributeError
        del tick.close
        # Should not raise
        qs._on_tick_stk("TSE", tick)


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

    def test_bidask_user_callback_exception_logged(self, mock_quote_api):
        qs = QuoteSync(mock_quote_api)
        qs.subscribe(codes=["2330"])
        user_cb = Mock(side_effect=Exception("user error"))
        qs.set_on_bidask_stk_callback(user_cb)
        bidask = make_bidask("2330")
        qs._on_bidask_stk("TSE", bidask)
        # Internal update should still have worked
        assert qs.snapshots(["2330"])[0].buy_price == 599.0
