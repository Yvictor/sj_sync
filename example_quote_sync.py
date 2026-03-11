"""Example usage of QuoteSync for real-time quote snapshots."""

import os
import time

import shioaji as sj
from dotenv import load_dotenv

from sj_sync import QuoteSync

load_dotenv()

# Initialize Shioaji API
api = sj.Shioaji()
api.login(
    api_key=os.environ["SJ_API_KEY"],
    secret_key=os.environ["SJ_SEC_KEY"],
)

# ============================================================================
# Example 1: Basic Usage — Subscribe and Query Snapshots
# ============================================================================
print("=== Example 1: Basic Usage ===")

qs = QuoteSync(api)

# Subscribe to Tick data (default)
qs.subscribe(["2330", "2317"])

# Wait a moment for initial streaming data
time.sleep(2)

# Query all snapshots locally (zero API calls)
all_snaps = qs.snapshots()
print(f"Total subscribed: {len(all_snaps)}")
for snap in all_snaps:
    print(
        f"  {snap.code}: close={snap.close}, volume={snap.total_volume}, "
        f"change={snap.change_price} ({snap.change_rate}%)"
    )

# Query filtered snapshots
filtered = qs.snapshots(["2330"])
print(f"\nFiltered (2330): close={filtered[0].close}")

# ============================================================================
# Example 2: Subscribe with BidAsk for Real-time Bid/Ask Prices
# ============================================================================
print("\n=== Example 2: Tick + BidAsk ===")

# Add BidAsk to already-subscribed code (delta — only subscribes BidAsk)
qs.subscribe(["2330"], quote_type=[sj.constant.QuoteType.BidAsk])

time.sleep(2)

snaps = qs.snapshots(["2330"])
snap = snaps[0]
print(
    f"  {snap.code}: close={snap.close}, "
    f"buy={snap.buy_price}x{snap.buy_volume}, "
    f"sell={snap.sell_price}x{snap.sell_volume}"
)

# ============================================================================
# Example 3: Subscribe Futures
# ============================================================================
print("\n=== Example 3: Futures ===")

# Subscribe to near-month TX futures
contracts = [api.Contracts.Futures.TXF.TXFR1]
qs.subscribe(
    contracts=contracts,
    quote_type=[sj.constant.QuoteType.Tick, sj.constant.QuoteType.BidAsk],
)

time.sleep(2)

for snap in qs.snapshots():
    print(
        f"  {snap.code}: close={snap.close}, "
        f"buy={snap.buy_price}, sell={snap.sell_price}, "
        f"vol={snap.total_volume}"
    )

# ============================================================================
# Example 4: User Callback
# ============================================================================
print("\n=== Example 4: User Callback ===")


def on_tick(exchange, tick):
    print(f"  [tick] {tick.code}: {tick.close} vol={tick.volume}")


def on_bidask(exchange, bidask):
    print(
        f"  [bidask] {bidask.code}: bid={bidask.bid_price[0]} ask={bidask.ask_price[0]}"
    )


qs.set_on_tick_stk_callback(on_tick)
qs.set_on_bidask_stk_callback(on_bidask)

print("Listening for 5 seconds...")
time.sleep(5)

# ============================================================================
# Example 5: Partial Unsubscribe
# ============================================================================
print("\n=== Example 5: Unsubscribe ===")

# Unsubscribe BidAsk only, keep Tick
qs.unsubscribe(["2330"], quote_type=[sj.constant.QuoteType.BidAsk])
print("Unsubscribed BidAsk for 2330, Tick still active")

# Full unsubscribe
qs.unsubscribe(["2317"])
print("Fully unsubscribed 2317")

print(f"\nRemaining subscriptions: {len(qs.snapshots())}")
for snap in qs.snapshots():
    print(f"  {snap.code}: close={snap.close}")

# Cleanup
api.logout()
print("\nDone!")
