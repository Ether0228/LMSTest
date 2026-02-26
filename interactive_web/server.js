/* eslint-disable no-console */
const http = require("http");
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

function loadDotEnvIfPresent() {
  // Minimal .env loader to avoid adding dependencies (dotenv).
  const envPath = path.join(__dirname, ".env");
  if (!fs.existsSync(envPath)) return;
  const content = fs.readFileSync(envPath, "utf8");
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const idx = line.indexOf("=");
    if (idx <= 0) continue;
    const key = line.slice(0, idx).trim();
    let val = line.slice(idx + 1).trim();
    if (!key) continue;
    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1);
    }
    if (process.env[key] == null || process.env[key] === "") process.env[key] = val;
  }
}

loadDotEnvIfPresent();

const PORT = parseInt(process.env.PORT || "8787", 10);
const AUTH_MODE = (process.env.AUTH_MODE || "mock").trim(); // mock | feishu
const SESSION_SECRET = (process.env.SESSION_SECRET || "").trim();
const BASE_URL = (process.env.BASE_URL || `http://localhost:${PORT}`).trim();

function loadTenants() {
  const raw = (process.env.TENANTS_JSON || "").trim();
  if (!raw) return {};
  try {
    return JSON.parse(raw);
  } catch {
    throw new Error("TENANTS_JSON is not valid JSON");
  }
}

const TENANTS = loadTenants();

function json(res, statusCode, body) {
  const data = Buffer.from(JSON.stringify(body));
  res.writeHead(statusCode, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": data.length,
    "Cache-Control": "no-store",
  });
  res.end(data);
}

function text(res, statusCode, body, contentType = "text/plain; charset=utf-8") {
  const data = Buffer.from(body);
  res.writeHead(statusCode, {
    "Content-Type": contentType,
    "Content-Length": data.length,
    "Cache-Control": "no-store",
  });
  res.end(data);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

function getCookie(req, name) {
  const header = req.headers.cookie || "";
  const parts = header.split(";").map((s) => s.trim());
  for (const p of parts) {
    const idx = p.indexOf("=");
    if (idx <= 0) continue;
    const k = p.slice(0, idx);
    if (k !== name) continue;
    return decodeURIComponent(p.slice(idx + 1));
  }
  return "";
}

function sign(data) {
  const h = crypto.createHmac("sha256", SESSION_SECRET).update(data).digest("hex");
  return `${data}.${h}`;
}

function verifySigned(signed) {
  const idx = signed.lastIndexOf(".");
  if (idx < 0) return null;
  const data = signed.slice(0, idx);
  const sig = signed.slice(idx + 1);
  const expect = crypto.createHmac("sha256", SESSION_SECRET).update(data).digest("hex");
  try {
    if (crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expect))) return data;
  } catch {
    return null;
  }
  return null;
}

function getTenantFromQuery(parsedUrl) {
  const t = (parsedUrl.query.t || "").toString().trim();
  if (!t) return { key: "", conf: null };
  return { key: t, conf: TENANTS[t] || null };
}

const tokenCache = new Map(); // tenantKey -> { token, expMs }

async function feishuGetTenantAccessToken(tenantKey, tenantConf) {
  const cached = tokenCache.get(tenantKey);
  const now = Date.now();
  if (cached && cached.expMs > now + 30_000) return cached.token;

  const resp = await fetch("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal", {
    method: "POST",
    headers: { "Content-Type": "application/json; charset=utf-8" },
    body: JSON.stringify({ app_id: tenantConf.appId, app_secret: tenantConf.appSecret }),
  });
  const data = await resp.json();
  const token = data.tenant_access_token;
  const expireSec = data.expire || 3600;
  if (!token) throw new Error(`feishu token error: ${JSON.stringify(data)}`);
  tokenCache.set(tenantKey, { token, expMs: now + expireSec * 1000 });
  return token;
}

const TABLE_CACHE_TTL_MS = Math.max(5_000, parseInt(process.env.TABLE_CACHE_TTL_MS || "60000", 10) || 60_000);
const ALLOW_MISSING_FULL_SCAN = (process.env.ALLOW_MISSING_FULL_SCAN || "0").trim() === "1";

