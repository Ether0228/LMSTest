# Pipeline 技术文档

> 给 AI 看的上下文文档。描述每个脚本做什么、数据如何流动、哪些已实现、哪些还缺。

---

## 项目背景

加拿大私立高中中国学生的学习仪表盘「通关指南」。数据来源是 Schoology LMS，经 Python pipeline 同步到飞书多维表格，Node.js 服务器聚合后提供 JSON API，Vanilla JS 前端渲染。

**核心业务逻辑：**
- Schoology 有两类作业：**AOL**（算分作业，Quiz/Test/Assignment，在 Gradebook 里）和**日常 Homework**（只在 Notification 提交记录里）
- 仪表盘要展示：每门课完成度、AOL 成绩、缺交列表、近期提交、DDL 日历
- 每学期学生选课为约 1-2 门课，一年 6 个学期，存在两学期重叠宽限期（2 周）

---

## 学校数据结构（必须理解）

### Schoology 侧

| 数据源 | 内容 | 访问方式 |
|---|---|---|
| Notification 页面 | 所有提交记录（含日常 Homework + AOL） | Selenium 爬取 `/home/notifications` |
| Gradebook API | AOL 作业列表、学生名单、得分、分类权重、课程总分% | requests `/iapi/grades/grader_header_data/{NID}` |
| gradesetup 页面 | 分类权重（AOL/AoF 各占多少 %）| requests `/course/{NID}/gradesetup` |
| 作业页面 Breadcrumb | 作业所属课程名 + Section ID（含学期信息） | Selenium 爬 `/assignment/{id}` 等 |

**Section ID 解码规则：**
课程标题格式 `"ESL Level 5: Section 2526S4N"`
- `2526` = 2025-26 学年
- `S4` = 第 4 学期
- 映射到学期标识 → `"2026-S4"`（用学年结束年 + 学期号）

### 飞书多维表格（7 张表）

| 表名 | Secret 变量 | 写入方 | 内容 |
|---|---|---|---|
| 提交记录表 | `FEISHU_TABLE_ID` | scraper_cloud_feishu | 学生 × 提交记录，唯一ID去重 |
| 花名册 | `FEISHU_ROSTER_TABLE_ID` | 手动 | 学生元数据：学分、OSSLT、公告、**所属课程（手动维护）** |
| 作业库 | `FEISHU_LIB_TABLE_ID` | fill_course_info + scrape_gradebook | 作业元数据：名称、链接、课程代码、学期、性质 |
| 缺交表 | `FEISHU_MISSING_TABLE_ID` | check_missing_sync | 学生 × 缺交作业，含手动确认字段 |
| Gradebook 表 | `FEISHU_GRADEBOOK_TABLE_ID` | scrape_gradebook | 学生 × AOL作业，含得分/权重/总分% |
| 汇总表 | `FEISHU_SUMMARY_TABLE_ID` | build_student_summary | 预聚合 JSON（备份，主路径是 PostgreSQL） |
| 系统配置表 | `FEISHU_CONFIG_TABLE_ID` | scrape_gradebook（grading_period）；手动（course_mapping） | 两个 key 见下 |

**系统配置表的两个条目：**
```
配置键: course_mapping  → 值: {"esl level 5": "ESLEO", "grade 12 data management": "MDM4U", ...}
配置键: grading_period  → 值: {"session":"Session 4","start_date":"2026-03-02","end_date":"2026-04-24"}
```
`grading_period` 由 `scrape_gradebook.py` 自动写入，`course_mapping` 手动维护（新课时加一条）。

### 学期日历文件

`config/academic_calendar.json`（已存在于 repo）：
```json
{
  "2026-S1": {"start": "2025-09-04", "end": "2025-10-29"},
  "2026-S2": {"start": "2025-11-03", "end": "2025-12-23"},
  "2026-S3": {"start": "2026-01-05", "end": "2026-02-28"},
  "2026-S4": {"start": "2026-03-02", "end": "2026-04-24"},
  "2026-S5": {"start": "2026-05-06", "end": "2026-06-30"},
  "2026-S6": {"start": "2026-07-06", "end": "2026-08-27"}
}
```
pipeline 从这里自动推断当前学期和活跃学期（宽限期 14 天），无需手动设置 `ACTIVE_SEMESTERS` 或 `CURRENT_SEMESTER`。

---

## 五个 Python 脚本

### 1. `scraper_cloud_feishu.py` — Notification 爬虫

