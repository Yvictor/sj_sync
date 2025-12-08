"""Tests for PositionSync real-time position tracking."""

from unittest.mock import Mock
from shioaji.constant import OrderState, Action, StockOrderCond

from sj_sync.position_sync import PositionSync
from sj_sync.models import FuturesPosition, StockPosition


def create_stock_deal(
    account,
    code: str,
    action: str,
    quantity: int,
    price: float,
    order_cond: str = "Cash",
):
    """Helper to create stock deal event data matching official API format."""
    return {
        "trade_id": f"test_{code}_{action}",
        "seqno": "269866",
        "ordno": "IN497",
        "exchange_seq": "669915",
        "broker_id": account.broker_id,
        "account_id": account.account_id,
        "action": action,
        "code": code,
        "order_cond": order_cond,
        "order_lot": "Common",
        "price": price,
        "quantity": quantity,
        "web_id": "137",
        "custom_field": "",
        "ts": 1673577256.354,
    }


class TestPositionSyncInitialization:
    """Test position initialization from list_positions()."""

    def test_init_with_empty_positions(self, mock_api):
        """Test initialization with no existing positions."""
        mock_api.list_positions.return_value = []

        sync = PositionSync(mock_api)

        positions = sync.list_positions()
        assert len(positions) == 0

    def test_init_with_stock_positions(self, mock_api, sample_stock_pnl):
        """Test initialization with stock positions."""
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType

        account = create_mock_account("9100", "1234567", AccountType.Stock)

        mock_api.list_accounts.return_value = [account]
        mock_api.list_positions.return_value = [sample_stock_pnl]
        mock_api.stock_account = account  # Set as default account

        sync = PositionSync(mock_api)

        positions = sync.list_positions()
        assert len(positions) == 1
        assert isinstance(positions[0], StockPosition)
        assert positions[0].code == "2330"
        assert positions[0].direction == Action.Buy
        assert positions[0].quantity == 10
        assert positions[0].yd_quantity == 10
        assert positions[0].cond == StockOrderCond.Cash

    def test_init_with_margin_trading(self, mock_api, sample_margin_pnl):
        """Test initialization with margin trading positions."""
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType

        account = create_mock_account("9100", "1234567", AccountType.Stock)

        mock_api.list_accounts.return_value = [account]
        mock_api.list_positions.return_value = [sample_margin_pnl]
        mock_api.stock_account = account

        sync = PositionSync(mock_api)

        positions = sync.list_positions()
        assert len(positions) == 1
        assert isinstance(positions[0], StockPosition)
        assert positions[0].cond == StockOrderCond.MarginTrading
        assert positions[0].quantity == 5

    def test_init_with_short_selling(self, mock_api, sample_short_pnl):
        """Test initialization with short selling positions."""
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType

        account = create_mock_account("9100", "1234567", AccountType.Stock)

        mock_api.list_accounts.return_value = [account]
        mock_api.list_positions.return_value = [sample_short_pnl]
        mock_api.stock_account = account

        sync = PositionSync(mock_api)

        positions = sync.list_positions()
        assert len(positions) == 1
        assert isinstance(positions[0], StockPosition)
        assert positions[0].cond == StockOrderCond.ShortSelling
        assert positions[0].direction == Action.Sell

    def test_init_filters_zero_quantity(self, mock_api):
        """Test that zero quantity positions are not stored."""
        pnl_zero = Mock()
        pnl_zero.code = "2330"
        pnl_zero.direction = Action.Buy
        pnl_zero.quantity = 0  # Zero quantity
        pnl_zero.cond = StockOrderCond.Cash
        pnl_zero.yd_quantity = 0

        mock_api.list_positions.return_value = [pnl_zero]
        mock_api.stock_account = Mock()

        sync = PositionSync(mock_api)

        positions = sync.list_positions()
        assert len(positions) == 0  # Should be filtered out

    def test_list_positions_filter_by_account(self, mock_api, sample_stock_pnl):
        """Test filtering positions by account."""
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType
        from shioaji.position import StockPosition as SjStockPosition

        account1 = create_mock_account("9100", "ACC1", AccountType.Stock)
        account2 = create_mock_account("9100", "ACC2", AccountType.Stock)

        pnl1 = Mock(spec=SjStockPosition)
        pnl1.code = "2330"
        pnl1.direction = Action.Buy
        pnl1.quantity = 10
        pnl1.yd_quantity = 10
        pnl1.cond = StockOrderCond.Cash

        pnl2 = Mock(spec=SjStockPosition)
        pnl2.code = "2317"
        pnl2.direction = Action.Buy
        pnl2.quantity = 5
        pnl2.yd_quantity = 5
        pnl2.cond = StockOrderCond.Cash

        # Setup list_accounts to return both accounts
        mock_api.list_accounts.return_value = [account1, account2]

        # Setup list_positions to return different results per account
        def list_positions_side_effect(account, unit, timeout=5000):
            if account == account1:
                return [pnl1]
            elif account == account2:
                return [pnl2]
            return []

        mock_api.list_positions.side_effect = list_positions_side_effect
        mock_api.stock_account = account1

        sync = PositionSync(mock_api)

        # Get all positions (only from default stock_account which is account1)
        all_positions = sync.list_positions()
        assert len(all_positions) == 1

        # Filter by account1
        acc1_positions = sync.list_positions(account=account1)  # type: ignore[arg-type]
        assert len(acc1_positions) == 1
        assert acc1_positions[0].code == "2330"

        # Filter by account2
        acc2_positions = sync.list_positions(account=account2)  # type: ignore[arg-type]
        assert len(acc2_positions) == 1
        assert acc2_positions[0].code == "2317"


