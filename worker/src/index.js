/**
 * TikTok 授权回调。作者点完后自动换 token，写入飞书「授权」表。
 * 密钥只放在 Worker 的环境变量里。
 */

const AUTH_TITLE = "授权";
const HEADERS = [
  "作者ID",
  "status",
  "open_id",
  "access_token",
  "refresh_token",
  "expires_at",
  "refresh_expires_at",
  "scope",
  "video_ids",
];

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/callback") {
      return handleCallback(url, env);
    }
    return html(
      "TikView 授权服务正在运行。作者点完授权链接后会回到 /callback。\nTikView authorization service is running. After approving, you will return to /callback.",
      200,
    );
  },
};

async function handleCallback(url, env) {
  const state = url.searchParams.get("state") || "";
  const error = url.searchParams.get("error");
  if (error) {
    const detail = url.searchParams.get("error_description") || error;
    return finish(env, state, "TV006", "授权没有完成：" + detail, 400);
  }
  const code = url.searchParams.get("code") || "";
  let authorId = "";
  try {
    authorId = await verifyState(env.STATE_SECRET, state);
  } catch (exc) {
    return finish(
      env,
      state,
      exc.code || "TV009",
      String(exc.message || exc),
      400,
    );
  }
  if (!code) {
    return finish(env, state, "TV007", "没有收到授权码。", 400);
  }
  let saved;
  try {
    const token = await exchangeCode(env, code);
    saved = await saveToken(env, token, authorId);
  } catch (exc) {
    return finish(
      env,
      state,
      "TV008",
      "保存授权失败：" + String(exc.message || exc),
      500,
    );
  }
  try {
    await markCreatorAuthorized(
      saved.feishuToken,
      spreadsheetToken(env.FEISHU_SPREADSHEET_TOKEN),
      authorId,
    );
  } catch (_exc) {
    // 令牌已经写入授权表。作者这边仍视为授权成功。
  }
  return successPage();
}

async function finish(env, state, errorCode, reasonZh, status) {
  await noteAuthFailure(env, state, errorCode + " " + reasonZh);
  await notifyGroup(env, errorCode, reasonZh, await knownAuthor(env, state));
  return failurePage(status);
}

async function knownAuthor(env, state) {
  try {
    return await verifyState(env.STATE_SECRET, state);
  } catch (exc) {
    return exc && exc.authorId ? exc.authorId : "";
  }
}

async function notifyGroup(env, errorCode, reasonZh, authorId) {
  const chatId = String(env.FEISHU_CHAT_ID || "").trim();
  if (!chatId) {
    return;
  }
  const text = [
    "**【TikView 系统通知】**",
    "⚠️ **授权异常**",
    "🕐 **时间：**" + beijingClock(),
    "🔢 **错误码：**" + errorCode,
    "📌 **原因：**" + reasonZh,
    "👉 **下一步：**" + nextStep(errorCode),
    "👤 **作者 ID：**" + (authorId || "无"),
  ].join("\n");
  try {
    const token = await feishuTenantToken(env);
    await fetch(
      "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
      {
        method: "POST",
        headers: {
          Authorization: "Bearer " + token,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          receive_id: chatId,
          msg_type: "interactive",
          content: JSON.stringify({
            config: { wide_screen_mode: true },
            elements: [{ tag: "markdown", content: text }],
          }),
        }),
      },
    );
  } catch (_exc) {
    // 作者页面仍显示授权失败。
  }
}

