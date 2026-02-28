/* ═══════════════════════════════════════════════════════════
   通关指南 · 学生仪表盘
   数据结构来源：build_student_summary.py → 飞书汇总表
   TODO: 替换为 fetch('/api/dashboard?t=...') 的返回值
   ═══════════════════════════════════════════════════════════ */

// ─── Mock 数据（与 build_student_summary.py 输出结构一致）──────
const MOCK_DATA = {
  student: {
    name: "李明",
    pinyin: "Li Ming",
    grade: 12,
    enrollment_date: "2025-09-02",
    credits_earned: 18,
    credits_remaining: 12
  },
  semester: {
    start_date: "2025-09-02",
    total_weeks: 8,
    current_week: 5
  },
  stage: "申请备战期",

  // 来自 课程进度JSON：每学期最多两门课
  course_progress: [
    {
      course: "Biology SBI4U",
      submittedCount: 8,  missingCount: 2, completion: 80.0,
      current_grade: 82.5,
      grade_updated_at: 1728518400000,
      aol_details: [
        { name: "Lab Report 1",  score: 88, max: 100 },
        { name: "Unit Test 1",   score: 75, max: 100 },
        { name: "Quiz 4",        score: 80, max: 100 }
      ]
    },
    {
      course: "Mathematics MHF4U",
      submittedCount: 11, missingCount: 1, completion: 91.7,
      current_grade: 91.0,
      grade_updated_at: 1728691200000,
      aol_details: [
        { name: "Unit Test 2",  score: 95, max: 100 },
        { name: "Midterm Exam", score: 88, max: 100 },
        { name: "Quiz 6",       score: 90, max: 100 }
      ]
    }
  ],

  // 来自 缺交明细JSON
  missing_items: [
    { course: "Biology SBI4U",     assignmentName: "Lab Report 3",  assignmentLink: "https://queenscanada.schoology.com/assignment/12345" },
    { course: "Biology SBI4U",     assignmentName: "Section Quiz 5", assignmentLink: "" },
    { course: "Mathematics MHF4U", assignmentName: "Unit Test 3",   assignmentLink: "https://queenscanada.schoology.com/assessment/67890" }
  ],

  // 来自 近期提交JSON（最多 20 条，跨课程）
  // submittedAt 可以是飞书毫秒时间戳（数字）或日期字符串
  recent_submitted: [
    { course: "Mathematics MHF4U", assignmentName: "Homework Set 6",   submittedAt: 1728777600000, status: "已提交" },
    { course: "Biology SBI4U",     assignmentName: "Lab Report 2",     submittedAt: 1728691200000, status: "已提交" },
    { course: "Mathematics MHF4U", assignmentName: "Quiz 8",           submittedAt: 1728604800000, status: "迟交"   },
    { course: "Biology SBI4U",     assignmentName: "Reading Response 4", submittedAt: 1728518400000, status: "已提交" },
    { course: "Mathematics MHF4U", assignmentName: "Homework Set 5",   submittedAt: 1728432000000, status: "已提交" },
    { course: "Biology SBI4U",     assignmentName: "Lab Practical 2",  submittedAt: 1728345600000, status: "已提交" },
    { course: "Mathematics MHF4U", assignmentName: "Quiz 7",           submittedAt: 1728259200000, status: "已提交" },
    { course: "Biology SBI4U",     assignmentName: "Discussion Post 3", submittedAt: 1728172800000, status: "已提交" }
  ],

  // 来自 推荐JSON
  recommendations: [
    { title: "优先处理缺交：复活与翻盘", anchorText: "4.8 危机关：复活与翻盘" },
    { title: "用 Rubric 直接提分",       anchorText: "4.4 作业关：Rubric 狙击手" }
  ],

  missing_total:   3,
  submitted_total: 19,

  // Combo（待加入 build_student_summary.py，当前 mock）
  // today 仅 mock 用，真实版本由后端传入
  combo: {
    current_streak: 7,
    today: "2025-10-10",
    months: [
      {
        label: "9月",
        year: 2025,
        month: 9,
        days: {
          "2025-09-01": "no_assignment",
          "2025-09-02": "hit",
          "2025-09-03": "hit",
          "2025-09-04": "hit",
          "2025-09-05": "hit",
          "2025-09-06": "no_assignment",
          "2025-09-07": "no_assignment",
          "2025-09-08": "hit",
          "2025-09-09": "hit",
          "2025-09-10": "hit",
          "2025-09-11": "hit",
          "2025-09-12": "hit",
          "2025-09-13": "no_assignment",
          "2025-09-14": "no_assignment",
          "2025-09-15": "hit",
          "2025-09-16": "hit",
          "2025-09-17": "miss",
          "2025-09-18": "hit",
          "2025-09-19": "hit",
          "2025-09-20": "no_assignment",
          "2025-09-21": "no_assignment",
          "2025-09-22": "hit",
          "2025-09-23": "hit",
          "2025-09-24": "hit",
          "2025-09-25": "hit",
          "2025-09-26": "hit",
          "2025-09-27": "no_assignment",
          "2025-09-28": "no_assignment",
          "2025-09-29": "hit",
          "2025-09-30": "hit"
        },
        day_details: {
          "2025-09-02": { "Biology SBI4U": 1 },
          "2025-09-03": { "Mathematics MHF4U": 1 },
          "2025-09-04": { "Biology SBI4U": 1, "Mathematics MHF4U": 1 },
          "2025-09-05": { "Biology SBI4U": 1 },
          "2025-09-08": { "Mathematics MHF4U": 1 },
          "2025-09-09": { "Biology SBI4U": 1 },
          "2025-09-10": { "Biology SBI4U": 1, "Mathematics MHF4U": 1 },
          "2025-09-11": { "Mathematics MHF4U": 1 },
          "2025-09-12": { "Biology SBI4U": 1 },
          "2025-09-15": { "Biology SBI4U": 1, "Mathematics MHF4U": 1 },
          "2025-09-16": { "Mathematics MHF4U": 1 },
          "2025-09-18": { "Biology SBI4U": 1 },
          "2025-09-19": { "Biology SBI4U": 1, "Mathematics MHF4U": 1 },
          "2025-09-22": { "Mathematics MHF4U": 1 },
          "2025-09-23": { "Biology SBI4U": 1 },
          "2025-09-24": { "Biology SBI4U": 1, "Mathematics MHF4U": 1 },
          "2025-09-25": { "Mathematics MHF4U": 1 },
          "2025-09-26": { "Biology SBI4U": 1 },
          "2025-09-29": { "Biology SBI4U": 1, "Mathematics MHF4U": 1 },
          "2025-09-30": { "Mathematics MHF4U": 1 }
        }
      },
      {
        label: "10月",
        year: 2025,
        month: 10,
        days: {
          "2025-10-01": "hit",
          "2025-10-02": "hit",
          "2025-10-03": "hit",
          "2025-10-04": "no_assignment",
          "2025-10-05": "no_assignment",
          "2025-10-06": "hit",
          "2025-10-07": "hit",
          "2025-10-08": "hit",
          "2025-10-09": "hit",
          "2025-10-10": "hit",
          "2025-10-11": "future",
          "2025-10-12": "future",
          "2025-10-13": "future",
          "2025-10-14": "future",
          "2025-10-15": "future",
          "2025-10-16": "future",
          "2025-10-17": "future",
          "2025-10-18": "future",
          "2025-10-19": "future",
          "2025-10-20": "future",
          "2025-10-21": "future",
          "2025-10-22": "future",
          "2025-10-23": "future",
          "2025-10-24": "future",
          "2025-10-25": "future",
          "2025-10-26": "future",
          "2025-10-27": "future",
          "2025-10-28": "future",
          "2025-10-29": "future",
          "2025-10-30": "future",
          "2025-10-31": "future"
        },
        day_details: {
          "2025-10-01": { "Biology SBI4U": 1 },
          "2025-10-02": { "Mathematics MHF4U": 1 },
          "2025-10-03": { "Biology SBI4U": 1, "Mathematics MHF4U": 1 },
          "2025-10-06": { "Biology SBI4U": 1 },
          "2025-10-07": { "Mathematics MHF4U": 1 },
          "2025-10-08": { "Biology SBI4U": 1, "Mathematics MHF4U": 1 },
          "2025-10-09": { "Mathematics MHF4U": 1 },
          "2025-10-10": { "Biology SBI4U": 1, "Mathematics MHF4U": 1 }
        }
      }
    ]
  }
}

