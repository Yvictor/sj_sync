"""Tests for PositionSync real-time position tracking."""

from unittest.mock import Mock
from shioaji.constant import OrderState, Action, StockOrderCond

from sj_sync.position_sync import PositionSync
from sj_sync.models import FuturesPosition, StockPosition


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
        def list_positions_side_effect(account, unit):
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

        # Add account to deal
        sample_stock_deal["account"] = mock_api.stock_account

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
        sample_stock_deal["account"] = account
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
        sample_sell_deal["account"] = account
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
            "code": "2330",
            "action": "Sell",
            "quantity": 10,
            "price": 510.0,
            "order_cond": "Cash",
            "account": account,
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
        buy_deal = {
            "code": "2454",
            "action": "Buy",
            "quantity": 5,
            "price": 200.0,
            "order_cond": "Cash",
            "account": account,
        }
        sync.on_order_deal_event(OrderState.StockDeal, buy_deal)

        positions = sync.list_positions()
        assert len(positions) == 1
        assert positions[0].quantity == 5

        # Sell 5 lots (close position)
        sell_deal = {
            "code": "2454",
            "action": "Sell",
            "quantity": 5,
            "price": 205.0,
            "order_cond": "Cash",
            "account": account,
        }
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
        buy_deal = {
            "code": "2330",
            "action": "Buy",
            "quantity": 10,
            "price": 500.0,
            "order_cond": "Cash",
            "account": account,
        }
        sync.on_order_deal_event(OrderState.StockDeal, buy_deal)

        # Sell 7 lots (partial close)
        sell_deal = {
            "code": "2330",
            "action": "Sell",
            "quantity": 7,
            "price": 505.0,
            "order_cond": "Cash",
            "account": account,
        }
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
        cash_deal = {
            "code": "2330",
            "action": "Buy",
            "quantity": 10,
            "price": 500.0,
            "order_cond": "Cash",
            "account": account,
        }
        sync.on_order_deal_event(OrderState.StockDeal, cash_deal)

        # Buy margin
        margin_deal = {
            "code": "2330",
            "action": "Buy",
            "quantity": 5,
            "price": 500.0,
            "order_cond": "MarginTrading",
            "account": account,
        }
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

        sample_short_deal["account"] = account
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

        sample_futures_deal["account"] = account
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
        deal1 = {
            "code": "2330",
            "action": "Buy",
            "quantity": 10,
            "price": 500.0,
            "order_cond": "Cash",
            "account": account1,
        }
        sync.on_order_deal_event(OrderState.StockDeal, deal1)

        # Account2 buys same stock
        deal2 = {
            "code": "2330",
            "action": "Buy",
            "quantity": 5,
            "price": 500.0,
            "order_cond": "Cash",
            "account": account2,
        }
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
        """Test that order callback is registered on init."""
        mock_api.list_positions.return_value = []
        sync = PositionSync(mock_api)

        mock_api.set_order_callback.assert_called_once()
        callback = mock_api.set_order_callback.call_args[0][0]
        assert callback == sync.on_order_deal_event
