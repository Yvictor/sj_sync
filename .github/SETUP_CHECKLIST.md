# CI/CD Setup Checklist

完成以下步驟來啟用完整的 GitHub Actions CI/CD 流程：

## ✅ 已完成

- [x] 創建 `.github/workflows/ci.yml` - 自動化測試和代碼檢查
- [x] 創建 `.github/workflows/publish.yml` - 自動發布到 PyPI
- [x] 配置 `pyproject.toml` - 添加 pytest-cov 和測試配置
- [x] 更新 `.gitignore` - 排除測試覆蓋率和構建文件
- [x] 更新 `README.md` - 添加狀態徽章和 CI/CD 說明

## 📋 待辦事項

### 1. 推送代碼到 GitHub

```bash
# 查看變更
git status

# 添加所有變更
git add .

# 提交
git commit -m "feat: add GitHub Actions CI/CD workflows

- Add CI workflow for automated testing and linting
- Add PyPI publish workflow for automatic releases
- Configure pytest-cov for coverage reporting
- Update README with status badges
- Add comprehensive BDD tests for Taiwan stock trading rules"

# 推送到 GitHub
git push origin master
```

### 2. 設置 Codecov（可選但推薦）

1. 訪問 https://codecov.io/
2. 使用 GitHub 登錄
3. 添加 `yvictor/sj_sync` 倉庫
4. 複製 `CODECOV_TOKEN`
5. 在 GitHub 倉庫中添加 Secret：
   - 前往：`Settings` → `Secrets and variables` → `Actions`
   - 點擊 `New repository secret`
   - Name: `CODECOV_TOKEN`
   - Value: [貼上你的 token]

### 3. 設置 PyPI Trusted Publisher（發布前必需）

**推薦方式：使用 Trusted Publisher (OIDC)**

1. 登錄 https://pypi.org/
2. 前往：`Account settings` → `Publishing` → `Add a new pending publisher`
3. 填寫：
   - **PyPI Project Name**: `sj-sync`
   - **Owner**: `yvictor`
   - **Repository name**: `sj_sync`
   - **Workflow name**: `publish.yml`
   - **Environment name**: `pypi`
4. 保存

這樣就不需要 API token，更安全！

**替代方式：使用 API Token**

如果不想用 Trusted Publisher：

1. 前往 https://pypi.org/manage/account/token/
2. 創建新 token（scope: 整個帳號或特定項目）
3. 複製 token
4. 在 GitHub 添加 Secret：
   - Name: `PYPI_TOKEN`
   - Value: [貼上 token]
5. 修改 `publish.yml`，將 OIDC 發布改為 token 發布

### 4. 啟用 Branch Protection（推薦）

保護主分支，確保代碼質量：

1. 前往倉庫 `Settings` → `Branches`
2. 點擊 `Add rule`
3. Branch name pattern: `master`（或 `main`）
4. 啟用：
   - [x] Require a pull request before merging
   - [x] Require status checks to pass before merging
     - 選擇：`Code Quality Checks`
     - 選擇：`Tests (Python 3.10)`
     - 選擇：`Build Package`
   - [x] Require conversation resolution before merging
5. 保存

### 5. 測試 CI

推送代碼後：

1. 前往 GitHub 倉庫
2. 點擊 `Actions` 標籤
3. 查看 CI workflow 是否成功運行
4. 檢查所有測試是否通過（應該看到 32 passed）

### 6. 測試發布流程（當準備發布時）

```bash
# 1. 更新版本號
# 編輯 pyproject.toml，將 version 改為 "0.1.1"

# 2. 提交版本變更
git add pyproject.toml
git commit -m "chore: bump version to 0.1.1"
git push

# 3. 創建並推送 tag
git tag v0.1.1
git push origin v0.1.1

# GitHub Actions 會自動：
# - 運行所有測試
# - 構建包
# - 發布到 PyPI
# - 創建 GitHub Release
```

## 🎯 驗證清單

完成後，確認以下項目：

- [ ] GitHub Actions CI 運行成功（綠色勾勾）
- [ ] README 上的徽章正常顯示
- [ ] Codecov 顯示覆蓋率報告
- [ ] 可以正常推送代碼並自動測試
- [ ] (可選) 測試發布到 TestPyPI 確認流程正常

## 📚 參考文檔

- [CI Setup Guide](.github/CI_SETUP.md) - 詳細的 CI/CD 配置說明
- [pytest-bdd Documentation](https://pytest-bdd.readthedocs.io/) - BDD 測試框架
- [Codecov Documentation](https://docs.codecov.com/) - 覆蓋率報告
- [PyPI Trusted Publishers](https://docs.pypi.org/trusted-publishers/) - OIDC 發布說明

## ❓ 常見問題

### Q: CI 失敗了怎麼辦？

檢查 Actions 日誌：
1. 前往 `Actions` 標籤
2. 點擊失敗的 workflow
3. 查看詳細日誌找出問題

### Q: 如何跳過 CI 運行？

在 commit message 中添加 `[skip ci]`：
```bash
git commit -m "docs: update README [skip ci]"
```

### Q: 如何只運行特定測試？

本地運行：
```bash
# 只運行 BDD 測試
uv run pytest tests/step_defs/ -v

# 只運行單元測試
uv run pytest tests/test_position_sync.py -v

# 運行特定測試
uv run pytest tests/test_position_sync.py::TestDayTrading -v
```

### Q: Coverage 報告在哪裡？

- **Codecov**: 前往 https://codecov.io/gh/yvictor/sj_sync
- **本地 HTML**: 運行測試後打開 `htmlcov/index.html`
- **終端**: 運行 `uv run pytest --cov=sj_sync --cov-report=term-missing`

## 🚀 完成！

完成所有步驟後，你的項目將具備：
- ✅ 自動化測試（每次 push/PR）
- ✅ 代碼質量保證
- ✅ 測試覆蓋率追蹤
- ✅ 自動發布到 PyPI
- ✅ 分支保護機制

現在可以安心開發，CI/CD 會自動確保代碼質量！
