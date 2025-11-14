# Codecov 和 PyPI 設置指南

## 📊 Codecov 設置（測試覆蓋率）

### 步驟 1：註冊並添加倉庫

1. **訪問 Codecov**
   - 前往：https://codecov.io/
   - 點擊右上角 `Sign up`

2. **使用 GitHub 登錄**
   - 選擇 `Log in with GitHub`
   - 授權 Codecov 訪問你的 GitHub 帳號

3. **添加倉庫**
   - 登錄後會看到 `Not yet setup` 頁面
   - 搜索或找到 `yvictor/sj_sync`
   - 點擊 `Setup repo`

### 步驟 2：獲取 Codecov Token

1. **進入倉庫設置**
   - 點擊倉庫名稱進入詳情頁
   - 前往 `Settings` 標籤

2. **複製 Upload Token**
   - 在 Settings 頁面找到 `Repository Upload Token`
   - 點擊 `Copy` 按鈕複製 token
   - Token 格式類似：`a1b2c3d4-e5f6-7890-abcd-ef1234567890`

### 步驟 3：添加 Token 到 GitHub Secrets

1. **打開 GitHub 倉庫**
   - 前往：https://github.com/yvictor/sj_sync

2. **進入 Secrets 設置**
   - 點擊 `Settings` 標籤
   - 左側菜單選擇 `Secrets and variables` → `Actions`

3. **添加新 Secret**
   - 點擊 `New repository secret` 按鈕
   - **Name**: 輸入 `CODECOV_TOKEN`（必須完全一致）
   - **Value**: 貼上剛才複製的 token
   - 點擊 `Add secret`

### 步驟 4：驗證設置

1. **推送代碼觸發 CI**
   ```bash
   git push origin master
   ```

2. **查看 Actions**
   - 前往 GitHub 倉庫的 `Actions` 標籤
   - 等待 CI 運行完成
   - 檢查 "Upload coverage to Codecov" 步驟是否成功

3. **查看 Codecov 報告**
   - 回到 https://codecov.io/gh/yvictor/sj_sync
   - 應該看到最新的覆蓋率報告（約 78.93%）

### 🎉 完成！

現在 README 上的 Codecov 徽章應該會顯示實際的覆蓋率數據！

---

## 📦 PyPI 設置（自動發布）

### 方案 A：Trusted Publisher (推薦，更安全)

#### 步驟 1：註冊 PyPI 帳號（如果還沒有）

1. **訪問 PyPI**
   - 前往：https://pypi.org/account/register/

2. **註冊帳號**
   - 填寫用戶名、郵箱、密碼
   - 驗證郵箱

3. **啟用 2FA（強烈推薦）**
   - 前往：https://pypi.org/manage/account/
   - 點擊 `Add 2FA with authentication application`
   - 使用 Google Authenticator 或類似 app 掃描 QR code

#### 步驟 2：創建項目（首次發布前）

**選項 1：先手動上傳一次（推薦新手）**

```bash
# 本地構建
uv build

# 安裝 twine（如果還沒有）
pip install twine

# 上傳到 PyPI
twine upload dist/*
# 輸入你的 PyPI 用戶名和密碼
```

**選項 2：直接配置 Trusted Publisher（進階）**

如果選擇這個方案，PyPI 會在你第一次推送 tag 時自動創建項目。

#### 步驟 3：配置 Trusted Publisher

1. **前往 PyPI Publishing 設置**
   - 登錄 https://pypi.org/
   - 前往：https://pypi.org/manage/account/publishing/

2. **添加 Pending Publisher**（如果項目還未創建）
   - 點擊 `Add a new pending publisher`
   - 填寫以下信息：
     ```
     PyPI Project Name: sj-sync
     Owner: yvictor
     Repository name: sj_sync
     Workflow name: publish.yml
     Environment name: pypi
     ```
   - 點擊 `Add`

3. **或者添加到現有項目**（如果項目已創建）
   - 前往項目頁面：https://pypi.org/project/sj-sync/
   - 點擊 `Manage` → `Publishing`
   - 點擊 `Add a new publisher`
   - 填寫相同的信息（如上）

#### 步驟 4：測試發布流程

```bash
# 1. 確保本地代碼已推送
git push origin master

# 2. 創建版本 tag
git tag v0.1.0

# 3. 推送 tag 觸發發布
git push origin v0.1.0
```

#### 步驟 5：驗證發布

1. **查看 GitHub Actions**
   - 前往：https://github.com/yvictor/sj_sync/actions
   - 找到 "Publish to PyPI" workflow
   - 確認所有步驟成功

2. **檢查 PyPI**
   - 前往：https://pypi.org/project/sj-sync/
   - 確認新版本已發布

3. **測試安裝**
   ```bash
   pip install sj-sync
   # 或
   uv add sj-sync
   ```

---

### 方案 B：使用 API Token（備選方案）

