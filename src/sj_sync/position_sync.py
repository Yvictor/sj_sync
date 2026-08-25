"""Real-time position synchronization for Shioaji."""

from loguru import logger
from typing import (
    Dict,
    List,
    Optional,
    Union,
    Tuple,
    TypedDict,
    Literal,
    Callable,
    cast,
)
import datetime
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from .shioaji_compat import (
    sj,
    Account,
    AccountType,
    Action,
    Deal,
    Future,
    FutureAccount,
    FuturesOrder,
    NativeOrderStatus as OrderStatus,
    Option,
    OrderState,
    SjFuturePosition,
    SjStockPosition,
    Stock,
    StockAccount,
    StockOrder,
    Status,
    StockOrderCond,
    Trade,
    Unit,
)
from .models import StockPosition, FuturesPosition, AccountDict
from .types import StockDeal, FuturesDeal

# Configure logger: add file handler for sj_sync logs (INFO and above)
# Keep default stderr handler so users can control it with LOGURU_* env vars
logger.add(
    "sj_sync.log",
    rotation="1 day",
    retention="5 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
)

# Type alias for order deal callback
OrderDealCallback = Callable[[OrderState, Union[StockDeal, FuturesDeal, Dict]], None]


class StockInconsistency(TypedDict):
    """Stock position inconsistency record."""

    type: Literal["missing_local", "mismatch", "missing_api"]
    code: str
    cond: StockOrderCond
    api: Optional[SjStockPosition]
    local: Optional[StockPosition]


