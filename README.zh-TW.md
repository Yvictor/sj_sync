# sj_sync

[![CI](https://github.com/yvictor/sj_sync/actions/workflows/ci.yml/badge.svg)](https://github.com/yvictor/sj_sync/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/yvictor/sj_sync/branch/master/graph/badge.svg)](https://codecov.io/gh/yvictor/sj_sync)
[![PyPI version](https://badge.fury.io/py/sj-sync.svg)](https://badge.fury.io/py/sj-sync)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Shioaji 的即時部位同步工具。

[English](README.md) | 繁體中文

## 概述

`sj_sync` 提供即時部位追蹤，使用成交回報（deal callback）而非重複呼叫 `api.list_positions()`。這種方式具有以下優勢：

- **減少 API 呼叫**：初始化時呼叫一次 `list_positions()`，之後透過回報更新
- **更即時**：成交發生時部位立即更新
- **追蹤所有細節**：支援現股、融資、融券、當沖、期貨選擇權

## 功能特色

- ✅ **即時更新**：透過 `OrderState.StockDeal` 和 `OrderState.FuturesDeal` 回報
- ✅ **自訂回報支援**：註冊自己的回報處理函式，同時保持自動同步
- ✅ **智能同步模式**：智慧切換本地計算與 API 查詢
- ✅ **手動同步 API**：強制與 API 伺服器同步以進行對帳
- ✅ **檔案日誌**：自動記錄到 `sj_sync.log`，支援輪轉和保留
- ✅ **多種交易類型**：現股、融資、融券、當沖結算
- ✅ **期貨選擇權支援**：追蹤期貨和選擇權部位
- ✅ **昨日庫存追蹤**：維護每個部位的 `yd_quantity`
- ✅ **盤中重啟支援**：從當日交易記錄計算 `yd_offset_quantity`
- ✅ **自動清理**：數量歸零時自動移除部位
- ✅ **多帳戶支援**：正確隔離不同帳戶的部位
- ✅ **Pydantic 模型**：型別安全的部位物件

## 安裝

```bash
uv add sj-sync
```

或使用 pip：

```bash
pip install sj-sync
```

## 使用方式

### 基本用法

```python
import shioaji as sj
from sj_sync import PositionSync

# 初始化並登入
api = sj.Shioaji()
api.login("YOUR_API_KEY", "YOUR_SECRET_KEY")

# 建立 PositionSync（自動載入部位並註冊回報）
sync = PositionSync(api)

# 取得所有部位
positions = sync.list_positions()
for pos in positions:
    print(f"{pos.code}: {pos.direction} {pos.quantity}")

# 取得特定帳戶的部位
stock_positions = sync.list_positions(account=api.stock_account)
futures_positions = sync.list_positions(account=api.futopt_account)

# 當訂單成交時，部位會自動更新！
```

### 智能同步模式

啟用智能同步以自動驗證和修正部位：

```python
# 啟用智能同步，設定 30 秒門檻值
sync = PositionSync(api, sync_threshold=30)

# 運作方式：
# - 成交後：使用本地計算 30 秒（快速、即時）
# - 30 秒後：切換到 API 查詢（驗證準確性）
# - 自動偵測並修正任何不一致
# - 背景同步不會阻塞部位查詢
```

**智能同步優勢：**
- 🚀 **快速回應**：活躍交易期間使用本地計算
- ✅ **自動驗證**：定期 API 檢查確保準確性
- 🔄 **自動修正**：偵測並修復部位不一致
- 📊 **兩全其美**：結合本地追蹤的速度與 API 的可靠性

**設定選項：**
- `sync_threshold=0`（預設）：總是使用本地計算（原始行為）
- `sync_threshold=30`：成交後 30 秒使用本地，之後查詢 API
- `sync_threshold=60`：成交後 60 秒使用本地，之後查詢 API

### 自訂回報處理

註冊自己的回報處理函式，同時保持自動部位同步：

```python
from sj_sync import PositionSync, OrderDealCallback
from shioaji.constant import OrderState

# 建立 PositionSync 實例
sync = PositionSync(api, sync_threshold=30)

# 定義自訂回報處理函式
def my_callback(state: OrderState, data: dict) -> None:
    if state == OrderState.StockDeal:
        print(f"股票成交: {data.get('code')} {data.get('action')} "
              f"{data.get('quantity')} @ {data.get('price')}")
    elif state == OrderState.FuturesDeal:
        print(f"期貨成交: {data.get('code')} {data.get('action')} "
              f"{data.get('quantity')} @ {data.get('price')}")

    # 在此加入自己的邏輯：
    # - 發送通知
    # - 更新資料庫
    # - 觸發交易策略
    # 等等

# 註冊回報處理函式
sync.set_order_callback(my_callback)

# 當成交發生時：
# 1. PositionSync 自動更新部位（內部處理）
# 2. 您的回報處理函式被呼叫（自訂處理）
# 3. 隨時可查詢更新後的部位
positions = sync.list_positions()
```

**回報鏈：**
- `PositionSync` 先處理成交事件（更新部位）
- 接著呼叫您的回報處理函式
- 使用者回報函式的例外會被捕捉並記錄（不會中斷部位同步）

### 手動同步

需要確保部位與 API 伺服器同步時，可手動觸發同步：

```python
from sj_sync import PositionSync

# 建立 PositionSync 實例
sync = PositionSync(api)

# 從 API 同步所有帳戶
sync.sync_from_api()

# 或只同步特定帳戶
sync.sync_from_api(account=api.stock_account)

# 適用情境：
# - 需要與 API 伺服器進行對帳驗證
# - 網路重新連線後
# - 懷疑本地部位可能不同步時
# - 手動對帳需求
```

**使用情境：**
- 🔄 **手動對帳**：需要時強制與 API 同步
- 🌐 **重新連線後**：網路問題後刷新部位
- ✅ **驗證**：對照本地部位與伺服器
- 🎯 **選擇性同步**：同步特定帳戶或所有帳戶

## 部位模型

### StockPosition（股票部位）

```python
class StockPosition(BaseModel):
    code: str           # 股票代碼（例如 "2330"）
    direction: Action   # Action.Buy 或 Action.Sell
    quantity: int       # 目前部位數量
    yd_quantity: int    # 昨日部位數量
    cond: StockOrderCond  # 現股、融資或融券
```

### FuturesPosition（期貨部位）

```python
class FuturesPosition(BaseModel):
    code: str           # 契約代碼（例如 "TXFJ4"）
    direction: Action   # Action.Buy 或 Action.Sell
    quantity: int       # 目前部位數量
```

## API 參考

### PositionSync

#### `__init__(api: sj.Shioaji, sync_threshold: int = 0, timeout: int = 5000)`
使用 Shioaji API 實例初始化。

**參數：**
- `api`：Shioaji API 實例
- `sync_threshold`：智能同步門檻值（秒），預設：0
  - `0`：停用 - 總是使用本地計算
  - `>0`：啟用 - 成交後 N 秒使用本地，之後查詢 API
- `timeout`：API 查詢逾時時間（毫秒），預設：5000

**自動執行：**
- 載入所有帳戶的部位
- 註冊成交回報
- 從當日交易計算 `yd_offset_quantity`（盤中重啟用）

#### `list_positions(account: Optional[Account] = None, unit: Unit = Unit.Common, timeout: Optional[int] = None) -> Union[List[StockPosition], List[FuturesPosition]]`
取得目前部位。

**參數：**
- `account`：篩選帳戶。`None` 使用預設帳戶（優先 stock_account，其次 futopt_account）
- `unit`：`Unit.Common`（張）或 `Unit.Share`（股）- 為相容性保留，即時追蹤不使用
- `timeout`：查詢逾時時間（毫秒）。`None` 使用實例預設值（在 `__init__` 設定）

**回傳：**
- 股票帳戶：`List[StockPosition]`
- 期貨帳戶：`List[FuturesPosition]`
- `None`（預設）：優先 stock_account，回退到 futopt_account

**範例：**
```python
# 取得預設帳戶部位
positions = sync.list_positions()

# 取得特定帳戶部位
stock_positions = sync.list_positions(account=api.stock_account)
futures_positions = sync.list_positions(account=api.futopt_account)
```

#### `set_order_callback(callback: OrderDealCallback) -> None`
註冊自訂回報處理函式以接收成交事件。

**參數：**
- `callback`：回報處理函式，簽名為 `(state: OrderState, data: Dict) -> None`

**範例：**
```python
def my_callback(state, data):
    print(f"成交: {data}")

sync.set_order_callback(my_callback)
```

**注意：** 您的回報處理函式會在 `PositionSync` 處理事件後被呼叫。使用者回報函式的例外會被捕捉並記錄。

#### `sync_from_api(account: Optional[Account] = None) -> None`
手動從 API 伺服器同步部位。

**參數：**
- `account`：要同步的特定帳戶。若為 `None`，則同步所有帳戶。

**範例：**
```python
# 從 API 同步所有帳戶
sync.sync_from_api()

# 只同步證券帳戶
sync.sync_from_api(account=api.stock_account)

# 只同步期貨帳戶
sync.sync_from_api(account=api.futopt_account)
```

**使用情境：**
- 手動與 API 伺服器對帳
- 網路重新連線後
- 需要驗證本地部位時
- 不受 `sync_threshold` 設定影響的強制刷新

**注意：** 此方法會清除要同步帳戶的現有部位，並從 API 伺服器重新載入。

#### `on_order_deal_event(state: OrderState, data: Dict)`
訂單成交事件回報。初始化時自動註冊。

處理：
- `OrderState.StockDeal`：股票成交事件
- `OrderState.FuturesDeal`：期貨/選擇權成交事件

## 運作原理

### 1. 初始化
- 呼叫 `api.list_accounts()` 取得所有帳戶
- 透過 `api.list_positions(account)` 載入各帳戶部位
- 從 `api.list_trades()` 計算 `yd_offset_quantity`（盤中重啟用）
- 註冊 `on_order_deal_event` 回報

### 2. 即時更新
- 當訂單成交時，Shioaji 觸發回報
- 回報更新內部部位字典
- 買進成交增加數量（或建立新部位）
- 賣出成交減少數量
- 數量歸零的部位自動移除
- 追蹤最後成交時間供智能同步使用

### 3. 智能同步（啟用時）
- **活躍交易期間**（成交後門檻值內）：
  - 立即回傳本地計算部位
  - 快速、即時、無 API 呼叫

- **門檻值期間後**（無近期成交）：
  - 查詢 `api.list_positions()` 驗證
  - **競態條件保護**：若 API 查詢期間發生成交，則回傳最新的本地部位
  - 立即回傳 API 部位給使用者（若無並發成交）
  - 背景執行緒比對 API 與本地部位
  - 自動修正發現的任何不一致

### 4. 部位儲存
- 股票部位：`{account_key: {(code, cond): StockPositionInner}}`
- 期貨部位：`{account_key: {code: FuturesPosition}}`
- 帳戶鍵值 = `broker_id + account_id`
- 內部模型追蹤 `yd_offset_quantity` 供精確計算

## 開發

### 設定

```bash
git clone https://github.com/yvictor/sj_sync.git
cd sj_sync
uv sync
```

### 執行測試

```bash
# 所有測試
uv run pytest tests/ -v

# 含涵蓋率報告
uv run pytest --cov=sj_sync --cov-report=html
```

### 程式碼品質

```bash
# Linting
uv run ruff check src/ tests/

# 格式化
uv run ruff format src/ tests/

# 型別檢查
uv run zuban check src/
```

### CI/CD

每次推送和 Pull Request 會自動觸發：
- ✅ 程式碼品質檢查（ruff、zuban）
- ✅ 所有 62 個測試（單元 + BDD + 智能同步）
- ✅ 涵蓋率報告至 Codecov（90%+）
- ✅ 建置驗證

詳見 [CI 設定指南](.github/CI_SETUP.md)。

## 測試

專案包含完整的 pytest 測試：

**單元測試（37 個測試）：**
- ✅ 從 `list_positions()` 初始化部位
- ✅ 買賣成交事件
- ✅ 當沖情境
- ✅ 融資融券
- ✅ 期貨/選擇權成交
- ✅ 多帳戶支援
- ✅ 自訂回報支援（3 個測試）
  - 回報註冊
  - 使用者回報呼叫
  - 使用者回報例外處理
- ✅ 智能同步模式（10 個測試）
  - 門檻值停用/啟用行為
  - 不穩定/穩定期間切換
  - 背景部位驗證
  - 不一致偵測與自動修正
  - API 查詢失敗處理
  - 手動同步 API（`sync_from_api`）
  - API 查詢期間的競態條件保護
- ✅ 邊界案例與錯誤處理

**BDD 測試（25 個場景，中文）：**
- ✅ 當沖交易（15 個場景 - 當沖抵銷規則）
- ✅ 盤中重啟（10 個場景 - yd_offset 計算）
- ✅ 融資融券（含昨日部位的融資融券交易）
- ✅ 混合場景（複雜混合交易情境）
- ✅ 正確處理 `yd_quantity` 和 `yd_offset_quantity`

執行測試：
```bash
# 所有測試（62 個）
uv run pytest tests/ -v

# 含涵蓋率報告（90%+）
uv run pytest --cov=sj_sync --cov-report=html --cov-report=term-missing
```

檢視涵蓋率報告：
```bash
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
```

## 授權

MIT License

## 貢獻

歡迎貢獻！請：
1. Fork 本專案
2. 建立功能分支
3. 為新功能新增測試
4. 確保所有測試通過（`pytest`、`zuban check`、`ruff check`）
5. 提交 Pull Request
