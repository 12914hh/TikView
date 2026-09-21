# Callback 页面文案

作者浏览器打开回调页时看到的文字。中文在上，英文在下。

作者页面只显示成功或失败，不显示错误码。错误码发到飞书群，并在能确定作者时写入达人管理「失败原因」。

## 授权成功

- 授权成功，可以关闭浏览器。
- Authorization succeeded. You can close the browser.

## 授权失败

不管能不能确定作者、能不能写进飞书，作者都看到：

- 授权失败，请关闭浏览器并联系商家。
- Authorization failed. Please close the browser and contact the business that sent you this link.

没有复制按钮。群里会收到错误码、中文原因、下一步，以及作者 ID。对不上作者时，作者 ID 为「无」。

群消息示例：

```text
**【TikView 系统通知】**
⚠️ **授权异常**
🕐 **时间：**【2026-09-21 17:26】
🔢 **错误码：**TV003
📌 **原因：**授权链接校验失败
👉 **下一步：**本机盖章用的 STATE_SECRET 和 Worker 上的不一致，或链接被改过。先把两边密钥改成同一个，再重新生成链接。不要让作者继续点旧链接。
👤 **作者 ID：**无
```

能写进达人管理时，「失败原因」格式仍是：`{错误码} {中文原因}`。

## 错误码对照

群里看到错误码后，按这一列处理。作者页面不会显示这些步骤。

| 错误码 | 中文原因 | 下一步 |
| --- | --- | --- |
| TV001 | 服务还没有配置 STATE_SECRET | 在 `worker` 目录执行 `npx wrangler secret put STATE_SECRET`，粘贴的值必须和本机 `.env` 里的 `STATE_SECRET` 完全一样。配好后重新生成链接，让作者再点一次。 |
| TV002 | 授权链接无效 | 链接不完整，或被聊天软件截断了。在窗口里重新生成，把整段链接发给作者，不要只复制其中一段。 |
| TV003 | 授权链接校验失败 | 本机盖章用的 `STATE_SECRET` 和 Worker 上的不一致，或链接被改过。先把两边密钥改成同一个，再重新生成链接。不要让作者继续点旧链接。 |
| TV004 | 授权链接里没有作者 ID | 生成链接时没有填写飞书作者 ID。在窗口里先填作者 ID，再点「生成授权链接」。 |
| TV005 | 授权链接已过期，请重新生成 | 链接超过 24 小时。重新生成一条发给作者。旧链接不能再用。 |
| TV006 | 授权没有完成：{原因} | 作者取消了同意，或 TikTok 拒绝了。请作者重新打开新链接，在同意页打开权限并点 Continue。若 `{原因}` 不是取消，把群里的原文留下来再查，不要反复点同一条旧链接。 |
| TV007 | 没有收到授权码。 | 作者没有点完同意，或中途关掉了页面。重新生成链接，让作者一直点到出现「授权成功」或「授权失败」那一页。 |
| TV008 | 保存授权失败：{原因} | 看群里的 `{原因}`。若是 `TikTok 没有返回 token` 或 Redirect 不一致：只改 Sandbox 的 Redirect URI 为 `https://tikview.12914hh.workers.dev/callback`，然后点 Apply changes；Worker 上的 Client Key、Secret 也要和 Sandbox 一致。若是飞书写入失败：检查 Worker 上的飞书应用凭证、表格 token，以及该应用有没有这个表格的编辑权限。审核通过前不要改 Production。 |
| TV009 | （程序原文） | 把群消息里的原因整段留下来。先重新生成一条链接再试一次。还是 TV009，再根据原文排查，不要继续用旧链接。 |

## 不是回调结果

直接打开网站根地址 `https://tikview.12914hh.workers.dev/`，地址里没有 `/callback` 时出现：

- TikView 授权服务正在运行。作者点完授权链接后会回到 /callback。
- TikView authorization service is running. After approving, you will return to /callback.

正常授权链接不会进入这一页。
