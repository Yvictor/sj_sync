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
    Contract = sj.Contract
    SjStockPosition = sj.StockPosition
    SjFuturePosition = sj.FuturePosition
    Snapshot = sj.Snapshot
    ChangeType = sj.ChangeType
    QuoteType = sj.QuoteType
    TickType = sj.TickType
else:  # pragma: no cover - covered by the Shioaji 1.3.3 compatibility test run.
    from shioaji.account import Account, AccountType
    from shioaji.contracts import Contract
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


__all__ = [
    "sj",
    "Action",
    "StockOrderCond",
    "OrderState",
    "Status",
    "Unit",
    "Account",
    "AccountType",
    "Contract",
    "SjStockPosition",
    "SjFuturePosition",
    "Snapshot",
    "ChangeType",
    "QuoteType",
    "TickType",
]
