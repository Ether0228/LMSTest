# 学期切换 SOP

> 每学期约需 20–30 分钟（实现学期标签后，旧版的"批量改忽略"步骤已取消）。

---

## 前置：明确哪些东西会变

| 类别 | 每学期变 | 每学期不变 |
|---|---|---|
| Schoology | Section NID（每门课每学期不同）、作业列表、学期日期 | App Token、Cookies（到期独立处理） |
| 飞书 | 花名册课程字段 | 所有 Table ID、App Token、作业库（保留历史） |
| GitHub Secrets | `SCHOOLOGY_SECTION_NIDS`、`SCHOOLOGY_GRADING_PERIOD`、`CURRENT_SEMESTER`、`ACTIVE_SEMESTERS` | 所有 Feishu 相关 Secret |
| 代码 | `fill_course_info.py` 内的 `COURSE_MAPPING`（如有新课程） | 其余脚本不动 |

---

## 学期标签机制（O1 实现后的新逻辑）

作业库新增 `学期` 文本列，两个 GitHub Secrets 控制哪些作业"算数"：

| Secret | 作用 | 示例值 |
|---|---|---|
| `CURRENT_SEMESTER` | 新自动建档的作业会打上这个标签 | `2026-S4` |
| `ACTIVE_SEMESTERS` | 逗号分隔，只有这些学期的作业会参与缺交考核 | `2026-S3,2026-S4`（补交宽限期） / `2026-S4`（正常期） |

**无标签的旧作业**（迁移前遗留）：始终参与考核，和以前行为一致。迁移方法见附录。

**宽限期场景举例**（你们的情况）：
- 2026-S3 结束，2026-S4 开始
- 期间 `ACTIVE_SEMESTERS=2026-S3,2026-S4` → 两个学期的缺交都显示
- S3 补交期结束后改为 `ACTIVE_SEMESTERS=2026-S4` → S3 缺交自动消失，无需改任何飞书记录

---

## 阶段一：旧学期最后一天 — 备档（10 min）

### 1. 飞书表格备档
在飞书多维表格中，对以下表格做一次「导出 CSV」（或复制到归档 Base）：
- **提交记录表**（`FEISHU_TABLE_ID`）
- **缺交表**（`FEISHU_MISSING_TABLE_ID`）
- **汇总表**（`FEISHU_SUMMARY_TABLE_ID`）

### 2. 记录旧学期 Secrets 备用
- 旧 `SCHOOLOGY_SECTION_NIDS`
- 旧 `SCHOOLOGY_GRADING_PERIOD`

---

## 阶段二：新学期第一天 — 切换（20–25 min）

按以下顺序执行，**顺序不能乱**。

### Step 1｜获取新 Section NID（5 min）

在 Schoology 中，进入每门新学期课程 → 地址栏里有 section NID：
```
https://queenscanada.schoology.com/course/8173239667/materials
                                          ↑ 这是 Section NID
```

整理成 JSON 格式：
```json
{"8173239667": "MCR3U", "8173239668": "MHF4U"}
```

### Step 2｜更新 GitHub Secrets（5 min）

进入仓库 → Settings → Secrets and variables → Actions，逐一更新：

| Secret 名 | 切换时设为 | 说明 |
|---|---|---|
| `SCHOOLOGY_SECTION_NIDS` | Step 1 整理的 JSON | 新学期各课 Section NID |
| `SCHOOLOGY_GRADING_PERIOD` | `{"start_date":"2026-03-03","end_date":"2026-04-30","session":"Session 4"}` | 新学期起止日期（手填先用着，gradebook 跑完后自动校准） |
| `CURRENT_SEMESTER` | `2026-S4` | 新建档作业的学期标签 |
| `ACTIVE_SEMESTERS` | `2026-S3,2026-S4` | 宽限期：两个学期都参与考核 |

> **宽限期结束后**（S3 补交彻底关闭），单独把 `ACTIVE_SEMESTERS` 改为 `2026-S4`，S3 的缺交自动从所有学生仪表盘消失。

### Step 3｜为旧学期作业打上标签（5 min，飞书操作）

在飞书 **作业库表** 中：
1. 筛选条件：`学期` 列 **为空** 且 `作业性质` ≠ `🚫 忽略`
2. 全选这些行 → 批量将 `学期` 字段设为旧学期标签（如 `2026-S3`）

这是**一次性迁移操作**，之后新作业会自动被 pipeline 打标签，无需再做。

> 如果飞书 作业库 还没有 `学期` 列，先手动建一列（文本类型，列名 `学期`）。

### Step 4｜更新飞书花名册（5 min）

在飞书 **花名册表** 中，逐个学生更新 `所属课程` 字段为新学期实际选课列表。

> 这一步控制哪些课的作业算该学生的"应交"，必须更新。

### Step 5｜清空提交记录表（可选，2 min）

- **清空的好处**：新学期完成度从零开始，不会因旧提交虚高
- **不清空也行**：缺交列表仍然正确（由作业库学期标签控制）；只是完成度数字会偏高