class TestStockDealEvents:
    """Test stock deal event handling."""

    def test_new_buy_position_from_deal(self, mock_api, sample_stock_deal):
        """Test creating new position from buy deal."""
        mock_api.list_positions.return_value = []
        sync = PositionSync(mock_api)

        # Simulate deal callback
        sync.on_order_deal_event(OrderState.StockDeal, sample_stock_deal)

        positions = sync.list_positions()
        assert len(positions) == 1
        assert positions[0].code == "2330"
        assert positions[0].direction == Action.Buy
        assert positions[0].quantity == 2

    def test_add_to_existing_position_same_direction(
        self, mock_api, sample_stock_pnl, sample_stock_deal
    ):
        """Test adding to existing position (same direction)."""
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType

        # Set account before creating sync
        account = create_mock_account("9100", "1234567", AccountType.Stock)
        mock_api.stock_account = account
        mock_api.list_accounts.return_value = [account]
        mock_api.list_positions.return_value = [sample_stock_pnl]

        sync = PositionSync(mock_api)

        # Initial position: 10 lots
        positions = sync.list_positions()
        assert positions[0].quantity == 10

        # Buy 2 more lots with same account
        sync.on_order_deal_event(OrderState.StockDeal, sample_stock_deal)

        positions = sync.list_positions()
        assert len(positions) == 1
        assert positions[0].quantity == 12  # 10 + 2

    def test_reduce_position_opposite_direction(
        self, mock_api, sample_stock_pnl, sample_sell_deal
    ):
        """Test reducing position (opposite direction)."""
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType

        # Set account before creating sync
        account = create_mock_account("9100", "1234567", AccountType.Stock)
        mock_api.stock_account = account
        mock_api.list_accounts.return_value = [account]
        mock_api.list_positions.return_value = [sample_stock_pnl]

        sync = PositionSync(mock_api)

        # Initial position: Buy 10 lots
        positions = sync.list_positions()
        assert positions[0].quantity == 10

        # Sell 3 lots with same account
        sync.on_order_deal_event(OrderState.StockDeal, sample_sell_deal)

        positions = sync.list_positions()
        assert len(positions) == 1
        assert positions[0].quantity == 7  # 10 - 3

    def test_close_position_exact_opposite(self, mock_api, sample_stock_pnl):
        """Test closing position when quantity becomes zero."""
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType

        # Set account before creating sync
        account = create_mock_account("9100", "1234567", AccountType.Stock)
        mock_api.stock_account = account
        mock_api.list_accounts.return_value = [account]
        mock_api.list_positions.return_value = [sample_stock_pnl]

        sync = PositionSync(mock_api)

        # Initial position: Buy 10 lots
        positions = sync.list_positions()
        assert len(positions) == 1

        # Sell exactly 10 lots to close with same account
        close_deal = {
            "trade_id": "test_close",
            "seqno": "269900",
            "ordno": "IN500",
            "exchange_seq": "669920",
            "broker_id": account.broker_id,
            "account_id": account.account_id,
            "action": "Sell",
            "code": "2330",
            "order_cond": "Cash",
            "order_lot": "Common",
            "price": 510.0,
            "quantity": 10,
            "web_id": "137",
            "custom_field": "",
            "ts": 1673577300.0,
        }
        sync.on_order_deal_event(OrderState.StockDeal, close_deal)

        # Position should be removed
        positions = sync.list_positions()
        assert len(positions) == 0