const ERROR_GUIDE = {
  TV001: {
    reason: "服务还没有配置 STATE_SECRET",
    next: "在 worker 目录执行 `npx wrangler secret put STATE_SECRET`，粘贴的值必须和本机 .env 里的 STATE_SECRET 完全一样。配好后重新生成链接，让作者再点一次。",
  },
  TV002: {
    reason: "授权链接无效",
    next: "链接不完整，或被聊天软件截断了。在窗口里重新生成，把整段链接发给作者，不要只复制其中一段。",
  },
  TV003: {
    reason: "授权链接校验失败",
    next: "本机盖章用的 STATE_SECRET 和 Worker 上的不一致，或链接被改过。先把两边密钥改成同一个，再重新生成链接。不要让作者继续点旧链接。",
  },
  TV004: {
    reason: "授权链接里没有作者 ID",
    next: "生成链接时没有填写飞书作者 ID。在窗口里先填作者 ID，再点「生成授权链接」。",
  },
  TV005: {
    reason: "授权链接已过期，请重新生成",
    next: "链接超过 24 小时。重新生成一条发给作者。旧链接不能再用。",
  },
  TV006: {
    reason: "作者取消了同意，或 TikTok 拒绝了这次授权",
    next: "请作者重新打开新链接，在同意页打开权限并点 Continue。若原因不是取消，把群里的原文留下来再查，不要反复点同一条旧链接。",
  },
  TV007: {
    reason: "没有收到授权码",
    next: "作者没有点完同意，或中途关掉了页面。重新生成链接，让作者一直点到出现「授权成功」或「授权失败」那一页。",
  },
  TV008: {
    reason: "换取令牌或写入飞书失败",
    next: "看同一条里的原因。若是 TikTok 没有返回 token 或 Redirect 不一致：只改 Sandbox 的 Redirect URI 为 https://tikview.12914hh.workers.dev/callback，然后点 Apply changes；Worker 上的 Client Key、Secret 也要和 Sandbox 一致。若是飞书写入失败：检查 Worker 上的飞书应用凭证、表格 token，以及该应用有没有这个表格的编辑权限。审核通过前不要改 Production。",
  },
  TV009: {
    reason: "程序遇到了没有单独编号的错误",
    next: "把群消息里的原因整段留下来。先重新生成一条链接再试一次。还是 TV009，再根据原文排查，不要继续用旧链接。",
  },
};

function nextStep(errorCode) {
  const guide = ERROR_GUIDE[errorCode];
  return guide ? guide.next : "把这条消息留下来，先重新生成授权链接再试一次。";
}

let tenantCache = { token: "", expireAt: 0 };

function beijingClock() {
  const shifted = new Date(Date.now() + 8 * 3600 * 1000);
  const year = shifted.getUTCFullYear();
  const month = String(shifted.getUTCMonth() + 1).padStart(2, "0");
  const day = String(shifted.getUTCDate()).padStart(2, "0");
  const hour = String(shifted.getUTCHours()).padStart(2, "0");
  const minute = String(shifted.getUTCMinutes()).padStart(2, "0");
  return (
    "【" + year + "-" + month + "-" + day + " " + hour + ":" + minute + "】"
  );
}

async function verifyState(secret, state) {
  if (!secret) {
    throw fail("TV001", "服务还没有配置 STATE_SECRET");
  }
  const dot = state.indexOf(".");
  if (dot <= 0) {
    throw fail("TV002", "授权链接无效");
  }
  const payload = state.slice(0, dot);
  const signature = state.slice(dot + 1);
  const expected = await hmacBase64(secret, payload);
  if (expected !== signature) {
    throw fail("TV003", "授权链接校验失败");
  }
  const data = JSON.parse(new TextDecoder().decode(base64UrlDecode(payload)));
  const authorId = String(data.a || "").trim();
  if (!authorId) {
    throw fail("TV004", "授权链接里没有作者 ID");
  }
  const issued = Number(data.t || 0);
  if (!issued || Date.now() / 1000 - issued > 24 * 3600) {
    throw fail("TV005", "授权链接已过期，请重新生成", { authorId });
  }
  return authorId;
}

function fail(code, zh, extra) {
  return Object.assign(new Error(zh), { code }, extra || {});
}

async function exchangeCode(env, code) {
  const body = new URLSearchParams({
    client_key: env.TIKTOK_CLIENT_KEY,
    client_secret: env.TIKTOK_CLIENT_SECRET,
    code,
    grant_type: "authorization_code",
    redirect_uri: env.TIKTOK_REDIRECT_URI,
  });
  const response = await fetch("https://open.tiktokapis.com/v2/oauth/token/", {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      "Cache-Control": "no-cache",
    },
    body,
  });
  const json = await response.json();
  if (json.error || !json.access_token || !json.open_id) {
    throw new Error(
      json.error_description || json.error || "TikTok 没有返回 token",
    );
  }
  return json;
}

