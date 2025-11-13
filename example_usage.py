"""Example usage of PositionSync for real-time position tracking."""

import shioaji as sj
from sj_sync import PositionSync

# Initialize Shioaji API
api = sj.Shioaji()
api.login("YOUR_API_KEY", "YOUR_SECRET_KEY")

# Create PositionSync instance
# This automatically loads all positions and registers callbacks
sync = PositionSync(api)

# Get all positions (from default account)
positions = sync.list_positions()
print(f"Total positions: {len(positions)}")

for pos in positions:
    print(f"{pos.code}: {pos.direction} {pos.quantity}")

# Get positions for specific account
stock_positions = sync.list_positions(account=api.stock_account)
print(f"\nStock account positions: {len(stock_positions)}")

futures_positions = sync.list_positions(account=api.futopt_account)
print(f"Futures account positions: {len(futures_positions)}")

# Positions will be automatically updated when orders are filled
# No need to call api.list_positions() repeatedly!
