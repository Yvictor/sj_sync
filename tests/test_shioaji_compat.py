"""Tests for version-aware Shioaji imports."""

import sj_sync.shioaji_compat as compat


def test_version_tuple_parses_numeric_versions():
    assert compat._version_tuple("1.5.3") == (1, 5, 3)
    assert compat._version_tuple("1.5.3rc1") == (1, 5, 3)
    assert compat._version_tuple("1.5.x") == (1, 5)
    assert compat._version_tuple("bad") == ()


def test_exports_expected_symbols():
    assert set(compat.__all__) == {
        "sj",
        "Action",
        "StockOrderCond",
        "OrderState",
        "Status",
        "Unit",
        "Account",
        "AccountType",
        "Contract",
        "SjStockPosition",
        "SjFuturePosition",
        "Snapshot",
        "ChangeType",
        "QuoteType",
        "TickType",
    }


def test_shioaji_1_5_imports_use_top_level_symbols():
    if compat._SHIOAJI_VERSION < (1, 5):
        return

    assert compat.Action is compat.sj.Action
    assert compat.StockOrderCond is compat.sj.StockOrderCond
    assert compat.OrderState is compat.sj.OrderState
    assert compat.Status is compat.sj.OrderStatus
    assert compat.Unit is compat.sj.Unit
    assert compat.Account is compat.sj.Account
    assert compat.AccountType is compat.sj.AccountType
    assert compat.Contract is compat.sj.Contract
    assert compat.SjStockPosition is compat.sj.StockPosition
    assert compat.SjFuturePosition is compat.sj.FuturePosition
    assert compat.Snapshot is compat.sj.Snapshot
    assert compat.ChangeType is compat.sj.ChangeType
    assert compat.QuoteType is compat.sj.QuoteType
    assert compat.TickType is compat.sj.TickType
