"""Version-aware Shioaji imports."""

import shioaji as sj


def _version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in version.split("."):
        digits = ""
        for char in part:
            if not char.isdigit():
                break
            digits += char
        if digits:
            parts.append(int(digits))
        else:
            break
    return tuple(parts)


_SHIOAJI_VERSION = _version_tuple(getattr(sj, "__version__", "0"))

if _SHIOAJI_VERSION >= (1, 5):
    Action = sj.Action
    StockOrderCond = sj.StockOrderCond
    OrderState = sj.OrderState
    Status = sj.OrderStatus
    Unit = sj.Unit
    Account = sj.Account
    AccountType = sj.AccountType
    StockAccount = sj.Account
    FutureAccount = sj.Account
    Contract = sj.Contract
    Stock = sj.Stock
    Future = sj.Future
    Option = sj.Option
    Deal = sj.Deal
    FuturesOrder = sj.FuturesOrder
    NativeOrderStatus = sj.OrderStatus
    StockOrder = sj.StockOrder
    Trade = sj.Trade
    SjStockPosition = sj.StockPosition
    SjFuturePosition = sj.FuturePosition
    Snapshot = sj.Snapshot
    ChangeType = sj.ChangeType
    QuoteType = sj.QuoteType
    TickType = sj.TickType
else:  # pragma: no cover - covered by the Shioaji 1.3.3 compatibility test run.
    from shioaji.account import Account, AccountType, FutureAccount, StockAccount
    from shioaji.contracts import Contract, Future, Option, Stock
    from shioaji.constant import (
        Action,
        ChangeType,
        OrderState,
        QuoteType,
        Status,
        StockOrderCond,
        TickType,
        Unit,
    )
    from shioaji.data import Snapshot
    from shioaji.position import FuturePosition as SjFuturePosition
    from shioaji.position import StockPosition as SjStockPosition
    from shioaji.order import (
        Deal,
        FuturesOrder,
        OrderStatus as NativeOrderStatus,
        StockOrder,
        Trade,
    )


__all__ = [
    "sj",
    "Action",
    "StockOrderCond",
    "OrderState",
    "Status",
    "Unit",
    "Account",
    "AccountType",
    "StockAccount",
    "FutureAccount",
    "Contract",
    "Stock",
    "Future",
    "Option",
    "Deal",
    "FuturesOrder",
    "NativeOrderStatus",
    "StockOrder",
    "Trade",
    "SjStockPosition",
    "SjFuturePosition",
    "Snapshot",
    "ChangeType",
    "QuoteType",
    "TickType",
]