建议清空，但如果想保留历史记录可以跳过。

### Step 6｜触发 Gradebook 流水线（手动，3 min）

GitHub Actions → **Scrape Gradebook** → Run workflow。

这会自动：
- 拉取新学期成绩册写入飞书（旧学期条目自动删除）
- 从 Schoology API 解析真实学期日期，更新 `SCHOOLOGY_GRADING_PERIOD`
- 把 Gradebook 中出现的新学期作业在作业库里标记为 `🔥 极其重要` 并打上 `CURRENT_SEMESTER` 标签

### Step 7｜触发主流水线验证（手动，3 min）

GitHub Actions → **Schoology Master Pipeline** → Run workflow。

检查日志关键行：
```
>>> 学期过滤 (2026-S3, 2026-S4): 120 → 80 条作业参与考核   ← 说明过滤生效
>>> 学期参数 [环境变量]: Session 4  2026-03-03 → 2026-04-30  ← 日期正确
>>> 缺交匹配统计: rows=X, links_matched=X                    ← 缺交数据正常
```

### Step 8｜浏览器验证（2 min）

打开任意一个学生仪表盘确认：
- [ ] 学期进度条：第 1 周 / 共 N 周
- [ ] 缺交列表：只有新学期（和宽限期内旧学期）作业
- [ ] 旧学期遗留缺交：正常显示（宽限期内）

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
| Schoology 发现新课程（fill_course_info 返回原名而非课程代码） | 在 `fill_course_info.py` 的 `COURSE_MAPPING` 中添加映射，提交代码 |
| `SCHOOLOGY_COOKIES` 过期（爬虫返回 "login" 页面） | 从浏览器重新导出 cookies，更新 GitHub Secret |
| 宽限期结束，旧学期缺交应消失 | 更新 `ACTIVE_SEMESTERS` 去掉旧学期标签（见阶段三） |
| Gradebook 成绩更新后想刷新仪表盘 | 手动触发 **Scrape Gradebook** + **Schoology Master Pipeline** |

---

## 附录 A：GitHub Secrets 完整一览

| Secret                      | 每学期是否变                    | 说明                                                                          |
| --------------------------- | ------------------------- | --------------------------------------------------------------------------- |
| `FEISHU_APP_ID`             | 否                         |                                                                             |
| `FEISHU_APP_SECRET`         | 否                         |                                                                             |
| `FEISHU_APP_TOKEN`          | 否                         |                                                                             |
| `FEISHU_TABLE_ID`           | 否                         | 提交记录表                                                                       |
| `FEISHU_ROSTER_TABLE_ID`    | 否                         | 花名册                                                                         |
| `FEISHU_LIB_TABLE_ID`       | 否                         | 作业库                                                                         |
| `FEISHU_MISSING_TABLE_ID`   | 否                         | 缺交表                                                                         |
| `FEISHU_SUMMARY_TABLE_ID`   | 否                         | 汇总表                                                                         |
| `FEISHU_GRADEBOOK_TABLE_ID` | 否                         | Gradebook 表                                                                 |
| `SCHOOLOGY_COOKIES`         | 到期更换                      | Selenium 格式 JSON 数组                                                         |
| `SCHOOLOGY_SECTION_NIDS`    | **每学期**                   | `{"nid":"课程代码", ...}`                                                       |
| `SCHOOLOGY_GRADING_PERIOD`  | **每学期**（gradebook 跑后自动校准） | `{"start_date":"YYYY-MM-DD","end_date":"YYYY-MM-DD","session":"Session N"}` |
| `CURRENT_SEMESTER`          | **每学期**                   | 新建档作业的学期标签，如 `2026-S4`                                                      |
| `ACTIVE_SEMESTERS`          | **每学期** + 宽限期结束时再改一次      | 参与考核的学期，如 `2026-S3,2026-S4` 或 `2026-S4`                                     |

---

## 附录 B：剩余优化机会

### 🟠 中等价值

**O2：花名册课程字段自动更新**
- 现状：每学期手动在飞书逐个改学生选课列表
- 方案：Schoology `/v1/sections/{nid}/enrollments` API 拉取名单自动对比更新
- 注意：需要 Schoology REST API Token（非 cookies）

**O3：Section NID 自动发现**
- 现状：手动从浏览器地址栏复制 NID
- 方案：Schoology `/v1/users/{uid}/sections` API 列出所有 section，按学期过滤
- 注意：同上，需要 API Token

**O4：`fill_course_info.py` 的 `COURSE_MAPPING` 外置**
- 现状：课程名→代码映射硬编码在文件里，增删课程需提交代码
- 方案：移到 GitHub Secret `COURSE_MAPPING_JSON`，无需改代码
- 成本：约 1 小时

### 🟡 低优先级

**O5：Cookies 健康检查**
- 在 `main_pipeline.yml` 最前面加 smoke test，cookies 过期时发通知

**O6：一键学期切换脚本**
- 把花名册更新整合成脚本，接受新学期参数自动执行