// ─── 工具函数 ─────────────────────────────────────────────────

function esc(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
}

// 格式化飞书时间戳（ms数字）或日期字符串 → "10月12日"
function formatDate(val) {
  if (!val) return ""
  const ts = typeof val === "number" ? val : Number(val)
  if (!isNaN(ts) && ts > 1000000000000) {
    const d = new Date(ts)
    return `${d.getMonth() + 1}月${d.getDate()}日`
  }
  const s = String(val).slice(0, 10)
  const parts = s.split(/[-/]/)
  if (parts.length >= 3) return `${parseInt(parts[1])}月${parseInt(parts[2])}日`
  return s
}

// 格式化为 "x月x日 HH:mm"（用于近期提交记录）
function formatDateTime(val) {
  if (!val) return ""
  const ts = typeof val === "number" ? val : Number(val)
  if (!isNaN(ts) && ts > 1000000000000) {
    const d = new Date(ts)
    const hh = String(d.getHours()).padStart(2, "0")
    const mm = String(d.getMinutes()).padStart(2, "0")
    return `${d.getMonth() + 1}月${d.getDate()}日 ${hh}:${mm}`
  }
  return formatDate(val)
}

// 英文日期 + 序数词：2025-09-10 → "Sep 10th"
const _MONTHS_EN = ["Jan","Feb","Mar","Apr","May","Jun",
                    "Jul","Aug","Sep","Oct","Nov","Dec"]
function _ordinal(n) {
  const s = ["th","st","nd","rd"], v = n % 100
  return n + (s[(v-20)%10] || s[v] || s[0])
}
function dateKeyToEN(key) {
  const [, m, d] = key.split('-').map(Number)
  return `${_MONTHS_EN[m-1]} ${_ordinal(d)}`
}

// 从课程全名提取课程代码："Biology SBI4U" → "SBI4U"
function courseCode(fullName) {
  return fullName.split(' ').pop()
}

function completionClass(pct) {
  if (pct >= 80) return "good"
  if (pct >= 60) return "warn"
  return "risk"
}

// ─── ASCII 进度条 ───────────────────────────────────────────────

