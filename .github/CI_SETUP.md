# GitHub Actions CI/CD Setup Guide

## Overview

This project uses GitHub Actions for automated testing, code quality checks, and publishing to PyPI.

## Workflows

### 1. CI Workflow (`.github/workflows/ci.yml`)

**Triggers:**
- Push to any branch
- Pull requests

**Jobs:**

#### Lint Job
- **Ruff Check**: Lints code for errors and style issues
- **Ruff Format Check**: Ensures code follows consistent formatting
- **Zuban Check**: Type checking (warnings only, doesn't fail CI)

#### Test Job
- Runs all 32 tests (18 unit tests + 14 BDD tests)
- Generates coverage report with pytest-cov
- Uploads coverage to Codecov
- Current coverage: ~79%

#### Build Job
- Verifies package can be built successfully
- Uploads build artifacts

### 2. Publish Workflow (`.github/workflows/publish.yml`)

**Triggers:**
- Version tags (e.g., `v0.1.0`, `v1.0.0`)

**Jobs:**
- Runs full CI test suite
- Verifies tag version matches package version
- Builds package
- Publishes to PyPI using trusted publisher (OIDC)
- Creates GitHub release with auto-generated notes

## Running Tests Locally

### Install Dependencies
```bash
uv sync
```

### Run All Tests
```bash
uv run pytest
```

### Run Tests with Coverage
```bash
uv run pytest --cov=sj_sync --cov-report=term-missing --cov-report=html
```

### Run Linting
```bash
# Check code
uv run ruff check src/ tests/

# Format code
uv run ruff format src/ tests/

# Type checking
uv run zuban check src/
```

### Build Package
```bash
uv build
```

## Test Structure

### Unit Tests (`tests/test_position_sync.py`)
- 18 tests covering core functionality
- Position initialization
- Stock/futures deal events
- Day trading scenarios
- Margin trading and short selling

### BDD Tests (`tests/features/` + `tests/step_defs/`)
- 14 BDD scenarios in Chinese
- **Day Trading** (`day_trading.feature`): 5 scenarios
  - 資買+券賣當沖 (Margin buy + short sell)
  - 券賣+資買當沖 (Short sell + margin buy)
  - 現股買賣當沖 (Cash trading)
- **Margin Trading** (`margin_trading.feature`): 5 scenarios
  - 優先抵銷昨日庫存 (Offset yesterday's position first)
  - 融資融券交易規則 (Margin/short trading rules)
- **Mixed Scenarios** (`mixed_scenarios.feature`): 4 scenarios
  - 複雜混合交易情境 (Complex mixed trading scenarios)

## Required Secrets

### For Codecov (Optional)
Add `CODECOV_TOKEN` to repository secrets:
1. Go to https://codecov.io/
2. Set up your repository
3. Copy the token
4. Add to GitHub: Settings → Secrets and variables → Actions → New secret

### For PyPI Publishing (Required for releases)

**Option 1: Trusted Publisher (Recommended)**
1. Go to https://pypi.org/manage/account/publishing/
2. Add a new publisher:
   - PyPI Project Name: `sj-sync`
   - Owner: `yvictor`
   - Repository name: `sj_sync`
   - Workflow name: `publish.yml`
   - Environment name: `pypi`

**Option 2: API Token (Alternative)**
1. Generate token at https://pypi.org/manage/account/token/
2. Add to GitHub: Settings → Secrets and variables → Actions
3. Name: `PYPI_TOKEN`
4. Update `publish.yml` to use token instead of OIDC

## Publishing a New Version

1. Update version in `pyproject.toml`
2. Commit changes
3. Create and push a tag:
   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```
4. GitHub Actions will automatically:
   - Run all tests
   - Build the package
   - Publish to PyPI
   - Create GitHub release

## Coverage Reports

Coverage reports are generated in multiple formats:
- **Terminal**: Shows missing lines during test run
- **HTML**: `htmlcov/index.html` (gitignored)
- **XML**: `coverage.xml` for Codecov (gitignored)

To view HTML coverage report locally:
```bash
uv run pytest --cov=sj_sync --cov-report=html
open htmlcov/index.html  # or xdg-open on Linux
```

## Taiwan Stock Trading Rules Tested

The BDD tests ensure correct implementation of Taiwan stock market rules:

### Day Trading (當沖)
- 資買 + 券賣 = Offset today's quantity
- 券賣 + 資買 = Offset today's quantity
- 現股買 + 現股賣 = Offset today's quantity

### Non-Day Trading
- 資買 + 資賣 = Offset yesterday's quantity first (yd_offset_quantity)
- 券賣 + 券買 = Offset yesterday's quantity first (yd_offset_quantity)
- **Note**: `yd_quantity` is fixed (yesterday's reference), never modified
- `yd_offset_quantity` tracks cumulative offsets for today

### Key Position Fields
- `quantity`: Total position quantity (包含昨日)
- `yd_quantity`: Yesterday's position (固定參考值)
- `yd_offset_quantity`: Yesterday's offset quantity (今日累積)
- **Calculation**:
  - Yesterday remaining = `yd_quantity - yd_offset_quantity`
  - Today remaining = `quantity - (yd_quantity - yd_offset_quantity)`

## Troubleshooting

### Tests Failing Locally
```bash
# Clean cached files
rm -rf .pytest_cache __pycache__ .coverage htmlcov/

# Reinstall dependencies
uv sync --reinstall
```

### Format Issues
```bash
# Auto-format code
uv run ruff format src/ tests/
```

### Build Issues
```bash
# Clean build artifacts
rm -rf dist/ build/ *.egg-info

# Rebuild
uv build
```

## Status Badges

Add to README.md:

```markdown
[![CI](https://github.com/yvictor/sj_sync/actions/workflows/ci.yml/badge.svg)](https://github.com/yvictor/sj_sync/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/yvictor/sj_sync/branch/master/graph/badge.svg)](https://codecov.io/gh/yvictor/sj_sync)
[![PyPI version](https://badge.fury.io/py/sj-sync.svg)](https://badge.fury.io/py/sj-sync)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
```