**触发：** GitHub Actions 每 30 分钟，Selenium + Cookie 登录

**做什么：**
1. 访问 Schoology `/home/notifications`
2. 筛选含 "submitted" / "resubmitted" 的通知
3. 解析：学生姓名、作业名、提交状态、时间、作业链接
4. 去重：MD5(原始文本) 作为唯一ID
5. **自动建档**：作业链接不在作业库时，创建新条目（含作业名、链接、"✅ 必交"；此时无课程/学期）
6. 写入飞书提交记录表（关联学生 record_id + 关联作业 record_id）

**输入：** Schoology Notification 页面
**输出：** 飞书提交记录表（新增行）；飞书作业库（新建档条目，无课程/学期）
**关键参数：** `TARGET_DATE`（回溯截止，默认昨天）、`MAX_PAGES`（翻页数，默认 2）

**已知限制：**
- 通知里无课程信息，新建档的作业库条目课程/学期为空，需 fill_course_info 补全
- 只抓 submitted/resubmitted，评论等通知过滤掉

---

### 2. `fill_course_info.py` — 作业库课程信息补全

**触发：** scraper_cloud_feishu 之后立即运行（GitHub Actions Step 5）

**做什么：**
1. 拉取作业库所有"所属课程"为空的条目
2. 对每个条目，用 Selenium 打开作业页面
3. 从 Breadcrumb 抓课程标题，如 `"ESL Level 5: Section 2526S4N"`
4. 解析学期：`Section 2526S4N` → `"2026-S4"`
5. 课程名映射（优先读飞书系统配置表，内置兜底）：`"ESL Level 5"` → `"ESLEO"`
6. 回写飞书作业库：`所属课程 = "ESLEO"`，`学期 = "2026-S4"`

**输入：** 飞书作业库（课程为空的条目）+ 飞书系统配置表（course_mapping）
**输出：** 飞书作业库（补全课程代码 + 学期标签）

**关键依赖：**
- `FEISHU_CONFIG_TABLE_ID` — 读取 course_mapping
- `SCHOOLOGY_COOKIES` — Selenium 登录

---

### 3. `scrape_gradebook.py` — Gradebook 爬虫

**触发：** GitHub Actions Step 6.5（在 check_missing 之后，build_summary 之前）

**做什么（每个 Section NID）：**
1. 访问 `/course/{NID}/gradesetup` → 抓分类权重（如 `{"U1 Test (AOL)": 6.0, ...}`）
2. 访问 `/iapi/grades/grader_header_data/{NID}` → 解析：
   - `user_data`：学生名单 + 课程总分%（`overall.numeric`）
   - `grade_item_data`：AOL 作业列表（名称、满分、截止日期）
   - `grades`：每个学生每道作业的得分
   - `grading_period`：学期起止日期
3. 写入飞书 Gradebook 表（upsert，按 Section 范围删除消失的作业行，不跨 Section 删）
4. 写本地 JSON 文件（供 build_student_summary.py 在同一 job 内读取）：
   - `pipeline/grading_period.json`：`{"session":"Session 3","start_date":"2026-01-05","end_date":"2026-02-28"}`
   - `pipeline/category_weights.json`：`{"NID": {"分类名": 权重}}`
   - `pipeline/section_semesters.json`：`{"NID": {"session":"Session 3","start_date":"...","end_date":"..."}}`
5. 可选：更新作业库（补全"🔥 极其重要"和截止日期）
6. 写飞书系统配置表 `grading_period` key

**输入：** `SCHOOLOGY_SECTION_NIDS` = `{"NID": "Course Name: Section 2526S4N", ...}`
**输出：** 飞书 Gradebook 表 + 三个本地 JSON 文件 + 飞书系统配置表

**SCHOOLOGY_SECTION_NIDS 格式（重要）：**
```json
{"8173239670": "Grade 12 Canadian and World Issues: Section 2526S3N"}
```
- NID 必须是纯数字（非数字会被跳过并报错）
- 课程名必须包含 `Section XXXXN` 后缀（用于学期推断）
- 每学期更新此 Secret，两学期重叠期同时填两个学期的所有 NID

**课程名 → 课程代码映射优先级：**
飞书系统配置表 `course_mapping` > 脚本内 `DEFAULT_COURSE_MAPPING`

---

### 4. `check_missing_sync.py` — 缺交核验

**触发：** GitHub Actions Step 6（在 fill_course_info 之后）