function asciiBar(pct, width = 22) {
  const filled = Math.round(pct / 100 * width)
  const empty  = width - filled
  return '[' + '█'.repeat(filled) + '░'.repeat(empty) + '] ' + String(pct).padStart(3, ' ') + '%'
}

// ─── ASCII 热力图 ───────────────────────────────────────────────

function renderHeatmapASCII(monthData) {
  const cells = buildHeatmapCells(monthData)
  const statusHTML = {
    hit:           '<span class="hmap-hit">√</span>',
    miss:          '<span class="hmap-miss">x</span>',
    no_assignment: '<span class="hmap-none">-</span>',
    future:        '<span class="hmap-future">.</span>',
    empty:         ' '
  }
  const dowLabels = ['一', '二', '三', '四', '五', '六', '日']

  let html = ''
  for (let d = 0; d < 7; d++) {
    const rowCells = cells.filter((_, i) => i % 7 === d)
    const rowHTML  = rowCells.map(c => statusHTML[c.status] || ' ').join(' ')
    html += dowLabels[d] + ' ' + rowHTML + '\n'
  }
  html += '\n'
  html += '<span class="hmap-legend">'
  html += '<span class="hmap-hit">#</span> 按时  '
  html += '<span class="hmap-miss">x</span> 缺交  '
  html += '<span class="hmap-none">-</span> 无作业  '
  html += '<span class="hmap-future">.</span> 未来'
  html += '</span>'
  return html
}

// ─── CSS 格子热力图 ─────────────────────────────────────────────

function renderAllMonthsGrid(months) {
  const blocksHTML = months.map(monthData => {
    const cells = buildHeatmapCells(monthData)
    const numCols = cells.length / 7

    const cellsHTML = cells.map(c => {
      if (c.status === "empty") return `<div class="hmap-cell hmap-cell--empty"></div>`
      const tip = c.tooltip ? ` data-tip="${esc(c.tooltip)}"` : ""
      return `<div class="hmap-cell hmap-cell--${c.status}"${tip}></div>`
    }).join("")

    const gridStyle =
      `grid-template-columns: repeat(${numCols}, 14px); grid-template-rows: repeat(7, 14px)`

    return `
      <div class="hmap-block">
        <div class="hmap-month-label">${esc(monthData.label)}</div>
        <div class="hmap-inner">
          <div class="hmap-dow-col">
            <div>一</div><div>二</div><div>三</div>
            <div>四</div><div>五</div><div>六</div><div>日</div>
          </div>
          <div class="hmap-css-grid" style="${gridStyle}">${cellsHTML}</div>
        </div>
      </div>
    `
  }).join("")

  return `
    <div class="hmap-months">${blocksHTML}</div>
    <div class="hmap-legend-row">
      <span class="hmap-legend-item"><span class="hmap-sw hmap-sw--hit"></span>按时</span>
      <span class="hmap-legend-item"><span class="hmap-sw hmap-sw--miss"></span>缺交</span>
      <span class="hmap-legend-item"><span class="hmap-sw hmap-sw--no_assignment"></span>无作业</span>
      <span class="hmap-legend-item"><span class="hmap-sw hmap-sw--future"></span>未来</span>
    </div>
  `
}

// ─── 折叠展开 ──────────────────────────────────────────────────
function toggleDetail(btn) {
  const body = btn.nextElementSibling
  const icon = btn.querySelector(".toggle-icon")
  const open = body.style.display !== "none"
  body.style.display = open ? "none" : "block"
  icon.textContent = open ? "[+]" : "[-]"
}

// ─── 区域 A：学期进度 ─────────────────────────────────────────

function renderSemester(data) {
  const { start_date, current_week, total_weeks } = data.semester

  // 日期显示
  const today = data.combo?.today ? new Date(data.combo.today) : new Date()
  const dayNames = ['日','一','二','三','四','五','六']
  document.getElementById("headerDate").textContent =
    `今天  ${today.getMonth()+1}月${today.getDate()}日（周${dayNames[today.getDay()]}）`

  // 学期进度（无数据时显示占位）
  if (!current_week || !total_weeks) {
    document.getElementById("headerCountdown").textContent = ""
    document.getElementById("semesterWeek").textContent = "学期进度加载中…"
    document.getElementById("stageLabel").textContent = data.stage
    const track = document.querySelector('.progress-track')
    if (track) track.innerHTML = `<span class="ascii-bar">${asciiBar(0)}</span>`
    return
  }

  const pct = Math.round((current_week / total_weeks) * 100)

  // 距学期结束天数
  if (start_date) {
    const endDate = new Date(start_date)
    endDate.setDate(endDate.getDate() + total_weeks * 7)
    const daysLeft = Math.max(0, Math.ceil((endDate - today) / 86400000))
    document.getElementById("headerCountdown").textContent =
      daysLeft > 0 ? `距学期结束还有 ${daysLeft} 天` : `学期已结束`
  }

  // 学期进度
  document.getElementById("semesterWeek").textContent = `第 ${current_week} 周 / 共 ${total_weeks} 周`
  document.getElementById("stageLabel").textContent = data.stage
  const track = document.querySelector('.progress-track')
  if (track) track.innerHTML = `<span class="ascii-bar">${asciiBar(pct)}</span>`
}

// ─── 区域 B：今日待处理 ───────────────────────────────────────

