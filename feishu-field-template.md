# 飞书多维表格字段模板

> 此文档记录仪表盘所需的飞书表格字段结构，供后续数据层接入时参考。
> 现有表格（Roster / Submissions / Missing / Library / Summary）保持不变，新增两张表。

---

## 新增表 1：Gradebook（成绩册）

**来源**：Python 爬取 Schoology 每门课的 Gradebook 页面（每课一页，含该课所有学生）
**同步频率**：随现有 GitHub Actions 任务一起跑，每 30 分钟更新

| 字段名               | 类型   | 说明                               | 示例值                |
| ----------------- | ---- | -------------------------------- | ------------------ |
| `course_name`     | 文本   | 课程名称                             | `Biology SBI4U`    |
| `student_name`    | 文本   | 学生姓名（与 Roster 表一致）               | `李明`               |
| `assignment_name` | 文本   | 作业/测验名称                          | `Lab Report 3`     |
| `score`           | 数字   | 学生实际得分                           | `72`               |
| `max_score`       | 数字   | 满分                               | `100`              |
| `score_pct`       | 数字   | 得分百分比（score/max_score × 100）     | `72`               |
| `course_average`  | 数字   | 该学生本课程当前加权均分（从 Gradebook 页面直接读取） | `72.4`             |
| `synced_at`       | 日期时间 | 最后同步时间                           | `2025-10-14 16:00` |

**用途**：
- `assignment_name` 与 Missing 表交叉比对 → 自动识别 AOL（无需教师手动标签）
- `course_average` → 仪表盘课程卡片显示当前成绩
- `score_pct < 60` → 触发低分预警信号

---

## 新增表 2：Gradesetup（权重配置）

**来源**：Python 爬取 Schoology 每门课的 Gradesetup 页面
**同步频率**：每学期开始时爬取一次（权重一般不变），如有变动可手动触发

| 字段名 | 类型 | 说明 | 示例值 |
|--------|------|------|--------|
| `course_name` | 文本 | 课程名称 | `Biology SBI4U` |
| `assignment_name` | 文本 | 作业/测验名称（与 Gradebook 表一致） | `Lab Report 3` |
| `weight` | 数字 | 该作业占课程总分的权重百分比 | `15` |
| `category` | 文本 | 分类名称（如有）| `Lab` |
| `is_configured` | 布尔 | 该课程 Gradesetup 是否有效配置（权重之和是否合理） | `true` |

**用途**：
- `weight` → 缺交优先级排序（weight × days_overdue 降序）
- `is_configured = false` → 仪表盘降级：不显示权重，按逾期天数排序

---

## 已有表字段确认（无需改动）

### Roster（花名册）
| 字段名 | 类型 | 说明 |
|--------|------|------|
| `student_name` | 文本 | 学生姓名（主键） |
| `grade` | 数字 | 年级（10 / 11 / 12） |
| `enrollment_date` | 日期 | 入学日期（用于阶段判断） |

### Missing（缺交记录）
| 字段名 | 类型 | 说明 |
|--------|------|------|
| `student_name` | 文本 | |
| `course_name` | 文本 | |
| `assignment_name` | 文本 | 与 Gradebook 表对照即可区分 AOL / AFL/AAL |
| `due_date` | 日期 | 截止日期（用于计算逾期天数） |

---

## AOL 自动识别逻辑（后端实现，无需飞书字段支持）

```
对于某学生某条缺交记录：
  IF assignment_name 存在于 Gradebook 表（同一课程）
    → 标记为 AOL（算分作业，优先级高）
  ELSE
    → 标记为 AFL/AAL（日常作业，显示为参与率）
```

此逻辑在 `server.js` 的 `summarizeForStudent()` 函数中实现，不需要在飞书表格中新增字段。

---

## `.env` 新增配置项

```
# 当前学期开始日期（每学期手动更新一次）
SEMESTER_START_DATE=2025-09-02

# 学期总周数（固定为 8，一般不变）
SEMESTER_TOTAL_WEEKS=8
```