如果 Trusted Publisher 有問題，可以使用 API token：

#### 步驟 1：生成 API Token

1. **前往 PyPI Token 設置**
   - 登錄：https://pypi.org/
   - 前往：https://pypi.org/manage/account/token/

2. **創建新 Token**
   - 點擊 `Add API token`
   - **Token name**: `GitHub Actions - sj_sync`
   - **Scope**:
     - 選擇 `Project: sj-sync`（如果項目已創建）
     - 或選擇 `Entire account`（如果項目未創建）
   - 點擊 `Add token`

3. **複製 Token**
   - ⚠️ **重要**：Token 只顯示一次，立即複製保存！
   - Token 格式：`pypi-AgEIcHlwaS5vcmc...`

#### 步驟 2：添加到 GitHub Secrets

1. **打開 GitHub 倉庫**
   - 前往：https://github.com/yvictor/sj_sync

2. **添加 Secret**
   - `Settings` → `Secrets and variables` → `Actions`
   - 點擊 `New repository secret`
   - **Name**: `PYPI_TOKEN`
   - **Value**: 貼上 token（包括 `pypi-` 前綴）
   - 點擊 `Add secret`

#### 步驟 3：修改 publish.yml

需要修改 `.github/workflows/publish.yml`：

```yaml
- name: Publish to PyPI
  uses: pypa/gh-action-pypi-publish@release/v1
  with:
    password: ${{ secrets.PYPI_TOKEN }}  # 使用 token 而不是 OIDC
    print-hash: true
```

---

## 🔍 常見問題

### Q: Codecov token 找不到怎麼辦？

**A**: 確保：
1. 已經在 Codecov 上添加了倉庫
2. 進入正確的倉庫設置頁面
3. Token 在 `Settings` → `General` 下的 `Repository Upload Token` 區域

### Q: PyPI Trusted Publisher 設置失敗？

**A**: 檢查：
1. 所有欄位是否填寫正確（特別注意大小寫）
2. Repository name 是 `sj_sync`（不是 `sj-sync`）
3. Workflow name 是 `publish.yml`（不是 `.github/workflows/publish.yml`）
4. Environment name 是 `pypi`（小寫）

### Q: 如何測試發布到 TestPyPI？

**A**: 使用 TestPyPI 進行測試：

1. 註冊 TestPyPI：https://test.pypi.org/account/register/
2. 配置 Trusted Publisher（使用相同步驟）
3. 修改 `publish.yml`：
   ```yaml
   - name: Publish to TestPyPI
     uses: pypa/gh-action-pypi-publish@release/v1
     with:
       repository-url: https://test.pypi.org/legacy/
   ```

### Q: 發布失敗，顯示版本已存在？

**A**: PyPI 不允許重複發布相同版本：
1. 刪除本地 tag：`git tag -d v0.1.0`
2. 刪除遠程 tag：`git push origin :refs/tags/v0.1.0`
3. 更新版本號後重新發布

### Q: 如何撤銷已發布的版本？

**A**: PyPI 不支持刪除已發布的版本，但可以：
1. 將版本標記為 "yanked"（不推薦安裝）
2. 前往 PyPI 項目管理頁面
3. 選擇版本，點擊 `Options` → `Yank`

---

## ✅ 設置完成檢查清單

### Codecov
- [ ] 在 Codecov 上添加了倉庫
- [ ] 複製了 Upload Token
- [ ] 在 GitHub Secrets 中添加了 `CODECOV_TOKEN`
- [ ] 推送代碼後 CI 成功上傳覆蓋率
- [ ] Codecov 徽章顯示正確的覆蓋率

### PyPI (Trusted Publisher)
- [ ] 註冊了 PyPI 帳號
- [ ] 啟用了 2FA
- [ ] 配置了 Trusted Publisher（或上傳了首個版本）
- [ ] 推送 tag 後自動發布成功
- [ ] 可以通過 `pip install sj-sync` 安裝

### PyPI (API Token - 備選)
- [ ] 生成了 API Token
- [ ] 在 GitHub Secrets 中添加了 `PYPI_TOKEN`
- [ ] 修改了 `publish.yml` 使用 token
- [ ] 推送 tag 後自動發布成功

---

## 📚 相關鏈接

- **Codecov**: https://codecov.io/
- **PyPI**: https://pypi.org/
- **TestPyPI**: https://test.pypi.org/
- **GitHub Actions Secrets**: https://github.com/yvictor/sj_sync/settings/secrets/actions
- **Trusted Publisher 文檔**: https://docs.pypi.org/trusted-publishers/

---

## 🆘 需要幫助？

遇到問題可以：
1. 查看 GitHub Actions 的詳細日誌
2. 檢查 Codecov 的 debug 信息
3. 參考 PyPI 的錯誤消息
4. 在 Issues 中提問：https://github.com/yvictor/sj_sync/issues
