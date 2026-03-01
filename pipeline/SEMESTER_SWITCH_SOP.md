# 学期切换 SOP

> 每学期约需 20–30 分钟。

---

## 前置：明确哪些东西会变

| 类别 | 每学期变 | 每学期不变 |
|---|---|---|
| Schoology | Section NID（每门课每学期不同）、作业列表、学期日期 | App Token、Cookies（到期独立处理） |
| 飞书 | 花名册课程字段、配置表 grading_period（自动更新） | 所有 Table ID、App Token、作业库（保留历史）、课程名映射 |
| GitHub Secrets | `SCHOOLOGY_SECTION_NIDS`、`CURRENT_SEMESTER`、`ACTIVE_SEMESTERS` | 所有 Feishu 相关 Secret、`SCHOOLOGY_GRADING_PERIOD`（现为备用） |
| 代码 | 无需改代码 | — |

---

## 学期标签机制

作业库有 `学期` 文本列，两个 GitHub Secrets 控制哪些作业"算数"：

| Secret | 作用 | 示例值 |
|---|---|---|
| `CURRENT_SEMESTER` | 新自动建档的作业会打上这个标签 | `2026-S4` |
| `ACTIVE_SEMESTERS` | 逗号分隔，只有这些学期的作业参与缺交考核 | `2026-S3,2026-S4`（补交宽限期）/ `2026-S4`（正常期） |

**无标签的旧作业**（迁移前遗留）：始终参与考核，和以前行为一致。

**宽限期举例**：
- S3 结束，S4 开始
- `ACTIVE_SEMESTERS=2026-S3,2026-S4` → 两学期缺交都显示
- S3 补交期结束后改为 `ACTIVE_SEMESTERS=2026-S4` → S3 缺交自动消失，无需改飞书

---

## 阶段一：旧学期最后一天 — 备档（10 min）

### 1. 飞书表格备档
在飞书多维表格中，对以下表格做一次「导出 CSV」（或复制到归档 Base）：
- **提交记录表**（`FEISHU_TABLE_ID`）
- **缺交表**（`FEISHU_MISSING_TABLE_ID`）
- **汇总表**（`FEISHU_SUMMARY_TABLE_ID`）

### 2. 记录旧学期 Section NID 备用
把当前 `SCHOOLOGY_SECTION_NIDS` 的内容存到本地备份。

---

## 阶段二：新学期第一天 — 切换（20–25 min）

按以下顺序执行，**顺序不能乱**。

### Step 1｜获取新 Section NID（5 min）

在 Schoology 中，进入每门新学期课程 → 地址栏里有 section NID：
```
https://queenscanada.schoology.com/course/8173239667/materials
                                          ↑ 这是 Section NID
```

整理成 JSON 格式（课程名会通过飞书配置表里的 course_mapping 自动映射为课程代码）：
```json
{"8173239667": "Grade 12 Physics", "8173239668": "Grade 12 Advanced Functions"}
```

> 如果 S4 有新课程名，先在飞书**系统配置表**里更新 `course_mapping` 的配置值，无需改代码。

### Step 2｜更新 GitHub Secrets（5 min）

进入仓库 → Settings → Secrets and variables → Actions，逐一更新：

| Secret 名 | 切换时设为 | 说明 |
|---|---|---|
| `SCHOOLOGY_SECTION_NIDS` | Step 1 整理的 JSON | 新学期各课 Section NID |
| `CURRENT_SEMESTER` | `2026-S4` | 新建档作业的学期标签 |
| `ACTIVE_SEMESTERS` | `2026-S3,2026-S4` | 宽限期：两个学期都参与考核 |

> **`SCHOOLOGY_GRADING_PERIOD` 不再需要手动更新**。Pipeline 跑完 Gradebook 步骤后，
> 会自动从 Schoology API 解析真实日期并写入飞书配置表，仪表盘自动更新。
> 该 Secret 仅作备用（飞书配置表读不到时才用）。

> **宽限期结束后**，单独把 `ACTIVE_SEMESTERS` 改为 `2026-S4`，S3 的缺交自动从所有仪表盘消失。

### Step 3｜为旧学期作业打上标签（5 min，飞书操作）

在飞书 **作业库表** 中：
1. 筛选条件：`学期` 列 **为空** 且 `作业性质` ≠ `🚫 忽略`
2. 全选这些行 → 批量将 `学期` 字段设为 `2026-S3`

> 这是**一次性迁移操作**，之后新作业由 pipeline 自动打标签，无需再做。
> 如果作业库还没有 `学期` 列，先手动建一列（文本类型，列名 `学期`）。

### Step 4｜更新飞书花名册（5 min）

在飞书 **花名册表** 中，逐个学生更新 `所属课程` 字段为新学期实际选课列表。

> 这一步控制哪些课的作业算该学生的"应交"，必须更新。

### Step 5｜清空提交记录表（可选，2 min）

- **清空的好处**：新学期完成度从零开始，不会因旧提交虚高
- **不清空也行**：缺交列表仍然正确（由作业库学期标签控制），只是完成度数字会偏高

### Step 6｜手动触发 Gradebook pipeline（3 min）

GitHub Actions → **Schoology Master Pipeline** → Run workflow（或等待自动触发）。