class TestDayTrading:
    """Test day trading scenarios (當沖)."""

    def test_day_trading_buy_then_sell(self, mock_api):
        """Test day trading: buy then sell same quantity."""
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType

        account = create_mock_account("9100", "1234567", AccountType.Stock)
        mock_api.stock_account = account

        mock_api.list_positions.return_value = []
        sync = PositionSync(mock_api)

        # Buy 5 lots
        buy_deal = create_stock_deal(account, "2454", "Buy", 5, 200.0)
        sync.on_order_deal_event(OrderState.StockDeal, buy_deal)

        positions = sync.list_positions()
        assert len(positions) == 1
        assert positions[0].quantity == 5

        # Sell 5 lots (close position)
        sell_deal = create_stock_deal(account, "2454", "Sell", 5, 205.0)
        sync.on_order_deal_event(OrderState.StockDeal, sell_deal)

        # Position should be removed after day trading close
        positions = sync.list_positions()
        assert len(positions) == 0

    def test_day_trading_partial(self, mock_api):
        """Test partial day trading (buy 10, sell 7)."""
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType

        account = create_mock_account("9100", "1234567", AccountType.Stock)
        mock_api.stock_account = account

        mock_api.list_positions.return_value = []
        sync = PositionSync(mock_api)

        # Buy 10 lots
        buy_deal = create_stock_deal(account, "2330", "Buy", 10, 500.0)
        sync.on_order_deal_event(OrderState.StockDeal, buy_deal)

        # Sell 7 lots (partial close)
        sell_deal = create_stock_deal(account, "2330", "Sell", 7, 505.0)
        sync.on_order_deal_event(OrderState.StockDeal, sell_deal)

        positions = sync.list_positions()
        assert len(positions) == 1
        assert positions[0].quantity == 3  # 10 - 7


class TestMarginAndShortSelling:
    """Test margin trading and short selling scenarios."""

    def test_margin_and_cash_same_stock(self, mock_api):
        """Test that margin and cash positions of same stock are separate."""
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType

        account = create_mock_account("9100", "1234567", AccountType.Stock)
        mock_api.stock_account = account

        mock_api.list_positions.return_value = []
        sync = PositionSync(mock_api)

        # Buy cash
        cash_deal = create_stock_deal(account, "2330", "Buy", 10, 500.0, "Cash")
        sync.on_order_deal_event(OrderState.StockDeal, cash_deal)

        # Buy margin
        margin_deal = create_stock_deal(
            account, "2330", "Buy", 5, 500.0, "MarginTrading"
        )
        sync.on_order_deal_event(OrderState.StockDeal, margin_deal)

        positions = sync.list_positions()
        assert len(positions) == 2  # Should be two separate positions

        cash_pos = [
            p
            for p in positions
            if isinstance(p, StockPosition) and p.cond == StockOrderCond.Cash
        ][0]
        margin_pos = [
            p
            for p in positions
            if isinstance(p, StockPosition) and p.cond == StockOrderCond.MarginTrading
        ][0]

        assert cash_pos.quantity == 10
        assert margin_pos.quantity == 5

    def test_short_selling_deal(self, mock_api, sample_short_deal):
        """Test short selling deal event."""
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType

        account = create_mock_account("9100", "1234567", AccountType.Stock)
        mock_api.stock_account = account

        mock_api.list_positions.return_value = []
        sync = PositionSync(mock_api)

        sync.on_order_deal_event(OrderState.StockDeal, sample_short_deal)

        positions = sync.list_positions()
        assert len(positions) == 1
        assert isinstance(positions[0], StockPosition)
        assert positions[0].cond == StockOrderCond.ShortSelling
        assert positions[0].direction == Action.Sell