async function saveToken(env, token, authorId) {
  const feishuToken = await feishuTenantToken(env);
  const spreadsheet = spreadsheetToken(tikviewSpreadsheet(env));
  let sheetId = await findAuthSheet(feishuToken, spreadsheet);
  if (!sheetId) {
    sheetId = await addAuthSheet(feishuToken, spreadsheet);
    await writeRow(feishuToken, spreadsheet, sheetId, 1, HEADERS);
  }
  const rows = await readRows(feishuToken, spreadsheet, sheetId);
  const now = Math.floor(Date.now() / 1000);
  const values = [
    authorId,
    "已授权",
    token.open_id,
    token.access_token,
    token.refresh_token || "",
    String(now + Number(token.expires_in || 0)),
    String(now + Number(token.refresh_expires_in || 0)),
    token.scope || "",
    "",
  ];
  const header = rows[0] || [];
  const openIdCol = columnIndex(header, "open_id");
  let target = 0;
  let firstEmpty = 0;
  for (let i = 1; i < rows.length; i += 1) {
    const openId = cell(rows[i], openIdCol);
    if (openId === token.open_id) {
      target = i + 1;
      break;
    }
    if (!openId && !firstEmpty) {
      firstEmpty = i + 1;
    }
  }
  if (!target) {
    target = firstEmpty || Math.max(rows.length, 1) + 1;
  }
  await writeRow(feishuToken, spreadsheet, sheetId, target, values);
  return { feishuToken, spreadsheet };
}

async function markCreatorAuthorized(token, spreadsheet, authorId) {
  const sheet = await findCreatorSheet(token, spreadsheet);
  const header = sheet.header;
  const authorCol = findColumn(header, "ID");
  const statusCol = findColumn(header, "授权状态");
  const trackCol = findColumn(header, "追踪");
  if (authorCol < 0 || statusCol < 0) {
    throw new Error("达人管理表缺少「ID」或「授权状态」列");
  }
  const rows = await readSheetRows(token, spreadsheet, sheet.sheetId);
  const updates = [];
  for (let i = 1; i < rows.length; i += 1) {
    if (cell(rows[i], authorCol) !== authorId) {
      continue;
    }
    if (trackCol >= 0 && cell(rows[i], trackCol) === "否") {
      continue;
    }
    updates.push({
      range: `${sheet.sheetId}!${columnName(statusCol + 1)}${i + 1}`,
      values: [["已授权"]],
    });
    const reasonCol = findReasonColumn(header);
    if (reasonCol >= 0) {
      updates.push({
        range: `${sheet.sheetId}!${columnName(reasonCol + 1)}${i + 1}`,
        values: [[""]],
      });
    }
  }
  await writeCells(token, spreadsheet, updates);
  return updates.filter((item) => item.values[0][0] === "已授权").length;
}

async function noteAuthFailure(env, state, message) {
  let authorId = "";
  try {
    authorId = await verifyState(env.STATE_SECRET, state);
  } catch (exc) {
    authorId = exc && exc.authorId ? exc.authorId : "";
  }
  if (!authorId) {
    return false;
  }
  try {
    const token = await feishuTenantToken(env);
    const spreadsheet = spreadsheetToken(env.FEISHU_SPREADSHEET_TOKEN);
    const marked = await markCreatorFailure(
      token,
      spreadsheet,
      authorId,
      message,
    );
    return marked > 0;
  } catch (_exc) {
    return false;
  }
}

async function markCreatorFailure(token, spreadsheet, authorId, message) {
  const sheet = await findCreatorSheet(token, spreadsheet);
  const header = sheet.header;
  const authorCol = findColumn(header, "ID");
  const reasonCol = findReasonColumn(header);
  const statusCol = findColumn(header, "授权状态");
  const trackCol = findColumn(header, "追踪");
  if (authorCol < 0 || reasonCol < 0) {
    throw new Error("达人管理表缺少「ID」或「失败原因」列");
  }
  const rows = await readSheetRows(token, spreadsheet, sheet.sheetId);
  const updates = [];
  for (let i = 1; i < rows.length; i += 1) {
    if (cell(rows[i], authorCol) !== authorId) {
      continue;
    }
    if (trackCol >= 0 && cell(rows[i], trackCol) === "否") {
      continue;
    }
    updates.push({
      range: `${sheet.sheetId}!${columnName(reasonCol + 1)}${i + 1}`,
      values: [[message]],
    });
    if (statusCol >= 0) {
      updates.push({
        range: `${sheet.sheetId}!${columnName(statusCol + 1)}${i + 1}`,
        values: [["授权失败"]],
      });
    }
  }
  await writeCells(token, spreadsheet, updates);
  return updates.filter((item) => item.values[0][0] === message).length;
}

