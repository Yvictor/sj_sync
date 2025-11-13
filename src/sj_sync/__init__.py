"""sj_sync - Real-time position synchronization for Shioaji."""

from .position_sync import PositionSync
from .models import StockPosition, FuturesPosition, Position, AccountDict

__all__ = [
    "PositionSync",
    "StockPosition",
    "FuturesPosition",
    "Position",
    "AccountDict",
]


def main() -> None:
    """Main entry point for CLI."""
    print("Hello from sj-sync!")
