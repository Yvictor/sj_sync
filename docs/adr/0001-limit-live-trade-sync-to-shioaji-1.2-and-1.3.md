# Limit live Trade synchronization to Shioaji 1.2.x and 1.3.x

sj_sync will provide reference-based live Trade synchronization only for Shioaji 1.2.x and 1.3.x, where `place_order()` and `list_trades()` expose shared mutable Trade objects. Shioaji 1.4 and later are disabled; Shioaji 1.5.x returns immutable Trade snapshots without stable object identity, so live Trade synchronization for 1.5 and later belongs in Shioaji's Rust core rather than in sj_sync. Combo reports remain outside sj_sync Trade projection.
