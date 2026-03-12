window.__previewBooted = true;

function resolvePreviewBoot() {
  window.__previewBootResolved = true;
  if (window.__previewFailSafe) {
    clearTimeout(window.__previewFailSafe);
    window.__previewFailSafe = 0;
  }
}

const PREVIEW_MOCK_DATA = {
  student: {
    name: "示例同学",
    pinyin: "示例同学",
    grade: null,
    credits_earned: 18,
    credits_remaining: 12,
  },
  semester: {
    start_date: "2026-02-02",
    end_date: "2026-04-24",
    total_weeks: 12,
    current_week: 6,
  },
  semLabel: "2025-2026学年 第3学期",
  stage: "申请备战期",
  course_progress: [
    {
      course: "MHF4U",
      submittedCount: 10,
      missingCount: 2,
      completion: 83.3,
      current_grade: 89.4,
      grade_updated_at: Date.now(),
      aolSubmitted: 3,
      aolMissing: 1,
      aol_details: [
        { name: "Unit Test 2", score: 91, max: 100, category: "Assessment of Learning", weight: 40 },
        { name: "Midterm Prep Quiz", score: 86, max: 100, category: "Assessment of Learning", weight: 20 },
      ],
      isCurrentSemester: true,
    },
    {
      course: "ENG4U",
      submittedCount: 8,
      missingCount: 1,
      completion: 88.9,
      current_grade: 84.2,
      grade_updated_at: Date.now(),
      aolSubmitted: 2,
      aolMissing: 0,
      aol_details: [
        { name: "Literary Essay", score: 84, max: 100, category: "Assessment of Learning", weight: 30 },
      ],
      isCurrentSemester: true,
    },
  ],
  missing_items: [
    { course: "MHF4U", assignmentName: "Quiz 9", assignmentLink: "" },
    { course: "MHF4U", assignmentName: "Chapter Review", assignmentLink: "" },
    { course: "ENG4U", assignmentName: "Reading Journal", assignmentLink: "" },
  ],
  attention_items: [
    { type: "low_score", course: "MHF4U", assignmentName: "Functions Quiz", assignmentLink: "", nature: "AoF", score: 52, maxScore: 100 },
  ],
  recent_submitted: [
    { course: "MHF4U", assignmentName: "Homework Set 7", submittedAt: Date.now() - 86400000, status: "已提交", assignmentLink: "" },
    { course: "ENG4U", assignmentName: "Poetry Reflection", submittedAt: Date.now() - 2 * 86400000, status: "迟交", assignmentLink: "" },
    { course: "MHF4U", assignmentName: "Trigonometry Notes", submittedAt: Date.now() - 3 * 86400000, status: "已提交", assignmentLink: "" },
  ],
  recommendations: [
    { title: "优先处理缺交：复活与翻盘", anchorText: "4.8 危机关：复活与翻盘" },
    { title: "建立每日循环，止住连锁迟交", anchorText: "4.2 每日循环 Daily Loop" },
  ],
  missing_total: 3,
  submitted_total: 18,
  combo: null,
  upcoming_deadlines: [
    { date_ms: Date.now() + 86400000, course: "MHF4U", name: "Chapter 6 Test", category: "Assessment of Learning", is_aol: true, weight: 35, assignmentLink: "" },
    { date_ms: Date.now() + 3 * 86400000, course: "ENG4U", name: "Essay Final Draft", category: "Assessment of Learning", is_aol: true, weight: 20, assignmentLink: "" },
    { date_ms: Date.now() + 6 * 86400000, course: "MHF4U", name: "Weekly Practice", category: "Assessment for Learning", is_aol: false, assignmentLink: "" },
  ],
  notices: [
    { type: "info", title: "📢 通知", body: "本周四晚 8 点进行选课答疑。" },
  ],
};

const GUIDE_ANCHOR_MAP = {
  "4.8 危机关：复活与翻盘": "#aol-recovery",
  "4.4 作业关：Rubric 狙击手": "#rubric",
  "4.2 每日循环 Daily Loop": "#maintain",
  "4.1 两个快速启动清单（任选其一，从今天开始）": "#onboarding",
  "七、终极任务": "#future",
};

const COMBO_MILESTONES = [
  [40, "全学期连击。这学期你做到了。"],
  [20, "半学期准时提交，你已经把它变成了习惯。"],
  [10, "两周连击，系统已经跑起来了。"],
  [5, "一整周都在节奏上。"],
  [3, "三天连击，继续压实。"],
  [1, "今天已经启动。"],
  [0, "先把今天补上，再重新连击。"],
];

const state = {
  data: null,
  raw: null,
  deadlines: [],
  selectedDateKey: "",
  calendarMonthOffset: 0,
};

const DEFAULT_FIXTURE_PATH = "/fixtures/chuhe-xiong-qea.json";
const LIVE_FETCH_TIMEOUT_MS = 12000;
const HOVER_OFFSET_PX = 8;

let floatingHoverEl = null;
let floatingHoverHideTimer = 0;

