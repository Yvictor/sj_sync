"""sj_sync - Real-time position synchronization for Shioaji."""

from .position_sync import PositionSync
from .models import StockPosition, FuturesPosition, Position, AccountDict
from .types import StockDeal, FuturesDeal

__all__ = [
    "PositionSync",
    "StockPosition",
    "FuturesPosition",
    "Position",
    "AccountDict",
    "StockDeal",
    "FuturesDeal",
]


def main() -> None:
    """Main entry point for CLI."""
    print("Hello from sj-sync!")
