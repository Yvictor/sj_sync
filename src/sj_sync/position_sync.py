"""Real-time position synchronization for Shioaji."""

from loguru import logger
from typing import Dict, List, Optional, Union, Tuple, TypedDict, Literal
import datetime
from concurrent.futures import ThreadPoolExecutor
import shioaji as sj
from shioaji.constant import OrderState, Action, StockOrderCond, Unit, Status
from shioaji.account import Account, AccountType
from shioaji.position import StockPosition as SjStockPostion
from shioaji.position import FuturePosition as SjFuturePostion
from .models import StockPosition, StockPositionInner, FuturesPosition, AccountDict


class StockInconsistency(TypedDict):
    """Stock position inconsistency record."""

    type: Literal["missing_local", "mismatch", "missing_api"]
    code: str
    cond: StockOrderCond
    api: Optional[SjStockPostion]
    local: Optional[StockPositionInner]


class PositionSync:
    """Synchronize positions in real-time using deal callbacks.

    Usage:
        sync = PositionSync(api)
        # Positions are automatically loaded on init
        positions = sync.list_positions()  # Get all positions
        positions = sync.list_positions(account=api.stock_account)  # Filter by account
    """

    def __init__(self, api: sj.Shioaji, sync_threshold: int = 0):
        """Initialize PositionSync with Shioaji API instance.

        Automatically loads all positions and registers deal callback.

        Args:
            api: Shioaji API instance
            sync_threshold: Smart sync threshold in seconds
                          - 0: Always use local calculated positions (default)
                          - >0: Use local positions for N seconds after deal,
                                then switch to API and compare
        """
        self.api = api
        self.sync_threshold = sync_threshold
        self.api.set_order_callback(self.on_order_deal_event)

        # Separate dicts for stock and futures positions
        # Stock: {account_key: {(code, cond): StockPositionInner}}
        # Futures: {account_key: {code: FuturesPosition}}
        # account_key = broker_id + account_id
        self._stock_positions: Dict[
            str, Dict[Tuple[str, StockOrderCond], StockPositionInner]
        ] = {}
        self._futures_positions: Dict[str, Dict[str, FuturesPosition]] = {}

        # Track last deal time for smart sync - one timestamp per account
        self._last_deal_time: Dict[str, datetime.datetime] = {}

        # Thread pool executor for background sync tasks
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sync")

        # Auto-load positions on init
        self._initialize_positions()

    def _get_account_key(self, account: Union[Account, AccountDict]) -> str:
        """Generate account key from Account object or dict.

        Args:
            account: Account object or AccountDict with broker_id and account_id

        Returns:
            Account key string (broker_id + account_id)
        """
        if isinstance(account, dict):
            return f"{account['broker_id']}{account['account_id']}"
        return f"{account.broker_id}{account.account_id}"

    def _get_default_account(self) -> Optional[Account]:
        """Get default account (stock_account first, then futopt_account).

        Returns:
            Default account or None if no account available
        """
        if hasattr(self.api, "stock_account") and self.api.stock_account is not None:
            return self.api.stock_account
        elif (
            hasattr(self.api, "futopt_account") and self.api.futopt_account is not None
        ):
            return self.api.futopt_account
        return None

    def _initialize_positions(self) -> None:
        """Initialize positions from api.list_positions() for all accounts."""
        # Get all accounts
        accounts = self.api.list_accounts()

        for account in accounts:
            account_key = self._get_account_key(account)

            try:
                # Load positions for this account
                positions_pnl = self.api.list_positions(
                    account=account, unit=Unit.Common
                )
            except Exception as e:
                logger.warning(f"Failed to load positions for account {account}: {e}")
                continue

            # Determine if this is stock or futures account based on account_type
            account_type = account.account_type
            if account_type == AccountType.Stock:
                # Load and sum today's trades for this stock account
                trades_sum = self._load_and_sum_today_trades(account)

                for pnl in positions_pnl:
                    if isinstance(pnl, SjStockPostion):
                        # Calculate yd_offset_quantity
                        yd_offset = self._calculate_yd_offset_for_position(
                            code=pnl.code,
                            cond=pnl.cond,
                            direction=pnl.direction,
                            yd_quantity=pnl.yd_quantity,
                            trades_sum=trades_sum,
                        )

                        position = StockPositionInner(
                            code=pnl.code,
                            direction=pnl.direction,
                            quantity=pnl.quantity,
                            yd_quantity=pnl.yd_quantity,
                            yd_offset_quantity=yd_offset,
                            cond=pnl.cond,
                        )
                        if account_key not in self._stock_positions:
                            self._stock_positions[account_key] = {}
                        key = (position.code, position.cond)
                        self._stock_positions[account_key][key] = position

            elif account_type == AccountType.Future:
                for pnl in positions_pnl:
                    if isinstance(pnl, SjFuturePostion):
                        position = FuturesPosition(
                            code=pnl.code,
                            direction=pnl.direction,
                            quantity=pnl.quantity,
                        )
                        if account_key not in self._futures_positions:
                            self._futures_positions[account_key] = {}
                        self._futures_positions[account_key][position.code] = position

            logger.info(f"Initialized positions for account {account_key}")

    def _load_and_sum_today_trades(
        self, account: Account
    ) -> Dict[Tuple[str, StockOrderCond, Action], int]:
        """Load and sum today's trades by (code, cond, action).

        Args:
            account: Account to load trades for

        Returns:
            Dict mapping (code, cond, action) -> total quantity
        """
        try:
            # Update status for this specific account
            self.api.update_status(account)
            all_trades = self.api.list_trades()

            # Sum quantities by (code, cond, action)
            trades_sum: Dict[Tuple[str, StockOrderCond, Action], int] = {}

            for t in all_trades:
                # Check if trade status is filled
                if t.status.status not in [Status.Filled, Status.PartFilled]:
                    continue

                # Check if trade belongs to this account
                try:
                    if (
                        t.order.account.broker_id != account.broker_id
                        or t.order.account.account_id != account.account_id
                    ):
                        continue

                    deal_qty = t.status.deal_quantity
                    if deal_qty <= 0:
                        continue

                    # Only process stock orders (which have order_cond)
                    if not hasattr(t.order, "order_cond"):
                        continue

                    # Key: (code, cond, action)
                    key = (t.contract.code, t.order.order_cond, t.order.action)
                    trades_sum[key] = trades_sum.get(key, 0) + deal_qty

                except AttributeError:
                    continue

            logger.info(
                f"Loaded and summed {len(trades_sum)} trade groups "
                f"for account {account.broker_id}{account.account_id}"
            )
            return trades_sum
        except Exception as e:
            logger.warning(f"Failed to load trades for yd_offset calculation: {e}")
            return {}

    def _calculate_yd_offset_for_position(
        self,
        code: str,
        cond: StockOrderCond,
        direction: Action,
        yd_quantity: int,
        trades_sum: Dict[Tuple[str, StockOrderCond, Action], int],
    ) -> int:
        """Calculate yd_offset_quantity for a single position.

        Args:
            code: Stock code
            cond: Order condition
            direction: Position direction (Buy/Sell)
            yd_quantity: Yesterday's quantity
            trades_sum: Dict mapping (code, cond, action) -> total quantity

        Returns:
            yd_offset_quantity: Amount of yesterday's position offset today
        """
        # If no yesterday position, no offset
        if yd_quantity == 0:
            return 0

        # Find opposite direction trades for this (code, cond)
        opposite_action = Action.Sell if direction == Action.Buy else Action.Buy
        key = (code, cond, opposite_action)

        # Get total opposite direction quantity (default 0 if no trades)
        yd_offset = trades_sum.get(key, 0)

        return yd_offset

    def _in_unstable_period(self, account: Optional[Account] = None) -> bool:
        """Check if account is in unstable period (within sync_threshold after last deal).

        Args:
            account: Account to check. None checks default account.

        Returns:
            True if account had a deal within sync_threshold seconds
        """
        if self.sync_threshold == 0:
            return False

        # Determine account_key
        if account is None:
            default_account = self._get_default_account()
            if default_account is None:
                return False
            account_key = self._get_account_key(default_account)
        else:
            account_key = self._get_account_key(account)

        # Check if account has recent deal
        if account_key not in self._last_deal_time:
            return False

        now = datetime.datetime.now()
        threshold = datetime.timedelta(seconds=self.sync_threshold)
        last_time = self._last_deal_time[account_key]

        return now - last_time < threshold

    def _convert_to_public_stock_position(
        self, inner: StockPositionInner
    ) -> StockPosition:
        """Convert internal position to public position (without yd_offset_quantity).

        Args:
            inner: Internal stock position with yd_offset_quantity

        Returns:
            Public StockPosition without internal fields
        """
        return StockPosition(
            code=inner.code,
            direction=inner.direction,
            quantity=inner.quantity,
            yd_quantity=inner.yd_quantity,
            cond=inner.cond,
        )

    def _get_local_positions(
        self, account: Optional[Account] = None
    ) -> Union[List[StockPosition], List[FuturesPosition]]:
        """Get positions from local tracking.

        Args:
            account: Account to filter. None uses default account.

        Returns:
            List of locally tracked positions
        """
        if account is None:
            # When account is None, try to find account with positions
            # First try stock_account
            if (
                hasattr(self.api, "stock_account")
                and self.api.stock_account is not None
            ):
                stock_key = self._get_account_key(self.api.stock_account)
                if stock_key in self._stock_positions:
                    return [
                        self._convert_to_public_stock_position(pos)
                        for pos in self._stock_positions[stock_key].values()
                    ]

            # Then try futopt_account
            if (
                hasattr(self.api, "futopt_account")
                and self.api.futopt_account is not None
            ):
                futopt_key = self._get_account_key(self.api.futopt_account)
                if futopt_key in self._futures_positions:
                    futures_list: List[FuturesPosition] = list(
                        self._futures_positions[futopt_key].values()
                    )
                    return futures_list

            # No positions found
            return []

        # Specific account provided
        account_key = self._get_account_key(account)
        account_type = account.account_type

        if account_type == AccountType.Stock:
            if account_key in self._stock_positions:
                return [
                    self._convert_to_public_stock_position(pos)
                    for pos in self._stock_positions[account_key].values()
                ]
            return []
        elif account_type == AccountType.Future:
            if account_key in self._futures_positions:
                futures_list: List[FuturesPosition] = list(
                    self._futures_positions[account_key].values()
                )
                return futures_list
            return []

        return []

    def list_positions(  # noqa: ARG002
        self, account: Optional[Account] = None, unit: Unit = Unit.Common
    ) -> Union[List[StockPosition], List[FuturesPosition]]:
        """Get all current positions.

        Smart sync behavior:
        - If sync_threshold = 0: Always return local positions
        - If sync_threshold > 0:
          - Within N seconds of last deal: Return local positions
          - After N seconds: Query API, compare, and return API positions

        Args:
            account: Account to filter. None uses default stock_account first, then futopt_account if no stock.
            unit: Unit.Common or Unit.Share (for compatibility, not used in real-time tracking)

        Returns:
            List of position objects for the specified account type:
            - Stock account: List[StockPosition]
            - Futures account: List[FuturesPosition]
            - None (default): List[StockPosition] from stock_account, or List[FuturesPosition] if no stock
        """
        # sync_threshold = 0: Always use local
        if self.sync_threshold == 0:
            return self._get_local_positions(account)

        # sync_threshold > 0: Check if in unstable period
        if self._in_unstable_period(account):
            logger.debug("In unstable period, using local positions")
            return self._get_local_positions(account)

        # Stable period: Query API and compare
        logger.debug("In stable period, querying API positions")
        return self._query_and_check_positions(account, unit)

    def _query_and_check_positions(
        self, account: Optional[Account] = None, unit: Unit = Unit.Common
    ) -> Union[List[StockPosition], List[FuturesPosition]]:
        """Query API positions, return immediately, then compare and update local in background.

        Args:
            account: Account to query
            unit: Unit type for query

        Returns:
            API positions (converted to our format)
        """
        # Determine which account to query
        if account is None:
            query_account = self._get_default_account()
            if query_account is None:
                logger.warning("No default account available")
                return []
        else:
            query_account = account

        # Query API
        try:
            api_positions_pnl = self.api.list_positions(
                account=query_account, unit=unit
            )
        except Exception as e:
            logger.error(f"Failed to query API positions: {e}, falling back to local")
            return self._get_local_positions(account)

        # Convert API positions to our format - return this to user immediately
        result = self._convert_api_positions(api_positions_pnl, query_account)

        # Get local positions NOW before submitting to thread (to avoid race condition)
        local_positions = self._get_local_positions(account)

        # Submit background task to compare and sync
        self._executor.submit(
            self._background_check_and_sync,
            query_account,
            api_positions_pnl,
            local_positions,
        )

        return result

    def _background_check_and_sync(
        self,
        query_account: Account,
        api_positions_pnl: list,
        local_positions: Union[List[StockPosition], List[FuturesPosition]],
    ) -> None:
        """Background thread to compare and sync positions.

        Args:
            query_account: The account that was queried
            api_positions_pnl: API positions result
            local_positions: Local positions snapshot (captured before thread execution)
        """
        try:
            if query_account.account_type == AccountType.Stock:
                stock_local = [
                    p for p in local_positions if isinstance(p, StockPosition)
                ]
                self._compare_and_sync_stock(
                    api_positions_pnl, stock_local, query_account
                )
            else:
                # For futures, just update local directly from API
                self._update_local_from_api_futures(
                    self._get_account_key(query_account), api_positions_pnl
                )
        except Exception as e:
            logger.error(f"Error in background position sync: {e}")

    def _convert_api_positions(
        self, api_positions, account: Account
    ) -> Union[List[StockPosition], List[FuturesPosition]]:
        """Convert API position format to our StockPosition/FuturesPosition format.

        Args:
            api_positions: Positions from api.list_positions()
            account: Account (to determine type)

        Returns:
            List of StockPosition or FuturesPosition
        """
        if not api_positions:
            if account.account_type == AccountType.Stock:
                stock_result: List[StockPosition] = []
                return stock_result
            else:
                futures_result: List[FuturesPosition] = []
                return futures_result

        # Process based on account type
        if account.account_type == AccountType.Stock:
            stock_list: List[StockPosition] = []
            for pnl in api_positions:
                if isinstance(pnl, SjStockPostion):
                    pos = StockPosition(
                        code=pnl.code,
                        direction=pnl.direction,
                        quantity=pnl.quantity,
                        yd_quantity=pnl.yd_quantity,
                        cond=pnl.cond,
                    )
                    stock_list.append(pos)
            return stock_list
        else:
            futures_list: List[FuturesPosition] = []
            for pnl in api_positions:
                if isinstance(pnl, SjFuturePostion):
                    pos = FuturesPosition(
                        code=pnl.code,
                        direction=pnl.direction,
                        quantity=pnl.quantity,
                    )
                    futures_list.append(pos)
            return futures_list

    def _compare_and_sync_stock(
        self, api_positions, local_positions: List[StockPosition], account: Account
    ) -> None:
        """Compare stock positions and sync if inconsistent.

        Args:
            api_positions: Positions from API
            local_positions: Local tracked positions (not used, kept for compatibility)
            account: Account being compared
        """
        account_key = self._get_account_key(account)

        # Build dict from API positions for easy lookup
        api_dict: Dict[Tuple[str, StockOrderCond], SjStockPostion] = {}
        for pnl in api_positions:
            if isinstance(pnl, SjStockPostion):
                key = (pnl.code, pnl.cond)
                api_dict[key] = pnl

        # Get local internal positions directly
        local_dict = self._stock_positions.get(account_key, {})

        # Find inconsistencies
        inconsistencies: List[StockInconsistency] = []

        # Check positions in API but not in local
        for key, api_pos in api_dict.items():
            if key not in local_dict:
                inconsistencies.append(
                    {
                        "type": "missing_local",
                        "code": api_pos.code,
                        "cond": api_pos.cond,
                        "api": api_pos,
                        "local": None,
                    }
                )
            else:
                local_pos = local_dict[key]
                # Compare quantity and yd_quantity
                if (
                    api_pos.quantity != local_pos.quantity
                    or api_pos.yd_quantity != local_pos.yd_quantity
                ):
                    inconsistencies.append(
                        {
                            "type": "mismatch",
                            "code": api_pos.code,
                            "cond": api_pos.cond,
                            "api": api_pos,
                            "local": local_pos,
                        }
                    )

        # Check positions in local but not in API
        for key, local_pos in local_dict.items():
            if key not in api_dict:
                inconsistencies.append(
                    {
                        "type": "missing_api",
                        "code": local_pos.code,
                        "cond": local_pos.cond,
                        "api": None,
                        "local": local_pos,
                    }
                )

        # If inconsistencies found, check if recent deals and log/sync
        if inconsistencies:
            self._handle_inconsistencies_stock(inconsistencies, account, api_dict)

    def _handle_inconsistencies_stock(
        self,
        inconsistencies: List[StockInconsistency],
        account: Account,
        api_dict: Dict[Tuple[str, StockOrderCond], SjStockPostion],
    ) -> None:
        """Handle stock position inconsistencies - log and update local.

        Args:
            inconsistencies: List of inconsistency dicts
            account: Account object
            api_dict: Dict of API positions by (code, cond)
        """
        # Log all inconsistencies
        for inc in inconsistencies:
            if inc["type"] == "mismatch":
                api_pos = inc["api"]
                local_pos = inc["local"]
                assert api_pos is not None and local_pos is not None
                logger.warning(
                    f"Position inconsistency detected for {inc['code']} [{inc['cond']}]: "
                    f"API(qty={api_pos.quantity}, yd={api_pos.yd_quantity}) vs "
                    f"Local(qty={local_pos.quantity}, yd={local_pos.yd_quantity}). "
                    f"Updating local from API."
                )
            elif inc["type"] == "missing_local":
                api_pos = inc["api"]
                assert api_pos is not None
                logger.warning(
                    f"Position {inc['code']} [{inc['cond']}] exists in API but not in local. "
                    f"Adding to local: qty={api_pos.quantity}, yd={api_pos.yd_quantity}"
                )
            elif inc["type"] == "missing_api":
                local_pos = inc["local"]
                assert local_pos is not None
                logger.warning(
                    f"Position {inc['code']} [{inc['cond']}] exists in local but not in API. "
                    f"Removing from local: qty={local_pos.quantity}, yd={local_pos.yd_quantity}"
                )

        # Update local positions from API
        self._update_local_from_api_stock(account, api_dict)

    def _update_local_from_api_stock(
        self,
        account: Account,
        api_dict: Dict[Tuple[str, StockOrderCond], SjStockPostion],
    ) -> None:
        """Update local stock positions from API positions.

        Args:
            account: Account object
            api_dict: Dict of API positions by (code, cond)
        """
        # Get trades_sum to calculate yd_offset_quantity
        trades_sum = self._load_and_sum_today_trades(account)
        account_key = self._get_account_key(account)

        # Clear existing positions for this account
        self._stock_positions[account_key] = {}

        # Rebuild from API with correct yd_offset_quantity
        for (code, cond), api_pos in api_dict.items():
            yd_offset = self._calculate_yd_offset_for_position(
                code=code,
                cond=cond,
                direction=api_pos.direction,
                yd_quantity=api_pos.yd_quantity,
                trades_sum=trades_sum,
            )

            position = StockPositionInner(
                code=code,
                direction=api_pos.direction,
                quantity=api_pos.quantity,
                yd_quantity=api_pos.yd_quantity,
                yd_offset_quantity=yd_offset,
                cond=cond,
            )
            self._stock_positions[account_key][(code, cond)] = position

        logger.info(f"Updated local stock positions from API for account {account_key}")

    def _update_local_from_api_futures(self, account_key: str, api_positions) -> None:
        """Update local futures positions from API (directly overwrite).

        Args:
            account_key: Account key
            api_positions: List of positions from api.list_positions()
        """
        # Clear and rebuild
        self._futures_positions[account_key] = {}

        for pnl in api_positions:
            if isinstance(pnl, SjFuturePostion):
                position = FuturesPosition(
                    code=pnl.code,
                    direction=pnl.direction,
                    quantity=pnl.quantity,
                )
                self._futures_positions[account_key][pnl.code] = position

        logger.info(
            f"Updated local futures positions from API for account {account_key}"
        )

    def on_order_deal_event(self, state: OrderState, data: Dict) -> None:
        """Callback for order deal events.

        Args:
            state: OrderState enum value
            data: Order/deal data dictionary
        """
        # Handle stock deals
        if state == OrderState.StockDeal:
            self._update_position(data, is_futures=False)
        # Handle futures deals
        elif state == OrderState.FuturesDeal:
            self._update_position(data, is_futures=True)

    def _update_position(self, deal: Dict, is_futures: bool = False) -> None:
        """Update position based on deal event.

        Args:
            deal: Deal data from callback
            is_futures: True if futures/options deal, False if stock deal
        """
        code = deal.get("code")
        action_value = deal.get("action")
        quantity = deal.get("quantity", 0)
        price = deal.get("price", 0)
        account = deal.get("account")

        if not code or not action_value or not account:
            logger.warning(f"Deal missing required fields: {deal}")
            return

        action = self._normalize_direction(action_value)

        if is_futures:
            self._update_futures_position(account, code, action, quantity, price)
        else:
            order_cond = self._normalize_cond(
                deal.get("order_cond", StockOrderCond.Cash)
            )
            self._update_stock_position(
                account, code, action, quantity, price, order_cond
            )

    def _is_day_trading_offset(
        self, code: str, account_key: str, action: Action, order_cond: StockOrderCond
    ) -> tuple[bool, StockOrderCond | None]:
        """Check if this is a day trading offset transaction.

        Day trading rules:
        - MarginTrading Buy + ShortSelling Sell = offset MarginTrading today's quantity
        - ShortSelling Sell + MarginTrading Buy = offset ShortSelling today's quantity
        - Cash Buy + Cash Sell = offset Cash today's quantity
        - Cash Sell (short) + Cash Buy = offset Cash today's quantity

        Returns:
            (is_day_trading, opposite_cond)
        """
        # MarginTrading + ShortSelling day trading
        if order_cond == StockOrderCond.ShortSelling and action == Action.Sell:
            # Check if there's today's MarginTrading position
            margin_key = (code, StockOrderCond.MarginTrading)
            if margin_key in self._stock_positions.get(account_key, {}):
                margin_pos = self._stock_positions[account_key][margin_key]
                # Today's quantity = quantity - (yd_quantity - yd_offset_quantity)
                yd_remaining = margin_pos.yd_quantity - margin_pos.yd_offset_quantity
                today_qty = margin_pos.quantity - yd_remaining
                if today_qty > 0:
                    return True, StockOrderCond.MarginTrading

        if order_cond == StockOrderCond.MarginTrading and action == Action.Buy:
            # Check if there's today's ShortSelling position
            short_key = (code, StockOrderCond.ShortSelling)
            if short_key in self._stock_positions.get(account_key, {}):
                short_pos = self._stock_positions[account_key][short_key]
                # Today's quantity = quantity - (yd_quantity - yd_offset_quantity)
                yd_remaining = short_pos.yd_quantity - short_pos.yd_offset_quantity
                today_qty = short_pos.quantity - yd_remaining
                if today_qty > 0:
                    return True, StockOrderCond.ShortSelling

        # Cash day trading
        if order_cond == StockOrderCond.Cash:
            cash_key = (code, StockOrderCond.Cash)
            if cash_key in self._stock_positions.get(account_key, {}):
                cash_pos = self._stock_positions[account_key][cash_key]
                # Buy then Sell or Sell then Buy
                if cash_pos.direction != action:
                    # Today's quantity = quantity - (yd_quantity - yd_offset_quantity)
                    yd_remaining = cash_pos.yd_quantity - cash_pos.yd_offset_quantity
                    today_qty = cash_pos.quantity - yd_remaining
                    if today_qty > 0:
                        return True, StockOrderCond.Cash

        return False, None

    def _update_stock_position(
        self,
        account: Union[Account, AccountDict],
        code: str,
        action: Action,
        quantity: int,
        price: float,
        order_cond: StockOrderCond,
    ) -> None:
        """Update stock position.

        Args:
            account: Account object or AccountDict from deal callback
            code: Stock code
            action: Buy or Sell action
            quantity: Trade quantity
            price: Trade price
            order_cond: Order condition (Cash, MarginTrading, ShortSelling)
        """
        account_key = self._get_account_key(account)

        # Initialize account dict if needed
        if account_key not in self._stock_positions:
            self._stock_positions[account_key] = {}

        # Check for day trading offset
        is_day_trading, opposite_cond = self._is_day_trading_offset(
            code, account_key, action, order_cond
        )

        if is_day_trading and opposite_cond:
            # Day trading: offset today's position in opposite condition
            self._process_day_trading_offset(
                account_key, code, quantity, price, order_cond, opposite_cond, action
            )
        else:
            # Normal trading or same-cond offset
            self._process_normal_trading(
                account_key, code, action, quantity, price, order_cond
            )

        # Track deal time for smart sync
        if self.sync_threshold > 0:
            self._last_deal_time[account_key] = datetime.datetime.now()

    def _process_day_trading_offset(
        self,
        account_key: str,
        code: str,
        quantity: int,
        price: float,
        order_cond: StockOrderCond,
        opposite_cond: StockOrderCond,
        action: Action,
    ) -> None:
        """Process day trading offset transaction.

        Day trading offsets today's quantity only.
        Note: yd_quantity and yd_offset_quantity are NOT modified in day trading.
        """
        opposite_key = (code, opposite_cond)
        opposite_pos = self._stock_positions[account_key][opposite_key]

        # Calculate today's quantity: quantity - (yd_quantity - yd_offset_quantity)
        yd_remaining = opposite_pos.yd_quantity - opposite_pos.yd_offset_quantity
        today_qty = opposite_pos.quantity - yd_remaining
        offset_qty = min(quantity, today_qty)
        remaining_qty = quantity - offset_qty

        # Offset today's position (only reduce quantity, yd_quantity & yd_offset_quantity stay unchanged)
        opposite_pos.quantity -= offset_qty
        logger.info(
            f"{code} DAY-TRADE OFFSET {action} {price} x {offset_qty} "
            f"[{order_cond}] offsets [{opposite_cond}] -> {opposite_pos}"
        )

        # Remove if zero
        if opposite_pos.quantity == 0:
            del self._stock_positions[account_key][opposite_key]
            logger.info(f"{code} [{opposite_cond}] REMOVED (day trading closed)")

        # IMPORTANT: Day trading can ONLY offset today's position, NOT yesterday's position
        # Yesterday's positions can only be closed by same-condition opposite trades:
        # - MarginTrading Buy can only be closed by MarginTrading Sell (資買 → 資賣)
        # - ShortSelling Sell can only be closed by ShortSelling Buy (券賣 → 券買)
        # Therefore, if there's remaining quantity after day trading offset,
        # it should create a NEW position, not offset yesterday's position.

        # If still remaining, create new position
        if remaining_qty > 0:
            self._create_or_update_position(
                account_key, code, action, remaining_qty, price, order_cond
            )

    def _process_normal_trading(
        self,
        account_key: str,
        code: str,
        action: Action,
        quantity: int,
        price: float,
        order_cond: StockOrderCond,
    ) -> None:
        """Process normal trading (non-day-trading).

        For margin/short trading with opposite direction:
        - Can only offset yesterday's position
        - Increase yd_offset_quantity, decrease quantity
        - yd_quantity never changes
        """
        key = (code, order_cond)
        position = self._stock_positions[account_key].get(key)

        if position is None:
            # Create new position
            self._create_or_update_position(
                account_key, code, action, quantity, price, order_cond
            )
        else:
            # Existing position
            if position.direction == action:
                # Same direction: add to position
                position.quantity += quantity
                logger.info(
                    f"{code} ADD {action} {price} x {quantity} [{order_cond}] -> {position}"
                )
            else:
                # Opposite direction: can only offset yesterday's position
                # Calculate yesterday's remaining
                yd_available = position.yd_quantity - position.yd_offset_quantity
                offset_qty = min(quantity, yd_available)

                if offset_qty > 0:
                    # Reduce quantity and increase yd_offset_quantity (yd_quantity never changes)
                    position.quantity -= offset_qty
                    position.yd_offset_quantity += offset_qty
                    logger.info(
                        f"{code} OFFSET YD {action} {price} x {offset_qty} [{order_cond}] -> {position}"
                    )

                    # Remove if zero
                    if position.quantity == 0:
                        del self._stock_positions[account_key][key]
                        logger.info(f"{code} CLOSED [{order_cond}] -> REMOVED")

    def _create_or_update_position(
        self,
        account_key: str,
        code: str,
        action: Action,
        quantity: int,
        price: float,
        order_cond: StockOrderCond,
    ) -> None:
        """Create new position or add to existing."""
        key = (code, order_cond)
        position = self._stock_positions[account_key].get(key)

        if position is None:
            position = StockPositionInner(
                code=code,
                direction=action,
                quantity=quantity,
                yd_quantity=0,
                yd_offset_quantity=0,  # New position today has no offset
                cond=order_cond,
            )
            self._stock_positions[account_key][key] = position
            logger.info(
                f"{code} NEW {action} {price} x {quantity} [{order_cond}] -> {position}"
            )
        else:
            position.quantity += quantity
            logger.info(
                f"{code} ADD {action} {price} x {quantity} [{order_cond}] -> {position}"
            )

    def _update_futures_position(
        self,
        account: Union[Account, AccountDict],
        code: str,
        action: Action,
        quantity: int,
        price: float,
    ) -> None:
        """Update futures position.

        Args:
            account: Account object or AccountDict from deal callback
            code: Contract code
            action: Buy or Sell action
            quantity: Trade quantity
            price: Trade price
        """
        account_key = self._get_account_key(account)

        # Initialize account dict if needed
        if account_key not in self._futures_positions:
            self._futures_positions[account_key] = {}

        position = self._futures_positions[account_key].get(code)

        if position is None:
            # Create new position
            position = FuturesPosition(
                code=code,
                direction=action,
                quantity=quantity,
            )
            self._futures_positions[account_key][code] = position
            logger.info(f"{code} NEW {action} {price} x {quantity} -> {position}")
        else:
            # Update existing position
            if position.direction == action:
                position.quantity += quantity
            else:
                position.quantity -= quantity

            # Remove if quantity becomes zero
            if position.quantity == 0:
                del self._futures_positions[account_key][code]
                logger.info(f"{code} CLOSED {action} {price} x {quantity} -> REMOVED")
            else:
                logger.info(f"{code} {action} {price} x {quantity} -> {position}")

        # Track deal time for smart sync
        if self.sync_threshold > 0:
            self._last_deal_time[account_key] = datetime.datetime.now()

    def _normalize_direction(self, direction: Union[Action, str]) -> Action:
        """Normalize direction to Action enum.

        Args:
            direction: Action enum or string

        Returns:
            Action enum (Buy or Sell)
        """
        if isinstance(direction, Action):
            return direction
        # Convert string to Action enum
        if direction == "Buy" or direction == "buy":
            return Action.Buy
        elif direction == "Sell" or direction == "sell":
            return Action.Sell
        return Action[direction]  # Fallback to enum lookup

    def _normalize_cond(self, cond: Union[StockOrderCond, str]) -> StockOrderCond:
        """Normalize order condition to StockOrderCond enum.

        Args:
            cond: StockOrderCond enum or string

        Returns:
            StockOrderCond enum
        """
        if isinstance(cond, StockOrderCond):
            return cond
        # Convert string to StockOrderCond enum
        try:
            return StockOrderCond[cond]
        except KeyError:
            # Fallback to Cash if invalid
            return StockOrderCond.Cash