class TestFuturesDealEvents:
    """Test futures deal event handling."""

    def test_new_futures_position_from_deal(self, mock_api, sample_futures_deal):
        """Test creating new futures position from deal."""
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType

        account = create_mock_account("9100", "1234567", AccountType.Future)
        mock_api.futopt_account = account

        mock_api.list_positions.return_value = []
        sync = PositionSync(mock_api)

        sync.on_order_deal_event(OrderState.FuturesDeal, sample_futures_deal)

        positions = sync.list_positions()
        assert len(positions) == 1
        assert isinstance(positions[0], FuturesPosition)
        assert positions[0].code == "TXFJ4"
        assert positions[0].quantity == 1


class TestMultipleAccounts:
    """Test multiple account scenarios."""

    def test_separate_accounts_separate_positions(self, mock_api):
        """Test that different accounts maintain separate positions."""
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType

        account1 = create_mock_account("9100", "ACC1", AccountType.Stock)
        account2 = create_mock_account("9100", "ACC2", AccountType.Stock)

        # Set account1 as default account
        mock_api.stock_account = account1

        mock_api.list_positions.return_value = []
        sync = PositionSync(mock_api)

        # Account1 buys
        deal1 = create_stock_deal(account1, "2330", "Buy", 10, 500.0)
        sync.on_order_deal_event(OrderState.StockDeal, deal1)

        # Account2 buys same stock
        deal2 = create_stock_deal(account2, "2330", "Buy", 5, 500.0)
        sync.on_order_deal_event(OrderState.StockDeal, deal2)

        # Default account positions (only account1)
        default_positions = sync.list_positions()
        assert len(default_positions) == 1
        assert default_positions[0].quantity == 10

        # Filter by account1
        acc1_pos = sync.list_positions(account=account1)  # type: ignore[arg-type]
        assert len(acc1_pos) == 1
        assert acc1_pos[0].quantity == 10

        # Filter by account2
        acc2_pos = sync.list_positions(account=account2)  # type: ignore[arg-type]
        assert len(acc2_pos) == 1
        assert acc2_pos[0].quantity == 5


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_deal_without_required_fields(self, mock_api):
        """Test handling deal event without required fields."""
        mock_api.list_positions.return_value = []
        sync = PositionSync(mock_api)

        # Deal missing account
        bad_deal = {
            "code": "2330",
            "action": "Buy",
            "quantity": 1,
            "price": 100.0,
        }
        sync.on_order_deal_event(OrderState.StockDeal, bad_deal)

        # Should not crash, just log warning
        positions = sync.list_positions()
        assert len(positions) == 0

    def test_callback_registration(self, mock_api):
        """Test that internal callback is registered on init."""
        mock_api.list_positions.return_value = []
        sync = PositionSync(mock_api)

        mock_api.set_order_callback.assert_called_once()
        callback = mock_api.set_order_callback.call_args[0][0]
        assert callback == sync._internal_callback

    def test_user_callback_registration(self, mock_api):
        """Test that user callback can be registered and is called."""
        from shioaji.constant import OrderState

        mock_api.list_positions.return_value = []
        sync = PositionSync(mock_api)

        # Create a mock user callback
        user_callback = Mock()

        # Register user callback
        sync.set_order_callback(user_callback)

        # Simulate a deal event
        deal_data = {
            "code": "2330",
            "action": "Buy",
            "quantity": 1000,
            "price": 500.0,
            "broker_id": "F002000",
            "account_id": "1234567",
            "order_cond": "Cash",
        }

        # Call internal callback (which should trigger user callback)
        sync._internal_callback(OrderState.StockDeal, deal_data)

        # Verify user callback was called
        user_callback.assert_called_once_with(OrderState.StockDeal, deal_data)

    def test_user_callback_exception_handling(self, mock_api):
        """Test that exceptions in user callback are caught and logged."""
        from shioaji.constant import OrderState
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType

        mock_api.list_positions.return_value = []

        # Setup mock stock account
        stock_account = create_mock_account("F002000", "1234567", AccountType.Stock)
        mock_api.stock_account = stock_account

        sync = PositionSync(mock_api)

        # Create a callback that raises an exception
        def failing_callback(state, data):
            raise ValueError("Test exception")

        # Register failing callback
        sync.set_order_callback(failing_callback)

        # Simulate a deal event
        deal_data = {
            "code": "2330",
            "action": "Buy",
            "quantity": 1000,
            "price": 500.0,
            "broker_id": "F002000",
            "account_id": "1234567",
            "order_cond": "Cash",
        }

        # Call internal callback - should not raise exception
        sync._internal_callback(OrderState.StockDeal, deal_data)

        # Verify position was still updated despite callback error
        positions = sync.list_positions()
        assert len(positions) == 1
        assert positions[0].code == "2330"
        assert positions[0].quantity == 1000