function renderTasks(data) {
  const urgent   = document.getElementById("taskUrgent")
  const reminder = document.getElementById("taskReminder")
  const allClear = document.getElementById("taskAllClear")

  // B-1：缺交作业，显示前 3 条，其余折叠
  if (data.missing_items && data.missing_items.length > 0) {
    urgent.style.display = "flex"
    const items   = data.missing_items
    const SHOW    = 3
    const visible = items.slice(0, SHOW)
    const hidden  = items.slice(SHOW)

    const renderItem = item => `
      <div class="task-item task-item--urgent">
        <div class="task-item__main">
          <div class="task-item__course">${esc(item.course)}</div>
          <div class="task-item__name">${esc(item.assignmentName)}</div>
        </div>
        ${item.assignmentLink
          ? `<a class="task-item__go" href="${esc(item.assignmentLink)}" target="_blank" rel="noopener">前往作业 →</a>`
          : `<span class="task-item__go task-item__go--na">暂无链接</span>`
        }
      </div>
    `

    const hiddenHTML = hidden.length > 0 ? `
      <button class="task-fold-btn" onclick="this.nextElementSibling.style.display='block';this.style.display='none'">
        ▸ 查看另外 ${hidden.length} 项缺交作业
      </button>
      <div style="display:none">${hidden.map(renderItem).join("")}</div>
    ` : ""

    document.getElementById("taskUrgentList").innerHTML =
      visible.map(renderItem).join("") + hiddenHTML
  }

  // B-2：日常参与提醒（待 Gradebook 数据接入后激活）
  reminder.style.display = "none"

  // 全部完成
  if (!data.missing_items || data.missing_items.length === 0) {
    allClear.style.display = "flex"
  }
}

// ─── 区域 C：课程进度卡片 ─────────────────────────────────────

function renderCourses(data) {
  // 按课程名将缺交明细和提交记录分组
  const missingByCourse = {}
  const submittedByCourse = {}

  ;(data.missing_items || []).forEach(item => {
    if (!missingByCourse[item.course]) missingByCourse[item.course] = []
    missingByCourse[item.course].push(item)
  })

  ;(data.recent_submitted || []).forEach(item => {
    if (!submittedByCourse[item.course]) submittedByCourse[item.course] = []
    submittedByCourse[item.course].push(item)
  })

  document.getElementById("courseGrid").innerHTML =
    (data.course_progress || []).map(cp => {
      const pct     = Math.round(cp.completion)
      const barCls  = completionClass(pct)
      const missing = missingByCourse[cp.course] || []
      const submitted = submittedByCourse[cp.course] || []

      // 未提交区块
      const missingHTML = missing.length > 0
        ? missing.map(m => `
            <div class="detail-item detail-item--missing">
              <span class="detail-item__name">${esc(m.assignmentName || "（未知作业）")}</span>
              ${m.assignmentLink
                ? `<a class="detail-item__link" href="${esc(m.assignmentLink)}" target="_blank" rel="noopener">前往 →</a>`
                : `<span class="detail-item__nolink">暂无链接</span>`
              }
            </div>
          `).join("")
        : `<div class="detail-empty">✓ 本课程无缺交作业</div>`

      // 已提交区块
      const submittedHTML = submitted.length > 0
        ? submitted.map(s => `
            <div class="detail-item detail-item--submitted">
              <span class="detail-item__name">${esc(s.assignmentName || "（未知作业）")}</span>
              <span class="detail-item__meta">
                ${s.status === "迟交" ? `<span class="tag-late">迟交</span>` : ""}
                <span class="detail-item__date">${formatDateTime(s.submittedAt)}</span>
              </span>
            </div>
          `).join("")
        : `<div class="detail-empty">暂无近期提交记录</div>`

      // AoL 评分区块
      const aolItems = cp.aol_details || []
      const aolHTML = aolItems.length > 0
        ? aolItems.map(a => `
            <div class="detail-item detail-item--submitted">
              <span class="detail-item__name">${esc(a.name)}</span>
              <span class="detail-item__date">${a.score} / ${a.max}</span>
            </div>
          `).join("")
        : `<div class="detail-empty">暂无 AoL 评分数据</div>`

      const gradeStr   = cp.current_grade != null ? `${cp.current_grade}%` : "—"
      const updatedStr = cp.grade_updated_at ? formatDate(cp.grade_updated_at) : ""

      return `
        <div class="course-card">

          <div class="course-card__header">
            <div class="course-card__name">${esc(cp.course)}</div>
            <div class="course-card__grade">
              <span class="grade__score">${gradeStr}</span>
              ${updatedStr ? `<span class="grade__updated">更新于 ${updatedStr}</span>` : ""}
            </div>
          </div>

          <div class="course-prog">
            <div class="ascii-course-bar ascii-course-bar--${barCls}">${asciiBar(pct)}</div>
            <div class="course-prog__counts">
              <span class="count--ok">已提交 ${cp.submittedCount}${cp.aolSubmitted > 0 ? ` <span class="tag-aol">含 ${cp.aolSubmitted} AoL</span>` : ""}</span>
              <span class="count--sep">·</span>
              <span class="${cp.missingCount > 0 ? "count--miss" : "count--ok"}">缺交 ${cp.missingCount}${cp.aolMissing > 0 ? ` <span class="tag-aol tag-aol--miss">含 ${cp.aolMissing} AoL</span>` : ""}</span>
            </div>
          </div>

          <div class="course-detail">
            <button class="course-detail__toggle" onclick="toggleDetail(this)">
              <span class="toggle-icon">[+]</span>
              AoL 评分详情
              ${updatedStr ? `<span class="grade__updated">更新于 ${updatedStr}</span>` : ""}
            </button>
            <div class="course-detail__body">
              ${aolHTML}
            </div>
          </div>

          <div class="course-detail">
            <button class="course-detail__toggle" onclick="toggleDetail(this)">
              <span class="toggle-icon">[+]</span>
              未提交作业
              ${missing.length > 0
                ? `<span class="detail-badge detail-badge--danger">${missing.length}</span>`
                : `<span class="detail-badge detail-badge--ok">0</span>`
              }
            </button>
            <div class="course-detail__body">
              ${missingHTML}
            </div>
          </div>

          <div class="course-detail">
            <button class="course-detail__toggle" onclick="toggleDetail(this)">
              <span class="toggle-icon">[+]</span>
              本周提交记录${data.recentWeekLabel ? ` (${data.recentWeekLabel})` : ""}
              <span class="detail-badge">${submitted.length}</span>
            </button>
            <div class="course-detail__body">
              ${submittedHTML}
            </div>
          </div>

        </div>
      `
    }).join("")
}

