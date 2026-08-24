"""Single accepted-design renderer shared by browser preview and Chromium PDF."""
from __future__ import annotations

import html
from typing import Any


def e(value: Any) -> str:
    return html.escape(str(value if value not in (None, "") else "—"))


CSS = r"""
:root{--ink:#17233b;--muted:#667085;--soft:#8a94a6;--line:#e4e9f2;--strong:#d5dce8;--paper:#fff;--canvas:#f4f6fa;--blue:#4869a9;--blue-soft:#eef3fb;--green:#317a62;--green-soft:#edf7f2;--amber:#a2671e;--amber-soft:#fff6e8;--violet:#6c63a8;--violet-soft:#f4f2fb;--shadow:0 18px 50px rgba(30,45,75,.08)}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;color:var(--ink);background:var(--canvas);font:15px/1.65 Inter,"SF Pro Display","PingFang SC","Noto Sans CJK SC","Microsoft YaHei",sans-serif;-webkit-font-smoothing:antialiased}button{font:inherit}.toolbar{position:sticky;top:0;z-index:20;display:flex;justify-content:space-between;align-items:center;padding:12px 24px;background:rgba(255,255,255,.94);border-bottom:1px solid var(--line);backdrop-filter:blur(14px)}.toolbar__title{font-size:13px;font-weight:700}.toolbar__actions{display:flex;gap:10px;align-items:center}.button{min-height:38px;padding:8px 13px;border:1px solid var(--strong);border-radius:10px;color:#35415a;background:#fff;cursor:pointer}.button--primary{color:#fff;border-color:var(--blue);background:var(--blue)}.switch{display:flex;gap:8px;color:var(--muted);font-size:13px}.report{width:min(1180px,calc(100% - 32px));margin:32px auto 64px;padding:54px 58px 42px;background:var(--paper);border:1px solid var(--line);box-shadow:var(--shadow)}.report-header{display:grid;grid-template-columns:1fr auto;gap:32px;padding-bottom:30px;border-bottom:1px solid var(--strong)}.school{margin:0 0 16px;color:var(--blue);font-size:13px;font-weight:750;letter-spacing:.13em}h1{margin:0;font-size:clamp(30px,4vw,46px);line-height:1.16;letter-spacing:-.035em}.student-name{color:var(--blue)}.report-subtitle{margin:13px 0 0;color:var(--muted);font-size:16px}.report-meta{display:grid;grid-template-columns:auto auto;gap:8px 22px;min-width:300px;padding-top:16px}.meta-label{color:var(--soft);font-size:12px}.meta-value{text-align:right;font-size:13px;font-weight:650}.annotation{display:inline-flex;margin-left:7px;padding:2px 7px;border:1px solid currentColor;border-radius:999px;font-size:10px;font-weight:700}.annotation--fact{color:var(--green)}.annotation--ai{color:var(--violet)}.annotation--human{color:var(--amber)}body:not(.show-annotations) .annotation,body:not(.show-annotations) .prototype-note{display:none}.prototype-note{margin:22px 0 0;padding:11px 14px;border:1px dashed #cdd5e2;border-radius:10px;color:#59657a;background:#fafbfc;font-size:12px}.opening{display:grid;grid-template-columns:1.45fr .9fr;gap:44px;padding:44px 0 36px}.opening h2{margin:0 0 14px;font-size:29px}.opening p{margin:0;color:#4f5d73;font-size:16px}.fact-list{display:grid;border-top:1px solid var(--line)}.fact-row{display:grid;grid-template-columns:1fr auto;gap:16px;padding:12px 0;border-bottom:1px solid var(--line)}.fact-row span{color:var(--muted);font-size:13px}.section{padding:42px 0;border-top:1px solid var(--strong)}.section-heading{display:grid;grid-template-columns:1fr minmax(260px,420px);gap:30px;align-items:end;margin-bottom:24px}.section-index{margin-bottom:6px;color:var(--blue);font-size:12px;font-weight:800;letter-spacing:.12em}.section h2{margin:0;font-size:27px}.section-heading p{margin:0;color:var(--muted);font-size:13px}.rhythm-summary{display:flex;flex-wrap:wrap;gap:10px 24px;margin-bottom:17px;color:#4f5c71;font-size:13px}.table-scroll{overflow-x:auto;border:1px solid var(--strong);border-radius:14px}table{width:100%;border-spacing:0;border-collapse:collapse}th,td{padding:10px;border:1px solid var(--line);text-align:left;vertical-align:top}.attendance{min-width:900px;table-layout:fixed}.attendance th{background:var(--blue-soft);font-size:12px}.session{padding:8px;border-radius:9px;background:var(--green-soft);font-size:11px}.session--online{background:var(--blue-soft)}.session--support{background:var(--amber-soft)}.session--project{background:var(--violet-soft)}.course-stories{border-top:1px solid var(--strong)}.course-story{display:grid;grid-template-columns:180px 1fr;gap:36px;padding:28px 0;border-bottom:1px solid var(--line)}.course-code{color:var(--blue);font-size:12px;font-weight:800;letter-spacing:.08em}.course-story h3{margin:4px 0}.course-time{color:var(--soft);font-size:12px}.story-grid{display:grid;grid-template-columns:1.1fr 1fr 1fr;gap:26px}.story-block h4{margin:0 0 6px;color:#4f5d73;font-size:12px}.story-block p{margin:0;color:#334158;font-size:13px;white-space:pre-line}.task-table{overflow-x:auto}.task-table table{min-width:820px}.status{display:inline-flex;padding:3px 8px;border-radius:999px;font-size:10px;font-weight:750;background:var(--blue-soft)}.status--done{color:var(--green);background:var(--green-soft)}.status--revise{color:var(--amber);background:var(--amber-soft)}.grade-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px;margin-top:28px}.chart-panel,.module{padding:22px;border:1px solid var(--line);border-radius:14px}.score-list{display:flex;gap:8px;align-items:end;height:120px}.score-point{flex:1;display:grid;align-content:end;text-align:center;color:var(--muted);font-size:10px}.score-bar{min-height:4px;background:var(--blue);border-radius:5px 5px 0 0}.dual-module{display:grid;grid-template-columns:.9fr 1.25fr;gap:34px}.plan-item{padding:11px 0;border-bottom:1px solid var(--line)}.timeline{border-left:1px solid #cfd6e2;padding-left:22px}.timeline-item{margin-bottom:16px}.evidence{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:22px}.evidence-card{margin:0;border:1px solid var(--line);border-radius:11px;overflow:hidden}.evidence-preview{height:92px;padding:14px;background:#f5f7fb}.mini-document{height:100%;padding:10px;background:#fff;border:1px solid #dfe5ef}.evidence-caption{padding:9px;font-size:10px}.next-week{display:grid;grid-template-columns:1fr 1.4fr;gap:48px;padding:40px 44px;color:#f7f9fd;background:#263a60}.next-week h2{margin:0;color:#fff}.next-week p,.action span{color:#cdd7e9}.action{display:grid;grid-template-columns:30px 1fr;gap:11px;padding:10px 0;border-bottom:1px solid rgba(255,255,255,.14)}.action-number{display:grid;width:26px;height:26px;place-items:center;border:1px solid rgba(255,255,255,.32);border-radius:50%}.report-footer{display:flex;justify-content:space-between;gap:32px;padding-top:30px;color:var(--soft);font-size:11px}.empty{padding:18px;color:var(--muted);background:#fafbfd;border:1px dashed var(--strong)}
.progress-layout{display:grid;grid-template-columns:1.25fr .95fr;gap:32px;margin-top:28px}.reflection{display:grid;gap:14px;padding:22px;border:1px solid var(--line);border-radius:14px;background:#fafbfd}.chart-panel h3,.reflection h3{margin:0 0 4px}.chart-subtitle{color:var(--soft);font-size:11px}.chart{width:100%;height:auto;margin-top:14px}.chart text{fill:#7c8799;font-family:inherit;font-size:10px}.reflection-item{padding-left:13px;border-left:3px solid var(--green)}.reflection-item--attention{border-left-color:var(--amber)}.reflection-item--support{border-left-color:var(--blue)}.reflection-item strong{display:block;margin-bottom:3px;font-size:13px}.reflection-item p{margin:0;color:#4e5b70;font-size:12px}.legend{display:flex;flex-wrap:wrap;gap:10px 22px;margin-top:14px;color:var(--muted);font-size:12px}.legend span{display:inline-flex;align-items:center;gap:7px}.legend i{width:9px;height:9px;border-radius:3px}.privacy-note{margin:16px 0 0;padding:12px 15px;border-left:3px solid #8ea2c8;color:#536077;background:#f7f9fd;font-size:12px}.button svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:1.8}.backlog-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:0 0 18px}.backlog-card{padding:15px;border:1px solid var(--line);border-radius:12px;background:#fafbfd}.backlog-card strong{display:block;font-size:20px}.backlog-card span{color:var(--muted);font-size:12px}.module-meta{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:14px 0}.module-meta div{padding:10px;background:#f7f9fd;border-radius:9px}.module-meta span{display:block;color:var(--soft);font-size:10px}.module-meta strong{font-size:12px}.module-note{margin:12px 0;padding:11px;border-left:3px solid var(--blue);background:var(--blue-soft);font-size:12px}.candidate-note{border-left-color:var(--violet);background:var(--violet-soft)}
@media(max-width:860px){.toolbar{padding:10px 14px}.report{width:100%;margin:0;padding:34px 20px;border:0;box-shadow:none}.report-header,.opening,.section-heading,.course-story,.story-grid,.dual-module,.next-week,.grade-grid,.progress-layout,.backlog-grid{grid-template-columns:1fr}.report-meta{min-width:0}.evidence{grid-template-columns:1fr 1fr}.next-week{margin-inline:-20px;padding:34px 20px}}
@media print{@page{size:A4;margin:11mm}body{background:#fff;font-size:10px}.toolbar,.prototype-note,.annotation{display:none!important}.report{width:100%;margin:0;padding:0;border:0;box-shadow:none}.report-header{padding-bottom:16px}h1{font-size:28px}.opening,.section{padding:20px 0}.section{break-before:auto}.section-heading,.course-story,.module,.chart-panel,.evidence-card,.next-week,.action{break-inside:avoid}.table-scroll,.task-table{overflow:visible}.attendance,.task-table table{min-width:0;font-size:8px}.attendance th,.attendance td,.task-table th,.task-table td{padding:4px}.session{padding:4px;font-size:7px}.course-story{padding:14px 0}.next-week{padding:24px 28px;print-color-adjust:exact;-webkit-print-color-adjust:exact}.report-footer{padding-top:10px}.session,.status,.score-bar,.evidence-preview{print-color-adjust:exact;-webkit-print-color-adjust:exact}}
"""