**做什么：**
1. 拉取：花名册、作业库、提交记录表、当前缺交表
2. 学期过滤作业库（优先读环境变量 `ACTIVE_SEMESTERS`，未设置则从 `academic_calendar.json` 自动推断）
3. 建立"已提交"索引：`学生姓名 + 作业链接` → submitted_keys
4. 遍历：作业库每条作业 × 花名册每个学生（判断学生是否选了这门课）
5. 交叉比对 → 逻辑缺交集合（应交但未交 且 老师未手动确认）
6. 同步飞书缺交表：新增缺交行、删除已销账行、更新"最后核验时间"

**输入：** 飞书花名册 + 作业库 + 提交记录表 + 缺交表
**输出：** 飞书缺交表（增删改）

**关键限制（已知，待解决）：**
判断"学生选了哪门课"用的是花名册的"所属课程"字段——这是**手动维护**的。
学期换了需要手动更新花名册每个学生的选课列表。
（计划：改为从 Gradebook user_data 自动推断，写 section_enrollment.json）

---

### 5. `build_student_summary.py` — 数据聚合

**触发：** GitHub Actions Step 7（always，即使前面步骤失败也跑）

**做什么：**
1. 读取 `config/academic_calendar.json` → 自动推断 active_semesters 和 current_semester
2. 拉取飞书五张表：花名册、提交记录、作业库（已按 active_semesters 过滤）、缺交表、Gradebook
3. 读本地 JSON：`grading_period.json`、`category_weights.json`、`section_semesters.json`
4. 按 (course_code, semester) 分组统计每个学生的：
   - 每门课提交数、缺交数、完成度（分子/分母均按学期隔离，不混用）
   - AOL 详情：得分、满分、分类权重
   - 课程总分%（来自 Gradebook `overall.numeric`）
5. 生成其他字段：DDL 日历、关注列表（缺交+低分）、推荐列表
6. 写入 PostgreSQL `student_summary(tenant, student_name, data jsonb, updated_at)`
7. 备份写飞书汇总表

**输入：** 飞书 5 张表 + 本地 3 个 JSON + academic_calendar.json
**输出：** PostgreSQL（主路径）+ 飞书汇总表（备份）

**关键修复（已做）：**
统计分母 = 该学期该课程的作业数（不再是跨学期合计），两学期重叠期数据不混淆。

---

## 数据完整流向图

```
Schoology
  │
  ├─ Notification 页面
  │       ↓
  │  scraper_cloud_feishu.py
  │       ├─ 写→ 飞书提交记录表（学生 × 提交）
  │       └─ 写→ 飞书作业库（新建档，课程/学期为空）
  │
  ├─ 作业页面 Breadcrumb
  │       ↓
  │  fill_course_info.py
  │       └─ 写→ 飞书作业库（补全 所属课程 + 学期）
  │
  └─ Gradebook API + gradesetup
          ↓
     scrape_gradebook.py
          ├─ 写→ 飞书 Gradebook 表（学生 × AOL作业 × 得分）
          ├─ 写→ pipeline/grading_period.json
          ├─ 写→ pipeline/category_weights.json
          ├─ 写→ pipeline/section_semesters.json
          └─ 写→ 飞书系统配置表（grading_period key）

飞书提交记录 + 飞书花名册 + 飞书作业库
          ↓
  check_missing_sync.py
          └─ 写→ 飞书缺交表

飞书5张表 + 本地JSON + academic_calendar.json
          ↓
  build_student_summary.py
          ├─ 写→ PostgreSQL（主缓存）
          └─ 写→ 飞书汇总表（备份）

PostgreSQL
    ↓
server.js  GET /api/dashboard?t={tenant}&student={name}
    ↓
app.js 前端渲染
```

---

## GitHub Actions Pipeline

文件：`.github/workflows/main_pipeline.yml`
触发：每 30 分钟 + 手动

```
Step 4  scraper_cloud_feishu   提交记录 + 自动建档
Step 5  fill_course_info       补全课程/学期（if success）
Step 6  check_missing_sync     缺交同步（if success）
Step 6.5 scrape_gradebook      Gradebook + 本地JSON（continue-on-error）
Step 7  build_student_summary  聚合 → PostgreSQL（always）
Step 8  飞书通知               仅失败时
```

---

## GitHub Secrets 完整清单