// ─── 区域 D：连击热力图 ────────────────────────────────────────

const COMBO_MILESTONES = [
  [40, "全学期连击。这学期你做到了。"],
  [20, "半学期准时提交，你已经是认真对待这件事的人了。"],
  [10, "两周连击，这不是运气，是习惯。"],
  [5,  "一整周准时提交，你找到节奏了。"],
  [3,  "三天了，好的开始。"],
  [1,  "今天开始了，明天继续。"],
  [0,  "连击中断了，整理一下，继续出发。"]
]

function comboMessage(streak) {
  for (const [n, msg] of COMBO_MILESTONES) {
    if (streak >= n) return msg
  }
  return ""
}

// 将某月展开为 grid 单元格数组（含首尾空白对齐）
function buildHeatmapCells(monthData) {
  const { year, month, days, day_details } = monthData
  const daysInMonth = new Date(year, month, 0).getDate()
  const firstDow = (new Date(year, month - 1, 1).getDay() + 6) % 7  // Mon=0

  const cells = []
  for (let i = 0; i < firstDow; i++) cells.push({ status: "empty", tooltip: "" })
  for (let d = 1; d <= daysInMonth; d++) {
    const key = `${year}-${String(month).padStart(2,"0")}-${String(d).padStart(2,"0")}`
    const status = days[key] || "empty"
    let tooltip = dateKeyToEN(key)
    if (day_details && day_details[key]) {
      const parts = Object.entries(day_details[key])
        .map(([course, cnt]) => `${courseCode(course)}: ${cnt}`)
      tooltip = parts.join(", ") + " on " + dateKeyToEN(key)
    }
    cells.push({ status, tooltip: status !== "empty" ? tooltip : "" })
  }
  const rem = cells.length % 7
  if (rem !== 0) for (let i = 0; i < 7 - rem; i++) cells.push({ status: "empty", tooltip: "" })
  return cells
}

function renderCombo(data) {
  const { current_streak, months } = data.combo
  document.getElementById("comboCount").textContent = current_streak
  document.getElementById("comboMessage").textContent = comboMessage(current_streak)

  // 所有月份合并显示
  document.getElementById("heatmapGrid").innerHTML =
    renderAllMonthsGrid(months)
}

// ─── 区域 E：情境化指南 ───────────────────────────────────────

// 推荐锚点映射（anchorText → guide anchor）
const ANCHOR_MAP = {
  "4.8 危机关：复活与翻盘":                       "#aol-recovery",
  "4.4 作业关：Rubric 狙击手":                    "#rubric",
  "4.2 每日循环 Daily Loop":                      "#maintain",
  "4.1 两个快速启动清单（任选其一，从今天开始）":  "#onboarding"
}

function renderGuideSnippet(data) {
  const recs = data.recommendations || []
  if (recs.length === 0) return

  const first  = recs[0]
  const anchor = ANCHOR_MAP[first.anchorText] || ""

  document.getElementById("guideSnippet").innerHTML = `
    <div class="guide-snippet__title">${esc(first.title)}</div>
    <p class="guide-snippet__preview">
      点击下方链接，直接跳转到对应指南章节查看详细操作步骤。
    </p>
    <a class="guide-snippet__link" href="/guide.html${esc(anchor)}">阅读完整建议 →</a>
    ${recs.length > 1 ? `
      <div class="guide-snippet__more">
        ${recs.slice(1).map(r => {
          const a = ANCHOR_MAP[r.anchorText] || ""
          return `<a class="guide-snippet__more-link" href="/guide.html${esc(a)}">${esc(r.title)}</a>`
        }).join("")}
      </div>
    ` : ""}
  `
}

