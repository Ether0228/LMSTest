# 通关指南 · 前端数据手册

> **用途**：在新对话窗口中粘贴本文件，帮助 AI 了解仪表盘所有可用数据字段，以便进行前端设计。

---

## 项目简介

「通关指南」是一个面向加拿大私立高中中国学生的学习仪表盘。
学生通过 Schoology LMS 提交作业，数据每 30 分钟自动同步到 Feishu 数据库，再由 Node.js 服务器聚合后以 JSON API 提供给前端。前端为**纯 Vanilla JS + HTML + CSS，无框架、无构建步骤**。

**技术栈**：HTML5 / CSS3 / ES2022 Vanilla JS / Node.js（零 npm 依赖）/ PostgreSQL（读取缓存）/ Feishu Bitable

---

## API 接口

```
GET /api/dashboard?t={tenant}&student={studentName}
```

返回 JSON，经 `normalizeApiResponse()` 适配后供前端使用。
以下描述的是**适配后**前端实际工作的数据结构（`renderAll(data)` 接收的对象）。

---

## 完整数据结构

### 顶层字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `student` | Object | 学生基本信息 |
| `semester` | Object | 学期进度 |
| `semLabel` | String | 学期标签，如 `"2025-2026学年 第3学期"` |
| `stage` | String | 学习阶段标签，如 `"在读"` / `"申请备战期"` |
| `course_progress` | Array | 每门课的进度与成绩（核心数据） |
| `missing_items` | Array | 所有缺交作业 |
| `attention_items` | Array | 需要关注的项目（缺交 + 低分合并） |
| `recent_submitted` | Array | 近期提交记录（最多 20 条） |
| `recommendations` | Array | 情境化建议（链接到通关指南） |
| `upcoming_deadlines` | Array | 未来 DDL 日历（最多 30 条） |
| `alerts` | Array | 通知/提醒（自动生成 + 老师自定义） |
| `missing_total` | Number | 缺交总数 |
| `submitted_total` | Number | 已提交总数 |
| `combo` | Object | 连续提交记录（热力图原始数据，现已替换为 DDL 日历） |

---

### `student` 对象