| Secret | 是否必须 | 说明 |
|---|---|---|
| `FEISHU_APP_ID` | 必须 | |
| `FEISHU_APP_SECRET` | 必须 | |
| `FEISHU_APP_TOKEN` | 必须 | 多维表格 App Token |
| `FEISHU_TABLE_ID` | 必须 | 提交记录表 |
| `FEISHU_ROSTER_TABLE_ID` | 必须 | 花名册 |
| `FEISHU_LIB_TABLE_ID` | 必须 | 作业库 |
| `FEISHU_MISSING_TABLE_ID` | 必须 | 缺交表 |
| `FEISHU_GRADEBOOK_TABLE_ID` | 必须 | Gradebook 表 |
| `FEISHU_SUMMARY_TABLE_ID` | 必须 | 汇总表（备份用）|
| `FEISHU_CONFIG_TABLE_ID` | 必须 | 系统配置表（course_mapping + grading_period）|
| `FEISHU_WEBHOOK_URL` | 可选 | 飞书群机器人告警 |
| `SCHOOLOGY_COOKIES` | 必须 | Selenium 格式 JSON 数组，Cookie 过期需更换 |
| `SCHOOLOGY_SECTION_NIDS` | 必须 | `{"NID": "Course: Section XXXXN"}` 每学期更新 |
| `DATABASE_URL` | 必须 | PostgreSQL 连接串（Render 托管）|
| `CACHE_TENANT_KEY` | 必须 | 租户标识如 `"queens"` |
| ~~`CURRENT_SEMESTER`~~ | **已删除** | 从日历自动推断 |
| ~~`ACTIVE_SEMESTERS`~~ | **已删除** | 从日历自动推断 |
| ~~`SCHOOLOGY_GRADING_PERIOD`~~ | **已删除** | 从日历/Gradebook自动推断 |

**学期切换时只需改：**
1. `SCHOOLOGY_SECTION_NIDS` — 新学期的课程 NID + 完整标题
2. `SCHOOLOGY_COOKIES` — Cookie 过期时
3. `config/academic_calendar.json` — 一年只需维护一次

---

## 前端 API 返回结构

`GET /api/dashboard?t={tenant}&student={name}` 返回 JSON，核心字段：

```
student           { name, credits_earned, credits_remaining }
semester          { start_date, end_date, total_weeks, current_week }
course_progress[] { course, submittedCount, missingCount, completion,
                    current_grade, aol_details[], isCurrentSemester, semester, sectionNid }
missing_items[]   { course, assignmentName, assignmentLink, nature }
attention_items[] { type(missing/low_score), course, assignmentName, score, maxScore }
recent_submitted[]{ course, assignmentName, submittedAt, status }
upcoming_deadlines[]{ date_ms, course, name, category, is_aol, weight }
alerts[]          { type(urgent/warn/ok/info), title, body }
recommendations[] { title, anchorText }
```

详见 `FRONTEND_DATA_SCHEMA.md`（项目根目录）。

---

## 已实现 vs 未实现

### 已实现 ✅

- 四个 pipeline 脚本全部联通，每 30 分钟自动运行
- Section ID 解析（`2526S4N` → `"2026-S4"`）
- 全年学期日历（`academic_calendar.json`），自动推断当前学期/活跃学期
- Gradebook 按 Section 范围 upsert（换 NID 不会删掉其他学期历史数据）
- 多学期数据隔离（统计分母按学期隔离，不跨学期合计）
- AOL 分类权重大小写不敏感匹配
- NID 格式校验（非数字时报错跳过，提示 JSON 写反）
- 429 自动重试（30/60/90s 退避）
- PostgreSQL 缓存层（主读取路径，< 10ms）
- Admin 总览页面（`/admin.html`）
- Cookie 过期检测 + 飞书告警

### 未实现 / 已知缺口 ❌

| 缺口 | 影响 | 建议方案 |
|---|---|---|
| 学生选课仍靠手动维护花名册"所属课程"字段 | 每学期换课需手动改飞书 | scrape_gradebook 写 `section_enrollment.json`，check_missing 和 build_summary 从此文件读 |
| server.js 有三条读取路径（磁盘/飞书汇总表/PostgreSQL）| 代码冗余，约 776 行 | 只保留 PostgreSQL + 飞书降级，目标 ~300 行 |
| 前端同一课程两学期显示两张同名卡片无区分 | UX 混乱 | app.js 渲染时加学期标签（`isCurrentSemester` + `semester` 字段已在数据里）|
| fill_course_info 每次跑 Selenium（慢）| 每 30 分钟都跑 | 可改为只在有新建档时触发，或加 `continue-on-error: true` |
