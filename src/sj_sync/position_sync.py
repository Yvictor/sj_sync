"""Real-time position synchronization for Shioaji."""

from loguru import logger
from typing import Dict, List, Optional, Union, Tuple
import shioaji as sj
from shioaji.constant import OrderState, Action, StockOrderCond, Unit
from shioaji.account import Account, AccountType
from shioaji.position import StockPosition as SjStockPostion
from shioaji.position import FuturePosition as SjFuturePostion
from .models import StockPosition, FuturesPosition, AccountDict


class PositionSync:
    """Synchronize positions in real-time using deal callbacks.

    Usage:
        sync = PositionSync(api)
        # Positions are automatically loaded on init
        positions = sync.list_positions()  # Get all positions
        positions = sync.list_positions(account=api.stock_account)  # Filter by account
    """

    def __init__(self, api: sj.Shioaji):
        """Initialize PositionSync with Shioaji API instance.

        Automatically loads all positions and registers deal callback.

        Args:
            api: Shioaji API instance
        """
        self.api = api
        self.api.set_order_callback(self.on_order_deal_event)

        # Separate dicts for stock and futures positions
        # Stock: {account_key: {(code, cond): StockPosition}}
        # Futures: {account_key: {code: FuturesPosition}}
        # account_key = broker_id + account_id
        self._stock_positions: Dict[
            str, Dict[Tuple[str, StockOrderCond], StockPosition]
        ] = {}
        self._futures_positions: Dict[str, Dict[str, FuturesPosition]] = {}

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
                logger.warning(
                    f"Failed to load positions for account {account}: {e}"
                )
                continue

            # Determine if this is stock or futures account based on account_type
            account_type = account.account_type
            if account_type == AccountType.Stock:
                for pnl in positions_pnl:
                    if isinstance(pnl, SjStockPostion):
                        position = StockPosition(
                            code=pnl.code,
                            direction=pnl.direction,
                            quantity=pnl.quantity,
                            yd_quantity=pnl.yd_quantity,
                            yd_offset_quantity=0,  # Today starts with 0 offset
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

    def list_positions(  # noqa: ARG002
        self, account: Optional[Account] = None, unit: Unit = Unit.Common
    ) -> Union[List[StockPosition], List[FuturesPosition]]:
        """Get all current positions.

        Args:
            account: Account to filter. None uses default stock_account first, then futopt_account if no stock.
            unit: Unit.Common or Unit.Share (for compatibility, not used in real-time tracking)

        Returns:
            List of position objects for the specified account type:
            - Stock account: List[StockPosition]
            - Futures account: List[FuturesPosition]
            - None (default): List[StockPosition] from stock_account, or List[FuturesPosition] if no stock
        """
        if account is None:
            # Use default accounts - prioritize stock_account
            if (
                hasattr(self.api, "stock_account")
                and self.api.stock_account is not None
            ):
                stock_account_key = self._get_account_key(self.api.stock_account)
                if stock_account_key in self._stock_positions:
                    return list(self._stock_positions[stock_account_key].values())

            # No stock positions, try futures
            if (
                hasattr(self.api, "futopt_account")
                and self.api.futopt_account is not None
            ):
                futopt_account_key = self._get_account_key(self.api.futopt_account)
                if futopt_account_key in self._futures_positions:
                    futures_list: List[FuturesPosition] = list(self._futures_positions[futopt_account_key].values())
                    return futures_list

            # No positions at all
            return []
        else:
            # Specific account - use AccountType enum
            account_key = self._get_account_key(account)
            account_type = account.account_type

            if account_type == AccountType.Stock:
                if account_key in self._stock_positions:
                    return list(self._stock_positions[account_key].values())
                return []
            elif account_type == AccountType.Future:
                if account_key in self._futures_positions:
                    futures_list: List[FuturesPosition] = list(self._futures_positions[account_key].values())
                    return futures_list
                return []

            return []

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

        # If there's remaining quantity after offsetting today's, it offsets yesterday's position
        if remaining_qty > 0 and opposite_key in self._stock_positions[account_key]:
            # Calculate how much yesterday's position is left
            opposite_pos = self._stock_positions[account_key][opposite_key]
            yd_available = opposite_pos.yd_quantity - opposite_pos.yd_offset_quantity
            yd_offset = min(remaining_qty, yd_available)

            if yd_offset > 0:
                # Reduce quantity and increase yd_offset_quantity (yd_quantity never changes)
                opposite_pos.quantity -= yd_offset
                opposite_pos.yd_offset_quantity += yd_offset
                remaining_qty -= yd_offset
                logger.info(
                    f"{code} OFFSET YD {action} {price} x {yd_offset} "
                    f"[{order_cond}] offsets [{opposite_cond}] yd -> {opposite_pos}"
                )

                if opposite_pos.quantity == 0:
                    del self._stock_positions[account_key][opposite_key]
                    logger.info(f"{code} [{opposite_cond}] REMOVED (fully closed)")

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