def render_attendance(attendance: dict[str, Any]) -> str:
    days = attendance.get("days", [])
    slots = attendance.get("slots", [])
    by_cell = {(x.get("slot"), x.get("day")): x for x in attendance.get("sessions", []) if x.get("fact_status") == "confirmed"}
    head = "".join(f"<th>{e(d.get('label'))}<br>{e(d.get('date'))}</th>" for d in days)
    rows = []
    for slot in slots:
        cells = []
        for day in days:
            item = by_cell.get((slot, day.get("key")))
            if not item:
                cells.append("<td></td>")
                continue
            mode = {"线上":"online","需支持":"support","PBL":"project"}.get(item.get("mode"), "good")
            cells.append(f"<td><div class='session session--{mode}'><strong>{e(item.get('title'))}</strong><span>{e(item.get('observation'))}</span></div></td>")
        rows.append(f"<tr><td>{e(slot)}</td>{''.join(cells)}</tr>")
    if not days or not slots:
        return "<div class='empty'>本周场次级出勤事实缺失或待确认。</div>"
    return f"<div class='table-scroll'><table class='attendance' aria-label='学生一周出勤透视表'><thead><tr><th>时间</th>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def render_courses(courses: list[dict[str, Any]]) -> str:
    visible = [c for c in courses if c.get("actual_content_confirmed") is True]
    if not visible:
        return "<div class='empty'>本周实际课程内容尚未完成老师确认，未进入对外版。</div>"
    return "<div class='course-stories'>" + "".join(
        f"<article class='course-story'><div><div class='course-code'>{e(c.get('code'))}</div><h3>{e(c.get('title'))}</h3><div class='course-time'>{e(c.get('session_summary') or ('本周'+str(c.get('session_count'))+'场已确认课程' if c.get('session_count') else '场次数待确认'))}</div></div><div class='story-grid'><div class='story-block'><h4>实际授课内容<span class='annotation annotation--fact'>确认事实</span></h4><p>{e(c.get('actual_content'))}</p></div><div class='story-block'><h4>课堂互动<span class='annotation annotation--human'>老师确认</span></h4><p>{e(c.get('confirmed_interaction')) if c.get('interaction_confirmation_status') == '已确认' else '本周无已确认互动事实。'}</p></div><div class='story-block'><h4>课程问题与学校支持<span class='annotation annotation--human'>老师确认</span></h4><p><strong>问题：</strong>{e(c.get('confirmed_issue')) if c.get('issue_confirmation_status') == '已确认' else '课程问题待老师确认。'}\n<strong>支持：</strong>{e(c.get('confirmed_support')) if c.get('support_confirmation_status') == '已确认' else '学校支持安排待老师确认。'}</p></div></div></article>" for c in visible
    ) + "</div>"