function esc(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function ensureFloatingHover() {
  if (floatingHoverEl) return floatingHoverEl;
  floatingHoverEl = document.createElement("div");
  floatingHoverEl.className = "floating-hover";
  floatingHoverEl.hidden = true;
  floatingHoverEl.addEventListener("mouseenter", () => {
    if (floatingHoverHideTimer) clearTimeout(floatingHoverHideTimer);
  });
  floatingHoverEl.addEventListener("mouseleave", () => {
    scheduleFloatingHoverHide();
  });
  floatingHoverEl.addEventListener("click", (event) => {
    const target = event.target instanceof Element ? event.target.closest("[data-deadline-link]") : null;
    if (!target) return;
    const href = target.getAttribute("data-deadline-link") || "";
    if (!href) return;
    event.preventDefault();
    event.stopPropagation();
    window.open(href, "_blank", "noopener");
  });
  document.body.appendChild(floatingHoverEl);
  document.addEventListener("scroll", hideFloatingHover, true);
  window.addEventListener("resize", hideFloatingHover);
  return floatingHoverEl;
}

function hideFloatingHover() {
  if (!floatingHoverEl) return;
  if (floatingHoverHideTimer) {
    clearTimeout(floatingHoverHideTimer);
    floatingHoverHideTimer = 0;
  }
  floatingHoverEl.hidden = true;
  floatingHoverEl.className = "floating-hover";
  floatingHoverEl.innerHTML = "";
}

function scheduleFloatingHoverHide() {
  if (floatingHoverHideTimer) clearTimeout(floatingHoverHideTimer);
  floatingHoverHideTimer = window.setTimeout(() => {
    hideFloatingHover();
  }, 120);
}

function showFloatingHover(anchor, source, variant) {
  const layer = ensureFloatingHover();
  if (floatingHoverHideTimer) {
    clearTimeout(floatingHoverHideTimer);
    floatingHoverHideTimer = 0;
  }
  layer.className = `floating-hover floating-hover--${variant}`;
  layer.innerHTML = source.innerHTML;
  layer.hidden = false;

  const anchorRect = anchor.getBoundingClientRect();
  const layerRect = layer.getBoundingClientRect();
  const maxLeft = Math.max(8, window.innerWidth - layerRect.width - 8);
  const centeredLeft = anchorRect.left + (anchorRect.width / 2) - (layerRect.width / 2);
  const left = Math.min(Math.max(8, centeredLeft), maxLeft);
  let top = anchorRect.top - layerRect.height - HOVER_OFFSET_PX;
  if (top < 8) {
    top = Math.min(window.innerHeight - layerRect.height - 8, anchorRect.bottom + HOVER_OFFSET_PX);
  }
  layer.style.left = `${left}px`;
  layer.style.top = `${Math.max(8, top)}px`;
  layer.classList.add("is-visible");
}

function bindFloatingHoverTips() {
  document.querySelectorAll(".combo-cell").forEach((cell) => {
    const tip = cell.querySelector(".combo-cell__tip");
    if (!tip) return;
    cell.onmouseenter = () => showFloatingHover(cell, tip, "combo");
    cell.onmouseleave = () => scheduleFloatingHoverHide();
    cell.onfocus = () => showFloatingHover(cell, tip, "combo");
    cell.onblur = () => scheduleFloatingHoverHide();
  });

  document.querySelectorAll("[data-calendar-day]").forEach((day) => {
    const tip = day.querySelector(".calendar-day__tooltip");
    if (!tip) return;
    day.onmouseenter = () => showFloatingHover(day, tip, "calendar");
    day.onmouseleave = () => scheduleFloatingHoverHide();
    day.onfocus = () => showFloatingHover(day, tip, "calendar");
    day.onblur = () => scheduleFloatingHoverHide();
  });
}

function formatDateCN(value) {
  const date = toDate(value);
  if (!date) return "暂无";
  return `${date.getMonth() + 1}月${date.getDate()}日`;
}

function formatDateTimeCN(value) {
  const date = toDate(value);
  if (!date) return "暂无";
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  return `${date.getMonth() + 1}月${date.getDate()}日 ${hh}:${mm}`;
}

function formatISODate(value) {
  const date = toDate(value);
  if (!date) return "";
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function toDate(value) {
  if (value == null || value === "") return null;
  if (value instanceof Date) return isNaN(value.getTime()) ? null : value;
  if (typeof value === "number") {
    const d = new Date(value);
    return isNaN(d.getTime()) ? null : d;
  }
  const numeric = Number(value);
  if (!isNaN(numeric) && numeric > 1000000000000) {
    const d = new Date(numeric);
    return isNaN(d.getTime()) ? null : d;
  }
  const d = new Date(value);
  return isNaN(d.getTime()) ? null : d;
}

function courseCode(course) {
  return String(course || "").trim() || "---";
}

function clampText(value, maxLen) {
  const text = String(value || "").trim();
  if (!text || text.length <= maxLen) return text;
  return `${text.slice(0, Math.max(1, maxLen - 1))}…`;
}

function mergeCourseNames(...courseLists) {
  const seen = new Set();
  const merged = [];
  for (const courseList of courseLists) {
    for (const course of courseList || []) {
      const value = String(course || "").trim();
      if (!value || seen.has(value)) continue;
      seen.add(value);
      merged.push(value);
    }
  }
  return merged;
}

function deadlineDisplayType(deadline) {
  const name = `${deadline?.name || ""} ${deadline?.category || ""}`;
  if (deadline?.is_aol || /assessment\s+of\s+learning|aol/i.test(name)) return "AoL";
  if (deadline?.category) return "Coursework";
  return "";
}

function deadlinePillLabel(deadline) {
  const parts = [];
  const displayType = deadline?.displayType || deadlineDisplayType(deadline);
  const weight = deadline?.weight;
  if (displayType) parts.push(displayType);
  if (weight != null && weight !== "") parts.push(`${weight}%`);
  return parts.join(" / ");
}

function deadlineCellLabel(deadlines) {
  if (!deadlines.length) return "";
  if (deadlines.length === 1) {
    const deadline = deadlines[0];
    if (deadline.is_aol || /aol/i.test(deadline.name || "")) return "AoL";
    return clampText(courseCode(deadline.course), 8);
  }
  return `+${deadlines.length}`;
}

function describeCourseRisk(course) {
  if (course.isCurrentSemester === false) {
    return { tone: "muted", label: "历史学期" };
  }
  if ((course.missingCount || 0) >= 5 || (course.completion || 0) < 35) {
    return { tone: "danger", label: "高风险" };
  }
  if ((course.missingCount || 0) > 0 || (course.completion || 0) < 60) {
    return { tone: "warn", label: "需补救" };
  }
  return { tone: "ok", label: "正常推进" };
}

function comboMessage(streak) {
  for (const [n, msg] of COMBO_MILESTONES) {
    if (streak >= n) return msg;
  }
  return "";
}

function computeComboFromSubmissions(submissions, todayStr, semesterStart, semesterEnd) {
  const today = new Date(`${todayStr}T00:00:00`);
  const dayMap = {};

  for (const submission of submissions || []) {
    const date = toDate(submission.submittedAt);
    if (!date) continue;
    const key = formatISODate(date);
    if (!dayMap[key]) dayMap[key] = [];
    dayMap[key].push({
      course: submission.course || "",
      assignmentName: submission.assignmentName || "",
    });
  }

  let streak = 0;
  for (let offset = 0; offset <= 30; offset++) {
    const d = new Date(today);
    d.setDate(today.getDate() - offset);
    const key = formatISODate(d);
    if (dayMap[key]) streak += 1;
    else if (offset > 0) break;
  }

  let firstMonth;
  let lastMonth;
  const startDate = semesterStart ? new Date(`${semesterStart}T00:00:00`) : null;
  const endDate = semesterEnd ? new Date(`${semesterEnd}T00:00:00`) : null;

  if (startDate && endDate && !isNaN(startDate) && !isNaN(endDate)) {
    firstMonth = { year: startDate.getFullYear(), month: startDate.getMonth() + 1 };
    const cap = endDate < today ? endDate : today;
    lastMonth = { year: cap.getFullYear(), month: cap.getMonth() + 1 };
  } else {
    const previousMonth = new Date(today.getFullYear(), today.getMonth() - 1, 1);
    firstMonth = { year: previousMonth.getFullYear(), month: previousMonth.getMonth() + 1 };
    lastMonth = { year: today.getFullYear(), month: today.getMonth() + 1 };
  }

  const months = [];
  let year = firstMonth.year;
  let month = firstMonth.month;
  while (year < lastMonth.year || (year === lastMonth.year && month <= lastMonth.month)) {
    const daysInMonth = new Date(year, month, 0).getDate();
    const label = `${month}月`;
    const days = {};
    const dayDetails = {};

    for (let day = 1; day <= daysInMonth; day++) {
      const key = `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
      const current = new Date(year, month - 1, day);
      if (current > today) {
        days[key] = "future";
      } else if (dayMap[key]) {
        days[key] = "hit";
        const details = {};
        for (const item of dayMap[key]) {
          const c = courseCode(item.course);
          details[c] = (details[c] || 0) + 1;
        }
        dayDetails[key] = details;
      } else {
        days[key] = "no_assignment";
      }
    }

    months.push({ label, year, month, days, day_details: dayDetails });
    month += 1;
    if (month > 12) {
      month = 1;
      year += 1;
    }
  }

  return { current_streak: streak, today: todayStr, months };
}

function normalizeApiResponse(raw) {
  const todayStr = new Date().toISOString().slice(0, 10);

  const recentSubmitted = (raw.recentSubmissions || []).map((item) => ({
    course: item.course || "",
    assignmentName: item.assignmentName || item.assignmentname || "",
    submittedAt: item.submittedAt || item.submittedat || "",
    status: item.status || "",
    assignmentLink: item.link || "",
  }));

  const missingItems = (raw.missingItems || []).map((item) => ({
    course: item.course || "",
    assignmentName: item.assignmentName || item.assignmentname || "",
    assignmentLink: item.assignmentLink || item.link || "",
  }));

  const attentionItems = (raw.attentionItems || []).map((item) => ({
    type: item.type || "missing",
    course: item.course || "",
    assignmentName: item.assignmentName || "",
    assignmentLink: item.assignmentLink || item.link || "",
    nature: item.nature || "",
    score: item.score ?? null,
    maxScore: item.maxScore ?? null,
  }));

  const upcomingDeadlines = (raw.upcomingDeadlines || []).map((deadline) => ({
    ...deadline,
    assignmentLink: deadline.assignmentLink || deadline.link || "",
    displayType: deadlineDisplayType(deadline),
  }));

  const courseProgress = (raw.courseProgress || []).map((course) => ({
    course: course.course || "",
    submittedCount: course.submittedCount || 0,
    missingCount: course.missingCount || 0,
    completion: course.completion || 0,
    current_grade: course.current_grade || null,
    grade_updated_at: course.grade_updated_at || null,
    aol_details: (course.aol_details || []).map((detail) => ({
      name: detail.name || "",
      score: detail.score ?? 0,
      max: detail.max ?? 0,
      category: detail.category || "",
      weight: detail.weight ?? null,
    })),
    aolSubmitted: course.aolSubmitted || 0,
    aolMissing: course.aolMissing || 0,
    semester: course.semester || null,
    sectionNid: course.sectionNid || null,
    isCurrentSemester: course.isCurrentSemester !== false,
  }));
  const courseProgressCodes = new Set(courseProgress.map((course) => String(course.course || "").trim()).filter(Boolean));
  const missingByCourseRaw = raw.missingByCourse || {};
  const missingCounts = new Map();
  for (const [courseName, count] of Object.entries(missingByCourseRaw)) {
    const key = String(courseName || "").trim();
    if (!key) continue;
    missingCounts.set(key, Number(count) || 0);
  }
  for (const item of missingItems) {
    const key = String(item.course || "").trim();
    if (!key || missingCounts.has(key)) continue;
    missingCounts.set(key, (missingCounts.get(key) || 0) + 1);
  }

  const fallbackCourses = mergeCourseNames(
    (raw.courses || []).map((course) => (typeof course === "string" ? course : course?.name || "")),
    missingItems.map((item) => item.course || ""),
    attentionItems.map((item) => item.course || ""),
    recentSubmitted.map((item) => item.course || ""),
    upcomingDeadlines.map((item) => item.course || ""),
  )
    .filter((course) => !courseProgressCodes.has(course))
    .map((course) => {
      const missingCount = missingCounts.get(course) || 0;
      return {
        course,
        submittedCount: 0,
        missingCount,
        completion: 0,
        current_grade: null,
        grade_updated_at: null,
        aol_details: [],
        aolSubmitted: 0,
        aolMissing: 0,
        semester: null,
        sectionNid: null,
        isCurrentSemester: true,
      };
    });

  const finalCourseProgress = [...courseProgress, ...fallbackCourses];

  const schoolYear = raw.schoolYear || "";
  const semesterNum = raw.semesterNum || "";
  let semLabel = "";
  if (schoolYear) semLabel += `${schoolYear}学年`;
  if (semesterNum) semLabel += `${semLabel ? " " : ""}第${semesterNum}学期`;

  const creditsEarned = raw.creditsEarned != null && raw.creditsEarned !== "" ? Number(raw.creditsEarned) : null;
  const creditsTarget = raw.creditsTarget != null && raw.creditsTarget !== "" ? Number(raw.creditsTarget) : null;
  const creditsRemaining = creditsEarned != null && creditsTarget != null
    ? Math.max(creditsTarget - creditsEarned, 0)
    : null;

  const student = {
    name: raw.studentName || "",
    pinyin: raw.studentName || "",
    grade: null,
    credits_earned: creditsEarned,
    credits_remaining: creditsRemaining,
  };

  const missingTotal = raw.missingTotal ?? 0;
  const systemInsights = [];
  if (missingTotal >= 10) {
    systemInsights.push({ type: "urgent", title: "⚠️ 缺交预警", body: `共 ${missingTotal} 个作业未提交，请优先处理。` });
  } else if (missingTotal > 0) {
    systemInsights.push({ type: "warn", title: "🔶 待处理缺交", body: `${missingTotal} 个作业待补交。` });
  } else {
    systemInsights.push({ type: "ok", title: "✓ 无缺交", body: "本学期所有作业均已提交，继续保持！" });
  }

  const worstCourse = finalCourseProgress
    .filter((course) => course.completion < 50 && course.missingCount > 0)
    .sort((a, b) => a.completion - b.completion)[0];
  if (worstCourse) {
    systemInsights.push({ type: "warn", title: "📉 课程警告", body: `${worstCourse.course} 完成度仅 ${Math.round(worstCourse.completion)}%，需重点关注。` });
  }

  const osslt = raw.osslt || "";
  if (osslt) {
    const isPass = /通过|pass|yes/i.test(osslt);
    systemInsights.push({ type: isPass ? "ok" : "info", title: "OSSLT", body: osslt });
  }

  const noticesRaw = raw.noticesRaw || "";
  const noticesFromRoster = noticesRaw
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => ({ type: "info", title: "📢 通知", body: line }));
  const noticesFromServer = (raw.notices || []).map((notice) => ({
    type: "info",
    title: notice.title || "📢 通知",
    body: notice.body || notice.content || "",
  }));

  return {
    student,
    semester: {
      start_date: raw.semesterStart || "",
      end_date: raw.semesterEnd || "",
      total_weeks: raw.totalWeeks || null,
      current_week: raw.currentWeek || null,
    },
    semLabel,
    stage: raw.stage || "在读",
    course_progress: finalCourseProgress,
    missing_items: missingItems,
    attention_items: attentionItems,
    recent_submitted: recentSubmitted,
    recommendations: raw.recommendations || [],
    missing_total: missingTotal,
    submitted_total: raw.submittedTotal ?? 0,
    combo: raw.combo || computeComboFromSubmissions(recentSubmitted, todayStr, raw.semesterStart, raw.semesterEnd),
    upcoming_deadlines: upcomingDeadlines,
    notices: [...noticesFromServer, ...noticesFromRoster],
    system_insights: systemInsights,
    recentWeekLabel: raw.recentWeekLabel || "",
  };
}

function getParams() {
  const params = new URLSearchParams(location.search);
  const isProductionEntry = location.pathname === "/" || location.pathname === "/index.html";
  return {
    tenant: (params.get("t") || "").trim(),
    student: (params.get("student") || "").trim(),
    live: isProductionEntry || (params.get("live") || "").trim() === "1",
    fixture: (params.get("fixture") || "").trim(),
  };
}

function showError(message) {
  document.getElementById("previewLoading").hidden = true;
  document.getElementById("previewApp").hidden = true;
  const error = document.getElementById("previewError");
  error.hidden = false;
  error.innerHTML = `
    <div class="error-screen__inner">
      <div class="loading-screen__eyebrow">PREVIEW LOAD ERROR</div>
      <div class="error-screen__title">页面未能装载数据</div>
      <div class="error-screen__body">${esc(message)}</div>
      <a class="error-screen__link" href="/preview-terminal-static.html${location.search}">查看静态快照</a>
    </div>
  `;
  resolvePreviewBoot();
}

window.addEventListener("error", (event) => {
  const message = event?.error?.stack || event?.message || "Unknown preview error";
  showError(message);
});

window.addEventListener("unhandledrejection", (event) => {
  const reason = event?.reason;
  const message =
    reason?.stack ||
    reason?.message ||
    (typeof reason === "string" ? reason : JSON.stringify(reason));
  showError(message || "Unhandled promise rejection");
});

function setTopLinks() {
  const query = location.search || "";
  const dashboardLink = document.getElementById("liveDashboardLink");
  const isProductionEntry = location.pathname === "/" || location.pathname === "/index.html";
  dashboardLink.href = isProductionEntry ? `/preview-terminal-static.html${query}` : `/${query}`;
  dashboardLink.textContent = isProductionEntry ? "查看静态快照" : "查看现网版";
  document.getElementById("guideLink").href = `/guide.html${query}`;
}

function buildFocusItems(data) {
  const items = [];
  const missingTop = (data.missing_items || []).slice(0, 2).map((item) => ({
    tone: "danger",
    badge: "Missing",
    title: item.assignmentName,
    meta: `${courseCode(item.course)} · 尽快补交，先提交可评分版本。`,
    href: item.assignmentLink || "",
  }));

  const lowScoreTop = (data.attention_items || [])
    .filter((item) => item.type === "low_score")
    .slice(0, 2)
    .map((item) => ({
      tone: "warn",
      badge: "Low Score",
      title: item.assignmentName,
      meta: `${courseCode(item.course)} · ${item.score ?? "-"} / ${item.maxScore ?? "-"}，建议先看 rubric 再修订。`,
      href: item.assignmentLink || "",
    }));

  items.push(...missingTop, ...lowScoreTop);

  if (!items.length) {
    items.push({
      tone: "ok",
      badge: "Clear",
      title: "当前没有缺交或低分预警",
      meta: "这时最适合把 upcoming DDL 提前拆成小任务，避免下一次集中爆发。",
      href: "",
    });
  }

  return items.slice(0, 4);
}

function renderProfile(data) {
  const profileName = document.getElementById("profileName");
  const profileMeta = document.getElementById("profileMeta");
  const profileAvatar = document.getElementById("profileAvatar");
  const semesterLabel = document.getElementById("semesterLabel");
  const semesterDates = document.getElementById("semesterDates");
  const creditNumbers = document.getElementById("creditNumbers");
  const creditHint = document.getElementById("creditHint");
  const creditFill = document.getElementById("creditFill");
  const semesterFill = document.getElementById("semesterFill");
  const semesterProgressText = document.getElementById("semesterProgressText");

  profileName.textContent = data.student.name || "未命名学生";
  profileMeta.textContent = `${data.course_progress.length} 门课程`;
  profileAvatar.textContent = data.student.name || "QEA";
  semesterLabel.textContent = data.semLabel || "当前学期";

  const endDate = toDate(data.semester.end_date);
  const now = new Date();
  let semesterEndHint = "";
  if (endDate) {
    const diffDays = Math.ceil((new Date(endDate.getFullYear(), endDate.getMonth(), endDate.getDate()) - new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 86400000);
    semesterEndHint = diffDays >= 0 ? ` · 距离学期结束还有 ${diffDays} 天` : " · 学期已结束";
  }
  semesterDates.textContent = `${data.semester.start_date || "待定"} 至 ${data.semester.end_date || "待定"}${semesterEndHint}`;

  const earned = data.student.credits_earned ?? 0;
  const remaining = data.student.credits_remaining ?? 0;
  const target = earned + remaining;
  const creditPct = target > 0 ? (earned / target) * 100 : 0;
  creditNumbers.textContent = `${earned} / ${target || "?"}`;
  creditHint.textContent = remaining > 0 ? `距离目标还差 ${remaining} 学分。` : "学分目标已完成或未配置。";
  creditFill.style.width = `${Math.max(0, Math.min(creditPct, 100))}%`;

  const totalWeeks = data.semester.total_weeks || 0;
  const currentWeek = data.semester.current_week || 0;
  const semesterPct = totalWeeks > 0 ? (currentWeek / totalWeeks) * 100 : 0;
  semesterProgressText.textContent = `${currentWeek || "-"} / ${totalWeeks || "-"}`;
  semesterFill.style.width = `${Math.max(0, Math.min(semesterPct, 100))}%`;
}

function renderHero(data) {
  document.getElementById("heroTitle").textContent = `${data.student.name || "同学"}，先处理最卡分的地方。`;
  const riskCourse = (data.course_progress || [])
    .filter((course) => course.isCurrentSemester !== false)
    .sort((a, b) => {
      const aRisk = (a.missingCount || 0) * 10 + (100 - (a.completion || 0));
      const bRisk = (b.missingCount || 0) * 10 + (100 - (b.completion || 0));
      return bRisk - aRisk;
    })[0];
  document.getElementById("heroSubtitle").textContent =
    data.missing_total > 0
      ? `当前共有 ${data.missing_total} 个缺交，优先提交可评分版本；${riskCourse ? `${riskCourse.course} 现在最需要补进度。` : "先清理最临近 DDL。"}`
      : "当前没有缺交压力，可以把注意力转向 upcoming DDL 的提前拆解和高权重项目准备。";
  const overviewMeta = document.getElementById("mobileTabOverviewMeta");
  const courseMeta = document.getElementById("mobileTabCourseMeta");
  const deadlineMeta = document.getElementById("mobileTabDeadlineMeta");
  if (overviewMeta) overviewMeta.textContent = `${data.missing_total || 0} missing`;
  if (courseMeta) courseMeta.textContent = `${(data.course_progress || []).length} courses`;
  if (deadlineMeta) deadlineMeta.textContent = `${(data.upcoming_deadlines || []).length} ddl`;
}

function renderFocus(data) {
  const html = buildFocusItems(data)
    .map((item) => `
      <article class="focus-item">
        <span class="focus-item__badge focus-item__badge--${esc(item.tone)}">${esc(item.badge)}</span>
        <div class="focus-item__content">
          <div class="focus-item__head">
            <div class="focus-item__title">${esc(item.title)}</div>
            ${item.href ? `<a class="focus-item__cta" href="${esc(item.href)}" target="_blank" rel="noopener">前往作业 →</a>` : ""}
          </div>
          <div class="focus-item__meta">${esc(item.meta)}</div>
        </div>
      </article>
    `)
    .join("");
  document.getElementById("focusList").innerHTML = html;
}

function buildTerminalRows(items, kind) {
  if (!items.length) return `<div class="terminal-empty">当前没有${kind === "missing" ? "未交" : kind === "recent" ? "近期提交" : "评分"}记录。</div>`;

  return `
    <div class="terminal-list">
      ${items
        .map((item) => {
          if (kind === "aol") {
            const pct = item.max ? Math.round((item.score / item.max) * 100) : null;
            return `
              <div class="terminal-row">
                <div class="terminal-row__main">
                  <div class="terminal-row__title">${esc(item.name)}</div>
                  <div class="terminal-row__sub">${esc(item.category || "成绩条目")}</div>
                </div>
                <div class="terminal-row__side">
                  <div class="terminal-row__score">${esc(item.score)} / ${esc(item.max)}${pct != null ? ` (${pct}%)` : ""}</div>
                  <div class="terminal-row__status">${item.weight != null ? `权重 ${esc(item.weight)}%` : "无权重信息"}</div>
                </div>
              </div>
            `;
          }

          if (kind === "missing") {
            return `
              <div class="terminal-row">
                <div class="terminal-row__main">
                  <div class="terminal-row__title">${esc(item.assignmentName)}</div>
                  <div class="terminal-row__sub">${esc(courseCode(item.course))}</div>
                </div>
                <div class="terminal-row__side">
                  ${item.assignmentLink ? `<a class="focus-item__cta" href="${esc(item.assignmentLink)}" target="_blank" rel="noopener">前往作业 →</a>` : `<div class="terminal-row__status">暂无链接</div>`}
                </div>
              </div>
            `;
          }

          return `
            <div class="terminal-row">
              <div class="terminal-row__main">
                <div class="terminal-row__title">${esc(item.assignmentName)}</div>
                <div class="terminal-row__sub">${esc(courseCode(item.course))} · ${esc(formatDateTimeCN(item.submittedAt))}</div>
              </div>
              <div class="terminal-row__side">
                <div class="terminal-row__score">${esc(item.status || "已提交")}</div>
              </div>
            </div>
          `;
        })
        .join("")}
    </div>
  `;
}

function renderCourseCard(course, data, options = {}) {
  const missingItems = (data.missing_items || []).filter((item) => item.course === course.course);
  const recentItems = (data.recent_submitted || []).filter((item) => item.course === course.course);
  const semesterChip = course.semester ? `<span class="course-card__chip">${esc(course.semester)}</span>` : "";
  const risk = describeCourseRisk(course);
  const gradeText = course.current_grade != null ? `${course.current_grade}%` : "--";
  const updatedText = course.grade_updated_at ? `更新于 ${formatDateCN(course.grade_updated_at)}` : "暂无总评分";
  const completion = Math.max(0, Math.min(Number(course.completion) || 0, 100));
  const defaultMissingOpen = options.defaultMissingOpen === true;

  return `
    <article class="terminal-card terminal-card--${esc(risk.tone)}" data-course-card>
      <div class="terminal-card__head">
        <div class="course-card__title-block">
          <div class="course-card__title">
            <span class="course-card__code">&gt; ${esc(course.course)}</span>
          </div>
          <div class="course-card__chips">
            ${semesterChip}
          </div>
        </div>
        <div class="course-card__grade">
          ${esc(gradeText)}
          <span class="course-card__grade-sub">${esc(updatedText)}</span>
        </div>
      </div>
      <div class="terminal-card__body">
        <div class="course-card__progress-head">
          <span>当前进度</span>
          <div class="course-card__progress-meta">
            <strong>${esc(completion)}%</strong>
            <span class="course-card__chip course-card__chip--${esc(risk.tone)}">${esc(risk.label)}</span>
          </div>
        </div>
        <div class="progress-bar">
          <div class="progress-bar__rail">
            <div class="progress-bar__fill" style="width:${completion}%"></div>
          </div>
        </div>
        <div class="course-card__stats">
          <span class="course-card__stat"><strong>${esc(course.submittedCount)}</strong> 已交</span>
          <span class="course-card__stat"><strong>${esc(course.missingCount)}</strong> 缺交</span>
          <span class="course-card__stat"><strong>${esc(course.aol_details?.length || 0)}</strong> 已评分</span>
        </div>

        <div class="terminal-sections">
          ${buildCourseSection("aol", "AoL 评分详情", course.aol_details || [], buildTerminalRows(course.aol_details || [], "aol"), false)}
          ${buildCourseSection("missing", "未提交作业", missingItems, buildTerminalRows(missingItems, "missing"), defaultMissingOpen && missingItems.length > 0)}
          ${buildCourseSection("recent", "本周提交记录", recentItems, buildTerminalRows(recentItems, "recent"), false)}
        </div>
      </div>
    </article>
  `;
}

function renderCourses(data) {
  const container = document.getElementById("courseList");
  const currentCourses = (data.course_progress || []).filter((course) => course.isCurrentSemester !== false);
  const historyCourses = (data.course_progress || []).filter((course) => course.isCurrentSemester === false);

  const currentHtml = currentCourses
    .map((course) => renderCourseCard(course, data, { defaultMissingOpen: false }))
    .join("");

  const historyHtml = historyCourses.length
    ? `
      <section class="course-history-block terminal-section" data-terminal-section>
        <button class="terminal-section__toggle" type="button">
          <span class="terminal-section__toggle-main">
            <span class="terminal-section__icon">[+]</span>
            <span class="terminal-section__label">历史学期</span>
          </span>
          <span class="terminal-section__count">${historyCourses.length}</span>
        </button>
        <div class="terminal-section__body">
          <div class="course-list course-list--history">
            ${historyCourses.map((course) => renderCourseCard(course, data, { defaultMissingOpen: false })).join("")}
          </div>
        </div>
      </section>
    `
    : "";

  container.innerHTML = `${currentHtml}${historyHtml}` || `<div class="terminal-empty">当前没有课程数据。</div>`;
}

function buildCourseSection(kind, label, items, body, isOpen) {
  const icon = isOpen ? "[-]" : "[+]";
  return `
    <section class="terminal-section ${isOpen ? "is-open" : ""}" data-terminal-section>
      <button class="terminal-section__toggle" type="button">
        <span class="terminal-section__toggle-main">
          <span class="terminal-section__icon">${icon}</span>
          <span class="terminal-section__label">${esc(label)}</span>
        </span>
        <span class="terminal-section__count">${Array.isArray(items) ? items.length : 0}</span>
      </button>
      <div class="terminal-section__body">${body}</div>
    </section>
  `;
}

function bindCourseSections() {
  document.querySelectorAll("[data-terminal-section]").forEach((section) => {
    const button = section.querySelector(".terminal-section__toggle");
    const icon = section.querySelector(".terminal-section__icon");
    button.addEventListener("click", () => {
      const open = section.classList.toggle("is-open");
      icon.textContent = open ? "[-]" : "[+]";
    });
  });
}

function renderRecentTable(data) {
  document.getElementById("recentWeekLabel").textContent = data.recentWeekLabel ? `统计区间 ${data.recentWeekLabel}` : "";
  const container = document.getElementById("recentTable");
  const rows = (data.recent_submitted || []).map((item) => `
    <div class="terminal-table__row">
      <div class="terminal-table__course">${esc(courseCode(item.course))}</div>
      <div>${esc(item.assignmentName || "")}</div>
      <div>${esc(formatDateCN(item.submittedAt))}</div>
      <div class="terminal-table__status">${esc(item.status || "已提交")}</div>
    </div>
  `).join("");

  container.innerHTML = `
    <div class="terminal-table__head">
      <div>Course</div>
      <div>Assignment</div>
      <div>Date</div>
      <div>Status</div>
    </div>
    ${rows || `<div class="terminal-table__row"><div class="terminal-empty">暂无近期提交记录。</div></div>`}
  `;
}

function renderAlerts(data) {
  const container = document.getElementById("alertList");
  const query = location.search || "";
  const guideItems = (data.recommendations || []).map((item) => {
    const anchor = GUIDE_ANCHOR_MAP[item.anchorText] || "";
    return `
      <a class="alert-guide-list__link" href="/guide.html${query}${anchor}">
        <span class="alert-guide-list__title">${esc(item.title || "阅读建议")}</span>
        <span class="alert-guide-list__meta">${esc(item.anchorText || "前往对应章节")}</span>
      </a>
    `;
  }).join("");
  const guideCards = guideItems ? `
    <article class="alert-card alert-card--guide-group">
      <span class="alert-card__tag alert-card__tag--guide">guide</span>
      <div class="alert-card__title">通关指南推荐</div>
      <div class="alert-guide-list">${guideItems}</div>
    </article>
  ` : "";
  const noticeCards = (data.notices || []).map((alert) => `
    <article class="alert-card">
      <span class="alert-card__tag alert-card__tag--${esc(alert.type || "info")}">notice</span>
      <div class="focus-item__title">${esc(alert.title || "通知")}</div>
      <div class="alert-card__body">${esc(alert.body || "")}</div>
    </article>
  `).join("");
  container.innerHTML = guideCards || noticeCards
    ? `${guideCards}${noticeCards}`
    : `<div class="notice-empty">暂无可推送的通关指南或老师通知。</div>`;
}

function buildCalendarDeadlineMap(deadlines) {
  const map = new Map();
  for (const deadline of deadlines || []) {
    const key = formatISODate(deadline.date_ms);
    if (!key) continue;
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(deadline);
  }
  return map;
}

function renderCalendar() {
  const label = document.getElementById("calendarLabel");
  const grid = document.getElementById("calendarGrid");
  const now = new Date();
  const monthDate = new Date(now.getFullYear(), now.getMonth() + state.calendarMonthOffset, 1);
  const year = monthDate.getFullYear();
  const month = monthDate.getMonth();
  const todayKey = formatISODate(now);
  const deadlineMap = buildCalendarDeadlineMap(state.deadlines);
  const weekdays = ["日", "一", "二", "三", "四", "五", "六"];
  const firstDay = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  label.textContent = `${year}.${String(month + 1).padStart(2, "0")}`;

  const items = weekdays.map((day) => `<div class="calendar-grid__weekday">${day}</div>`);

  for (let i = 0; i < firstDay; i++) {
    items.push(`<div class="calendar-day calendar-day--empty"></div>`);
  }

  for (let day = 1; day <= daysInMonth; day++) {
    const key = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const deadlines = deadlineMap.get(key) || [];
    const selected = state.selectedDateKey === key;
    const classes = [
      "calendar-day",
      key === todayKey ? "calendar-day--today" : "",
      deadlines.length ? "calendar-day--has-event" : "",
      selected ? "calendar-day--selected" : "",
    ].filter(Boolean).join(" ");
    items.push(`
      <button class="${classes}" type="button" data-calendar-day="${key}">
        <div class="calendar-day__head">
          <div class="calendar-day__number">${day}</div>
        </div>
        <div class="calendar-day__dots">
          ${deadlines.slice(0, 3).map((deadline) => `<span class="calendar-day__dot ${deadline.is_aol ? "calendar-day__dot--aol" : ""}"></span>`).join("")}
        </div>
        ${deadlines.length ? `
          <div class="calendar-day__tooltip">
            ${deadlines.map((deadline) => `
              <article class="calendar-tooltip__item ${deadline.assignmentLink ? "calendar-tooltip__item--link" : ""}" ${deadline.assignmentLink ? `data-deadline-link="${esc(deadline.assignmentLink)}"` : ""}>
                <div class="calendar-tooltip__title">${esc(deadline.name || "")}${deadline.assignmentLink ? ` <span class="calendar-tooltip__cta">打开 →</span>` : ""}</div>
                <div class="calendar-tooltip__meta">${esc(courseCode(deadline.course))} · ${esc(formatDateTimeCN(deadline.date_ms))}</div>
                ${deadlinePillLabel(deadline) ? `<span class="calendar-tooltip__pill">${esc(deadlinePillLabel(deadline))}</span>` : ""}
              </article>
            `).join("")}
          </div>
        ` : ""}
      </button>
    `);
  }

  grid.innerHTML = items.join("");

  if (!state.selectedDateKey) {
    const firstDeadline = state.deadlines[0];
    state.selectedDateKey = firstDeadline ? formatISODate(firstDeadline.date_ms) : todayKey;
  }

  grid.querySelectorAll("[data-calendar-day]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedDateKey = button.getAttribute("data-calendar-day") || "";
      renderCalendar();
    });
  });

  grid.querySelectorAll("[data-deadline-link]").forEach((node) => {
    node.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const href = node.getAttribute("data-deadline-link") || "";
      if (!href) return;
      window.open(href, "_blank", "noopener");
    });
  });
  bindFloatingHoverTips();
}

function bindCalendarNav() {
  document.getElementById("calendarPrev").addEventListener("click", () => {
    state.calendarMonthOffset -= 1;
    renderCalendar();
  });
  document.getElementById("calendarNext").addEventListener("click", () => {
    state.calendarMonthOffset += 1;
    renderCalendar();
  });
}

function renderUpcomingList() {
  const container = document.getElementById("upcomingList");
  const items = (state.deadlines || []).slice(0, 3);
  if (!container) return;
  container.innerHTML = items.length
    ? items.map((item) => `
      <article class="upcoming-item ${item.assignmentLink ? "upcoming-item--link" : ""}" ${item.assignmentLink ? `data-deadline-link="${esc(item.assignmentLink)}"` : ""}>
        <div class="upcoming-item__date">${esc(formatDateCN(item.date_ms))}</div>
        <div>
          <div class="upcoming-item__title">${esc(item.name || "")}${item.assignmentLink ? ` <span class="calendar-tooltip__cta">打开 →</span>` : ""}</div>
          <div class="upcoming-item__meta">${esc(courseCode(item.course))} · ${esc(item.category || "DDL")}</div>
          ${deadlinePillLabel(item) ? `<span class="upcoming-item__pill">${esc(deadlinePillLabel(item))}</span>` : ""}
        </div>
      </article>
    `).join("")
    : `<div class="terminal-empty">暂无 upcoming 作业。</div>`;

  container.querySelectorAll("[data-deadline-link]").forEach((node) => {
    node.addEventListener("click", () => {
      const href = node.getAttribute("data-deadline-link") || "";
      if (!href) return;
      window.open(href, "_blank", "noopener");
    });
  });
}

function renderCombo(data) {
  const combo = data.combo || computeComboFromSubmissions(data.recent_submitted || [], new Date().toISOString().slice(0, 10), data.semester.start_date, data.semester.end_date);
  const months = Array.isArray(combo.months) ? combo.months : [];
  const cells = [];

  for (let i = months.length - 1; i >= 0; i--) {
    const month = months[i];
    const entries = Object.entries(month.days || {});
    for (let j = entries.length - 1; j >= 0; j--) {
      const [dateKey, status] = entries[j];
      const detail = month.day_details?.[dateKey];
      const tip = detail
        ? Object.entries(detail).map(([course, count]) => `${course}: ${count}`).join(" / ")
        : dateKey;
      cells.push({ status, tip: `${dateKey}${detail ? ` · ${tip}` : ""}` });
      if (cells.length >= 28) break;
    }
    if (cells.length >= 28) break;
  }

  while (cells.length < 28) {
    cells.push({ status: "empty", tip: "" });
  }

  document.getElementById("streakCount").textContent = `${combo.current_streak || 0} days`;
  document.getElementById("streakMessage").textContent = comboMessage(combo.current_streak || 0);
  document.getElementById("comboGrid").innerHTML = cells
    .reverse()
    .map((cell) => {
      const status = cell.status === "no_assignment" ? "no_assignment" : (cell.status || "empty");
      return `
      <div class="combo-cell combo-cell--${esc(status)}">
        ${cell.tip ? `<span class="combo-cell__tip">${esc(cell.tip)}</span>` : ""}
      </div>
    `;
    })
    .join("");
  bindFloatingHoverTips();
}

function maybeShowNotices(data, params) {
  const notices = data.notices || [];
  if (!notices.length) return;

  const key = `qea__preview_notice_seen__${params.tenant || "mock"}__${params.student || "mock"}`;
  if (localStorage.getItem(key) === "1") return;

  const modal = document.getElementById("noticeModal");
  const list = document.getElementById("noticeModalList");
  list.innerHTML = notices
    .map((alert) => `
      <div class="notice-modal__item">
        <div class="focus-item__title">${esc(alert.title || "通知")}</div>
        <div class="alert-card__body">${esc(alert.body || "")}</div>
      </div>
    `)
    .join("");

  const close = () => {
    localStorage.setItem(key, "1");
    modal.hidden = true;
  };

  modal.hidden = false;
  document.getElementById("noticeModalButton").onclick = close;
  modal.querySelectorAll("[data-close-notice]").forEach((node) => {
    node.onclick = close;
  });
}

function renderAll(data, raw, params) {
  hideFloatingHover();
  state.data = data;
  state.raw = raw;
  state.deadlines = (data.upcoming_deadlines || []).slice().sort((a, b) => (a.date_ms || 0) - (b.date_ms || 0));
  state.selectedDateKey = state.deadlines[0] ? formatISODate(state.deadlines[0].date_ms) : formatISODate(new Date());
  const now = new Date();
  if (state.deadlines[0]) {
    const firstDeadline = toDate(state.deadlines[0].date_ms);
    state.calendarMonthOffset = firstDeadline
      ? (firstDeadline.getFullYear() - now.getFullYear()) * 12 + (firstDeadline.getMonth() - now.getMonth())
      : 0;
  } else {
    state.calendarMonthOffset = 0;
  }

  renderProfile(data);
  renderHero(data);
  renderFocus(data);
  renderCourses(data);
  bindCourseSections();
  renderRecentTable(data);
  renderAlerts(data);
  renderCombo(data);
  renderUpcomingList();
  renderCalendar();
  maybeShowNotices(data, params);
}

function lsGet(key, ttl) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return null;
    if (Date.now() - (parsed.ts || 0) > ttl) {
      localStorage.removeItem(key);
      return null;
    }
    return parsed.data || null;
  } catch {
    return null;
  }
}

function lsSet(key, data) {
  try {
    localStorage.setItem(key, JSON.stringify({ data, ts: Date.now() }));
  } catch {}
}

async function fetchJsonWithTimeout(url, timeoutMs = LIVE_FETCH_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new Error("fetch_timeout")), timeoutMs);
  try {
    const resp = await fetch(url, { signal: controller.signal });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await resp.json();
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error(`实时数据请求超时（>${Math.round(timeoutMs / 1000)}s）`);
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

async function loadDashboardData(params) {
  const ttl = 25 * 60 * 1000;
  const cacheKey = `qea__preview__${params.tenant || "mock"}__${params.student || "mock"}`;
  const cached = lsGet(cacheKey, ttl);
  if (cached) {
    renderAll(normalizeApiResponse(cached), cached, params);
    document.getElementById("previewLoading").hidden = true;
    document.getElementById("previewApp").hidden = false;
    resolvePreviewBoot();
    fetchJsonWithTimeout(`/api/dashboard?t=${encodeURIComponent(params.tenant)}&student=${encodeURIComponent(params.student)}`, 8000)
      .then((data) => { if (data) lsSet(cacheKey, data); })
      .catch(() => {});
    return;
  }

  if (!params.tenant) {
    throw new Error("缺少租户参数，现网入口需要通过 ?t=租户 打开。");
  }
  const raw = await fetchJsonWithTimeout(`/api/dashboard?t=${encodeURIComponent(params.tenant)}&student=${encodeURIComponent(params.student)}`);
  lsSet(cacheKey, raw);
  renderAll(normalizeApiResponse(raw), raw, params);
  document.getElementById("previewLoading").hidden = true;
  document.getElementById("previewApp").hidden = false;
  resolvePreviewBoot();
}

async function loadFixtureData(params) {
  const fixturePath = params.fixture || DEFAULT_FIXTURE_PATH;
  const resp = await fetch(fixturePath, { cache: "no-store" });
  if (!resp.ok) throw new Error(`Fixture HTTP ${resp.status}`);
  const raw = await resp.json();
  renderAll(normalizeApiResponse(raw), raw, params);
  document.getElementById("previewLoading").hidden = true;
  document.getElementById("previewApp").hidden = false;
  resolvePreviewBoot();
}

function renderMockPreview() {
  const data = PREVIEW_MOCK_DATA.combo
    ? PREVIEW_MOCK_DATA
    : {
        ...PREVIEW_MOCK_DATA,
        combo: computeComboFromSubmissions(
          PREVIEW_MOCK_DATA.recent_submitted,
          new Date().toISOString().slice(0, 10),
          PREVIEW_MOCK_DATA.semester.start_date,
          PREVIEW_MOCK_DATA.semester.end_date
        ),
      };
  renderAll(data, data, { tenant: "", student: "" });
  document.getElementById("previewLoading").hidden = true;
  document.getElementById("previewApp").hidden = false;
  resolvePreviewBoot();
}

(function init() {
  setTopLinks();
  bindCalendarNav();

  const params = getParams();
  if (!params.live) {
    loadFixtureData(params).catch((error) => {
      console.warn("[preview-terminal] fixture load failed, fallback to mock:", error);
      renderMockPreview();
    });
    return;
  }

  loadDashboardData(params).catch((error) => {
    console.warn("[preview-terminal] API failed:", error);
    showError(error?.message || "实时数据装载失败");
  });
})();
