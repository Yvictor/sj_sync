"""Example usage of PositionSync for real-time position tracking."""

import shioaji as sj
from sj_sync import PositionSync
from sj_sync.models import StockPosition

# Initialize Shioaji API
api = sj.Shioaji()
api.login("YOUR_API_KEY", "YOUR_SECRET_KEY")

# ============================================================================
# Example 1: Basic Usage (Original Behavior)
# ============================================================================
print("=== Example 1: Basic Usage ===")

# Create PositionSync instance (sync_threshold=0 by default)
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

# ============================================================================
# Example 2: Smart Sync Mode (Recommended for Production)
# ============================================================================
print("\n=== Example 2: Smart Sync Mode ===")

# Enable smart sync with 30-second threshold
# This provides the best of both worlds:
# - Fast response during active trading (uses local calculations)
# - Automatic verification after quiet period (queries API)
# - Auto-correction of any inconsistencies
sync_smart = PositionSync(api, sync_threshold=30)

# During active trading (within 30s after a deal):
# - Returns local calculated positions immediately (fast!)
# - No API calls needed

# After 30 seconds of no deals:
# - Queries api.list_positions() to verify accuracy
# - Returns API positions immediately to you
# - Background thread compares and auto-corrects any differences

positions = sync_smart.list_positions()
print(f"Smart sync positions: {len(positions)}")

for pos in positions:
    # Each position has:
    # - code: Stock/futures code
    # - direction: Buy or Sell
    # - quantity: Current total quantity
    # - yd_quantity: Yesterday's quantity (for stocks)
    # - cond: Order condition (Cash/MarginTrading/ShortSelling for stocks)
    if isinstance(pos, StockPosition):  # Stock position
        print(
            f"{pos.code}: {pos.direction} qty={pos.quantity}, yd={pos.yd_quantity}, cond={pos.cond}"
        )
    else:  # Futures position
        print(f"{pos.code}: {pos.direction} qty={pos.quantity}")

# ============================================================================
# Example 3: Different Sync Thresholds
# ============================================================================
print("\n=== Example 3: Different Sync Thresholds ===")

# For high-frequency trading (query API more frequently)
sync_hft = PositionSync(api, sync_threshold=10)  # 10 seconds
print("High-frequency mode: 10s threshold")

# For normal trading (balance between speed and verification)
sync_normal = PositionSync(api, sync_threshold=30)  # 30 seconds (recommended)
print("Normal mode: 30s threshold")

# For low-frequency trading (minimize API calls)
sync_lft = PositionSync(api, sync_threshold=60)  # 60 seconds
print("Low-frequency mode: 60s threshold")

# Disable smart sync (always use local calculations only)
sync_local_only = PositionSync(api, sync_threshold=0)  # Disabled
print("Local-only mode: disabled")

# ============================================================================
# Example 4: Custom Timeout Settings
# ============================================================================
print("\n=== Example 4: Custom Timeout Settings ===")

# Set default timeout during initialization (in milliseconds)
sync_timeout = PositionSync(api, sync_threshold=30, timeout=10000)  # 10 seconds
print("Default timeout: 10 seconds")

# Override timeout for specific query
positions = sync_timeout.list_positions(timeout=3000)  # 3 seconds for this call
print(f"Query with 3s timeout: {len(positions)} positions")

# Use default timeout (no timeout parameter specified)
positions = sync_timeout.list_positions()  # Uses 10s default
print(f"Query with default timeout: {len(positions)} positions")

# ============================================================================
# Example 5: Handling Midday Restart
# ============================================================================
print("\n=== Example 5: Midday Restart Support ===")

# If you restart your program during trading hours:
# - PositionSync automatically loads today's trades via api.list_trades()
# - Calculates yd_offset_quantity to correctly track yesterday's positions
# - Ensures accurate position tracking even after restart

sync_restart = PositionSync(api, sync_threshold=30)
positions = sync_restart.list_positions()

print(f"Positions after restart: {len(positions)}")
# All position quantities and yesterday's tracking will be accurate!

# ============================================================================
# Example 6: Using Custom Callback with Auto-Sync
# ============================================================================
print("\n=== Example 6: Custom Callback ===")

# PositionSync automatically handles position updates internally
# But you can also register your own callback to receive deal events
sync_callback = PositionSync(api, sync_threshold=30)


# Define your custom callback
def my_deal_callback(state, data):
    """Custom callback to handle deal events."""
    from shioaji.constant import OrderState

    if state == OrderState.StockDeal:
        print(f"Stock deal: {data.get('code')} {data.get('action')} {data.get('quantity')} @ {data.get('price')}")
    elif state == OrderState.FuturesDeal:
        print(f"Futures deal: {data.get('code')} {data.get('action')} {data.get('quantity')} @ {data.get('price')}")

    # You can add your custom logic here
    # - Send notifications
    # - Update database
    # - Trigger trading strategies
    # etc.


# Register your callback - positions are still auto-updated by PositionSync
sync_callback.set_order_callback(my_deal_callback)

print("Custom callback registered. Positions auto-sync + custom notifications enabled!")

# Now when deals occur:
# 1. PositionSync automatically updates positions (internal)
# 2. Your callback is called for custom processing
# 3. You can query updated positions anytime
positions = sync_callback.list_positions()
print(f"Current positions: {len(positions)}")
