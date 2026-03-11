"""Real-time quote snapshot synchronization for Shioaji."""

import time
from typing import Callable, Dict, List, Optional, Set

from loguru import logger

import shioaji as sj
from shioaji.constant import ChangeType, QuoteType, TickType
from shioaji.data import Snapshot

logger.add(
    "sj_sync.log",
    rotation="1 day",
    retention="5 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
)

# Rate limit: 50 subscribe/unsubscribe calls per 5 seconds
_RATE_LIMIT_CALLS = 50
_RATE_LIMIT_WINDOW = 5.0

# Batch size for api.snapshots()
_SNAPSHOT_BATCH_SIZE = 500


class QuoteSync:
    """Synchronize quote snapshots in real-time using streaming callbacks.

    Subscribes to Shioaji streaming (Tick/BidAsk), maintains local Snapshot
    objects, and serves queries locally without additional API calls.

    Usage:
        qs = QuoteSync(api)
        qs.subscribe(["2330", "2317"])
        snaps = qs.snapshots(["2330"])

    Note: One QuoteSync per api instance — creating a second will overwrite
    the first's callbacks.
    """

    def __init__(self, api: sj.Shioaji) -> None:
        self.api = api
        self._snapshots: Dict[str, Snapshot] = {}
        self._contracts: Dict[str, sj.contracts.Contract] = {}
        self._subscribed: Dict[str, Set[QuoteType]] = {}
        self._user_tick_stk_callback: Optional[Callable] = None
        self._user_tick_fop_callback: Optional[Callable] = None
        self._user_bidask_stk_callback: Optional[Callable] = None
        self._user_bidask_fop_callback: Optional[Callable] = None

        api.quote.set_on_tick_stk_v1_callback(self._on_tick_stk)
        api.quote.set_on_tick_fop_v1_callback(self._on_tick_fop)
        api.quote.set_on_bidask_stk_v1_callback(self._on_bidask_stk)
        api.quote.set_on_bidask_fop_v1_callback(self._on_bidask_fop)

    def subscribe(
        self,
        codes: Optional[List[str]] = None,
        contracts: Optional[List[sj.contracts.Contract]] = None,
        quote_type: Optional[List[QuoteType]] = None,
    ) -> None:
        """Subscribe to streaming quotes for given codes/contracts.

        Args:
            codes: Stock/futures/options codes to subscribe.
            contracts: Contract objects to subscribe.
            quote_type: List of QuoteType to subscribe. Defaults to [QuoteType.Tick].
        """
        if codes is None and contracts is None:
            raise ValueError("Must provide either codes or contracts")

        if quote_type is None:
            quote_type = [QuoteType.Tick]

        resolved: List[sj.contracts.Contract] = []
        if contracts:
            resolved.extend(contracts)
        if codes:
            for code in codes:
                contract = self._resolve_contract(code)
                resolved.append(contract)

        # Separate new contracts (need initial snapshot) from existing
        new_contracts = [c for c in resolved if c.code not in self._snapshots]

        # Fetch initial snapshots for new contracts in batches
        if new_contracts:
            for i in range(0, len(new_contracts), _SNAPSHOT_BATCH_SIZE):
                batch = new_contracts[i : i + _SNAPSHOT_BATCH_SIZE]
                try:
                    snaps = self.api.snapshots(batch)
                    for snap in snaps:
                        self._snapshots[snap.code] = snap
                except Exception as e:
                    codes_str = [c.code for c in batch]
                    logger.warning(
                        f"Failed to fetch initial snapshots for {codes_str}: {e}"
                    )

        # Store contracts and compute delta subscriptions
        rate_limit_timestamps: List[float] = []
        for contract in resolved:
            code = contract.code
            self._contracts[code] = contract

            # Ensure snapshot exists even if api.snapshots() failed
            if code not in self._snapshots:
                self._snapshots[code] = self._empty_snapshot(code)

            existing = self._subscribed.get(code, set())
            new_types = set(quote_type) - existing

            for qt in new_types:
                self._rate_limit(rate_limit_timestamps)
                self.api.quote.subscribe(contract, quote_type=qt)
                rate_limit_timestamps.append(time.monotonic())

            self._subscribed[code] = existing | set(quote_type)

    def unsubscribe(
        self,
        codes: List[str],
        quote_type: Optional[List[QuoteType]] = None,
    ) -> None:
        """Unsubscribe from streaming quotes.

        Args:
            codes: Codes to unsubscribe.
            quote_type: Specific QuoteTypes to unsubscribe. None = all types.
        """
        rate_limit_timestamps: List[float] = []
        for code in codes:
            if code not in self._subscribed:
                continue

            contract = self._contracts.get(code)
            if contract is None:
                continue

            types_to_remove = (
                set(quote_type) if quote_type else set(self._subscribed[code])
            )

            for qt in types_to_remove:
                if qt in self._subscribed[code]:
                    self._rate_limit(rate_limit_timestamps)
                    self.api.quote.unsubscribe(contract, quote_type=qt)
                    rate_limit_timestamps.append(time.monotonic())

            self._subscribed[code] -= types_to_remove

            if not self._subscribed[code]:
                del self._subscribed[code]
                del self._snapshots[code]
                del self._contracts[code]

    def snapshots(
        self,
        codes: Optional[List[str]] = None,
        contracts: Optional[List[sj.contracts.Contract]] = None,
    ) -> List[Snapshot]:
        """Get snapshots. Returns live mutable references.

        Args:
            codes: Filter by code strings (preserves order).
            contracts: Filter by Contract objects (preserves order).
            None for both = all snapshots.

        Returns:
            List of Snapshot objects.
        """
        if codes is None and contracts is None:
            return list(self._snapshots.values())
        keys: List[str] = []
        if contracts:
            keys.extend(c.code for c in contracts)
        if codes:
            keys.extend(codes)
        return [self._snapshots[k] for k in keys if k in self._snapshots]

    def set_on_tick_stk_callback(self, callback: Callable) -> None:
        """Register user callback for stock tick events."""
        self._user_tick_stk_callback = callback

    def set_on_tick_fop_callback(self, callback: Callable) -> None:
        """Register user callback for futures/options tick events."""
        self._user_tick_fop_callback = callback

    def set_on_bidask_stk_callback(self, callback: Callable) -> None:
        """Register user callback for stock bid/ask events."""
        self._user_bidask_stk_callback = callback

    def set_on_bidask_fop_callback(self, callback: Callable) -> None:
        """Register user callback for futures/options bid/ask events."""
        self._user_bidask_fop_callback = callback

    # -- Internal callbacks --

    def _on_tick_stk(self, exchange, tick) -> None:
        try:
            if tick.code not in self._snapshots:
                return
            snap = self._snapshots[tick.code]
            snap.close = float(tick.close)
            snap.open = float(tick.open)
            snap.high = float(tick.high)
            snap.low = float(tick.low)
            snap.volume = tick.volume
            snap.total_volume = tick.total_volume
            snap.amount = int(tick.amount)
            snap.total_amount = int(tick.total_amount)
            snap.tick_type = tick.tick_type
            snap.average_price = float(tick.avg_price)
            snap.change_price = float(tick.price_chg)
            snap.change_rate = float(tick.pct_chg)
            snap.change_type = tick.chg_type
        except Exception as e:
            logger.error(
                f"Error in tick_stk callback for {getattr(tick, 'code', '?')}: {e}"
            )
        try:
            if self._user_tick_stk_callback:
                self._user_tick_stk_callback(exchange, tick)
        except Exception as e:
            logger.error(f"Error in user tick_stk callback: {e}")

    def _on_tick_fop(self, exchange, tick) -> None:
        try:
            if tick.code not in self._snapshots:
                return
            snap = self._snapshots[tick.code]
            snap.close = float(tick.close)
            snap.open = float(tick.open)
            snap.high = float(tick.high)
            snap.low = float(tick.low)
            snap.volume = tick.volume
            snap.total_volume = tick.total_volume
            snap.amount = int(tick.amount)
            snap.total_amount = int(tick.total_amount)
            snap.tick_type = tick.tick_type
            snap.average_price = float(tick.avg_price)
            snap.change_price = float(tick.price_chg)
            snap.change_rate = float(tick.pct_chg)
            snap.change_type = tick.chg_type
        except Exception as e:
            logger.error(
                f"Error in tick_fop callback for {getattr(tick, 'code', '?')}: {e}"
            )
        try:
            if self._user_tick_fop_callback:
                self._user_tick_fop_callback(exchange, tick)
        except Exception as e:
            logger.error(f"Error in user tick_fop callback: {e}")

    def _on_bidask_stk(self, exchange, bidask) -> None:
        try:
            if bidask.code not in self._snapshots:
                return
            snap = self._snapshots[bidask.code]
            if bidask.bid_price:
                snap.buy_price = float(bidask.bid_price[0])
                snap.buy_volume = int(bidask.bid_volume[0])
            if bidask.ask_price:
                snap.sell_price = float(bidask.ask_price[0])
                snap.sell_volume = int(bidask.ask_volume[0])
        except Exception as e:
            logger.error(
                f"Error in bidask_stk callback for {getattr(bidask, 'code', '?')}: {e}"
            )
        try:
            if self._user_bidask_stk_callback:
                self._user_bidask_stk_callback(exchange, bidask)
        except Exception as e:
            logger.error(f"Error in user bidask_stk callback: {e}")

    def _on_bidask_fop(self, exchange, bidask) -> None:
        try:
            if bidask.code not in self._snapshots:
                return
            snap = self._snapshots[bidask.code]
            if bidask.bid_price:
                snap.buy_price = float(bidask.bid_price[0])
                snap.buy_volume = int(bidask.bid_volume[0])
            if bidask.ask_price:
                snap.sell_price = float(bidask.ask_price[0])
                snap.sell_volume = int(bidask.ask_volume[0])
        except Exception as e:
            logger.error(
                f"Error in bidask_fop callback for {getattr(bidask, 'code', '?')}: {e}"
            )
        try:
            if self._user_bidask_fop_callback:
                self._user_bidask_fop_callback(exchange, bidask)
        except Exception as e:
            logger.error(f"Error in user bidask_fop callback: {e}")

    # -- Helpers --

    def _resolve_contract(self, code: str) -> sj.contracts.Contract:
        """Resolve a code string to a Contract object."""
        for collection in [
            self.api.Contracts.Stocks,
            self.api.Contracts.Futures,
            self.api.Contracts.Options,
        ]:
            try:
                contract = collection[code]
                if contract is not None:
                    return contract
            except (KeyError, IndexError, AttributeError):
                continue
        raise ValueError(f"Cannot resolve contract for code: {code}")

    @staticmethod
    def _empty_snapshot(code: str = "") -> Snapshot:
        """Create an empty Snapshot with default values."""
        return Snapshot(
            ts=0,
            code=code,
            exchange="",
            open=0.0,
            high=0.0,
            low=0.0,
            close=0.0,
            tick_type=TickType.No,
            change_price=0.0,
            change_rate=0.0,
            change_type=ChangeType.Unchanged,
            average_price=0.0,
            volume=0,
            total_volume=0,
            amount=0,
            total_amount=0,
            yesterday_volume=0.0,
            buy_price=0.0,
            buy_volume=0.0,
            sell_price=0.0,
            sell_volume=0,
            volume_ratio=0.0,
        )

    @staticmethod
    def _rate_limit(timestamps: List[float]) -> None:
        """Simple rate limiter: sleep if we've hit the limit within the window."""
        now = time.monotonic()
        # Remove timestamps outside the window
        while timestamps and now - timestamps[0] > _RATE_LIMIT_WINDOW:
            timestamps.pop(0)
        if len(timestamps) >= _RATE_LIMIT_CALLS:
            sleep_time = _RATE_LIMIT_WINDOW - (now - timestamps[0])
            if sleep_time > 0:
                time.sleep(sleep_time)