class TestSmartSync:
    """Test smart sync feature with sync_threshold."""

    def test_sync_threshold_disabled_always_use_local(self, mock_api, sample_stock_pnl):
        """Test sync_threshold=0 always uses local positions."""
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType

        account = create_mock_account("9100", "1234567", AccountType.Stock)
        mock_api.list_accounts.return_value = [account]
        mock_api.list_positions.return_value = [sample_stock_pnl]
        mock_api.stock_account = account

        # sync_threshold=0 (default, disabled)
        sync = PositionSync(mock_api, sync_threshold=0)

        # Clear the initialization call
        mock_api.list_positions.reset_mock()

        # list_positions should use local without querying API
        positions = sync.list_positions()

        # Should not call API again
        mock_api.list_positions.assert_not_called()

        assert len(positions) == 1
        assert positions[0].code == "2330"

    def test_sync_threshold_in_unstable_period_use_local(
        self, mock_api, sample_stock_pnl
    ):
        """Test using local positions within threshold after deal."""
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType

        account = create_mock_account("9100", "1234567", AccountType.Stock)
        mock_api.list_accounts.return_value = [account]
        mock_api.list_positions.return_value = [sample_stock_pnl]
        mock_api.stock_account = account

        # Enable smart sync with 5 second threshold
        sync = PositionSync(mock_api, sync_threshold=5)

        # Simulate a deal event
        deal = create_stock_deal(account, "2330", "Buy", 1, 500.0)
        sync.on_order_deal_event(OrderState.StockDeal, deal)

        # Clear the initialization call
        mock_api.list_positions.reset_mock()

        # Immediately after deal, should use local (within unstable period)
        positions = sync.list_positions()

        # Should not call API
        mock_api.list_positions.assert_not_called()

        assert len(positions) == 1

    def test_sync_threshold_in_stable_period_query_api(
        self, mock_api, sample_stock_pnl
    ):
        """Test querying API after threshold period."""
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType
        import datetime

        account = create_mock_account("9100", "1234567", AccountType.Stock)
        mock_api.list_accounts.return_value = [account]
        mock_api.list_positions.return_value = [sample_stock_pnl]
        mock_api.stock_account = account

        # Enable smart sync with 1 second threshold
        sync = PositionSync(mock_api, sync_threshold=1)

        # Manually set last deal time to 2 seconds ago (beyond threshold)
        account_key = sync._get_account_key(account)  # type: ignore[arg-type]
        sync._last_deal_time[account_key] = (
            datetime.datetime.now() - datetime.timedelta(seconds=2)
        )

        # Clear the initialization call
        mock_api.list_positions.reset_mock()

        # After threshold, should query API
        positions = sync.list_positions()

        # Should call API
        mock_api.list_positions.assert_called_once()

        assert len(positions) == 1

    def test_sync_threshold_no_previous_deals_query_api(
        self, mock_api, sample_stock_pnl
    ):
        """Test querying API when no previous deals recorded."""
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType

        account = create_mock_account("9100", "1234567", AccountType.Stock)
        mock_api.list_accounts.return_value = [account]
        mock_api.list_positions.return_value = [sample_stock_pnl]
        mock_api.stock_account = account

        # Enable smart sync
        sync = PositionSync(mock_api, sync_threshold=30)

        # Clear the initialization call
        mock_api.list_positions.reset_mock()

        # No deals yet, should query API (not in unstable period)
        positions = sync.list_positions()

        # Should call API
        mock_api.list_positions.assert_called_once()

        assert len(positions) == 1

    def test_background_sync_with_inconsistent_positions(
        self, mock_api, sample_stock_pnl
    ):
        """Test background sync detects and updates inconsistent positions."""
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType
        from shioaji.position import StockPosition as SjStockPosition

        account = create_mock_account("9100", "1234567", AccountType.Stock)
        mock_api.list_accounts.return_value = [account]
        mock_api.stock_account = account

        # Initialize with one position
        mock_api.list_positions.return_value = [sample_stock_pnl]
        sync = PositionSync(mock_api, sync_threshold=1)

        # Set last deal time to past threshold
        import datetime

        account_key = sync._get_account_key(account)  # type: ignore[arg-type]
        sync._last_deal_time[account_key] = (
            datetime.datetime.now() - datetime.timedelta(seconds=2)
        )

        # API returns different quantity (inconsistency)
        inconsistent_pnl = Mock(spec=SjStockPosition)
        inconsistent_pnl.code = "2330"
        inconsistent_pnl.direction = Action.Buy
        inconsistent_pnl.quantity = 15  # Different from local (11)
        inconsistent_pnl.yd_quantity = 10
        inconsistent_pnl.cond = StockOrderCond.Cash

        mock_api.list_positions.return_value = [inconsistent_pnl]
        mock_api.list_trades.return_value = []  # No trades today

        # Query API - should trigger background sync
        positions = sync.list_positions()

        # Wait for background thread to complete
        sync._executor.shutdown(wait=True)

        # Local positions should eventually be updated from API
        # (Note: In real scenario, this happens asynchronously)
        assert len(positions) == 1
        assert positions[0].quantity == 15  # API value returned immediately

    def test_futures_position_direct_update_from_api(
        self, mock_api, sample_futures_pnl
    ):
        """Test futures positions are directly updated from API."""
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType
        import datetime

        account = create_mock_account("9100", "FUTOPT", AccountType.Future)
        mock_api.list_accounts.return_value = [account]
        mock_api.futopt_account = account
        mock_api.list_positions.return_value = [sample_futures_pnl]

        # Enable smart sync
        sync = PositionSync(mock_api, sync_threshold=1)

        # Set last deal time to past threshold
        account_key = sync._get_account_key(account)  # type: ignore[arg-type]
        sync._last_deal_time[account_key] = (
            datetime.datetime.now() - datetime.timedelta(seconds=2)
        )

        # Clear the initialization call
        mock_api.list_positions.reset_mock()

        # Query should update futures directly from API
        positions = sync.list_positions(account=account)  # type: ignore[arg-type]

        # Should call API
        mock_api.list_positions.assert_called_once()

        # Wait for background thread
        sync._executor.shutdown(wait=True)

        assert len(positions) == 1
        assert isinstance(positions[0], FuturesPosition)

    def test_api_query_failure_fallback_to_local(self, mock_api, sample_stock_pnl):
        """Test fallback to local positions when API query fails."""
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType
        import datetime

        account = create_mock_account("9100", "1234567", AccountType.Stock)
        mock_api.list_accounts.return_value = [account]
        mock_api.list_positions.return_value = [sample_stock_pnl]
        mock_api.stock_account = account

        # Enable smart sync
        sync = PositionSync(mock_api, sync_threshold=1)

        # Set last deal time to past threshold
        account_key = sync._get_account_key(account)  # type: ignore[arg-type]
        sync._last_deal_time[account_key] = (
            datetime.datetime.now() - datetime.timedelta(seconds=2)
        )

        # Make API query fail
        mock_api.list_positions.side_effect = Exception("API Error")

        # Should fallback to local positions without crashing
        positions = sync.list_positions()

        # Should still return local positions
        assert len(positions) == 1
        assert positions[0].code == "2330"

    def test_get_default_account_no_accounts(self, mock_api):
        """Test _get_default_account when no accounts available."""
        # No stock_account or futopt_account
        mock_api.list_accounts.return_value = []
        mock_api.stock_account = None
        mock_api.futopt_account = None

        sync = PositionSync(mock_api, sync_threshold=0)

        # Should return None when no accounts
        result = sync._get_default_account()
        assert result is None

    def test_get_default_account_only_futopt(self, mock_api):
        """Test _get_default_account when only futopt_account exists."""
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType

        futopt_account = create_mock_account("9100", "FUTOPT", AccountType.Future)

        mock_api.list_accounts.return_value = [futopt_account]
        mock_api.stock_account = None
        mock_api.futopt_account = futopt_account

        sync = PositionSync(mock_api, sync_threshold=0)

        # Should return futopt_account when no stock_account
        result = sync._get_default_account()
        assert result == futopt_account

    def test_initialize_positions_api_error(self, mock_api):
        """Test _initialize_positions handles API errors gracefully."""
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType

        account = create_mock_account("9100", "1234567", AccountType.Stock)
        mock_api.list_accounts.return_value = [account]
        # Make list_positions raise an exception
        mock_api.list_positions.side_effect = Exception("API Connection Error")
        mock_api.stock_account = account

        # Should not crash, just log warning and continue
        sync = PositionSync(mock_api, sync_threshold=0)

        # Positions should be empty since API call failed
        positions = sync.list_positions()
        assert len(positions) == 0

    def test_in_unstable_period_no_default_account(self, mock_api):
        """Test _in_unstable_period when no default account exists."""
        mock_api.list_accounts.return_value = []
        mock_api.stock_account = None
        mock_api.futopt_account = None

        sync = PositionSync(mock_api, sync_threshold=30)

        # Should return False (not in unstable period) when no account
        result = sync._in_unstable_period(account=None)
        assert result is False

    def test_query_and_check_positions_no_default_account(self, mock_api):
        """Test _query_and_check_positions when no default account."""
        mock_api.list_accounts.return_value = []
        mock_api.stock_account = None
        mock_api.futopt_account = None

        sync = PositionSync(mock_api, sync_threshold=30)

        # Should return empty list and log warning
        positions = sync._query_and_check_positions(account=None)
        assert positions == []

    def test_background_check_and_sync_exception_handling(
        self, mock_api, sample_stock_pnl
    ):
        """Test _background_check_and_sync handles exceptions gracefully."""
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType
        import datetime

        account = create_mock_account("9100", "1234567", AccountType.Stock)
        mock_api.list_accounts.return_value = [account]
        mock_api.stock_account = account
        mock_api.list_positions.return_value = [sample_stock_pnl]

        sync = PositionSync(mock_api, sync_threshold=1)

        # Set last deal time to past threshold
        account_key = sync._get_account_key(account)  # type: ignore[arg-type]
        sync._last_deal_time[account_key] = (
            datetime.datetime.now() - datetime.timedelta(seconds=2)
        )

        # Make _compare_and_sync_stock raise an exception by mocking list_trades
        mock_api.list_trades.side_effect = Exception("Background sync error")

        # Query API - should trigger background sync
        positions = sync.list_positions()

        # Wait for background thread to complete
        sync._executor.shutdown(wait=True)

        # Should not crash - exception should be caught and logged
        assert len(positions) == 1

    def test_handle_inconsistencies_all_types(self, mock_api, sample_stock_pnl):
        """Test _handle_inconsistencies_stock with all inconsistency types."""
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType
        from shioaji.position import StockPosition as SjStockPosition
        import datetime

        account = create_mock_account("9100", "1234567", AccountType.Stock)
        mock_api.list_accounts.return_value = [account]
        mock_api.stock_account = account

        # Initialize with one position (2330)
        mock_api.list_positions.return_value = [sample_stock_pnl]
        sync = PositionSync(mock_api, sync_threshold=1)

        # Set last deal time to past threshold
        account_key = sync._get_account_key(account)  # type: ignore[arg-type]
        sync._last_deal_time[account_key] = (
            datetime.datetime.now() - datetime.timedelta(seconds=2)
        )

        # Create API positions with:
        # - mismatch: 2330 with different quantity
        # - missing_local: 2454 not in local
        # - missing_api: local has 1101 not in API
        inconsistent_pnl = Mock(spec=SjStockPosition)
        inconsistent_pnl.code = "2330"
        inconsistent_pnl.direction = Action.Buy
        inconsistent_pnl.quantity = 20  # Different from local
        inconsistent_pnl.yd_quantity = 15
        inconsistent_pnl.cond = StockOrderCond.Cash

        new_pnl = Mock(spec=SjStockPosition)
        new_pnl.code = "2454"
        new_pnl.direction = Action.Buy
        new_pnl.quantity = 5
        new_pnl.yd_quantity = 5
        new_pnl.cond = StockOrderCond.Cash

        # Add a position to local that's not in API
        from sj_sync.models import StockPositionInner

        sync._stock_positions[account_key][("1101", StockOrderCond.Cash)] = (
            StockPositionInner(
                code="1101",
                direction=Action.Buy,
                quantity=3,
                yd_quantity=3,
                yd_offset_quantity=0,
                cond=StockOrderCond.Cash,
            )
        )

        mock_api.list_positions.return_value = [inconsistent_pnl, new_pnl]
        mock_api.list_trades.return_value = []

        # Query API - should trigger background sync with all three types
        positions = sync.list_positions()

        # Wait for background thread to complete
        sync._executor.shutdown(wait=True)

        # All inconsistencies should be logged and synced
        assert len(positions) == 2  # API positions returned

    def test_load_and_sum_today_trades_with_non_stock_orders(
        self, mock_api, sample_stock_pnl
    ):
        """Test _load_and_sum_today_trades filters non-stock orders."""
        from tests.conftest import create_mock_account
        from shioaji.account import AccountType

        account = create_mock_account("9100", "1234567", AccountType.Stock)

        # Create mock trades with various edge cases
        from shioaji.constant import Status

        # Trade 1: Filled stock order (should be included)
        trade1 = Mock()
        trade1.status.status = Status.Filled
        trade1.status.deal_quantity = 5
        trade1.order.account.broker_id = "9100"
        trade1.order.account.account_id = "1234567"
        trade1.order.order_cond = StockOrderCond.Cash
        trade1.order.action = Action.Buy
        trade1.contract.code = "2330"

        # Trade 2: Non-filled order (should be skipped)
        trade2 = Mock()
        trade2.status.status = Status.Cancelled
        trade2.status.deal_quantity = 0
        trade2.order.account.broker_id = "9100"
        trade2.order.account.account_id = "1234567"
        trade2.order.order_cond = StockOrderCond.Cash
        trade2.order.action = Action.Buy
        trade2.contract.code = "2330"

        # Trade 3: Different account (should be skipped)
        trade3 = Mock()
        trade3.status.status = Status.Filled
        trade3.status.deal_quantity = 3
        trade3.order.account.broker_id = "9999"
        trade3.order.account.account_id = "9999999"
        trade3.order.order_cond = StockOrderCond.Cash
        trade3.order.action = Action.Buy
        trade3.contract.code = "2330"

        # Trade 4: Zero deal quantity (should be skipped)
        trade4 = Mock()
        trade4.status.status = Status.Filled
        trade4.status.deal_quantity = 0
        trade4.order.account.broker_id = "9100"
        trade4.order.account.account_id = "1234567"
        trade4.order.order_cond = StockOrderCond.Cash
        trade4.order.action = Action.Buy
        trade4.contract.code = "2330"

        # Trade 5: Futures order (no order_cond, should be skipped)
        trade5 = Mock()
        trade5.status.status = Status.Filled
        trade5.status.deal_quantity = 1
        trade5.order.account.broker_id = "9100"
        trade5.order.account.account_id = "1234567"
        trade5.order.action = Action.Buy
        trade5.contract.code = "TXFJ4"
        # No order_cond attribute

        # Trade 6: AttributeError (should be skipped)
        trade6 = Mock()
        trade6.status.status = Status.Filled
        trade6.status.deal_quantity = 2
        # Missing account attribute will raise AttributeError

        mock_api.list_accounts.return_value = [account]
        mock_api.list_positions.return_value = [sample_stock_pnl]
        mock_api.list_trades.return_value = [
            trade1,
            trade2,
            trade3,
            trade4,
            trade5,
            trade6,
        ]
        mock_api.stock_account = account

        sync = PositionSync(mock_api, sync_threshold=0)

        # Should handle all edge cases without crashing
        # Only trade1 should be counted
        positions = sync.list_positions()
        assert len(positions) == 1
