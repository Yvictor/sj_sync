# sj_sync

[![CI](https://github.com/yvictor/sj_sync/actions/workflows/ci.yml/badge.svg)](https://github.com/yvictor/sj_sync/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/yvictor/sj_sync/branch/master/graph/badge.svg)](https://codecov.io/gh/yvictor/sj_sync)
[![PyPI version](https://badge.fury.io/py/sj-sync.svg)](https://badge.fury.io/py/sj-sync)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Real-time position synchronization for Shioaji.

English | [繁體中文](README.zh-TW.md)

## Overview

`sj_sync` provides real-time position tracking using deal callbacks instead of repeatedly calling `api.list_positions()`. This approach:

- **Reduces API calls**: Initialize once with `list_positions()`, then update via callbacks
- **More responsive**: Positions update immediately when deals are executed
- **Tracks all details**: Supports cash, margin trading, short selling, day trading, and futures/options

## Features

- ✅ **Real-time updates** via `OrderState.StockDeal` and `OrderState.FuturesDeal` callbacks
- ✅ **Custom callback support**: Register your own callback while maintaining auto-sync
- ✅ **Smart sync mode**: Intelligently switches between local calculations and API queries
- ✅ **Manual sync API**: Force sync with API server for reconciliation
- ✅ **File logging**: Automatic logging to `sj_sync.log` with rotation and retention
- ✅ **Multiple trading types**: Cash, margin trading, short selling, day trading settlement
- ✅ **Futures/options support**: Tracks futures and options positions
- ✅ **Yesterday's quantity tracking**: Maintains `yd_quantity` for each position
- ✅ **Midday restart support**: Calculates `yd_offset_quantity` from today's trades
- ✅ **Automatic cleanup**: Removes positions when quantity reaches zero
- ✅ **Multi-account support**: Properly isolates positions across different accounts
- ✅ **Pydantic models**: Type-safe position objects
- ✅ **QuoteSync**: Real-time quote snapshots via streaming (Tick/BidAsk)

## Installation

```bash
uv add sj-sync
```

Or with pip:

```bash
pip install sj-sync
```

## Usage

### Basic Usage

```python
import shioaji as sj
from sj_sync import PositionSync

# Initialize and login
api = sj.Shioaji()
api.login("YOUR_API_KEY", "YOUR_SECRET_KEY")

# Create PositionSync (auto-loads positions and registers callbacks)
sync = PositionSync(api)

# Get all positions
positions = sync.list_positions()
for pos in positions:
    print(f"{pos.code}: {pos.direction} {pos.quantity}")

# Get positions for specific account
stock_positions = sync.list_positions(account=api.stock_account)
futures_positions = sync.list_positions(account=api.futopt_account)

# Positions auto-update when orders are filled!
```

### Smart Sync Mode

Enable smart sync to automatically verify and correct positions periodically:

```python
# Enable smart sync with 30-second threshold
sync = PositionSync(api, sync_threshold=30)

# How it works:
# - After a deal: Uses local calculations for 30 seconds (fast, responsive)
# - After 30 seconds: Switches to API query (verifies accuracy)
# - Automatically detects and corrects any inconsistencies
# - Background sync doesn't block position queries
```

**Smart Sync Benefits:**
- 🚀 **Fast response**: Local calculations during active trading
- ✅ **Auto-verification**: Periodic API checks ensure accuracy
- 🔄 **Auto-correction**: Detects and fixes position inconsistencies
- 📊 **Best of both**: Combines speed of local tracking with reliability of API

**Configuration:**
- `sync_threshold=0` (default): Always use local calculations (original behavior)
- `sync_threshold=30`: Use local for 30s after deals, then query API
- `sync_threshold=60`: Use local for 60s after deals, then query API

### Custom Callback

Register your own callback to receive deal events while maintaining automatic position synchronization:

```python
from sj_sync import PositionSync, OrderDealCallback
from shioaji.constant import OrderState

# Create PositionSync instance
sync = PositionSync(api, sync_threshold=30)

# Define your custom callback
def my_callback(state: OrderState, data: dict) -> None:
    if state == OrderState.StockDeal:
        print(f"Stock deal: {data.get('code')} {data.get('action')} "
              f"{data.get('quantity')} @ {data.get('price')}")
    elif state == OrderState.FuturesDeal:
        print(f"Futures deal: {data.get('code')} {data.get('action')} "
              f"{data.get('quantity')} @ {data.get('price')}")

    # Add your custom logic here:
    # - Send notifications
    # - Update database
    # - Trigger trading strategies
    # etc.

# Register your callback
sync.set_order_callback(my_callback)

# Now when deals occur:
# 1. PositionSync automatically updates positions (internal)
# 2. Your callback is called for custom processing
# 3. You can query updated positions anytime
positions = sync.list_positions()
```

**Callback Chain:**
- `PositionSync` processes deal events first (updates positions)
- Your callback is then invoked with the same event data
- Exceptions in user callback are caught and logged (won't break position sync)

### Manual Sync

Manually sync positions from API server when you need to ensure positions are up-to-date:

```python
from sj_sync import PositionSync

# Create PositionSync instance
sync = PositionSync(api)

# Sync all accounts from API
sync.sync_from_api()

# Or sync a specific account
sync.sync_from_api(account=api.stock_account)

# Useful when:
# - You want to verify positions against API server
# - After network reconnection
# - When you suspect local positions might be out of sync
# - For manual reconciliation
```

**Use Cases:**
- 🔄 **Manual reconciliation**: Force sync with API when needed
- 🌐 **After reconnection**: Refresh positions after network issues
- ✅ **Verification**: Double-check local positions against server
- 🎯 **Selective sync**: Sync specific accounts or all accounts

### QuoteSync

Real-time quote snapshots via streaming, without repeatedly calling `api.snapshots()`:

```python
import shioaji as sj
from sj_sync import QuoteSync

api = sj.Shioaji()
api.login("YOUR_API_KEY", "YOUR_SECRET_KEY")

# Create QuoteSync (registers streaming callbacks)
qs = QuoteSync(api)

# Subscribe to Tick data (default)
qs.subscribe(["2330", "2317"])

# Subscribe to Tick + BidAsk for real-time bid/ask prices
qs.subscribe(["2330"], quote_type=[sj.constant.QuoteType.Tick, sj.constant.QuoteType.BidAsk])

# Query snapshots locally (zero API calls)
all_snaps = qs.snapshots()              # all subscribed
filtered = qs.snapshots(["2330"])       # filtered by codes
snap = qs.snapshot("2330")              # single, or None

# Unsubscribe
qs.unsubscribe(["2317"])                                        # all types
qs.unsubscribe(["2330"], quote_type=[sj.constant.QuoteType.BidAsk])  # partial
```

**User Callbacks:**
```python
# Chain your own callback after internal snapshot update
def on_tick(exchange, tick):
    print(f"{tick.code}: {tick.close}")

qs.set_on_tick_stk_callback(on_tick)
qs.set_on_bidask_stk_callback(my_bidask_handler)
```

**How QuoteSync Works:**
1. `subscribe()` fetches initial snapshots via `api.snapshots()`, then subscribes to streaming
2. Streaming callbacks (Tick/BidAsk) update local `Snapshot` objects in-place
3. `snapshots()` / `snapshot()` return live references to these objects — zero API calls
4. Delta logic: adding BidAsk to an already-Tick-subscribed code only subscribes BidAsk

## Position Models

### StockPosition

```python
class StockPosition(BaseModel):
    code: str           # Stock code (e.g., "2330")
    direction: Action   # Action.Buy or Action.Sell
    quantity: int       # Current position quantity
    yd_quantity: int    # Yesterday's position quantity
    cond: StockOrderCond  # Cash, MarginTrading, or ShortSelling
```

### FuturesPosition

```python
class FuturesPosition(BaseModel):
    code: str           # Contract code (e.g., "TXFJ4")
    direction: Action   # Action.Buy or Action.Sell
    quantity: int       # Current position quantity
```

## API Reference

### PositionSync

#### `__init__(api: sj.Shioaji, sync_threshold: int = 0, timeout: int = 5000)`
Initialize with Shioaji API instance.

**Args:**
- `api`: Shioaji API instance
- `sync_threshold`: Smart sync threshold in seconds (default: 0)
  - `0`: Disabled - always use local calculations
  - `>0`: Enabled - use local for N seconds after deal, then query API
- `timeout`: API query timeout in milliseconds (default: 5000)

**Automatically:**
- Loads all positions from all accounts
- Registers deal callback for real-time updates
- Calculates `yd_offset_quantity` from today's trades (for midday restart)

#### `list_positions(account: Optional[Account] = None, unit: Unit = Unit.Common, timeout: Optional[int] = None) -> Union[List[StockPosition], List[FuturesPosition]]`
Get current positions.

**Args:**
- `account`: Account to filter. `None` uses default account (stock_account first, then futopt_account if no stock)
- `unit`: `Unit.Common` (lots) or `Unit.Share` (shares) - for compatibility, not used in real-time tracking
- `timeout`: Query timeout in milliseconds. `None` uses instance default (set in `__init__`)

**Returns:**
- Stock account: `List[StockPosition]`
- Futures account: `List[FuturesPosition]`
- `None` (default): Prioritizes stock_account, falls back to futopt_account

**Example:**
```python
# Get default account positions
positions = sync.list_positions()

# Get specific account positions
stock_positions = sync.list_positions(account=api.stock_account)
futures_positions = sync.list_positions(account=api.futopt_account)
```

#### `set_order_callback(callback: OrderDealCallback) -> None`
Register a custom callback to receive deal events.

**Args:**
- `callback`: Function with signature `(state: OrderState, data: Dict) -> None`

**Example:**
```python
def my_callback(state, data):
    print(f"Deal: {data}")

sync.set_order_callback(my_callback)
```

**Note:** Your callback is invoked after `PositionSync` processes the event. Exceptions in user callback are caught and logged.

#### `sync_from_api(account: Optional[Account] = None) -> None`
Manually sync positions from API server.

**Args:**
- `account`: Specific account to sync. If `None`, syncs all accounts.

**Example:**
```python
# Sync all accounts from API
sync.sync_from_api()

# Sync only stock account
sync.sync_from_api(account=api.stock_account)

# Sync only futures account
sync.sync_from_api(account=api.futopt_account)
```

**Use Cases:**
- Manual reconciliation with API server
- After network reconnection
- When you need to verify local positions
- Force refresh regardless of `sync_threshold` setting

**Note:** This method clears existing positions for the account(s) being synced and reloads from API server.

#### `on_order_deal_event(state: OrderState, data: Dict)`
Callback for order deal events. Automatically registered on init.

Handles:
- `OrderState.StockDeal`: Stock deal events
- `OrderState.FuturesDeal`: Futures/options deal events

### QuoteSync

#### `__init__(api: sj.Shioaji)`
Initialize with Shioaji API instance. Registers streaming callbacks.

#### `subscribe(codes=None, contracts=None, quote_type=None)`
Subscribe to streaming quotes. Fetches initial snapshots, then subscribes to streaming.

**Args:**
- `codes`: List of stock/futures/options codes
- `contracts`: List of Contract objects
- `quote_type`: List of `QuoteType` (default: `[QuoteType.Tick]`)

#### `unsubscribe(codes, quote_type=None)`
Unsubscribe from streaming quotes. `quote_type=None` unsubscribes all types.

#### `snapshots(codes=None) -> List[Snapshot]`
Get all or filtered snapshots. Returns live mutable references.

#### `snapshot(code) -> Optional[Snapshot]`
Get a single snapshot. Returns `None` if not subscribed.

#### `set_on_tick_stk_callback(callback)` / `set_on_tick_fop_callback(callback)`
Register user callback for tick events (called after internal update).

#### `set_on_bidask_stk_callback(callback)` / `set_on_bidask_fop_callback(callback)`
Register user callback for bid/ask events (called after internal update).

## How It Works

### 1. Initialization
- Calls `api.list_accounts()` to get all accounts
- Loads positions for each account via `api.list_positions(account)`
- Calculates `yd_offset_quantity` from `api.list_trades()` (for midday restart)
- Registers `on_order_deal_event` callback

### 2. Real-time Updates
- When orders are filled, Shioaji triggers the callback
- Callback updates internal position dictionaries
- Buy deals increase quantity (or create new position)
- Sell deals decrease quantity
- Zero quantity positions are automatically removed
- Tracks last deal time for smart sync

### 3. Smart Sync (when enabled)
- **During active trading** (within threshold after deal):
  - Returns local calculated positions immediately
  - Fast, responsive, no API calls

- **After threshold period** (no recent deals):
  - Queries `api.list_positions()` for verification
  - **Race condition protection**: If deals occur during API query, returns fresh local positions instead
  - Returns API positions immediately to user (if no concurrent deals)
  - Background thread compares API vs local positions
  - Auto-corrects any inconsistencies found

### 4. Position Storage
- Stock positions: `{account_key: {(code, cond): StockPositionInner}}`
- Futures positions: `{account_key: {code: FuturesPosition}}`
- Account key = `broker_id + account_id`
- Internal model tracks `yd_offset_quantity` for accurate calculations

## Development

### Setup

```bash
git clone https://github.com/yvictor/sj_sync.git
cd sj_sync
uv sync
```

### Run Tests

```bash
# All tests
uv run pytest tests/ -v

# With coverage
uv run pytest --cov=sj_sync --cov-report=html
```

### Code Quality

```bash
# Linting
uv run ruff check src/ tests/

# Formatting
uv run ruff format src/ tests/

# Type checking
uv run zuban check src/
```

### CI/CD

Every push and pull request triggers automated:
- ✅ Code quality checks (ruff, zuban)
- ✅ All 62 tests (unit + BDD + smart sync)
- ✅ Coverage report to Codecov (90%+)
- ✅ Build verification

See [CI Setup Guide](.github/CI_SETUP.md) for details.

## Testing

The project includes comprehensive pytest tests covering:

**Unit Tests (37 tests):**
- ✅ Position initialization from `list_positions()`
- ✅ Buy/sell deal events
- ✅ Day trading scenarios
- ✅ Margin trading and short selling
- ✅ Futures/options deals
- ✅ Multi-account support
- ✅ Custom callback support (3 tests)
  - Callback registration
  - User callback invocation
  - Exception handling in user callback
- ✅ Smart sync mode (10 tests)
  - Threshold disabled/enabled behavior
  - Unstable/stable period switching
  - Background position verification
  - Inconsistency detection and auto-correction
  - API query failure handling
  - Manual sync API (`sync_from_api`)
  - Race condition protection during API query
- ✅ Edge cases and error handling

**BDD Tests (25 scenarios in Chinese):**
- ✅ 當沖交易 (15 scenarios - Day trading offset rules)
- ✅ 盤中重啟 (10 scenarios - Midday restart with yd_offset calculation)
- ✅ 融資融券 (Margin/short trading with yesterday's positions)
- ✅ 混合場景 (Complex mixed trading scenarios)
- ✅ Correct handling of `yd_quantity` and `yd_offset_quantity`

Run tests with:
```bash
# All tests (62 total)
uv run pytest tests/ -v

# With coverage report (90%+)
uv run pytest --cov=sj_sync --cov-report=html --cov-report=term-missing
```

View coverage report:
```bash
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

## License

MIT License

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass (`pytest`, `zuban check`, `ruff check`)
5. Submit a pull request