这会自动：
- 拉取新学期 Gradebook 数据写入飞书
- 从 Schoology API 解析真实学期日期，**写入飞书系统配置表**（`grading_period` 键）
- 仪表盘学期进度条、倒计时、热力图范围自动更新为新学期日期

### Step 7｜触发主流水线验证（3 min）

GitHub Actions → **Schoology Master Pipeline** → Run workflow。

检查日志关键行：
```
>>> 学期过滤 (2026-S3, 2026-S4): 120 → 80 条作业参与考核   ← 过滤生效
>>> 学期参数 [飞书配置表]: Session 4  2026-03-03 → 2026-04-30  ← 日期正确
>>> 缺交匹配统计: rows=X, links_matched=X                    ← 缺交数据正常
  [config] 更新 'grading_period'                             ← 配置表正确更新（非新建）
```

### Step 8｜浏览器验证（2 min）

打开任意一个学生仪表盘确认：
- [ ] 学期进度条：第 1 周 / 共 N 周
- [ ] 倒计时：距学期结束还有 X 天
- [ ] 热力图：从新学期开始日期起显示
- [ ] 缺交列表：只有新学期（和宽限期内旧学期）作业

---

## 阶段三：宽限期结束 — 关闭旧学期缺交（1 min）

S3 补交窗口关闭后，只需在 GitHub Secrets 中：

```
ACTIVE_SEMESTERS = 2026-S4
```

下次主流水线自动运行后，所有学生仪表盘上的 S3 缺交条目自动消失，**不需要改飞书任何记录**。

---

## 阶段四：新学期中 — 日常维护

| 触发条件 | 操作 |
|---|---|
| Schoology 发现新课程（仪表盘显示原始英文课程名而非代码） | 在飞书**系统配置表**里修改 `course_mapping` 配置值，无需改代码 |
| `SCHOOLOGY_COOKIES` 过期（pipeline 通知 Cookie 已失效） | 从浏览器重新导出 cookies，更新 GitHub Secret `SCHOOLOGY_COOKIES` |
| 宽限期结束，旧学期缺交应消失 | 更新 `ACTIVE_SEMESTERS` 去掉旧学期标签（见阶段三） |
| 需要诊断某学生数据 | 本地运行 `python pipeline/debug.py student <姓名>` |
| 飞书系统配置表出现重复的 grading_period 行 | 手动删除多余行，只保留一条；pipeline 下次运行后自动更新 |

---

## 附录 A：GitHub Secrets 完整一览

| Secret | 每学期是否变 | 说明 |
|---|---|---|
| `FEISHU_APP_ID` | 否 | |
| `FEISHU_APP_SECRET` | 否 | |
| `FEISHU_APP_TOKEN` | 否 | |
| `FEISHU_TABLE_ID` | 否 | 提交记录表 |
| `FEISHU_ROSTER_TABLE_ID` | 否 | 花名册 |
| `FEISHU_LIB_TABLE_ID` | 否 | 作业库 |
| `FEISHU_MISSING_TABLE_ID` | 否 | 缺交表 |
| `FEISHU_SUMMARY_TABLE_ID` | 否 | 汇总表 |
| `FEISHU_GRADEBOOK_TABLE_ID` | 否 | Gradebook 表 |
| `FEISHU_CONFIG_TABLE_ID` | 否 | 系统配置表（course_mapping / grading_period） |
| `FEISHU_WEBHOOK_URL` | 否 | 飞书群通知机器人 |
| `SCHOOLOGY_COOKIES` | 到期更换 | Selenium 格式 JSON 数组 |
| `SCHOOLOGY_SECTION_NIDS` | **每学期** | `{"nid":"课程英文名", ...}` |
| `SCHOOLOGY_GRADING_PERIOD` | **可选备用** | Pipeline 自动更新飞书配置表，此 Secret 仅在飞书读取失败时作 fallback |
| `CURRENT_SEMESTER` | **每学期** | 新建档作业的学期标签，如 `2026-S4` |
| `ACTIVE_SEMESTERS` | **每学期** + 宽限期结束时再改一次 | 参与考核的学期，如 `2026-S3,2026-S4` 或 `2026-S4` |

---

## 附录 B：已完成优化 / 剩余优化机会

### ✅ 已完成

**课程名映射外置（原 O4）**
- 课程名→代码映射已迁移到飞书**系统配置表**（`course_mapping` 键）
- 新增/修改课程映射：直接在飞书修改配置值，无需提交代码
- 本地初始化：`python pipeline/debug.py init-config`

**Cookie 健康检查（原 O5）**
- `scrape_gradebook.py` 每次运行前自动验证 Cookie 有效性
- Cookie 失效时立即终止并通过飞书 Webhook 发送告警通知

**grading_period 自动同步**
- Pipeline 从 Schoology API 解析学期日期，自动写入飞书配置表
- 仪表盘进度条/倒计时/热力图无需人工干预自动更新

### 🟠 中等价值（待做）

**花名册课程字段自动更新**
- 现状：每学期手动在飞书逐个改学生选课列表
- 方案：Schoology `/v1/sections/{nid}/enrollments` API 拉取名单自动对比更新
- 注意：需要 Schoology REST API Token（非 cookies）

**Section NID 自动发现**
- 现状：手动从浏览器地址栏复制 NID
- 方案：Schoology `/v1/users/{uid}/sections` API 列出所有 section，按学期过滤
- 注意：同上，需要 API Token
