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

        key = (code, order_cond)
        position = self._stock_positions[account_key].get(key)

        if position is None:
            # Create new position
            position = StockPosition(
                code=code,
                direction=action,
                quantity=quantity,
                yd_quantity=0,
                cond=order_cond,
            )
            self._stock_positions[account_key][key] = position
            logger.info(
                f"{code} NEW {action} {price} x {quantity} [{order_cond}] -> {position}"
            )
        else:
            # Update existing position
            if position.direction == action:
                position.quantity += quantity
            else:
                position.quantity -= quantity

            # Update cond if changed (e.g., day trading settlement)
            if position.cond != order_cond:
                # Remove old key and add with new key
                del self._stock_positions[account_key][key]
                position.cond = order_cond
                new_key = (code, order_cond)
                self._stock_positions[account_key][new_key] = position

            # Remove if quantity becomes zero
            if position.quantity == 0:
                del self._stock_positions[account_key][key]
                logger.info(
                    f"{code} CLOSED {action} {price} x {quantity} [{order_cond}] -> REMOVED"
                )
            else:
                logger.info(
                    f"{code} {action} {price} x {quantity} [{order_cond}] -> {position}"
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
