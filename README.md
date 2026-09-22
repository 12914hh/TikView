# TikView

每周把已授权 TikTok 作者的公开视频播放量写回飞书「达人管理」表。

## 已实现

- 飞书读表、按列名定位
- TikTok Login Kit 授权，支持多个作者
- 自动刷新 access_token
- 按视频 ID 写回播放量
- 「追踪」填 `否` 的行跳过
- 授权失效时标记「已过期」，不改播放量
- 本地窗口可改自动更新时间和开关。时间写在 TikView 表的「配置」工作表。电脑关着时由 GitHub 按这个北京时间自动跑
- 播放量更新结果、授权失败会发到飞书群（需要 `FEISHU_CHAT_ID`）

自动更新时间和开关只存在 TikView 表的「配置」工作表里。窗口保存、GitHub 到点判断都读这张表。飞书读不到时按默认处理：每周一北京时间 10:00，定时任务关闭。

## 给朋友用

双击 `启动.bat`，窗口里可以：

1. 填写飞书作者 ID，点「生成授权链接」，把链接发给作者。
2. 作者点开、登录、点继续，看到「授权成功」即可。授权会自动写入飞书里的「授权」表。
3. 点「更新播放量」，把对得上的视频写回「达人管理」。
4. 在「自动更新」里选星期和小时，点「保存时间」。确认后点「开启定时任务」，到点才会自动跑；点「停止定时任务」就不再自动跑。电脑关着时由 GitHub 执行。

要发给同事一个不用装 Python 的窗口，双击 `打包.bat`。完成后把 `dist\TikView` 整个文件夹压缩后发出去，让对方双击里面的 `TikView.exe`。压缩包里有 `.env`，不要发到公开的地方。

作者自动完成授权之前，要先把 `worker` 部署到 Cloudflare，并把 Login Kit 的 Redirect URI 改成：

```text
https://tikview.<你的子域>.workers.dev/callback
```

`.env` 里的 `TIKTOK_REDIRECT_URI` 改成同一个地址。`STATE_SECRET` 本地和 Worker 必须相同。

在 `worker` 目录：

```powershell
npx wrangler login
npx wrangler secret put FEISHU_APP_ID
npx wrangler secret put FEISHU_APP_SECRET
npx wrangler secret put FEISHU_SPREADSHEET_TOKEN
npx wrangler secret put FEISHU_TIKVIEW_SPREADSHEET_TOKEN
npx wrangler secret put FEISHU_CHAT_ID
npx wrangler secret put TIKTOK_CLIENT_KEY
npx wrangler secret put TIKTOK_CLIENT_SECRET
npx wrangler secret put TIKTOK_REDIRECT_URI
npx wrangler secret put STATE_SECRET
npx wrangler deploy
```

审核还没变成 Live 时，只有 Sandbox 的 Target user 能点链接。作者页面上的成功、失败文案和错误码对照在 `docs/callback文案.md`。

## 自动更新（不依赖 Cloudflare）

GitHub 自己的 `schedule` 经常漏触发。更稳的做法是用免费网站定时服务每小时叫醒一次 Actions；电脑关着也能跑。

1. 在 GitHub 建一个只用于这个仓库的 Token（细粒度）：权限 **Contents: Read**、**Actions: Write**。
2. 打开 [cron-job.org](https://cron-job.org/)（或其他免费 HTTP 定时）注册，新建任务：
   - URL：`https://api.github.com/repos/12914hh/TikView/dispatches`
   - 方法：`POST`
   - 调度：每小时一次（例如每小时的第 10 分钟）
   - Header：
     - `Authorization: Bearer 你的Token`
     - `Accept: application/vnd.github+json`
     - `X-GitHub-Api-Version: 2022-11-28`
     - `User-Agent: tikview-cron`
   - Body（JSON）：`{"event_type":"tikview-schedule-check"}`
3. 窗口里选好星期/小时，点「开启定时任务」。

叫醒之后仍会读飞书「配置」：开关关掉就不跑；不到设定时间也不跑；过了设定时间且当天还没成功过会补跑一次。网页上点 Run workflow 仍可随时强制跑。

## 命令行

```powershell
.\.venv\Scripts\python.exe pull.py
.\.venv\Scripts\python.exe pull.py --write
```

`.env` 需要飞书和 TikTok 凭证。授权和自动更新时间在新建的 TikView 表里，不要把这张表公开。本机 `tokens.json` 仍会保留一份备份。改自动更新请用窗口。

## 审核通过后

1. 把 `.env` 里的 TikTok Client key / secret 换成 Production，Worker 上的同一对密钥也要换。Production 的 Redirect URI 设为同一个 `/callback` 地址。审核期间不要动 Production。
2. 在窗口里生成链接，让作者自己点开授权。
3. 在 GitHub 仓库的 Secrets 里配置 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_SPREADSHEET_TOKEN`、`FEISHU_TIKVIEW_SPREADSHEET_TOKEN`、`FEISHU_CHAT_ID`、`TIKTOK_CLIENT_KEY`、`TIKTOK_CLIENT_SECRET`。不用再存 `tokens.json`。
4. 自动更新时间在窗口里选星期和小时后点「保存时间」，再点「开启定时任务」。另按上面「自动更新」一节配好免费定时叫醒。电脑可以关着。