function findReasonColumn(header) {
  for (const name of ["失败原因", "失败原图"]) {
    const index = findColumn(header, name);
    if (index >= 0) {
      return index;
    }
  }
  return -1;
}

async function findCreatorSheet(token, spreadsheet) {
  const sheets = await listSheets(token, spreadsheet);
  for (const sheet of sheets) {
    if (!sheet.sheet_id || sheet.title === AUTH_TITLE || sheet.hidden) {
      continue;
    }
    const headerRows = await readRange(
      token,
      spreadsheet,
      `${sheet.sheet_id}!A1:AZ1`,
    );
    const header = headerRows[0] || [];
    if (header.some((name) => normHeader(name) === "视频ID")) {
      return { sheetId: sheet.sheet_id, header };
    }
  }
  throw new Error("没有找到带「视频ID」的达人管理表");
}

function findColumn(header, name) {
  const wanted = normHeader(name);
  return header.findIndex((item) => normHeader(item) === wanted);
}

function normHeader(name) {
  return String(name || "")
    .replaceAll("（", "(")
    .replaceAll("）", ")")
    .replaceAll(" ", "")
    .trim();
}

async function listSheets(token, spreadsheet) {
  const response = await fetch(
    `https://open.feishu.cn/open-apis/sheets/v3/spreadsheets/${spreadsheet}/sheets/query`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  const json = await response.json();
  return (json.data && json.data.sheets) || [];
}

async function readSheetRows(token, spreadsheet, sheetId) {
  const rows = [];
  for (let start = 1; start <= 5000; start += 200) {
    const end = start + 199;
    const values = await readRange(
      token,
      spreadsheet,
      `${sheetId}!A${start}:AZ${end}`,
    );
    if (!values.length || values.every((row) => rowEmpty(row))) {
      break;
    }
    rows.push(...values);
    if (values.length < 200) {
      break;
    }
  }
  while (rows.length && rowEmpty(rows[rows.length - 1])) {
    rows.pop();
  }
  return rows;
}

async function readRange(token, spreadsheet, range) {
  const response = await fetch(
    `https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/${spreadsheet}/values/${encodeURIComponent(range)}`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  const json = await response.json();
  if (json.code) {
    throw new Error(json.msg || "读取飞书失败");
  }
  return (
    (json.data && json.data.valueRange && json.data.valueRange.values) || []
  );
}

async function writeCells(token, spreadsheet, updates) {
  for (let start = 0; start < updates.length; start += 50) {
    const chunk = updates.slice(start, start + 50);
    const response = await fetch(
      `https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/${spreadsheet}/values_batch_update`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ valueRanges: chunk }),
      },
    );
    const json = await response.json();
    if (json.code) {
      throw new Error(json.msg || "写入达人管理失败");
    }
  }
}

function spreadsheetToken(raw) {
  let token = String(raw || "").trim();
  const marker = "/sheets/";
  if (token.includes(marker)) {
    token = token.split(marker)[1];
  }
  return token.split("?")[0].split("#")[0].replace(/\/$/, "");
}

function tikviewSpreadsheet(env) {
  const raw = String(env.FEISHU_TIKVIEW_SPREADSHEET_TOKEN || "").trim();
  if (!raw) {
    throw new Error("还没有配置 FEISHU_TIKVIEW_SPREADSHEET_TOKEN");
  }
  return raw;
}

async function feishuTenantToken(env) {
  if (tenantCache.token && Date.now() < tenantCache.expireAt) {
    return tenantCache.token;
  }
  const response = await fetch(
    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        app_id: env.FEISHU_APP_ID,
        app_secret: env.FEISHU_APP_SECRET,
      }),
    },
  );
  const json = await response.json();
  if (!json.tenant_access_token) {
    throw new Error(json.msg || "获取飞书凭证失败");
  }
  const expire = Number(json.expire || 7200);
  tenantCache = {
    token: json.tenant_access_token,
    expireAt: Date.now() + Math.max(60, expire - 300) * 1000,
  };
  return tenantCache.token;
}