```json
{
  "name": "张三",
  "pinyin": "Zhang San",
  "grade": null,
  "credits_earned": 18,
  "credits_remaining": 12
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | String | 学生姓名（中文） |
| `credits_earned` | Number \| null | 已获得学分数 |
| `credits_remaining` | Number \| null | 距毕业所需剩余学分（= target - earned） |

---

### `semester` 对象

```json
{
  "start_date": "2026-01-05",
  "end_date": "2026-02-28",
  "total_weeks": 8,
  "current_week": 5
}
```

---

### `course_progress[]` ——最重要的数据

每个学生每学期通常选修 **1–2 门课**。

```json
{
  "course": "MDM4U",
  "submittedCount": 12,
  "missingCount": 2,
  "completion": 85.7,
  "current_grade": 88.5,
  "grade_updated_at": 1740000000000,
  "aolSubmitted": 3,
  "aolMissing": 1,
  "aol_details": [
    {
      "name": "Unit Test 2",
      "score": 88,
      "max": 100,
      "category": "Assessment of Learning",
      "weight": 40.0
    },
    {
      "name": "Midterm Exam",
      "score": 76,
      "max": 100,
      "category": "Assessment of Learning",
      "weight": 40.0
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `course` | String | 课程代码，如 `"MDM4U"` / `"SPH3U"` |
| `submittedCount` | Number | 本学期已提交作业数 |
| `missingCount` | Number | 本学期缺交数 |
| `completion` | Number | 完成度百分比（0–100） |
| `current_grade` | Number \| null | 课程总分%（如 88.5）；null 表示暂无成绩 |
| `grade_updated_at` | Number \| null | 成绩更新时间（Unix ms） |
| `aolSubmitted` | Number | 已提交的 AoL 作业数 |
| `aolMissing` | Number | 缺交的 AoL 作业数 |
| `aol_details` | Array | AoL 评分明细（见下） |

**`aol_details` 条目**

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | String | 作业名称 |
| `score` | Number | 得分 |
| `max` | Number | 满分 |
| `category` | String | 分类名（如 `"Assessment of Learning"`） |
| `weight` | Number \| null | 该分类占课程总分的权重%（如 `40.0`）；无数据时为 null |

---

### `missing_items[]`

```json
[
  {
    "course": "MDM4U",
    "assignmentName": "Unit Test 3",
    "assignmentLink": "https://queenscanada.schoology.com/assessment/123"
  }
]
```

---

### `attention_items[]`

缺交和低分作业合并列表，用于「需要关注」区域。

```json
[
  {
    "type": "missing",
    "course": "MDM4U",
    "assignmentName": "Unit Test 3",
    "assignmentLink": "https://queenscanada.schoology.com/assessment/123",
    "nature": "AoL",
    "score": null,
    "maxScore": null
  },
  {
    "type": "lowscore",
    "course": "SPH3U",
    "assignmentName": "Lab Report 2",
    "assignmentLink": "",
    "nature": "AoF",
    "score": 45,
    "maxScore": 100
  }
]
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `type` | String | `"missing"` 或 `"lowscore"` |
| `nature` | String | 作业性质，如 `"AoL"` / `"AoF"` / `"🚫 忽略"` |
| `score` / `maxScore` | Number \| null | 低分条目有值；缺交条目为 null |

---

### `recent_submitted[]`

```json
[
  {
    "course": "MDM4U",
    "assignmentName": "Homework Set 6",
    "submittedAt": "2026-02-20",
    "status": "已提交",
    "assignmentLink": ""
  },
  {
    "course": "SPH3U",
    "assignmentName": "Lab Report 2",
    "submittedAt": "2026-02-19",
    "status": "迟交",
    "assignmentLink": "https://queenscanada.schoology.com/assignment/456"
  }
]
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `submittedAt` | String | 提交日期，格式 `"YYYY-MM-DD"` |
| `status` | String | `"已提交"` / `"迟交"` / `"重新提交"` 等 |

---

### `upcoming_deadlines[]`

DDL 日历数据，用于显示未来截止日期。

```json
[
  {
    "date_ms": 1740614400000,
    "course": "MDM4U",
    "name": "Chapter 5 Test",
    "category": "Assessment of Learning",
    "is_aol": true,
    "weight": 40.0
  },
  {
    "date_ms": 1740700800000,
    "course": "SPH3U",
    "name": "Lab Report 3",
    "category": "Assessment for Learning",
    "is_aol": false
  }
]
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `date_ms` | Number | 截止时间（Unix ms） |
| `course` | String | 课程代码 |
| `name` | String | 作业名 |
| `category` | String | 分类名 |
| `is_aol` | Boolean | 是否为 AoL（算入成绩的正式评估） |
| `weight` | Number（可选） | 该分类权重%，无则字段缺失 |

**分组规则**（前端渲染时使用）：
- 今天：`date_ms` 在今日 00:00–23:59
- 本周：今日之后 7 天内
- 下周：7–14 天后
- 更远：14 天后

---

### `alerts[]`

自动生成 + 老师手动写入的通知。

```json
[
  { "type": "urgent", "title": "⚠️ 缺交预警", "body": "共 12 个作业未提交，请优先处理。" },
  { "type": "warn",   "title": "📉 课程警告", "body": "MDM4U 完成度仅 42%，需重点关注。" },
  { "type": "ok",     "title": "✓ 无缺交",   "body": "本学期所有作业均已提交，继续保持！" },
  { "type": "info",   "title": "📢 通知",     "body": "下周三学校开放日，请准时出席。" }
]
```

`type` 枚举：`"urgent"` / `"warn"` / `"ok"` / `"info"`

---

### `recommendations[]`

情境化建议，链接到通关指南文章。

```json
[
  { "title": "优先处理缺交：复活与翻盘", "anchorText": "4.8 危机关：复活与翻盘" },
  { "title": "用 Rubric 直接提分",       "anchorText": "4.4 作业关：Rubric 狙击手" }
]
```

点击 `anchorText` 跳转到 `/guide.html#{slugified-anchor}`。

---

## 当前页面结构（`index.html`）

```
<header class="topbar">          ← 顶栏：品牌名 + "通关指南全文"按钮

<main class="dashboard">

  <section class="area area--header">   ← 顶部摘要区
    .header__profile                    ← 左：头像 + 姓名 + 学分
    .header__right                      ← 中：日期、学期进度条、DDL日历
      #ddlCalendar                      ← DDL日历（upcoming_deadlines渲染）
    .header__announce                   ← 右：公告栏（alerts渲染）

  <section class="area area--tasks">    ← 今日待处理
    #taskUrgent                         ← 红色：需立即处理（AoL缺交等）
    #taskReminder                       ← 黄色：日常参与提醒
    #taskAllClear                       ← 全部完成状态

  <section class="area area--attention"> ← 需要关注（attention_items）
    前8条常显，更多可展开

  <section class="area" id="area-c">   ← 课程进度卡片（course_progress）
    #courseGrid                         ← 每门课一张卡片

  <section class="area area--guide">   ← 情境化建议（recommendations）
    #guideSnippet
```

---

## 课程卡片（最核心的 UI 组件）

当前渲染逻辑（`app.js renderCourseProgress()`）：

```
┌─────────────────────────────────────────────┐
│ MDM4U          [已提交12 缺交2]  📊 88.5%   │
│ ████████████░░░░  85.7%  完成度              │
│ ▼ AoL 评分详情（点击展开）                   │
│   Unit Test 2    88/100 (88%)  [40%比重]    │
│   Midterm Exam   76/100 (76%)  [40%比重]    │
└─────────────────────────────────────────────┘
```

**已有 CSS class**：
- `.course-card`：卡片容器
- `.course-card__header`：标题行
- `.course-card__grade`：成绩百分比
- `.course-card__bar`：进度条容器
- `.course-card__bar-fill`：进度条填充
- `.aol-section`：AoL 展开区域
- `.aol-pct`：百分比标注（灰色小字）
- `.aol-weight`：权重徽章（蓝色小标签）
- `.detail-item`、`.detail-item--submitted`：明细行

---

## 数据覆盖率说明

| 字段 | 可靠性 | 备注 |
|---|---|---|
| `course_progress.course` | ✅ 始终有 | 课程代码如 MDM4U |
| `course_progress.completion` | ✅ 始终有 | 0–100 |
| `course_progress.current_grade` | ⚠️ 可能 null | 成绩未出时为 null |
| `aol_details` | ⚠️ 可能空 | 有 AoL 评分时才有 |
| `aol_details[].weight` | ⚠️ 可能 null | 分类权重，Schoology gradesetup 抓取 |
| `upcoming_deadlines` | ⚠️ 可能空 | 需 gradebook 中有截止日期字段 |
| `student.credits_earned` | ⚠️ 可能 null | 花名册中填写 |
| `semester.current_week` | ✅ 始终计算 | 由服务端从 grading_period 计算 |
| `alerts` | ✅ 始终有 | 至少有一条自动生成 |
| `attention_items` | ✅ 有缺交/低分时 | 可能为空数组 |

---

## 设计约束

1. **纯 Vanilla JS**，无 React/Vue/Svelte，所有渲染通过 `element.innerHTML = ...` 完成
2. **无构建步骤**，直接修改 `public/app.js` 和 `public/styles.css` 即可生效
3. **CSS 变量**已定义在 `:root`（颜色、间距），新组件优先使用已有变量
4. **移动端优先**：学生主要用手机查看，需保证 360px 宽度可用
5. **中文界面**：所有 UI 文本为简体中文，课程名保留英文代码（MDM4U 等）
6. 每个学生**每学期最多 2 门课**（加拿大私立高中每学期选课制度）

---

## 文件位置

| 文件 | 说明 |
|---|---|
| `interactive_web/public/app.js` | 全部前端逻辑（渲染 + 数据适配） |
| `interactive_web/public/styles.css` | 全部样式 |
| `interactive_web/public/index.html` | 仪表盘页面结构 |
| `interactive_web/public/guide.html` | 通关指南全文页 |
| `interactive_web/server.js` | Node.js 后端，提供 `/api/dashboard` |
| `pipeline/build_student_summary.py` | 数据聚合 pipeline |