def render_tasks(tasks: list[dict[str, Any]]) -> str:
    categories = {"缺交": [t for t in tasks if t.get("Backlog状态") == "缺交积压"], "返工": [t for t in tasks if t.get("Backlog状态") == "返工积压"], "待审": [t for t in tasks if t.get("当前执行状态") == "已提交待审"]}
    backlog = "<div class='backlog-grid' aria-label='Backlog视图'>" + "".join(f"<div class='backlog-card'><strong>{len(items)}</strong><span>{label} · {e('、'.join(x.get('任务名称','') for x in items) or '暂无')}</span></div>" for label, items in categories.items()) + "</div>"
    rows = "".join(f"<tr><td>{e(t.get('课程') or t.get('所属模块'))}</td><td>{e(t.get('任务名称'))}</td><td>{e(t.get('当前有效Deadline'))}</td><td>{e(t.get('当前提交状态'))}</td><td><span class='status {'status--done' if t.get('当前任务状态') == '已完成' else 'status--revise' if t.get('当前任务状态') == '需返工' else ''}'>{e(t.get('当前执行状态'))}</span></td><td>{e(t.get('教师反馈') or '待老师检查')}</td></tr>" for t in tasks)
    if not rows:
        rows = "<tr><td colspan='6'>本周任务事实缺失或待同步。</td></tr>"
    return f"{backlog}<div class='task-table'><table aria-label='任务明细'><thead><tr><th>课程/模块</th><th>任务</th><th>有效截止</th><th>提交</th><th>检查结果</th><th>教师反馈</th></tr></thead><tbody>{rows}</tbody></table></div>"