// ─── 磁盘缓存（pipeline 写 / Node 读，请求响应 < 5ms）─────────────
// CACHE_DIR: 缓存目录，默认 interactive_web/cache/
// DISK_CACHE_TTL_MS: 缓存有效期，默认 25 分钟（pipeline 每 4 小时更新一次，留余量）
const CACHE_DIR = path.resolve(process.env.CACHE_DIR || path.join(__dirname, "cache"));
const DISK_CACHE_TTL_MS = Math.max(60_000, parseInt(process.env.DISK_CACHE_TTL_MS || String(25 * 60 * 1000), 10));
try { fs.mkdirSync(CACHE_DIR, { recursive: true }); } catch {}

function _safeCacheName(s) {
  // 保留中文、字母、数字、连字符、下划线；其余替换为 _
  return String(s).replace(/[^\w\u4e00-\u9fff-]/g, "_").slice(0, 100);
}
function diskCacheFile(tenantKey, studentName) {
  return path.join(CACHE_DIR, `${_safeCacheName(tenantKey)}__${_safeCacheName(studentName)}.json`);
}
function diskCacheGet(tenantKey, studentName) {
  try {
    const file = diskCacheFile(tenantKey, studentName);
    const age = Date.now() - fs.statSync(file).mtimeMs;
    if (age > DISK_CACHE_TTL_MS) return null;
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch { return null; }
}
function diskCacheSet(tenantKey, studentName, data) {
  try {
    const payload = { ...data, _cachedAt: Date.now() };
    fs.writeFileSync(diskCacheFile(tenantKey, studentName), JSON.stringify(payload), "utf8");
  } catch (e) { console.warn("[cache] write failed:", e.message); }
}
// ─────────────────────────────────────────────────────────────────
const FILTER_FALLBACK_ON_EMPTY = (process.env.FILTER_FALLBACK_ON_EMPTY || "1").trim() === "1";
const ALLOW_LIVE_FALLBACK_WHEN_SUMMARY_MISS = (process.env.ALLOW_LIVE_FALLBACK_WHEN_SUMMARY_MISS || "0").trim() === "1";
const tableCache = new Map(); // cacheKey -> { items, expMs }

function escapeFilterValue(s) {
  return String(s).replaceAll("\\", "\\\\").replaceAll('"', '\\"');
}

function buildEqualsFilter(fieldName, value) {
  return JSON.stringify({
    conjunction: "and",
    conditions: [{ field_name: fieldName, operator: "is", value: String(value) }],
  });
}

function cacheKeyFromQueryParts(parts) {
  return parts
    .filter((p) => p != null && p !== "")
    .map((p) => (typeof p === "string" ? p : JSON.stringify(p)))
    .join("|");
}

async function bitableFetchAll(token, appToken, tableId, queryParams = {}) {
  const items = [];
  let pageToken = "";
  while (true) {
    const u = new URL(`https://open.feishu.cn/open-apis/bitable/v1/apps/${appToken}/tables/${tableId}/records`);
    u.searchParams.set("page_size", String(queryParams.page_size || 500));
    if (pageToken) u.searchParams.set("page_token", pageToken);
    if (queryParams.view_id) u.searchParams.set("view_id", String(queryParams.view_id));
    if (queryParams.filter) u.searchParams.set("filter", String(queryParams.filter));
    if (queryParams.sort) u.searchParams.set("sort", String(queryParams.sort));
    if (queryParams.field_names) u.searchParams.set("field_names", String(queryParams.field_names));

    const resp = await fetch(u, { headers: { Authorization: `Bearer ${token}` } });
    const data = await resp.json();
    if (data.code !== 0) break;
    const payload = data.data || {};
    items.push(...(payload.items || []));
    if (!payload.has_more) break;
    pageToken = payload.page_token || "";
    if (!pageToken) break;
  }
  return items;
}

async function bitableFetchAllCached(tenantKey, token, appToken, tableId, { forceRefresh = false } = {}) {
  const cacheKey = `${tenantKey}:${appToken}:${tableId}:ALL`;
  const now = Date.now();
  const cached = tableCache.get(cacheKey);
  if (!forceRefresh && cached && cached.expMs > now) return cached.items;

  const items = await bitableFetchAll(token, appToken, tableId);
  tableCache.set(cacheKey, { items, expMs: now + TABLE_CACHE_TTL_MS });
  return items;
}

async function bitableFetchByFilterCached(tenantKey, token, appToken, tableId, filter, fieldNames, { forceRefresh = false } = {}) {
  const qp = {};
  if (filter) qp.filter = filter;
  if (fieldNames?.length) qp.field_names = JSON.stringify(fieldNames);

  const cacheKey = `${tenantKey}:${appToken}:${tableId}:F:${cacheKeyFromQueryParts([qp.filter || "", qp.field_names || ""])}`;
  const now = Date.now();
  const cached = tableCache.get(cacheKey);
  if (!forceRefresh && cached && cached.expMs > now) return cached.items;

  const items = await bitableFetchAll(token, appToken, tableId, qp);
  tableCache.set(cacheKey, { items, expMs: now + TABLE_CACHE_TTL_MS });
  return items;
}

async function bitableFetchOneByTextField(tenantKey, token, appToken, tableId, fieldName, value, fieldNames, opts = {}) {
  const filter = buildEqualsFilter(fieldName, value);
  const rows = await bitableFetchByFilterCached(tenantKey, token, appToken, tableId, filter, fieldNames, opts);
  return rows[0] || null;
}

function getFieldLinkUrl(val) {
  if (!val) return "";
  if (typeof val === "string") return val.trim();
  if (typeof val === "object" && val.link) return String(val.link).trim();
  return String(val).trim();
}

function normalizeName(s) {
  return String(s || "").trim().replace(/\s+/g, " ").toLowerCase();
}

function extractLinkedRecordIds(value) {
  const out = [];
  const visit = (node) => {
    if (node == null) return;
    if (typeof node === "string") {
      const s = node.trim();
      if (s.startsWith("rec")) out.push(s);
      return;
    }
    if (Array.isArray(node)) {
      for (const x of node) visit(x);
      return;
    }
    if (typeof node === "object") {
      for (const k of ["record_id", "recordId", "id"]) {
        const v = node[k];
        if (typeof v === "string" && v.trim().startsWith("rec")) out.push(v.trim());
      }
      for (const k of ["record_ids", "recordIds", "link_record_ids", "linkRecordIds"]) {
        const v = node[k];
        if (Array.isArray(v)) {
          for (const rid of v) {
            if (typeof rid === "string" && rid.trim().startsWith("rec")) out.push(rid.trim());
          }
        }
      }
      for (const v of Object.values(node)) {
        if (v && (typeof v === "object" || Array.isArray(v))) visit(v);
      }
    }
  };
  visit(value);
  return [...new Set(out)];
}

function summarizeForStudent({ rosterRec, submissions, missing }) {
  const courses = Array.isArray(rosterRec?.fields?.["所属课程"]) ? rosterRec.fields["所属课程"] : [];

  const missingByCourse = new Map();
  for (const m of missing) {
    const course = (m.fields?.["所属课程"] || "").toString().trim() || "未分类";
    missingByCourse.set(course, (missingByCourse.get(course) || 0) + 1);
  }

  const recent = submissions
    .slice()
    .sort((a, b) => {
      const ta = Date.parse(a.fields?.["提交时间"] || "") || 0;
      const tb = Date.parse(b.fields?.["提交时间"] || "") || 0;
      return tb - ta;
    })
    .slice(0, 20)
    .map((r) => ({
      studentName: r.fields?.["学生姓名"] || "",
      assignmentName: r.fields?.["作业名称"] || "",
      status: r.fields?.["提交状态"] || "",
      submittedAt: r.fields?.["提交时间"] || "",
      link: getFieldLinkUrl(r.fields?.["作业链接"]),
      raw: r.fields?.["原始通知"] || "",
    }));

  const missingTotal = missing.length;
  const submittedTotal = submissions.length;

  // 智能推荐：只用“可从现有表算出来”的信号；学分相关后续用 roster 扩展字段接入
  const recommendations = [];
  if (missingTotal > 0) {
    recommendations.push({ type: "guide", title: "优先处理缺交：复活与翻盘", anchorText: "4.8 危机关：复活与翻盘" });
    recommendations.push({ type: "guide", title: "用 Rubric 直接提分", anchorText: "4.4 作业关：Rubric 狙击手" });
  }
  if (missingTotal >= 3) {
    recommendations.push({ type: "guide", title: "建立每日循环，止住连锁迟交", anchorText: "4.2 每日循环 Daily Loop" });
  }
  if (submittedTotal === 0) {
    recommendations.push({ type: "guide", title: "48 小时快速启动", anchorText: "4.1 两个快速启动清单（任选其一，从今天开始）" });
  }

  // 可选：如果 roster 里有“目标学分/已获学分”就做临近毕业提醒
  const creditsTarget = Number(rosterRec?.fields?.["目标学分"] || 0) || 0;
  const creditsEarned = Number(rosterRec?.fields?.["已获学分"] || 0) || 0;
  if (creditsTarget > 0 && creditsEarned > 0) {
    const remaining = Math.max(creditsTarget - creditsEarned, 0);
    if (remaining <= 2) recommendations.push({ type: "guide", title: "进入终极任务：升学与未来探索", anchorText: "七、终极任务" });
  }

  return {
    courses,
    missingTotal,
    missingByCourse: Object.fromEntries([...missingByCourse.entries()].sort((a, b) => b[1] - a[1])),
    submittedTotal,
    recentSubmissions: recent,
    recommendations,
  };
}

function parseMaybeJson(value, fallback) {
  if (value == null || value === "") return fallback;
  if (typeof value === "object") return value;
  try {
    return JSON.parse(String(value));
  } catch {
    return fallback;
  }
}

function normalizeFieldKey(s) {
  return String(s || "").replace(/\s+/g, "").toLowerCase();
}

function getFieldLoose(fields, preferredKey, aliases = []) {
  if (!fields || typeof fields !== "object") return undefined;
  if (Object.prototype.hasOwnProperty.call(fields, preferredKey)) return fields[preferredKey];
  for (const key of aliases) {
    if (Object.prototype.hasOwnProperty.call(fields, key)) return fields[key];
  }
  const targetSet = new Set([preferredKey, ...aliases].map(normalizeFieldKey));
  for (const [k, v] of Object.entries(fields)) {
    if (targetSet.has(normalizeFieldKey(k))) return v;
  }
  for (const [k, v] of Object.entries(fields)) {
    const nk = normalizeFieldKey(k);
    if (nk.includes("课程进度json") || nk.includes("课程进度")) return v;
  }
  return undefined;
}

async function tryLoadFromSummaryTable(tenantKey, token, tenantConf, studentName, forceRefresh, rosterRecordIdHint = "") {
  const summaryTableId = (tenantConf.summaryTableId || "").trim();
  if (!summaryTableId) return null;

  let row = await bitableFetchOneByTextField(
    tenantKey,
    token,
    tenantConf.appToken,
    summaryTableId,
    "学生姓名",
    studentName,
    null,
    { forceRefresh },
  );
  if (!row) {
    const allRows = await bitableFetchAllCached(tenantKey, token, tenantConf.appToken, summaryTableId, { forceRefresh });
    const targetName = normalizeName(studentName);
    row =
      allRows.find((r) => {
        const ids = extractLinkedRecordIds(r.fields?.["关联学生"]);
        return rosterRecordIdHint && ids.includes(rosterRecordIdHint);
      }) ||
      allRows.find((r) => normalizeName(r.fields?.["学生姓名"]) === targetName) ||
      null;
  }
  if (!row) return null;

  const f = row.fields || {};
  const recsRaw = parseMaybeJson(getFieldLoose(f, "推荐JSON"), []);
  const recommendations = Array.isArray(recsRaw)
    ? recsRaw.map((item) => ({ type: "guide", title: item?.title || "", anchorText: item?.anchorText || "" }))
    : [];
  const courses = parseMaybeJson(getFieldLoose(f, "课程清单JSON"), []);
  const missingByCourse = parseMaybeJson(getFieldLoose(f, "缺交按课程JSON"), {});
  const recentSubmissions = parseMaybeJson(getFieldLoose(f, "近期提交JSON"), []);
  const courseProgress = parseMaybeJson(getFieldLoose(f, "课程进度JSON", ["课程进度Json", "课程进度"]), []);
  const missingItems = parseMaybeJson(getFieldLoose(f, "缺交明细JSON", ["缺交明细Json"]), []);
  const summaryUpdatedAt = getFieldLoose(f, "最后更新时间");

  return {
    tenant: tenantKey,
    studentName: String(getFieldLoose(f, "学生姓名") || studentName),
    rosterRecordId: extractLinkedRecordIds(f["关联学生"])[0] || rosterRecordIdHint || "",
    courses,
    missingTotal: Number(getFieldLoose(f, "缺交总数") || 0) || 0,
    missingByCourse,
    courseProgress,
    missingItems,
    submittedTotal: Number(getFieldLoose(f, "已提交总数") || 0) || 0,
    recentSubmissions,
    recommendations,
    missingSource: "summary_table",
    summaryUpdatedAt: summaryUpdatedAt || null,
  };
}

async function handleApiDashboard(req, res, parsedUrl) {
  const { key: tenantKey, conf: tenantConf } = getTenantFromQuery(parsedUrl);
  if (!tenantKey) return json(res, 400, { error: "missing tenant key: use ?t=tenant_a" });

  if (AUTH_MODE !== "mock" && !SESSION_SECRET) {
    return json(res, 500, { error: "SESSION_SECRET is required when AUTH_MODE != mock" });
  }

  const forceRefresh = (parsedUrl.query.refresh || "").toString().trim() === "1";

  // Demo mode: let non-technical users preview UI without any Feishu config.
  if (AUTH_MODE === "mock" && !tenantConf) {    const studentName = (parsedUrl.query.student || "").toString().trim() || "示例同学";
    const demo = {
      tenant: tenantKey,
      studentName,
      rosterRecordId: "",
      courses: ["ENG4U", "MHF4U", "SPH4U"],
      missingTotal: 2,
      missingByCourse: { ENG4U: 1, MHF4U: 1 },
      submittedTotal: 6,
      recentSubmissions: [
        { assignmentName: "ENG4U - Paragraph Writing", status: "Submitted", submittedAt: "2026/02/23 20:10", link: "", raw: "" },
        { assignmentName: "MHF4U - Quiz 1", status: "Resubmitted", submittedAt: "2026/02/22 19:02", link: "", raw: "" },
      ],
      recommendations: [
        { type: "guide", title: "优先处理缺交：复活与翻盘", anchorText: "4.8 危机关：复活与翻盘" },
        { type: "guide", title: "用 Rubric 直接提分", anchorText: "4.4 作业关：Rubric 狙击手" },
      ],
      _note: "demo data (AUTH_MODE=mock, tenant config missing)",
    };
    return json(res, 200, demo);
  }

  if (!tenantConf) return json(res, 400, { error: `unknown tenant key: ${tenantKey}` });

  const token = await feishuGetTenantAccessToken(tenantKey, tenantConf);

  // 身份：MVP 先支持 mock（从 query/student 取）；生产必须改成飞书免登/OAuth 后写 session
  let studentName = "";
  if (AUTH_MODE === "mock") {
    studentName = (parsedUrl.query.student || "").toString().trim();
    if (!studentName) return json(res, 400, { error: "mock mode requires ?student=姓名" });
  } else {
    const signed = getCookie(req, "qea_session");
    const data = signed ? verifySigned(signed) : null;
    if (!data) return json(res, 401, { error: "not logged in" });
    const session = JSON.parse(data);
    studentName = (session.studentName || "").trim();
    if (!studentName) return json(res, 401, { error: "session missing studentName" });
  }

  // ── 磁盘缓存快速通道（pipeline 已写好文件，直接返回，< 5ms）────
  if (!forceRefresh) {
    const hit = diskCacheGet(tenantKey, studentName);
    if (hit) {
      const ageMin = Math.round((Date.now() - (hit._cachedAt || 0)) / 60000);
      console.log(`[cache] hit: ${tenantKey}/${studentName} (${ageMin}min ago)`);
      return json(res, 200, hit);
    }
  }
  const rosterHint = await bitableFetchOneByTextField(
    tenantKey,
    token,
    tenantConf.appToken,
    tenantConf.rosterTableId,
    "学生姓名",
    studentName,
    ["学生姓名"],
    { forceRefresh },
  );
  const rosterHintId = rosterHint?.record_id || "";

  // Fastest path: use precomputed summary table if configured.
  const hasSummaryTable = !!(tenantConf.summaryTableId || "").trim();
  const summaryPayload = await tryLoadFromSummaryTable(
    tenantKey,
    token,
    tenantConf,
    studentName,
    forceRefresh,
    rosterHintId,
  );
  if (summaryPayload) {
    diskCacheSet(tenantKey, studentName, summaryPayload);
    return json(res, 200, summaryPayload);
  }
  if (hasSummaryTable && !ALLOW_LIVE_FALLBACK_WHEN_SUMMARY_MISS) {
    return json(res, 200, {
      tenant: tenantKey,
      studentName,
      rosterRecordId: rosterHintId,
      courses: [],
      missingTotal: 0,
      missingByCourse: {},
      missingItems: [],
      submittedTotal: 0,
      recentSubmissions: [],
      recommendations: [{ type: "guide", title: "未找到你的汇总数据，请联系老师刷新汇总", anchorText: "四、日常通关系统（把机制变成分数）" }],
      missingSource: "summary_miss_fast_return",
    });
  }

  // Speed strategy:
  // - roster: filter by studentName (text field)
  // - submissions: filter by studentName (text field)
  // - missing: try filter by linked roster record id; if filter fails, fall back to cached full table
  const rosterRec = await bitableFetchOneByTextField(
    tenantKey,
    token,
    tenantConf.appToken,
    tenantConf.rosterTableId,
    "学生姓名",
    studentName,
    ["学生姓名", "所属课程", "目标学分", "已获学分"],
    { forceRefresh },
  );
  let resolvedRosterRec = rosterRec;

  // If filter syntax/field config differs across bases, recover correctness with cached scan.
  if (!resolvedRosterRec && FILTER_FALLBACK_ON_EMPTY) {
    const rosterAll = await bitableFetchAllCached(tenantKey, token, tenantConf.appToken, tenantConf.rosterTableId, { forceRefresh });
    const targetName = normalizeName(studentName);
    resolvedRosterRec = rosterAll.find((r) => normalizeName(r.fields?.["学生姓名"]) === targetName) || null;
  }
  const rosterRecId = resolvedRosterRec?.record_id || "";

  const submissionsFilter = buildEqualsFilter("学生姓名", studentName);
  let subForStudent = await bitableFetchByFilterCached(
    tenantKey,
    token,
    tenantConf.appToken,
    tenantConf.submissionsTableId,
    submissionsFilter,
    ["学生姓名", "作业名称", "提交状态", "提交时间", "作业链接", "原始通知", "关联学生", "唯一ID"],
    { forceRefresh },
  );

  if (!subForStudent.length && FILTER_FALLBACK_ON_EMPTY) {
    const submissionsAll = await bitableFetchAllCached(tenantKey, token, tenantConf.appToken, tenantConf.submissionsTableId, { forceRefresh });
    const targetName = normalizeName(studentName);
    subForStudent = submissionsAll.filter((r) => normalizeName(r.fields?.["学生姓名"]) === targetName);
  }

  let missingForStudent = [];
  let missingSource = "none";
  const missingStudentNameField = (tenantConf.missingStudentNameField || "").trim();

  // Fast path: if missing table has a denormalized text field (e.g. 学生姓名), use direct filter.
  if (missingStudentNameField) {
    const missingFilterByName = buildEqualsFilter(missingStudentNameField, studentName);
    missingForStudent = await bitableFetchByFilterCached(
      tenantKey,
      token,
      tenantConf.appToken,
      tenantConf.missingTableId,
      missingFilterByName,
      ["所属课程", "关联学生", "处理状态", "最后核验时间", "发现日期", "唯一标识", missingStudentNameField],
      { forceRefresh },
    );
    missingSource = "filtered_by_name_field";
    if (!missingForStudent.length && FILTER_FALLBACK_ON_EMPTY && rosterRecId) {
      const missingAll = await bitableFetchAllCached(tenantKey, token, tenantConf.appToken, tenantConf.missingTableId, { forceRefresh });
      missingForStudent = missingAll.filter((r) => {
        const linked = r.fields?.["关联学生"];
        return Array.isArray(linked) && linked.includes(rosterRecId);
      });
      missingSource = "fallback_after_name_filter_empty";
    }
  } else if (ALLOW_MISSING_FULL_SCAN && rosterRecId) {
    // Optional fallback: expensive on large tables, disabled by default.
    const missingAll = await bitableFetchAllCached(tenantKey, token, tenantConf.appToken, tenantConf.missingTableId, { forceRefresh });
    missingForStudent = missingAll.filter((r) => {
      const linked = r.fields?.["关联学生"];
      return Array.isArray(linked) && linked.includes(rosterRecId);
    });
    missingSource = "full_scan_fallback";
  } else {
    // Keep response fast; ask for schema optimization instead of full scan.
    missingSource = "skipped_no_name_field";
  }

  const summary = summarizeForStudent({ rosterRec: resolvedRosterRec, submissions: subForStudent, missing: missingForStudent });

  const result = {
    tenant: tenantKey,
    studentName,
    rosterRecordId: rosterRecId,
    missingSource,
    ...summary,
  };
  diskCacheSet(tenantKey, studentName, result);
  return json(res, 200, result);
}

function serveStatic(req, res, parsedUrl) {
  const publicDir = path.join(__dirname, "public");
  let pathname = parsedUrl.pathname || "/";
  if (pathname === "/") pathname = "/index.html";
  const filePath = path.normalize(path.join(publicDir, pathname));
  if (!filePath.startsWith(publicDir)) return text(res, 403, "forbidden");

  if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) return text(res, 404, "not found");

  const ext = path.extname(filePath).toLowerCase();
  const ct =
    ext === ".html"
      ? "text/html; charset=utf-8"
      : ext === ".css"
        ? "text/css; charset=utf-8"
        : ext === ".js"
          ? "application/javascript; charset=utf-8"
          : "application/octet-stream";
  const data = fs.readFileSync(filePath);
  res.writeHead(200, { "Content-Type": ct, "Content-Length": data.length, "Cache-Control": "no-store" });
  res.end(data);
}

