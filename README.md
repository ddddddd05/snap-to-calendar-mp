# Snap-to-Calendar 微信小程序 + FastAPI 后端

## 目录结构
- `backend/`：Python FastAPI 后端（提供 `/api/extract` 提取接口和 `/api/export-csv` 账单导出接口）
- `miniprogram/`：原生微信小程序前端（支持选截图、调用 `wx.addPhoneCalendar` 一键加手机日历、导出 `.csv`）

## 启动步骤

### 1. 启动 Python 后端
在本项目根目录（`snap-to-calendar-mp/`）下执行：
```powershell
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
- （可选）如需启用**截图识图**，复制 `.env.example` 为 `.env`，填入你的 `AI_API_KEY`、`AI_BASE_URL`、`AI_MODEL`。不填也能直接识别纯文字。

### 2. 打开微信小程序
1. 打开 **微信开发者工具** → 选择 **导入项目**。
2. 目录选择本项目下的 `miniprogram/` 文件夹。
3. AppID 可先选 **测试号**（`project.config.json` 已设置 `urlCheck: false`，不校验域名）。
4. 即可在模拟器里测试文字提取与示例；点右上角 **「预览」** 用微信扫码可在手机上真实测试 `wx.addPhoneCalendar` 一键加日历（真机调试时把 `miniprogram/app.js` 里的 `127.0.0.1` 改成你电脑的局域网 IP）。

## 如果要上传发布小程序
1. 在微信公众平台注册个人小程序账号，拿到正式的 `AppID`，替换 `project.config.json` 里的 `touristappid`。
2. 后端需要部署到一台有 **HTTPS 备案域名** 的云服务器上，并在微信公众平台「开发管理 → 服务器域名」里把该域名加入 `request合法域名`。
3. 在微信开发者工具点右上角 **「上传」**，然后在微信公众平台提交审核即可。