def render_grades(series: list[dict[str, Any]]) -> str:
    if not series:
        return "<article class='chart-panel'><h3>近期作业分数</h3><div class='empty'>暂无可展示的已评分任务序列。</div></article>"
    colors = ("#4869a9", "#a2671e", "#317a62", "#6c63a8")
    lines, labels, legend = [], [], []
    max_points = max(len(course.get("points", [])) for course in series)
    for course_index, course in enumerate(series):
        points = course.get("points", [])
        coords = []
        for index, point in enumerate(points):
            x = 58 + (index * 440 / max(max_points - 1, 1))
            score = max(0, min(100, float(point.get("score", 0))))
            y = 180 - score * 1.35
            coords.append(f"{x:.1f},{y:.1f}")
            if course_index == 0:
                labels.append(f"<text x='{x:.1f}' y='205' text-anchor='middle'>{e(point.get('label'))}</text>")
        color = colors[course_index % len(colors)]
        lines.append(f"<polyline points='{' '.join(coords)}' fill='none' stroke='{color}' stroke-width='3' stroke-linecap='round' stroke-linejoin='round'/>")
        lines.extend(f"<circle cx='{coord.split(',')[0]}' cy='{coord.split(',')[1]}' r='4' fill='{color}'/>" for coord in coords)
        legend.append(f"<span style='color:{color}'>● {e(course.get('course_code'))}</span>")
    positives = [course.get("positive_note") for course in series if course.get("positive_confirmation_status") == "已确认" and course.get("positive_note")]
    attentions = [course.get("attention_note") for course in series if course.get("attention_confirmation_status") == "已确认" and course.get("attention_note")]
    reasons = [course.get("attention_reason") for course in series if course.get("attention_reason_confirmation_status") == "已确认" and course.get("attention_reason")]
    supports = [course.get("school_support") for course in series if course.get("support_confirmation_status") == "已确认" and course.get("school_support")]
    positive = " ".join(positives) or "暂无已确认的高分鼓励说明。"
    attention = " ".join(attentions) or "暂无已确认的低分关注事项。"
    if reasons:
        attention += " 已确认原因：" + " ".join(reasons)
    support = " ".join(supports) or "学校支持安排待老师确认。"
    chart = f"<article class='chart-panel'><h3>近期作业分数<span class='annotation annotation--fact'>评分事实</span></h3><div class='chart-subtitle'>按课程展示近期已评分任务，不表示课程总分趋势</div><svg class='chart' viewBox='0 0 540 220' role='img' aria-label='按课程展示近期作业分数'><g stroke='#e6eaf1'><line x1='48' y1='45' x2='520' y2='45'/><line x1='48' y1='90' x2='520' y2='90'/><line x1='48' y1='135' x2='520' y2='135'/><line x1='48' y1='180' x2='520' y2='180'/></g><g><text x='14' y='49'>100</text><text x='21' y='94'>67</text><text x='21' y='139'>33</text><text x='27' y='184'>0</text>{''.join(labels)}</g>{''.join(lines)}<foreignObject x='300' y='5' width='220' height='30'><div xmlns='http://www.w3.org/1999/xhtml' style='display:flex;gap:10px;font-size:10px'>{''.join(legend)}</div></foreignObject></svg></article>"
    reflection = f"<aside class='reflection'><h3>事实性成绩说明与学校支持</h3><div class='reflection-item'><strong>值得肯定（确认事实）</strong><p>{e(positive)}</p></div><div class='reflection-item reflection-item--attention'><strong>需要关注（确认事实）</strong><p>{e(attention)}</p></div><div class='reflection-item reflection-item--support'><strong>学校支持（确认安排）</strong><p>{e(support)}</p></div></aside>"
    return f"<div class='progress-layout'>{chart}{reflection}</div>"


