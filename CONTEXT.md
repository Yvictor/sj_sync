# sj_sync Domain

This context describes the trading state that sj_sync keeps current from Shioaji order and deal reports.

## Language

**Native API**:
The original `sj.Shioaji` instance supplied to sj_sync and retained as the public trading API.
_Avoid_: Wrapped API, proxied API

**Native Trade**:
The `sj.Trade` object returned by `Native API.place_order()` or exposed by `Native API.list_trades()`.
_Avoid_: SyncedTrade, Trade proxy

**Local Order**:
An order submitted through the same Native API instance used by sj_sync, for which that client can expose an existing Native Trade reference.
_Avoid_: Client-owned order, own order

**External Order**:
An order submitted by another client for the same trading account and observed by sj_sync only through order or deal reports.
_Avoid_: Unknown order, foreign order

**Unresolved Order Report**:
A new-order report whose Native Trade is not yet visible in the Native API, so sj_sync cannot yet classify it as a Local Order or External Order. It remains unresolved for at most one second.
_Avoid_: External Order, missing Trade

**External Trade**:
A Native Trade constructed and owned by sj_sync from an External Order report. It appears in `PositionSync.list_trades()` but is not guaranteed to appear in `Native API.list_trades()`.
_Avoid_: Trade proxy, Local Trade

**Deferred Deal**:
A deal report received before the corresponding Local or External Trade can be resolved. It is retained by trade ID and applied once, using exchange sequence as its deduplication identity.
_Avoid_: Missing deal, failed deal

**Tracked Trade Reference**:
A reference held by sj_sync to a Native Trade so an order or deal report can make the existing Trade observable with its latest state.
_Avoid_: Trade copy, Trade snapshot

**Live Trade Synchronization**:
Reference-based updating of Native Trades from non-combo order and deal reports, supported for Shioaji 1.2.x and 1.3.x only. It is disabled on Shioaji 1.4 and later; Shioaji 1.5 and later own this responsibility in their Rust core.
_Avoid_: Trade polling, Rust Trade synchronization

**Trade Snapshot**:
A Native Trade materialized from current API state without a stable object identity. Shioaji 1.5.x returns Trade Snapshots from `list_trades()`.
_Avoid_: Tracked Trade Reference

**Reconciliation**:
Recovery of authoritative Trade state through `update_status()` after startup, reconnection, or suspected missed reports.
_Avoid_: Polling, live update