async function findAuthSheet(token, spreadsheet) {
  const response = await fetch(
    `https://open.feishu.cn/open-apis/sheets/v3/spreadsheets/${spreadsheet}/sheets/query`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  const json = await response.json();
  const sheets = (json.data && json.data.sheets) || [];
  const found = sheets.find((sheet) => sheet.title === AUTH_TITLE);
  return found ? found.sheet_id : "";
}

async function addAuthSheet(token, spreadsheet) {
  const response = await fetch(
    `https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/${spreadsheet}/sheets_batch_update`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        requests: [{ addSheet: { properties: { title: AUTH_TITLE } } }],
      }),
    },
  );
  const json = await response.json();
  const replies = (json.data && json.data.replies) || [];
  const sheetId =
    replies[0] && replies[0].addSheet && replies[0].addSheet.properties.sheetId;
  if (!sheetId) {
    throw new Error("创建授权表失败");
  }
  return sheetId;
}

async function readRows(token, spreadsheet, sheetId) {
  const range = encodeURIComponent(`${sheetId}!A1:I500`);
  const response = await fetch(
    `https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/${spreadsheet}/values/${range}`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  const json = await response.json();
  const rows =
    (json.data && json.data.valueRange && json.data.valueRange.values) || [];
  while (rows.length && rowEmpty(rows[rows.length - 1])) {
    rows.pop();
  }
  return rows;
}

function rowEmpty(row) {
  if (!row) {
    return true;
  }
  return row.every((value) => cellValue(value) === "");
}

function cellValue(value) {
  if (value == null) {
    return "";
  }
  return String(value).trim();
}

async function writeRow(token, spreadsheet, sheetId, rowNumber, values) {
  const end = columnName(values.length);
  const range = `${sheetId}!A${rowNumber}:${end}${rowNumber}`;
  const response = await fetch(
    `https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/${spreadsheet}/values`,
    {
      method: "PUT",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ valueRange: { range, values: [values] } }),
    },
  );
  const json = await response.json();
  if (json.code) {
    throw new Error(json.msg || "写入飞书失败");
  }
}

function columnIndex(header, name) {
  const found = header.findIndex((item) => cellValue(item) === name);
  return found >= 0 ? found : 2;
}

function cell(row, index) {
  if (!row || index >= row.length || row[index] == null) {
    return "";
  }
  return String(row[index]).trim();
}

function columnName(index) {
  let letters = "";
  while (index > 0) {
    index -= 1;
    letters = String.fromCharCode(65 + (index % 26)) + letters;
    index = Math.floor(index / 26);
  }
  return letters;
}

async function hmacBase64(secret, payload) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(payload),
  );
  return base64UrlEncode(new Uint8Array(signature));
}

function base64UrlEncode(bytes) {
  let text = "";
  for (const byte of bytes) {
    text += String.fromCharCode(byte);
  }
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function base64UrlDecode(text) {
  const padded = text + "=".repeat((4 - (text.length % 4)) % 4);
  const binary = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

function successPage() {
  return html(
    [
      "授权成功，可以关闭浏览器。",
      "Authorization succeeded. You can close the browser.",
    ].join("\n"),
    200,
  );
}

function failurePage(status) {
  return html(
    [
      "授权失败，请关闭浏览器并联系商家。",
      "Authorization failed. Please close the browser and contact the business that sent you this link.",
    ].join("\n"),
    status,
  );
}

function html(message, status) {
  const paragraphs = String(message)
    .split("\n")
    .map((line) => `<p>${escapeHtml(line)}</p>`)
    .join("");
  const body = `<!DOCTYPE html><html lang="zh-CN"><meta charset="utf-8"><title>TikView</title><body>${paragraphs}</body></html>`;
  return new Response(body, {
    status,
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
}

function escapeHtml(text) {
  return text.replace(
    /[&<>"]/g,
    (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[char],
  );
}