def render_modules(ielts: dict[str, Any], pbl: dict[str, Any]) -> str:
    plan="".join(f"<div class='plan-item'><strong>{e(x.get('title'))}</strong><div>{e(x.get('status'))} · {e(x.get('evidence_status'))}</div></div>" for x in ielts.get("confirmed_plan", [])) or "<div class='empty'>暂无已确认IELTS计划。</div>"
    target = e(ielts.get("target")) if ielts.get("target_confirmation_status") == "已确认" else "目标待确认"
    progress = f"{e(ielts.get('completed_count', 0))} / {e(ielts.get('planned_count', len(ielts.get('confirmed_plan', []))))}"
    unfinished = e("、".join(ielts.get("unfinished_items", []))) if ielts.get("unfinished_items") else "暂无已确认未完成项"
    ielts_support = e(ielts.get("confirmed_support")) if ielts.get("support_confirmation_status") == "已确认" else "支持安排待老师确认"
    project = pbl if pbl.get("stage_confirmed") else {}
    timeline="".join(f"<div class='timeline-item'><strong>{e(x.get('title'))}</strong><div>{e(x.get('detail'))}</div></div>" for x in project.get("milestones", [])) or "<div class='empty'>PBL阶段尚未人工确认。</div>"
    evidence="".join(f"<figure class='evidence-card'><div class='evidence-preview'><div class='mini-document'>{e(x.get('label'))}</div></div><figcaption class='evidence-caption'>{e(x.get('caption'))}</figcaption></figure>" for x in project.get("evidence_cards", []))
    review = e(project.get("ai_review_status")) if project.get("ai_review_status") else "暂无AI检查候选"
    review_note = e(project.get("ai_review_note")) if project.get("ai_review_note") else "等待可读证据和已确认完成标准"
    return f"<div class='dual-module'><article class='module'><h3>IELTS 目标与周计划</h3><div class='module-meta'><div><span>已确认目标</span><strong>{target}</strong></div><div><span>计划完成进度</span><strong>{progress}</strong></div><div><span>未完成项</span><strong>{unfinished}</strong></div><div><span>学校支持</span><strong>{ielts_support}</strong></div></div>{plan}</article><article class='module'><h3>PBL · {e(project.get('name','待确认项目'))}</h3><div class='module-meta'><div><span>当前阶段</span><strong>{e(project.get('stage','待人工确认'))}</strong></div><div><span>阶段确认</span><strong>{'已确认' if project else '待确认'}</strong></div></div><div class='timeline'>{timeline}</div><div class='evidence'>{evidence}</div><div class='module-note candidate-note'><strong>AI review候选：{review}</strong><br>{review_note}<br>候选不等于任务完成或阶段推进，最终由老师人工复核。</div></article></div>"