class PositionSync:
    """Synchronize positions in real-time using deal callbacks.

    Usage:
        sync = PositionSync(api)
        # Positions are automatically loaded on init
        positions = sync.list_positions()  # Get all positions
        positions = sync.list_positions(account=api.stock_account)  # Filter by account
    """

    def __init__(self, api: sj.Shioaji, sync_threshold: int = 0, timeout: int = 5000):
        """Initialize PositionSync with Shioaji API instance.

        Automatically loads all positions and registers internal callback.

        Args:
            api: Shioaji API instance
            sync_threshold: Smart sync threshold in seconds
                          - 0: Always use local calculated positions (default)
                          - >0: Use local positions for N seconds after deal,
                                then switch to API and compare
            timeout: API query timeout in milliseconds (default: 5000)
        """
        self.api = api
        self.sync_threshold = sync_threshold
        self.timeout = timeout
        self._user_callback: Optional[OrderDealCallback] = None
        self._live_trade_sync_enabled = self._supports_live_trade_sync()

        # Separate dicts for stock and futures positions
        # Stock: {account_key: {(code, cond): StockPosition}}
        # Futures: {account_key: {code: FuturesPosition}}
        # account_key = broker_id + account_id
        self._stock_positions: Dict[
            str, Dict[Tuple[str, StockOrderCond], StockPosition]
        ] = {}
        self._futures_positions: Dict[str, Dict[str, FuturesPosition]] = {}

        # Native Trade references keyed by (account key, order id).
        self._trades: Dict[Tuple[str, str], Trade] = {}
        self._trade_lock = threading.RLock()
        self._seen_deal_events: set[Tuple[str, str, str]] = set()
        self._projected_deal_events: set[Tuple[str, str, str]] = set()
        self._deferred_deals: Dict[
            Tuple[str, str], Dict[Tuple[str, str, str], Dict]
        ] = {}
        self._pending_new_orders: set[Tuple[str, str]] = set()
        self._discarded_order_keys: set[Tuple[str, str]] = set()
        self._seen_order_events: set[Tuple[str, str, str, float]] = set()
        self._last_order_event_ts: Dict[Tuple[str, str], float] = {}
        self._pending_order_events: Dict[
            Tuple[str, str],
            Dict[Tuple[str, str, str, float], Tuple[OrderState, Dict]],
        ] = {}
        self._trade_sync_closed = threading.Event()
        self._closed = False

        # Track last deal time for smart sync - one timestamp per account
        self._last_deal_time: Dict[str, datetime.datetime] = {}

        # Thread pool executor for background sync tasks
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sync")
        self._trade_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="trade-sync"
        )

        self.api.set_order_callback(self._internal_callback)

        if self._live_trade_sync_enabled:
            self._reconcile_trade_references()
        else:
            logger.warning(
                "Live Trade synchronization is disabled for Shioaji "
                f"{getattr(sj, '__version__', 'unknown')}; it is supported only "
                "for Shioaji 1.2.x and 1.3.x."
            )

        # Auto-load positions on init.
        self._initialize_positions()

    @staticmethod
    def _supports_live_trade_sync() -> bool:
        """Return whether the installed Shioaji exposes mutable Trade references."""
        match = re.match(r"^(\d+)\.(\d+)", getattr(sj, "__version__", ""))
        return bool(match and match.group(1) == "1" and match.group(2) in {"2", "3"})

    def _trade_key(self, trade: Trade) -> Tuple[str, str]:
        """Return the stable account/order identity for a Native Trade."""
        order = getattr(trade, "order")
        return self._get_account_key(order.account), str(order.id)

    def _refresh_trade_references(self) -> None:
        """Merge Native Trade references currently known by Shioaji."""
        try:
            trades = self.api.list_trades()
            with self._trade_lock:
                for trade in trades:
                    self._trades[self._trade_key(trade)] = trade
        except Exception as e:
            logger.warning(f"Failed to load Trade references: {e}")

    def _reconcile_trade_references(
        self, account: Optional[Account] = None, clear_unresolved: bool = False
    ) -> None:
        """Refresh authoritative Trade state, then retain its Native references."""
        try:
            if account is None:
                self.api.update_status(timeout=self.timeout)
            else:
                self.api.update_status(account, timeout=self.timeout)
        except Exception as e:
            logger.warning(f"Failed to reconcile Trade status: {e}")
        self._refresh_trade_references()
        with self._trade_lock:
            trade_keys = list(self._trades)
        for trade_key in trade_keys:
            self._replay_pending_order_events(trade_key)
            self._replay_deferred_deals(trade_key)
        if clear_unresolved:
            account_key = (
                self._get_account_key(account) if account is not None else None
            )

            def in_scope(trade_key: Tuple[str, str]) -> bool:
                return account_key is None or trade_key[0] == account_key

            with self._trade_lock:
                known_keys = set(self._trades)
                unresolved = {
                    key
                    for key in self._pending_new_orders - known_keys
                    if in_scope(key)
                }
                self._discarded_order_keys.update(unresolved)
                self._pending_new_orders.difference_update(unresolved)
                deferred_missing = {
                    key
                    for key in set(self._deferred_deals) - known_keys
                    if in_scope(key)
                }
                for trade_key in deferred_missing:
                    self._deferred_deals.pop(trade_key, None)
                pending_missing = {
                    key
                    for key in set(self._pending_order_events) - known_keys
                    if in_scope(key)
                }
                for trade_key in pending_missing:
                    self._pending_order_events.pop(trade_key, None)
            for _, order_id in unresolved | deferred_missing | pending_missing:
                logger.warning(
                    f"Discarded unresolved Trade reports for order {order_id} "
                    "after reconciliation"
                )

    @staticmethod
    def _enum_value(value: object) -> str:
        """Normalize Shioaji enums and callback strings."""
        return str(getattr(value, "value", value))

    @staticmethod
    def _is_combo_event(state: OrderState, data: Dict) -> bool:
        """Return whether a futures report belongs to an unsupported combo order."""
        if state == OrderState.FuturesOrder:
            value = data.get("order", {}).get("combo", False)
        elif state == OrderState.FuturesDeal:
            value = data.get("combo", False)
        else:
            return False
        return value is True or str(value).lower() == "true"

    def _project_order_event(self, data: Dict) -> bool:
        """Project an order report into an existing Native Trade reference."""
        if not self._live_trade_sync_enabled:
            return False

        order_data = data["order"]
        account_key = self._get_account_key(order_data["account"])
        key = (account_key, str(order_data["id"]))
        operation = data["operation"]
        op_type = self._enum_value(operation["op_type"])
        op_code = str(operation["op_code"])
        status_data = data.get("status", {})
        exchange_ts = float(status_data.get("exchange_ts", 0))
        event_key = (key[0], key[1], op_type, exchange_ts)

        with self._trade_lock:
            trade = self._trades.get(key)
            if trade is None:
                return False
            if event_key in self._seen_order_events:
                return True
            self._seen_order_events.add(event_key)

            last_ts = self._last_order_event_ts.get(key, float("-inf"))
            if exchange_ts < last_ts:
                return True
            self._last_order_event_ts[key] = exchange_ts

            terminal = {Status.Filled, Status.Cancelled, Status.Failed}
            current_status = trade.status.status
            if op_type == "New" and current_status not in terminal:
                trade.status.status = (
                    Status.Submitted if op_code == "00" else Status.Failed
                )
            elif (
                op_type == "Cancel"
                and op_code == "00"
                and current_status not in terminal
            ):
                trade.status.status = Status.Cancelled

            for field in ("id", "seqno", "ordno", "custom_field"):
                if field in order_data:
                    setattr(trade.order, field, order_data[field])

            trade.status.status_code = op_code
            trade.status.msg = str(operation.get("op_msg", ""))
            if "id" in status_data:
                trade.status.id = status_data["id"]
            if exchange_ts and (op_code == "00" or op_type == "New"):
                event_time = datetime.datetime.fromtimestamp(
                    exchange_ts,
                    tz=datetime.timezone(datetime.timedelta(hours=8)),
                )
                if op_type == "New" and trade.status.order_datetime is None:
                    trade.status.order_datetime = event_time
                trade.status.modified_time = event_time
            if op_code == "00" and op_type in {"UpdateQty", "Cancel"}:
                trade.status.cancel_quantity += (
                    status_data.get("cancel_quantity", 0) or 0
                )
            if (
                op_code == "00"
                and op_type == "UpdatePrice"
                and "modified_price" in status_data
            ):
                trade.status.modified_price = status_data["modified_price"]
            if op_code == "00":
                for field in (
                    "order_quantity",
                    "web_id",
                ):
                    if field in status_data:
                        setattr(trade.status, field, status_data[field])
        return True

    def _order_trade_key(self, data: Dict) -> Tuple[str, str]:
        """Return the account/order identity from an order report."""
        order_data = data["order"]
        return self._get_account_key(order_data["account"]), str(order_data["id"])

    def _order_event_key(self, data: Dict) -> Tuple[str, str, str, float]:
        """Return the deduplication identity of an order report."""
        trade_key = self._order_trade_key(data)
        op_type = self._enum_value(data["operation"]["op_type"])
        exchange_ts = float(data.get("status", {}).get("exchange_ts", 0))
        return trade_key[0], trade_key[1], op_type, exchange_ts

    def _defer_order_event(self, state: OrderState, data: Dict) -> None:
        """Retain an Update/Cancel report until its Local Trade appears."""
        trade_key = self._order_trade_key(data)
        event_key = self._order_event_key(data)
        with self._trade_lock:
            self._pending_order_events.setdefault(trade_key, {})[event_key] = (
                state,
                data,
            )
        logger.warning(
            f"Deferred {self._enum_value(data['operation']['op_type'])} report "
            f"for unresolved order {trade_key[1]}"
        )

    def _replay_pending_order_events(self, trade_key: Tuple[str, str]) -> None:
        """Project retained Update/Cancel reports after a Local Trade appears."""
        with self._trade_lock:
            pending = list(self._pending_order_events.get(trade_key, {}).items())
        for event_key, (state, data) in pending:
            if self._project_order_event(data):
                with self._trade_lock:
                    events = self._pending_order_events.get(trade_key)
                    if events is not None:
                        events.pop(event_key, None)
                        if not events:
                            self._pending_order_events.pop(trade_key, None)
                self._replay_deferred_deals(trade_key)
                self._notify_user_callback(state, data)

    def _build_external_trade(self, state: OrderState, data: Dict) -> Trade:
        """Build a Native Trade for an order submitted by another client."""
        order_data = dict(data["order"])
        account_data = order_data.pop("account")
        common_account = {
            "person_id": account_data.get("person_id", ""),
            "broker_id": account_data["broker_id"],
            "account_id": account_data["account_id"],
            "signed": account_data.get("signed", False),
            "username": account_data.get("username", ""),
        }
        contract_data = dict(data["contract"])

        if state == OrderState.StockOrder:
            account = StockAccount(**common_account)
            order_data["account"] = account
            order = StockOrder(**order_data)
            contract = Stock(**contract_data)
        else:
            account = FutureAccount(**common_account)
            if "oc_type" in order_data and "octype" not in order_data:
                order_data["octype"] = order_data.pop("oc_type")
            for extra_field in ("market_type", "subaccount", "combo"):
                order_data.pop(extra_field, None)
            order_data["account"] = account
            order = FuturesOrder(**order_data)
            security_type = self._enum_value(contract_data.get("security_type", "FUT"))
            full_code = contract_data.pop("full_code", None)
            if full_code:
                contract_data["code"] = full_code
            contract_cls = Option if security_type == "OPT" else Future
            option_right = contract_data.get("option_right")
            if contract_cls is Future:
                contract_data.pop("option_right", None)
            elif option_right == "OptionCall":
                contract_data["option_right"] = "C"
            elif option_right == "OptionPut":
                contract_data["option_right"] = "P"
            contract = contract_cls(**contract_data)

        status_data = data.get("status", {})
        status = OrderStatus(
            id=status_data.get("id", order.id),
            status=Status.PendingSubmit,
            status_code="",
            web_id=status_data.get("web_id", ""),
            modified_price=status_data.get("modified_price", 0),
            order_quantity=status_data.get("order_quantity", order.quantity),
            deal_quantity=0,
            cancel_quantity=status_data.get("cancel_quantity", 0),
            deals=[],
        )
        return Trade(contract=contract, order=order, status=status)

    def _resolve_new_order(self, state: OrderState, data: Dict) -> None:
        """Resolve a callback-before-return race, then classify an External Order."""
        key = self._order_trade_key(data)
        deadline = time.monotonic() + 1.0
        try:
            while not self._trade_sync_closed.is_set() and time.monotonic() < deadline:
                self._refresh_trade_references()
                with self._trade_lock:
                    if key in self._discarded_order_keys:
                        return
                    if key in self._trades:
                        break
                self._trade_sync_closed.wait(0.02)

            with self._trade_lock:
                if key in self._discarded_order_keys:
                    return
                if key not in self._trades and not self._trade_sync_closed.is_set():
                    self._trades[key] = self._build_external_trade(state, data)

            if not self._trade_sync_closed.is_set():
                self._project_order_event(data)
                self._replay_deferred_deals(key)
                self._notify_user_callback(state, data)
        except Exception as e:
            logger.error(f"Failed to resolve order report {key[1]}: {e}")
        finally:
            with self._trade_lock:
                self._pending_new_orders.discard(key)

    def _schedule_new_order_resolution(self, state: OrderState, data: Dict) -> bool:
        """Schedule unresolved New report classification once."""
        if self._enum_value(data["operation"]["op_type"]) != "New":
            return False
        key = self._order_trade_key(data)
        with self._trade_lock:
            if self._closed or self._trade_sync_closed.is_set():
                return True
            if key in self._pending_new_orders:
                return True
            self._pending_new_orders.add(key)
            try:
                self._trade_executor.submit(self._resolve_new_order, state, data)
            except RuntimeError:
                self._pending_new_orders.discard(key)
        return True

    def _notify_user_callback(
        self, state: OrderState, data: Union[StockDeal, FuturesDeal, Dict]
    ) -> None:
        """Notify the user after internal projections have run."""
        if self._user_callback is not None:
            try:
                self._user_callback(state, data)
            except Exception as e:
                logger.error(f"Error in user callback: {e}")

    def _deal_event_key(self, data: Dict) -> Tuple[str, str, str]:
        """Return the account, Trade, and exchange identity of a deal report."""
        account: AccountDict = {
            "broker_id": str(data["broker_id"]),
            "account_id": str(data["account_id"]),
        }
        account_key = self._get_account_key(account)
        return account_key, str(data["trade_id"]), str(data["exchange_seq"])

    def _project_deal_event(self, data: Dict) -> bool:
        """Project a deal report into its Native Trade once."""
        if not self._live_trade_sync_enabled:
            return False

        event_key = self._deal_event_key(data)
        with self._trade_lock:
            if event_key in self._projected_deal_events:
                return True

        trade_key = (event_key[0], event_key[1])
        with self._trade_lock:
            trade = self._trades.get(trade_key)
            if trade is None:
                self._deferred_deals.setdefault(trade_key, {})[event_key] = data
                return False

            deals: List[Deal] = trade.status.deals or []
            trade.status.deals = deals
            deals.append(
                Deal(
                    seq=str(data["exchange_seq"]),
                    price=data["price"],
                    quantity=data["quantity"],
                    ts=data["ts"],
                )
            )
            trade.status.deal_quantity += data["quantity"]
            order_quantity = trade.status.order_quantity or trade.order.quantity
            if trade.status.status not in {
                Status.Filled,
                Status.Cancelled,
                Status.Failed,
            }:
                trade.status.status = (
                    Status.Filled
                    if trade.status.deal_quantity >= order_quantity
                    else Status.PartFilled
                )
            self._projected_deal_events.add(event_key)
            pending = self._deferred_deals.get(trade_key)
            if pending is not None:
                pending.pop(event_key, None)
                if not pending:
                    self._deferred_deals.pop(trade_key, None)
        return True

    def _replay_deferred_deals(self, trade_key: Tuple[str, str]) -> None:
        """Apply retained Deal-before-Order reports without touching positions again."""
        with self._trade_lock:
            deferred = list(self._deferred_deals.get(trade_key, {}).values())
        for deal in deferred:
            self._project_deal_event(deal)

    def list_trades(self) -> List[Trade]:
        """Return a new list containing the currently tracked Native Trades."""
        if not self._live_trade_sync_enabled:
            return list(self.api.list_trades())
        self._refresh_trade_references()
        with self._trade_lock:
            trade_keys = list(self._trades)
        for trade_key in trade_keys:
            self._replay_pending_order_events(trade_key)
            self._replay_deferred_deals(trade_key)
        with self._trade_lock:
            return list(self._trades.values())

    def close(self) -> None:
        """Stop background classification and synchronization work."""
        with self._trade_lock:
            if self._closed:
                return
            self._closed = True
            self._trade_sync_closed.set()
        thread_name = threading.current_thread().name
        self._trade_executor.shutdown(
            wait=not thread_name.startswith("trade-sync"), cancel_futures=True
        )
        self._executor.shutdown(
            wait=not thread_name.startswith("sync"), cancel_futures=True
        )

    def __enter__(self) -> "PositionSync":
        """Return this sync for use as a context manager."""
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Close background workers when leaving a context."""
        self.close()

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
            self._sync_account_positions(
                account, refresh_trades=not self._live_trade_sync_enabled
            )

    def _sync_account_positions(
        self, account: Account, refresh_trades: bool = True
    ) -> None:
        """Sync positions from API for a specific account.

        Args:
            account: Account to sync positions for
        """
        account_key = self._get_account_key(account)

        try:
            # Load positions for this account
            positions_pnl = self.api.list_positions(
                account=account, unit=Unit.Common, timeout=self.timeout
            )
        except Exception as e:
            logger.warning(f"Failed to load positions for account {account}: {e}")
            return

        # Determine if this is stock or futures account based on account_type
        account_type = account.account_type
        if account_type == AccountType.Stock:
            # Load and sum today's trades for this stock account
            trades_sum = self._load_and_sum_today_trades(
                account, refresh_status=refresh_trades
            )

            # Clear existing positions for this account
            self._stock_positions[account_key] = {}

            for pnl in positions_pnl:
                if isinstance(pnl, SjStockPosition):
                    # Calculate yd_offset_quantity
                    yd_offset = self._calculate_yd_offset_for_position(
                        code=pnl.code,
                        cond=pnl.cond,
                        direction=pnl.direction,
                        yd_quantity=pnl.yd_quantity,
                        trades_sum=trades_sum,
                    )

                    position = StockPosition(
                        code=pnl.code,
                        direction=pnl.direction,
                        quantity=pnl.quantity,
                        yd_quantity=pnl.yd_quantity,
                        yd_offset_quantity=yd_offset,
                        cond=pnl.cond,
                    )
                    key = (position.code, position.cond)
                    self._stock_positions[account_key][key] = position

        elif account_type == AccountType.Future:
            # Clear existing positions for this account
            self._futures_positions[account_key] = {}

            for pnl in positions_pnl:
                if isinstance(pnl, SjFuturePosition):
                    position = FuturesPosition(
                        code=pnl.code,
                        direction=pnl.direction,
                        quantity=pnl.quantity,
                    )
                    self._futures_positions[account_key][position.code] = position

        logger.info(f"Synced positions from API for account {account_key}")

    def _load_and_sum_today_trades(
        self, account: Account, refresh_status: bool = True
    ) -> Dict[Tuple[str, StockOrderCond, Action], int]:
        """Load and sum today's trades by (code, cond, action).

        Args:
            account: Account to load trades for

        Returns:
            Dict mapping (code, cond, action) -> total quantity
        """
        try:
            if refresh_status:
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

    def _get_local_positions(
        self, account: Optional[Account] = None
    ) -> Union[List[StockPosition], List[FuturesPosition]]:
        """Get positions from local tracking.

        Returns shallow copies (model_copy()) so callers cannot mutate the
        internal cache and so the returned list is a stable snapshot — the
        deal-callback path mutates the cached objects in place, so handing
        out the live references would let those values shift under callers.

        Args:
            account: Account to filter. None uses default account.

        Returns:
            List of locally tracked positions (independent copies)
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
                        pos.model_copy()
                        for pos in self._stock_positions[stock_key].values()
                    ]

            # Then try futopt_account
            if (
                hasattr(self.api, "futopt_account")
                and self.api.futopt_account is not None
            ):
                futopt_key = self._get_account_key(self.api.futopt_account)
                if futopt_key in self._futures_positions:
                    return [
                        pos.model_copy()
                        for pos in self._futures_positions[futopt_key].values()
                    ]

            # No positions found
            return []

        # Specific account provided
        account_key = self._get_account_key(account)
        account_type = account.account_type

        if account_type == AccountType.Stock:
            if account_key in self._stock_positions:
                return [
                    pos.model_copy()
                    for pos in self._stock_positions[account_key].values()
                ]
            return []
        elif account_type == AccountType.Future:
            if account_key in self._futures_positions:
                return [
                    pos.model_copy()
                    for pos in self._futures_positions[account_key].values()
                ]
            return []

        return []

    def sync_from_api(self, account: Optional[Account] = None) -> None:
        """Manually sync positions from API server.

        This method allows you to manually refresh positions from the API,
        useful when you want to ensure positions are in sync with the server.

        Args:
            account: Specific account to sync. If None, syncs all accounts.

        Example:
            >>> # Sync all accounts
            >>> sync.sync_from_api()
            >>>
            >>> # Sync only stock account
            >>> sync.sync_from_api(account=api.stock_account)
        """
        if self._live_trade_sync_enabled:
            self._reconcile_trade_references(account, clear_unresolved=True)

        if account is None:
            # Sync all accounts
            accounts = self.api.list_accounts()
            for acc in accounts:
                self._sync_account_positions(
                    acc, refresh_trades=not self._live_trade_sync_enabled
                )
        else:
            # Sync specific account
            self._sync_account_positions(
                account, refresh_trades=not self._live_trade_sync_enabled
            )

    def list_positions(
        self,
        account: Optional[Account] = None,
        unit: Unit = Unit.Common,
        timeout: Optional[int] = None,
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
            timeout: Query timeout in milliseconds (only used when querying API). None uses instance default.

        Returns:
            List of position objects for the specified account type:
            - Stock account: List[StockPosition]
            - Futures account: List[FuturesPosition]
            - None (default): List[StockPosition] from stock_account, or List[FuturesPosition] if no stock
        """
        # Use instance default timeout if not specified
        query_timeout = timeout if timeout is not None else self.timeout

        # sync_threshold = 0: Always use local
        if self.sync_threshold == 0:
            return self._get_local_positions(account)

        # sync_threshold > 0: Check if in unstable period
        if self._in_unstable_period(account):
            logger.debug("In unstable period, using local positions")
            return self._get_local_positions(account)

        # Stable period: Query API and compare
        logger.debug("In stable period, querying API positions")
        return self._query_and_check_positions(account, unit, query_timeout)

    def _query_and_check_positions(
        self,
        account: Optional[Account] = None,
        unit: Unit = Unit.Common,
        timeout: int = 5000,
    ) -> Union[List[StockPosition], List[FuturesPosition]]:
        """Query API positions, return immediately, then compare and update local in background.

        If deals occur during API query, returns local positions instead to ensure freshness.

        Args:
            account: Account to query
            unit: Unit type for query
            timeout: Query timeout in milliseconds

        Returns:
            API positions or local positions (if deals occurred during query)
        """
        # Determine which account to query
        if account is None:
            query_account = self._get_default_account()
            if query_account is None:
                logger.warning("No default account available")
                return []
        else:
            query_account = account

        # Record last deal time before querying API
        account_key = self._get_account_key(query_account)
        last_deal_before_query = self._last_deal_time.get(account_key)

        # Query API
        try:
            api_positions_pnl = self.api.list_positions(
                account=query_account, unit=unit, timeout=timeout
            )
        except Exception as e:
            logger.error(f"Failed to query API positions: {e}, falling back to local")
            return self._get_local_positions(account)

        # Check if deals occurred during API query
        last_deal_after_query = self._last_deal_time.get(account_key)
        if last_deal_after_query != last_deal_before_query:
            # New deals occurred during query - use fresh local positions
            logger.info(
                "Deals occurred during API query, using local positions for freshness"
            )
            return self._get_local_positions(account)

        # No new deals - convert API positions to our format
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

        For stock positions, yd_offset_quantity is computed from today's filled
        trades via _load_and_sum_today_trades + _calculate_yd_offset_for_position
        so the immediately returned yd_remaining_quantity is correct even when
        the position is new to local state. This matches the calculation that
        the background sync thread performs and means callers cannot observe a
        misleading yd_offset_quantity=0 transient value.

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
            trades_sum = self._load_and_sum_today_trades(account)
            stock_list: List[StockPosition] = []
            for pnl in api_positions:
                if isinstance(pnl, SjStockPosition):
                    yd_offset = self._calculate_yd_offset_for_position(
                        code=pnl.code,
                        cond=pnl.cond,
                        direction=pnl.direction,
                        yd_quantity=pnl.yd_quantity,
                        trades_sum=trades_sum,
                    )
                    pos = StockPosition(
                        code=pnl.code,
                        direction=pnl.direction,
                        quantity=pnl.quantity,
                        yd_quantity=pnl.yd_quantity,
                        yd_offset_quantity=yd_offset,
                        cond=pnl.cond,
                    )
                    stock_list.append(pos)
            return stock_list
        else:
            futures_list: List[FuturesPosition] = []
            for pnl in api_positions:
                if isinstance(pnl, SjFuturePosition):
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
        api_dict: Dict[Tuple[str, StockOrderCond], SjStockPosition] = {}
        for pnl in api_positions:
            if isinstance(pnl, SjStockPosition):
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
        api_dict: Dict[Tuple[str, StockOrderCond], SjStockPosition],
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
        api_dict: Dict[Tuple[str, StockOrderCond], SjStockPosition],
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

            position = StockPosition(
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
            if isinstance(pnl, SjFuturePosition):
                position = FuturesPosition(
                    code=pnl.code,
                    direction=pnl.direction,
                    quantity=pnl.quantity,
                )
                self._futures_positions[account_key][pnl.code] = position

        logger.info(
            f"Updated local futures positions from API for account {account_key}"
        )

    def _internal_callback(
        self, state: OrderState, data: Union[StockDeal, FuturesDeal, Dict]
    ) -> None:
        """Internal callback wrapper that chains to user callback.

        Args:
            state: OrderState enum value
            data: Order/deal data dictionary
        """
        if self._closed:
            return

        apply_position = True
        event_data = cast(Dict, data)
        is_combo = self._is_combo_event(state, event_data)

        # Project Trade state before positions and the user callback.
        if (
            self._live_trade_sync_enabled
            and not is_combo
            and state
            in (
                OrderState.StockOrder,
                OrderState.FuturesOrder,
            )
        ):
            order_data = event_data
            resolved = self._project_order_event(order_data)
            if resolved:
                self._replay_deferred_deals(self._order_trade_key(order_data))
            if not resolved and self._schedule_new_order_resolution(state, order_data):
                return
            if not resolved:
                self._defer_order_event(state, order_data)
                return
        elif not is_combo and state in (OrderState.StockDeal, OrderState.FuturesDeal):
            deal_data = event_data
            if "trade_id" in deal_data and "exchange_seq" in deal_data:
                event_key = self._deal_event_key(deal_data)
                with self._trade_lock:
                    apply_position = event_key not in self._seen_deal_events
                    self._seen_deal_events.add(event_key)
                self._project_deal_event(deal_data)

        # Process position update next.
        if apply_position:
            self.on_order_deal_event(state, data)

        # Then call user callback if registered.
        self._notify_user_callback(state, data)

    def set_order_callback(self, callback: OrderDealCallback) -> None:
        """Set user callback for order deal events.

        This allows users to register their own callback while still
        maintaining automatic position synchronization.

        Args:
            callback: User callback function with signature (state, data) -> None

        Example:
            >>> sync = PositionSync(api)
            >>> def my_callback(state, data):
            ...     print(f"Deal event: {data}")
            >>> sync.set_order_callback(my_callback)
        """
        self._user_callback = callback

    def on_order_deal_event(
        self, state: OrderState, data: Union[StockDeal, FuturesDeal, Dict]
    ) -> None:
        """Callback for order deal events.

        Args:
            state: OrderState enum value
            data: Order/deal data dictionary
        """
        # Handle stock deals
        if state == OrderState.StockDeal:
            self._update_position(cast(StockDeal, data), is_futures=False)
        # Handle futures deals
        elif state == OrderState.FuturesDeal:
            self._update_position(cast(FuturesDeal, data), is_futures=True)

    def _update_position(
        self, deal: Union[StockDeal, FuturesDeal], is_futures: bool = False
    ) -> None:
        """Update position based on deal event.

        Args:
            deal: Deal data from callback
            is_futures: True if futures/options deal, False if stock deal
        """
        # For futures, use full_code to get complete contract code
        # For stocks, use code
        if is_futures:
            code: str = deal.get("full_code") or deal["code"]  # type: ignore[assignment]
        else:
            code = cast(str, deal["code"])

        action = self._normalize_direction(cast(str, deal["action"]))
        quantity = deal.get("quantity", 0)
        price = deal.get("price", 0)
        broker_id = cast(str, deal["broker_id"])
        account_id = cast(str, deal["account_id"])

        # Create AccountDict from deal data
        account: AccountDict = {
            "broker_id": broker_id,
            "account_id": account_id,
        }

        if is_futures:
            self._update_futures_position(account, code, action, quantity, price)
        else:
            order_cond = self._normalize_cond(
                cast(str, deal.get("order_cond", StockOrderCond.Cash))
            )
            self._update_stock_position(
                account, code, action, quantity, price, order_cond
            )

    def _is_day_trading_offset(
        self, code: str, account_key: str, action: Action, order_cond: StockOrderCond
    ) -> Tuple[bool, Optional[StockOrderCond]]:
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
            position = StockPosition(
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
        # Convert string to Action enum/constants. Shioaji 1.5 constants are
        # Rust-backed classes and are not subscriptable like Python Enum.
        normalized = str(direction)
        if normalized.lower() == "buy":
            return Action.Buy
        if normalized.lower() == "sell":
            return Action.Sell
        try:
            return getattr(Action, normalized)
        except AttributeError:
            return Action[normalized]  # type: ignore[index]

    def _normalize_cond(self, cond: Union[StockOrderCond, str]) -> StockOrderCond:
        """Normalize order condition to StockOrderCond enum.

        Args:
            cond: StockOrderCond enum or string

        Returns:
            StockOrderCond enum
        """
        if isinstance(cond, StockOrderCond):
            return cond
        # Convert string to StockOrderCond enum/constants. Shioaji 1.5 constants
        # expose attributes but do not support StockOrderCond["Cash"].
        normalized = str(cond)
        try:
            return getattr(StockOrderCond, normalized)
        except AttributeError:
            pass
        try:
            return StockOrderCond[normalized]  # type: ignore[index]
        except (KeyError, TypeError):
            # Fallback to Cash if invalid
            return StockOrderCond.Cash
