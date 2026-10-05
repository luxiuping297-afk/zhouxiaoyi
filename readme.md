# 股票雷达

纯静态网站，无需后端、数据库、依赖安装或构建。支持股票列表、代码/名称搜索、上涨/下跌筛选、涨跌幅排序和刷新。
使用 `static/stocks.json` 中的六条演示行情，**不是实时行情**。刷新会重新读取数据文件。

## 部署到 GitHub Pages（推荐）

1. 将本项目所有文件提交并推送到 GitHub 仓库 `luxiuping297-afk/zhouxiaoyi` 的 `main` 分支。
2. 打开仓库 **Settings → Pages → Build and deployment → Source**，选择 **GitHub Actions**。
3. 打开 **Actions → Deploy stock radar to GitHub Pages → Run workflow**，选择 `main` 并运行。如果推送已自动触发且成功，无需再次运行。
4. 等待部署成功，点击部署任务中的 **github-pages** 地址，或在 **Settings → Pages** 中点击 **Visit site**。

默认预期地址为 `https://luxiuping297-afk.github.io/zhouxiaoyi/`，实际地址以部署结果为准。部署完成前，该地址可能返回 404。以后更新 `main` 分支会自动重新部署。
如果 Pages 提示不可用，请检查仓库可见性与 GitHub 账户方案是否支持该仓库的 Pages 功能。

网站文件全部位于 `static/`，也可以直接将这个目录部署到其他支持静态网站的托管平台；无需构建命令。
资源使用相对路径，支持 GitHub Pages 的 `/zhouxiaoyi/` 子路径。

## 本地运行

需要 Python 3.10+，不需要安装第三方依赖。

```bash
cd /workspace/zhouxiaoyi
python3 app.py --host 0.0.0.0 --port 8000
```

在本机运行时，在浏览器地址栏输入 `http://127.0.0.1:8000`。Ctrl+C 停止。
也可使用标准静态服务：`python3 -m http.server 8000 --directory static`。
不要直接双击 HTML 文件：浏览器可能阻止通过 file 协议加载 JSON。

## 文件

- `static/index.html`：中文页面。
- `static/app.js`：加载 JSON、搜索、筛选、排序和错误提示。
- `static/style.css`：响应式样式，红涨绿跌。
- `static/stocks.json`：演示行情的唯一数据文件。
- `static/.nojekyll`：禁用 Jekyll 处理。
- `.github/workflows/pages.yml`：GitHub Pages 自动部署配置。
- `app.py`：可选本地 HTTP 服务，兼容原来的 `/api/stocks` 接口。

修改演示行情后，推送到 `main` 并等待部署完成即可更新公网网站。
此版本不包含真实行情、登录或交易；静态网站文件和数据会公开提供，请勿放入密码或 API 密钥。

## 2026-10-05 部署修复与继续操作

部署任务自身的 `permissions` 必须同时包含 `contents: read`、`pages: write`、`id-token: write`；任务权限会覆盖工作流级权限，漏掉读取权限会导致 Checkout 报 Repository not found。

根目录 `index.html` 为按分支发布 Pages 提供入口，跳转到 `static/`；Actions 直接发布 `static/` 时也能打开相同页面。建议 Pages Source 选择 GitHub Actions，以免两种发布方式同时覆盖站点。

关电脑后无需重建项目：查看雷达直接打开 https://luxiuping297-afk.github.io/zhouxiaoyi/ 。继续编辑时打开本仓库；使用 Codex 时回到昨天的任务并选择同一个仓库，继续描述修改要求。已经提交到 GitHub 的文件不会因为关电脑丢失。