// ─── 从提交记录推算 Combo 热力图 ──────────────────────────────
// submissions: [{submittedAt, course, assignmentName, ...}]
// todayStr: "YYYY-MM-DD"
// 覆盖的月份范围：今天起往前 2 个自然月（确保至少有数据的那几个月都显示）
function computeComboFromSubmissions(submissions, todayStr) {
  const today = new Date(todayStr + "T00:00:00")

  // 按日期分组提交记录，建立 dayMap: "YYYY-MM-DD" → [{course, assignmentName}]
  const dayMap = {}
  for (const s of submissions) {
    const raw = s.submittedAt
    if (!raw) continue
    let d
    if (typeof raw === "number") d = new Date(raw)
    else d = new Date(raw)
    if (isNaN(d.getTime())) continue
    const key = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`
    if (!dayMap[key]) dayMap[key] = []
    dayMap[key].push({ course: s.course || "", assignmentName: s.assignmentName || "" })
  }

  // 计算连击数：从今天往前，连续有 hit 的天数
  let streak = 0
  for (let offset = 0; offset <= 30; offset++) {
    const d = new Date(today)
    d.setDate(d.getDate() - offset)
    const key = `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`
    if (dayMap[key]) streak++
    else if (offset > 0) break
  }

  // 生成月份列表：当前月 + 前一个月（共 2 个月）
  const months = []
  for (let mOffset = 1; mOffset >= 0; mOffset--) {
    const ref = new Date(today.getFullYear(), today.getMonth() - mOffset, 1)
    const year = ref.getFullYear()
    const month = ref.getMonth() + 1
    const daysInMonth = new Date(year, month, 0).getDate()
    const label = `${month}月`
    const days = {}
    const day_details = {}
    for (let d = 1; d <= daysInMonth; d++) {
      const key = `${year}-${String(month).padStart(2,"0")}-${String(d).padStart(2,"0")}`
      const dayDate = new Date(year, month - 1, d)
      if (dayDate > today) {
        days[key] = "future"
      } else if (dayMap[key]) {
        days[key] = "hit"
        const detailMap = {}
        for (const item of dayMap[key]) {
          const c = item.course || "Unknown"
          detailMap[c] = (detailMap[c] || 0) + 1
        }
        day_details[key] = detailMap
      } else {
        days[key] = "no_assignment"
      }
    }
    months.push({ label, year, month, days, day_details })
  }

  return { current_streak: streak, today: todayStr, months }
}

// ─── 服务端数据 → 前端格式适配层 ──────────────────────────────
// 服务端返回 camelCase；前端 MOCK_DATA 用 snake_case
function normalizeApiResponse(raw) {
  const todayStr = new Date().toISOString().slice(0, 10)

  // recent_submitted
  const recentSubmitted = (raw.recentSubmissions || []).map(s => ({
    course:         s.course        || "",
    assignmentName: s.assignmentName || s.assignmentname || "",
    submittedAt:    s.submittedAt   || s.submittedat    || "",
    status:         s.status        || "",
    assignmentLink: s.link          || "",
  }))

  // missing_items
  const missingItems = (raw.missingItems || []).map(m => ({
    course:         m.course         || "",
    assignmentName: m.assignmentName || m.assignmentname || "",
    assignmentLink: m.assignmentLink || m.link           || "",
  }))

  // attention_items：缺交 + 低分合并列表（来自 关注列表JSON）
  const attentionItems = (raw.attentionItems || []).map(item => ({
    type:           item.type           || "missing",
    course:         item.course         || "",
    assignmentName: item.assignmentName || "",
    assignmentLink: item.assignmentLink || item.link || "",
    nature:         item.nature         || "",
    score:          item.score          ?? null,
    maxScore:       item.maxScore       ?? null,
  }))

  // course_progress
  const courseProgress = (raw.courseProgress || []).map(cp => ({
    course:          cp.course         || "",
    submittedCount:  cp.submittedCount || 0,
    missingCount:    cp.missingCount   || 0,
    completion:      cp.completion     || 0,
    current_grade:   cp.current_grade  || null,
    grade_updated_at: cp.grade_updated_at || null,
    aol_details:     cp.aol_details    || [],
    aolSubmitted:    cp.aolSubmitted   || 0,
    aolMissing:      cp.aolMissing     || 0,
  }))

  const finalCourseProgress = courseProgress.length > 0
    ? courseProgress
    : (raw.courses || []).map(c => ({
        course: typeof c === "string" ? c : (c.name || ""),
        submittedCount: 0, missingCount: 0, completion: 0,
        current_grade: null, aol_details: []
      }))

  // 学期标签："2025-2026学年 第3学期"
  const schoolYear  = raw.schoolYear  || ""
  const semesterNum = raw.semesterNum || ""
  let semLabel = ""
  if (schoolYear)  semLabel += schoolYear + "学年"
  if (semesterNum) semLabel += (semLabel ? " " : "") + "第" + semesterNum + "学期"

  // 已修/剩余学分
  const creditsEarned  = (raw.creditsEarned  != null && raw.creditsEarned  !== "") ? Number(raw.creditsEarned)  : null
  const creditsTarget  = (raw.creditsTarget  != null && raw.creditsTarget  !== "") ? Number(raw.creditsTarget)  : null
  const creditsRemaining = (creditsEarned != null && creditsTarget != null) ? Math.max(creditsTarget - creditsEarned, 0) : null

  const student = {
    name:              raw.studentName || "",
    pinyin:            raw.studentName || "",
    grade:             null,
    credits_earned:    creditsEarned,
    credits_remaining: creditsRemaining,
  }

  // OSSLT 状态
  const osslt = raw.osslt || ""

  // combo
  const combo = raw.combo
    || computeComboFromSubmissions(recentSubmitted, todayStr)

  // 自动生成学情提醒
  const missingTotal = raw.missingTotal ?? 0
  const alerts = []
  if (missingTotal >= 10) {
    alerts.push({ type: "urgent", title: "⚠️ 缺交预警", body: `共 ${missingTotal} 个作业未提交，请优先处理。` })
  } else if (missingTotal > 0) {
    alerts.push({ type: "warn", title: "🔶 待处理缺交", body: `${missingTotal} 个作业待补交。` })
  } else {
    alerts.push({ type: "ok", title: "✓ 无缺交", body: "本学期所有作业均已提交，继续保持！" })
  }
  // 完成度最低的课程预警
  const worstCourse = finalCourseProgress
    .filter(cp => cp.completion < 50 && cp.missingCount > 0)
    .sort((a, b) => a.completion - b.completion)[0]
  if (worstCourse) {
    alerts.push({ type: "warn", title: "📉 课程警告", body: `${worstCourse.course} 完成度仅 ${Math.round(worstCourse.completion)}%，需重点关注。` })
  }
  if (osslt) {
    const isPass = /通过|pass|yes/i.test(osslt)
    alerts.push({ type: isPass ? "ok" : "info", title: "OSSLT", body: osslt })
  }
  // 来自服务端的自定义通知（花名册 公告 字段，每行一条）
  const noticesRaw = raw.noticesRaw || ""
  const noticesFromRoster = noticesRaw
    .split("\n").map(s => s.trim()).filter(Boolean)
    .map(line => ({ type: "info", title: "📢 通知", body: line }))
  const noticesFromServer = (raw.notices || []).map(n => ({ type: "info", title: n.title || "📢 通知", body: n.body || n.content || "" }))

  return {
    student,
    semester:        {
      start_date:   raw.semesterStart || "",
      total_weeks:  raw.totalWeeks    || null,
      current_week: raw.currentWeek   || null,
    },
    semLabel,
    stage:           raw.stage || "在读",
    course_progress: finalCourseProgress,
    missing_items:   missingItems,
    attention_items: attentionItems,
    recent_submitted: recentSubmitted,
    recommendations: raw.recommendations || [],
    missing_total:   missingTotal,
    submitted_total: raw.submittedTotal ?? 0,
    combo,
    alerts:          [...alerts, ...noticesFromServer, ...noticesFromRoster],
  }
}

// ─── 区域 B2：关注列表 ────────────────────────────────────────

function buildAttentionItemHTML(item) {
  const isMissing  = item.type === "missing"
  const cls        = isMissing ? "task-item--urgent" : "task-item--warning"
  const typeTag    = isMissing
    ? `<span class="task-item__type-tag tag--missing">缺交</span>`
    : `<span class="task-item__type-tag tag--low-score">低分</span>`
  const scoreStr   = (!isMissing && item.score != null && item.maxScore != null)
    ? `<span class="task-item__score">${item.score}/${item.maxScore} (${Math.round(item.score / item.maxScore * 100)}%)</span>`
    : ""
  const link = item.assignmentLink
    ? `<a class="task-item__go" href="${esc(item.assignmentLink)}" target="_blank" rel="noopener">前往作业 →</a>`
    : `<span class="task-item__go task-item__go--na">暂无链接</span>`
  return `
    <div class="task-item ${cls}">
      <div class="task-item__main">
        <div class="task-item__course">${esc(item.course)}${typeTag}</div>
        <div class="task-item__name">${esc(item.assignmentName)}</div>
      </div>
      <div class="task-item__meta">
        ${scoreStr}
        ${link}
      </div>
    </div>
  `
}

function toggleAttentionMore() {
  const more = document.getElementById("attentionListMore")
  const icon = document.getElementById("attentionToggleIcon")
  const btn  = document.getElementById("attentionToggleMore")
  const open = more.style.display !== "none"
  more.style.display = open ? "none" : "flex"
  if (!open) { more.style.flexDirection = "column"; more.style.gap = "4px" }
  icon.textContent = open ? "[+]" : "[-]"
  const total = more.children.length
  btn.lastChild.textContent = open ? ` 展开更多（${total}）` : " 收起"
}

function renderAttentionList(data) {
  const items   = (data.attention_items || []).filter(i => i.type === "low_score")
  const section = document.getElementById("area-attention")
  if (!section) return
  if (!items.length) { section.style.display = "none"; return }
  section.style.display = "block"
  const top  = items.slice(0, 3)
  const rest = items.slice(3)
  document.getElementById("attentionListTop").innerHTML = top.map(buildAttentionItemHTML).join("")
  const moreEl  = document.getElementById("attentionListMore")
  const moreBtn = document.getElementById("attentionToggleMore")
  if (rest.length) {
    moreEl.innerHTML = rest.map(buildAttentionItemHTML).join("")
    moreBtn.style.display = "block"
    moreBtn.lastChild.textContent = ` 展开更多（${rest.length}）`
  } else {
    moreBtn.style.display = "none"
  }
}

// ─── 入口 ─────────────────────────────────────────────────────

function renderAll(data) {
  window._dashData = data  // 供 switchHeatmapMonth 使用

  // 仪表盘标题
  const pinyin = data.student.pinyin || data.student.name
  document.getElementById("dashboardTitle").textContent = `${pinyin} 的仪表盘`

  // 个人档案卡
  const s = data.student
  document.getElementById("profileAvatar").textContent = pinyin
  const courseNames = (data.course_progress || [])
    .map(c => `<div>${esc(c.course)}</div>`).join("")
  const semLabelHTML = data.semLabel
    ? `<div class="profile__sem">${esc(data.semLabel)}</div>` : ""
  const creditsHTML = (s.credits_earned != null || s.credits_remaining != null)
    ? `<div class="profile__credits">已修 ${s.credits_earned ?? "—"} 学分<br>剩余 ${s.credits_remaining ?? "—"} 学分</div>`
    : ""
  document.getElementById("profileInfo").innerHTML = `
    <div class="profile__stage">${esc(data.stage)}</div>
    ${semLabelHTML}
    <div class="profile__courses">${courseNames}</div>
    ${creditsHTML}
  `

  // 公告栏
  const announcePanel = document.getElementById("announcePanel")
  if (announcePanel) {
    const alerts = data.alerts || []
    if (alerts.length === 0) {
      announcePanel.innerHTML = `<div class="announce-item announce-item--info"><div class="announce-item__body">暂无通知</div></div>`
    } else {
      announcePanel.innerHTML = alerts.map(a => `
        <div class="announce-item announce-item--${esc(a.type || "info")}">
          ${a.title ? `<div class="announce-item__title">${esc(a.title)}</div>` : ""}
          <div class="announce-item__body">${esc(a.body || "")}</div>
        </div>
      `).join("")
    }
  }

  renderSemester(data)
  renderTasks(data)
  renderAttentionList(data)
  renderCourses(data)
  renderCombo(data)
  renderGuideSnippet(data)
}

;(function () {
  // ── Loading 控制 ──────────────────────────────────────────
  const overlay  = document.getElementById("loadingOverlay")
  const tipEl    = document.getElementById("loadingTip")

  const TIPS = [
    "💡 每天 3 分钟登录 Schoology 查看 DDL，胜过临时抱佛脚。",
    "📋 先读 Rubric 再写作业，对齐评分标准是最省力的提分方式。",
    "⏰ 作业迟交？先提交一个可评分版本，再发消息说明情况。",
    "📅 把未来 14 天所有 DDL 写进日历，至少设置一次提醒。",
    "🔁 每周 15 分钟存档复盘：分数、反馈、风险、下周升级点。",
    "🤝 找老师提问时带上你已尝试的步骤，反馈会更精准。",
    "📁 文件命名建议：课程-任务-版本-日期，方便随时找到。",
    "🎯 连续两周迟交？是系统没跑起来，回到 Daily Loop 重启。",
    "🧠 错题本只需 3 栏：题目 / 错的原因 / 下次怎么做。",
    "🚀 入学第一件事：把本学期所有 DDL 一次性写进日历。",
  ]

  let tipIdx = 0
  let tipTimer = null

  function showTip(text) {
    tipEl.classList.add("fade")
    setTimeout(() => {
      tipEl.textContent = text
      tipEl.classList.remove("fade")
    }, 400)
  }

  function startTips() {
    showTip(TIPS[tipIdx])
    tipTimer = setInterval(() => {
      tipIdx = (tipIdx + 1) % TIPS.length
      showTip(TIPS[tipIdx])
    }, 3500)
  }

  function hideLoading() {
    clearInterval(tipTimer)
    overlay.classList.add("hidden")
    setTimeout(() => overlay.remove(), 350)
  }

  // ── localStorage 缓存 ──────────────────────────────────────
  const CACHE_TTL = 25 * 60 * 1000   // 25 分钟，与 pipeline 周期匹配

  function lsGet(key) {
    try {
      const raw = localStorage.getItem(key)
      if (!raw) return null
      const { data, ts } = JSON.parse(raw)
      if (Date.now() - ts > CACHE_TTL) { localStorage.removeItem(key); return null }
      return data
    } catch { return null }
  }

  function lsSet(key, data) {
    try { localStorage.setItem(key, JSON.stringify({ data, ts: Date.now() })) } catch {}
  }

  // ── 入口逻辑 ──────────────────────────────────────────────
  const params  = new URLSearchParams(location.search)
  const tenant  = (params.get("t") || "").trim()
  const student = (params.get("student") || "").trim()

  if (!tenant || !student) {
    hideLoading()
    renderAll(MOCK_DATA)
    return
  }

  startTips()

  const cacheKey = `qea__${tenant}__${student}`
  const cached   = lsGet(cacheKey)

  if (cached) {
    // 有缓存：立即渲染，loading 几乎不可见
    hideLoading()
    renderAll(normalizeApiResponse(cached))
    // 后台静默刷新，下次访问得到最新数据
    fetch(`/api/dashboard?t=${encodeURIComponent(tenant)}&student=${encodeURIComponent(student)}`)
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) lsSet(cacheKey, data) })
      .catch(() => {})
    return
  }

  // 无缓存：显示 loading，等待 API
  const url = `/api/dashboard?t=${encodeURIComponent(tenant)}&student=${encodeURIComponent(student)}`
  fetch(url)
    .then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.json()
    })
    .then(data => {
      lsSet(cacheKey, data)
      hideLoading()
      renderAll(normalizeApiResponse(data))
    })
    .catch(err => {
      console.warn("[dashboard] API 失败，降级 MOCK_DATA:", err)
      hideLoading()
      renderAll(MOCK_DATA)
    })
})()
