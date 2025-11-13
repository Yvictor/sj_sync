# sj_sync

Real-time position synchronization for Shioaji.

## Overview

`sj_sync` provides real-time position tracking using deal callbacks instead of repeatedly calling `api.list_positions()`. This approach:

- **Reduces API calls**: Initialize once with `list_positions()`, then update via callbacks
- **More responsive**: Positions update immediately when deals are executed
- **Tracks all details**: Supports cash, margin trading, short selling, day trading, and futures/options

## Features

- ✅ **Real-time updates** via `OrderState.StockDeal` and `OrderState.FuturesDeal` callbacks
- ✅ **Multiple trading types**: Cash, margin trading, short selling, day trading settlement
- ✅ **Futures/options support**: Tracks futures and options positions
- ✅ **Yesterday's quantity tracking**: Maintains `yd_quantity` for each position
- ✅ **Automatic cleanup**: Removes positions when quantity reaches zero
- ✅ **Multi-account support**: Properly isolates positions across different accounts
- ✅ **Pydantic models**: Type-safe position objects

## Installation

```bash
uv add sj-sync
```

Or with pip:

```bash
pip install sj-sync
```

## Usage

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

#### `__init__(api: sj.Shioaji)`
Initialize with Shioaji API instance. Automatically:
- Loads all positions from all accounts
- Registers deal callback for real-time updates

#### `list_positions(account: Optional[Account] = None, unit: Unit = Unit.Common) -> Union[List[StockPosition], List[FuturesPosition]]`
Get current positions.

**Args:**
- `account`: Account to filter. `None` uses default account (stock_account first, then futopt_account if no stock)
- `unit`: `Unit.Common` (lots) or `Unit.Share` (shares) - for compatibility, not used in real-time tracking

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

#### `on_order_deal_event(state: OrderState, data: Dict)`
Callback for order deal events. Automatically registered on init.

Handles:
- `OrderState.StockDeal`: Stock deal events
- `OrderState.FuturesDeal`: Futures/options deal events

## How It Works

1. **Initialization**:
   - Calls `api.list_accounts()` to get all accounts
   - Loads positions for each account via `api.list_positions(account)`
   - Registers `on_order_deal_event` callback

2. **Real-time Updates**:
   - When orders are filled, Shioaji triggers the callback
   - Callback updates internal position dictionaries
   - Buy deals increase quantity (or create new position)
   - Sell deals decrease quantity
   - Zero quantity positions are automatically removed

3. **Position Storage**:
   - Stock positions: `{account_key: {(code, cond): StockPosition}}`
   - Futures positions: `{account_key: {code: FuturesPosition}}`
   - Account key = `broker_id + account_id`

## Development

### Setup

```bash
git clone https://github.com/yvictor/sj_sync.git
cd sj_sync
uv sync
```

### Run Tests

```bash
uv run pytest tests/ -v
```

### Type Checking

```bash
uv run zuban check src/
```

### Linting

```bash
uv run ruff check src/ tests/
```

## Testing

The project includes comprehensive pytest tests covering:

- ✅ Position initialization from `list_positions()`
- ✅ Buy/sell deal events
- ✅ Day trading scenarios
- ✅ Margin trading and short selling
- ✅ Futures/options deals
- ✅ Multi-account support
- ✅ Edge cases and error handling

Run tests with:
```bash
uv run pytest tests/ -v --cov=src/sj_sync
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
