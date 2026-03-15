#!/usr/bin/env node
/* eslint-disable no-console */
const fs = require("fs");
const path = require("path");

function usage() {
  console.log("Usage:");
  console.log("  node interactive_web/scripts/analyze_navigation_profiles.js <admin_export.json> [--course=COURSE_CODE]");
  console.log("");
  console.log("Input:");
  console.log("  JSON array from /api/admin?t=<tenant>&key=<ADMIN_KEY>");
}

function safeNum(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function pct(numerator, denominator) {
  if (!Number.isFinite(numerator) || !Number.isFinite(denominator) || denominator <= 0) return null;
  return (numerator / denominator) * 100;
}

function isCurrentCourse(cp) {
  return cp && cp.isCurrentSemester !== false;
}

function isHighPriorityMissing(item) {
  const nature = String(item?.nature || "");
  return nature.includes("🔥");
}

function daysUntil(ts) {
  const n = safeNum(ts);
  if (n == null) return null;
  return Math.ceil((n - Date.now()) / 86400000);
}

function quantile(sortedVals, q) {
  if (!sortedVals.length) return null;
  const pos = (sortedVals.length - 1) * q;
  const base = Math.floor(pos);
  const rest = pos - base;
  if (sortedVals[base + 1] !== undefined) return sortedVals[base] + rest * (sortedVals[base + 1] - sortedVals[base]);
  return sortedVals[base];
}

function classify(student) {
  const r = student.submitRate;
  const hp = student.highPriorityMissing;
  const gAvg = student.gradeAvg;
  const gSpan = student.gradeSpan;
  const streak = student.streak;
  const ddl7 = student.ddl7;
  const aol7 = student.aol7;
  const trend = student.recentMomentum;

  if (r != null && r < 35 && hp >= 1) return "失速风险型";
  if ((ddl7 >= 2 || aol7 >= 1) && hp >= 1) return "临期救火型";
  if (gSpan != null && gSpan >= 18) return "偏科失衡型";
  if (gAvg != null && gAvg >= 80 && (streak < 4 || trend < 0)) return "高潜冲刺型";
  if (trend > 0 && r != null && r >= 45 && r < 75) return "慢热恢复型";
  return "稳定推进型";
}

function buildNavigatorAdvice(profile, s, phase) {
  const courseHint = s.worstCourse || s.topRiskCourse || "当前课程";
  const p1 = phase === 1;
  const p2 = phase === 2;
  const p3 = phase === 3;
  const p4 = phase === 4;

  if (profile === "失速风险型") {
    return [
      p1 ? `先稳住节奏：今天只做 ${courseHint} 的 1 个🔥任务。` : `立即止血：优先清掉 ${courseHint} 的🔥任务。`,
      "联系中教老师确认补交窗口和优先顺序。",
      "未来3天每天至少完成1个可提交任务。"
    ];
  }
  if (profile === "临期救火型") {
    return [
      `未来7天关键窗口较密集，优先处理 ${courseHint}。`,
      "把 AoL/高权重作业放在日程前半段。",
      "每天结束前核对一次截止日期和提交状态。"
    ];
  }
  if (profile === "偏科失衡型") {
    return [
      `主攻短板课程：${courseHint}。`,
      "保持强势课程最低维护投入，避免被反超。",
      "本周和老师确认一次短板课程提分路径。"
    ];
  }
  if (profile === "高潜冲刺型") {
    return [
      p3 || p4 ? "进入冲刺节奏：确保高权重任务先提交。" : "保持上升势头，避免节奏断档。",
      "把连击目标设为 7 天。",
      "每周复盘一次低分题型与反馈。"
    ];
  }
  if (profile === "慢热恢复型") {
    return [
      "恢复趋势已出现，保持固定提交时段。",
      "先确保本周零新增缺交。",
      "若有不确定任务，24小时内找老师确认。"
    ];
  }
  return [
    p1 ? "适应期继续建立节奏，不急于冲刺。" : "保持当前节奏，持续稳步推进。",
    "每周至少一次检查高优先任务清单。",
    "维持连击并避免新增缺交。"
  ];
}

function computePhase(currentWeek) {
  if (!Number.isFinite(currentWeek) || currentWeek <= 0) return 1;
  if (currentWeek <= 2) return 1;
  if (currentWeek <= 4) return 2;
  if (currentWeek <= 6) return 3;
  return 4;
}

function summarizeByCourse(students) {
  const map = new Map();
  for (const s of students) {
    for (const c of s.currentCourses) {
      if (!map.has(c.course)) {
        map.set(c.course, {
          course: c.course,
          students: 0,
          gradeVals: [],
          submitRates: [],
          missingVals: [],
          highPriorityMissingCount: 0
        });
      }
      const row = map.get(c.course);
      row.students += 1;
      const total = (c.submittedCount || 0) + (c.missingCount || 0);
      const sr = pct(c.submittedCount || 0, total);
      if (sr != null) row.submitRates.push(sr);
      if (safeNum(c.current_grade) != null) row.gradeVals.push(Number(c.current_grade));
      row.missingVals.push(Number(c.missingCount || 0));
      row.highPriorityMissingCount += s.highPriorityMissingByCourse[c.course] || 0;
    }
  }

  return [...map.values()]
    .map((r) => ({
      course: r.course,
      students: r.students,
      avgGrade: r.gradeVals.length ? +(r.gradeVals.reduce((a, b) => a + b, 0) / r.gradeVals.length).toFixed(1) : null,
      avgSubmitRate: r.submitRates.length ? +(r.submitRates.reduce((a, b) => a + b, 0) / r.submitRates.length).toFixed(1) : null,
      avgMissing: r.missingVals.length ? +(r.missingVals.reduce((a, b) => a + b, 0) / r.missingVals.length).toFixed(1) : null,
      highPriorityMissingCount: r.highPriorityMissingCount
    }))
    .sort((a, b) => b.students - a.students || a.course.localeCompare(b.course));
}

function main() {
  const input = process.argv[2];
  const courseArg = (process.argv.slice(3).find((a) => a.startsWith("--course=")) || "").split("=")[1] || "";
  const targetCourse = courseArg.trim();
  if (!input) {
    usage();
    process.exit(1);
  }

  const absPath = path.resolve(input);
  if (!fs.existsSync(absPath)) {
    console.error("Input file not found:", absPath);
    process.exit(1);
  }

  const raw = JSON.parse(fs.readFileSync(absPath, "utf8"));
  if (!Array.isArray(raw)) {
    console.error("Input JSON must be an array.");
    process.exit(1);
  }

  const students = raw.map((row) => {
    const studentName = String(row.studentName || "");
    const courseProgress = Array.isArray(row.courseProgress) ? row.courseProgress : [];
    const missingItems = Array.isArray(row.missingItems) ? row.missingItems : [];
    const recentSubmissions = Array.isArray(row.recentSubmissions) ? row.recentSubmissions : [];
    const upcomingDeadlines = Array.isArray(row.upcomingDeadlines) ? row.upcomingDeadlines : [];
    const combo = row.combo || {};
    const currentWeek = safeNum(row.currentWeek) || null;

    const currentCourses = courseProgress.filter(isCurrentCourse);
    const currentCourseNames = new Set(currentCourses.map((c) => c.course).filter(Boolean));

    const submitted = currentCourses.reduce((s, c) => s + Number(c.submittedCount || 0), 0);
    const missing = currentCourses.reduce((s, c) => s + Number(c.missingCount || 0), 0);
    const submitRate = pct(submitted, submitted + missing);

    const grades = currentCourses.map((c) => safeNum(c.current_grade)).filter((v) => v != null);
    const gradeAvg = grades.length ? +(grades.reduce((a, b) => a + b, 0) / grades.length).toFixed(1) : null;
    const gradeSpan = grades.length >= 2 ? +(Math.max(...grades) - Math.min(...grades)).toFixed(1) : null;

    const hpCurrent = missingItems.filter((m) => currentCourseNames.has(m.course) && isHighPriorityMissing(m));
    const highPriorityMissing = hpCurrent.length;
    const highPriorityMissingByCourse = hpCurrent.reduce((acc, m) => {
      acc[m.course] = (acc[m.course] || 0) + 1;
      return acc;
    }, {});

    const d7 = upcomingDeadlines.filter((d) => {
      const dd = daysUntil(d.date_ms);
      return dd != null && dd >= 0 && dd <= 7;
    });
    const ddl7 = d7.length;
    const aol7 = d7.filter((d) => d.is_aol === true).length;

    const streak = Number(combo.current_streak || 0);
    const recentMomentum = recentSubmissions.length >= 2 ? 1 : recentSubmissions.length === 1 ? 0 : -1;

    const topRiskCourse = Object.entries(highPriorityMissingByCourse).sort((a, b) => b[1] - a[1])[0]?.[0] || null;
    const worstCourse = currentCourses
      .slice()
      .sort((a, b) => Number(a.completion || 0) - Number(b.completion || 0))[0]?.course || null;

    const phase = computePhase(currentWeek);

    const feature = {
      studentName,
      phase,
      currentWeek,
      currentCourseCount: currentCourses.length,
      submitted,
      missing,
      submitRate: submitRate == null ? null : +submitRate.toFixed(1),
      gradeAvg,
      gradeSpan,
      highPriorityMissing,
      ddl7,
      aol7,
      streak,
      recentMomentum,
      topRiskCourse,
      worstCourse,
      currentCourses,
      highPriorityMissingByCourse
    };

    const profile = classify(feature);
    const advice = buildNavigatorAdvice(profile, feature, phase);
    return { ...feature, profile, advice };
  });

  const profiles = students.reduce((acc, s) => {
    acc[s.profile] = (acc[s.profile] || 0) + 1;
    return acc;
  }, {});

  const rates = students.map((s) => s.submitRate).filter((v) => v != null).sort((a, b) => a - b);
  const hpVals = students.map((s) => s.highPriorityMissing).sort((a, b) => a - b);
  const gradeVals = students.map((s) => s.gradeAvg).filter((v) => v != null).sort((a, b) => a - b);

  const thresholdSuggestion = {
    submitRate_p25: quantile(rates, 0.25),
    submitRate_p50: quantile(rates, 0.5),
    submitRate_p75: quantile(rates, 0.75),
    highPriorityMissing_p75: quantile(hpVals, 0.75),
    gradeAvg_p25: quantile(gradeVals, 0.25),
    gradeAvg_p50: quantile(gradeVals, 0.5),
    gradeAvg_p75: quantile(gradeVals, 0.75)
  };

  const out = {
    generatedAt: new Date().toISOString(),
    assumptions: [
      "Only current-semester courses are used (isCurrentSemester !== false).",
      "High-priority missing tasks are nature containing 🔥."
    ],
    totalStudents: students.length,
    profileDistribution: profiles,
    thresholdSuggestion,
    courseSummary: summarizeByCourse(students),
    studentProfiles: students
      .sort((a, b) => (b.highPriorityMissing - a.highPriorityMissing) || ((a.submitRate ?? 999) - (b.submitRate ?? 999)))
      .map((s) => ({
        studentName: s.studentName,
        phase: s.phase,
        profile: s.profile,
        submitRate: s.submitRate,
        highPriorityMissing: s.highPriorityMissing,
        gradeAvg: s.gradeAvg,
        gradeSpan: s.gradeSpan,
        ddl7: s.ddl7,
        aol7: s.aol7,
        streak: s.streak,
        topRiskCourse: s.topRiskCourse,
        worstCourse: s.worstCourse,
        advice: s.advice
      }))
  };

  if (targetCourse) {
    const courseStudents = students
      .map((s) => {
        const c = s.currentCourses.find((x) => String(x.course || "").trim().toUpperCase() === targetCourse.toUpperCase());
        if (!c) return null;
        const submitted = Number(c.submittedCount || 0);
        const missing = Number(c.missingCount || 0);
        const submitRate = pct(submitted, submitted + missing);
        return {
          studentName: s.studentName,
          profile: s.profile,
          course: c.course,
          submitted,
          missing,
          completion: Number(c.completion || 0),
          current_grade: safeNum(c.current_grade),
          submitRate: submitRate == null ? null : +submitRate.toFixed(1),
          highPriorityMissingInCourse: s.highPriorityMissingByCourse[c.course] || 0
        };
      })
      .filter(Boolean)
      .sort((a, b) => (b.highPriorityMissingInCourse - a.highPriorityMissingInCourse) || ((a.submitRate ?? 999) - (b.submitRate ?? 999)));

    out.courseFocus = {
      course: targetCourse,
      students: courseStudents.length,
      rows: courseStudents
    };
  }

  const outputPath = path.join(path.dirname(absPath), "navigation_analysis_output.json");
  fs.writeFileSync(outputPath, JSON.stringify(out, null, 2), "utf8");

  console.log("Analysis complete.");
  console.log("Output:", outputPath);
  console.log("");
  console.log("Profile distribution:");
  for (const [k, v] of Object.entries(out.profileDistribution)) {
    console.log(`- ${k}: ${v}`);
  }
  console.log("");
  console.log("Top courses by enrollment:");
  for (const c of out.courseSummary.slice(0, 8)) {
    console.log(`- ${c.course}: n=${c.students}, avgGrade=${c.avgGrade ?? "NA"}, avgSubmitRate=${c.avgSubmitRate ?? "NA"}%, avgMissing=${c.avgMissing ?? "NA"}`);
  }
  if (out.courseFocus) {
    console.log("");
    console.log(`Course focus: ${out.courseFocus.course} (students=${out.courseFocus.students})`);
    for (const r of out.courseFocus.rows.slice(0, 20)) {
      console.log(`- ${r.studentName}: submitRate=${r.submitRate ?? "NA"}%, missing=${r.missing}, highPriorityMissing=${r.highPriorityMissingInCourse}, grade=${r.current_grade ?? "NA"}`);
    }
  }
}

main();