def render_actions(actions: list[dict[str, Any]]) -> str:
    confirmed=[x for x in actions if x.get("confirmation_status")=="已确认"]
    if not confirmed:return "<div class='empty'>下周行动尚未由师生确认，未进入对外版。</div>"
    return "<div class='action-list'>"+"".join(f"<div class='action'><div class='action-number'>{i}</div><div><strong>{e(x.get('action'))}</strong><span>{e(x.get('school_support'))}</span></div></div>" for i,x in enumerate(confirmed,1))+"</div>"


def render_weekly_report(payload: dict[str, Any], drafts: dict[str, Any]) -> str:
    meta=payload.get("report",{}); att=payload.get("attendance",{}); tasks=payload.get("task_records",[])
    return f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{e(meta.get('title','学生周度学习反馈'))}</title><style>{CSS}</style></head><body class='show-annotations'>
<div class='toolbar' aria-label='网页工具栏'><div class='toolbar__title'>学生周度学习反馈</div><div class='toolbar__actions'><label class='switch'><input id='annotationToggle' type='checkbox' checked>显示数据来源标注</label><button class='button' onclick='window.print()'><svg viewBox='0 0 24 24' aria-hidden='true'><path d='M6 9V3h12v6M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2M6 14h12v7H6z'/></svg>打印</button><button class='button button--primary' onclick='window.print()'><svg viewBox='0 0 24 24' aria-hidden='true'><path d='M12 3v12m0 0 4-4m-4 4-4-4M5 21h14'/></svg>导出 PDF</button></div></div>
<main class='report' data-template='student-weekly-feedback-v1'><header class='report-header'><div><p class='school'>STUDENT LEARNING WEEKLY FEEDBACK</p><h1><span class='student-name'>{e(payload.get('student',{}).get('name'))}</span>的第 {e(payload.get('week',{}).get('number'))} 周学习反馈</h1><p class='report-subtitle'>{e(meta.get('subtitle','我们一起回看这一周发生了什么，也一起确定下一步怎样更顺利。'))}</p></div><div class='report-meta'><span class='meta-label'>学期</span><span class='meta-value'>{e(meta.get('term'))}</span><span class='meta-label'>周期</span><span class='meta-value'>{e(payload.get('week',{}).get('start'))}–{e(payload.get('week',{}).get('end'))}</span><span class='meta-label'>智育师</span><span class='meta-value'>{e(meta.get('educator'))}</span><span class='meta-label'>版本</span><span class='meta-value'>{e(meta.get('version_label'))}</span></div></header>
<div class='prototype-note'>绿色为确定性事实，紫色为AI候选，棕色为人工确认；打印与PDF自动隐藏本说明和工具栏。</div>
<section class='opening'><div><h2>{e(meta.get('opening_title','这一周，我们一起回看学习事实'))}<span class='annotation annotation--human'>老师确认</span></h2><p>{e(meta.get('confirmed_opening','本周总体描述待智育师确认。'))}</p></div><div class='fact-list'><div class='fact-row'><span>参与学习场次</span><strong>{e(att.get('观察到参与场次'))} / {e(att.get('应参加场次'))}</strong></div><div class='fact-row'><span>任务检查通过</span><strong>{sum(t.get('当前任务状态')=='已完成' for t in tasks)} / {len(tasks)}</strong></div><div class='fact-row'><span>下周共同重点</span><strong>{e(meta.get('next_focus'))}</strong></div></div></section>
<section class='section' id='weekly-rhythm'><div class='section-heading'><div><div class='section-index'>01 · WEEKLY RHYTHM</div><h2>本周学习节奏</h2></div><p>呈现已确认的场次参与事实，用于识别学习条件和支持需求，不作行为评分。</p></div><div class='rhythm-summary'><span>线下参与：<strong>{e(att.get('offline_count'))}</strong></span><span>线上参与：<strong>{e(att.get('online_count'))}</strong></span><span>需要支持：<strong>{e(att.get('support_summary'))}</strong></span></div>{render_attendance(att)}<div class='legend'><span><i style='background:var(--green-soft)'></i>线下参与</span><span><i style='background:var(--blue-soft)'></i>线上参与</span><span><i style='background:var(--amber-soft)'></i>已确认的特殊情况</span><span><i style='background:var(--violet-soft)'></i>个人项目</span></div><p class='privacy-note'>关于线上画面：这项信息只用于帮助老师理解线上学习条件、及时提供技术或课堂支持，不作为监视工具，也不作为对学生态度、品格或动机的评价。</p></section>
<section class='section' id='learning-in-class'><div class='section-heading'><div><div class='section-index'>02 · LEARNING IN CLASS</div><h2>课堂里发生了什么</h2></div><p>只呈现老师已确认的实际授课内容、互动与学校支持。</p></div>{render_courses(payload.get('courses',[]))}</section>
<section class='section' id='tasks-progress'><div class='section-heading'><div><div class='section-index'>03 · TASKS & ACADEMIC PROGRESS</div><h2>任务与学业进展</h2></div><p>提交不等于完成；仅检查通过才计为完成。</p></div>{render_tasks(tasks)}{render_grades(payload.get('grade_series',[]))}</section>
<section class='section' id='ielts-pbl'><div class='section-heading'><div><div class='section-index'>04 · IELTS & PERSONAL PROJECT</div><h2>IELTS 与个人项目</h2></div><p>只使用已确认计划、阶段和学习证据。</p></div>{render_modules(payload.get('ielts_report',{}),payload.get('pbl_report',{}))}</section>
<section class='next-week' id='next-week'><div><div class='section-index'>05 · NEXT WEEK</div><h2>下周，我们一起这样推进</h2><p>这里仅写入师生或智育师已确认的行动与学校支持。</p></div>{render_actions(payload.get('confirmed_next_actions',[]))}</section>
<footer class='report-footer'><div><strong>关于这份反馈</strong>内容基于已确认学习事实；AI仅协助整理，教育判断与发布由老师负责。</div><div><strong>{e(meta.get('educator'))}</strong>确认时间：{e(meta.get('confirmed_at'))}</div></footer></main>
<script>const t=document.getElementById('annotationToggle');t.addEventListener('change',e=>document.body.classList.toggle('show-annotations',e.target.checked));</script></body></html>"""