async function handleGuideMd(req, res) {
  const guidePath = path.join(__dirname, "..", "01 通关指南初始文稿.md");
  if (!fs.existsSync(guidePath)) return text(res, 404, "guide not found");
  const md = fs.readFileSync(guidePath, "utf8");
  return text(res, 200, md, "text/markdown; charset=utf-8");
}

const server = http.createServer(async (req, res) => {
  try {
    const parsedUrl = new URL(req.url, BASE_URL);
    const query = Object.fromEntries(parsedUrl.searchParams.entries());
    const reqLike = { pathname: parsedUrl.pathname, query };
    if ((reqLike.pathname || "").startsWith("/api/dashboard")) return await handleApiDashboard(req, res, reqLike);
    if ((reqLike.pathname || "") === "/api/guide.md") return await handleGuideMd(req, res);
    return serveStatic(req, res, reqLike);
  } catch (e) {
    console.error(e);
    return json(res, 500, { error: String(e?.message || e) });
  }
});

server.listen(PORT, () => {
  console.log(`[interactive_web] listening on ${BASE_URL} (PORT=${PORT}, AUTH_MODE=${AUTH_MODE})`);
  if (!Object.keys(TENANTS).length) console.log("[interactive_web] TENANTS_JSON is empty; dashboard API will fail until configured");
});
