# 学生学习运营 Workflow 实施计划（V1 fixture 骨架）

## 审计结论

现有 LMSTest 已实现 Schoology 的提交/作业库/Gradebook 同步及飞书汇总，
但没有学习场次、课程周摘要、互动、IELTS、PBL、周反馈或发布的可测试
workflow。新模块不改动现有 `main_pipeline.yml`，避免影响生产同步链。

## 已实现的离线闭环

`student_ops_workflows.yml` 只由 `workflow_dispatch` 触发。它运行匿名
fixture、所有单元测试并上传工件；不会读取 Secrets，不会请求线上服务。
每个阶段使用同一固定输入、同一周唯一键和稳定 hash，因此可重跑。
单独选择某个阶段时，执行器只运行其必需依赖，而不是无条件运行整条链。

1. `session_content`：只从文字纪要产生六段式 AI 候选；缺来源不调用 AI。
2. `course_weekly`：仅消费已确认的实际课堂内容；没有确认事实时阻断。
3. `participation`：仅保留有来源且能唯一匹配学生的互动候选。
4. `tasks`：按返工→补做→原始 Deadline 计算，不把提交当作通过。
5. `grades`：生成稳定的 append-only 候选事件；无历史不声称趋势。
6. `ielts`：生成 Exception Queue 式候选，不自动创建正式学生任务。
7. `pbl`：生成证据 manifest 和待复核候选；不可读证据不作质量结论。
8. `weekly_payload`：即使 AI 不可用也可组装事实与模块状态。
9. `weekly_drafts`：所有内容均为待审核草稿，不含教育策略决策。
10. `publish`：仅在 fixture 的“智育师已确认”旗标为真时产生本地 HTML/PDF
    快照；还必须有稳定的确认时间/版本，且课程、任务、成绩、IELTS、PBL等
    关键事实模块不能为`blocked`。不会生成对外链接或写入飞书。

## 第二阶段：可配置 AI 与发布预览

- 真实 AI 是显式 `--ai-mode live` 才启用的 OpenAI-compatible HTTP adapter；
  `AI_API_KEY`、`AI_BASE_URL`、`AI_MODEL` 缺一不可，错误只记录安全错误码。
- `session_content` 使用已确认的完整六段式 Prompt。周度草稿按模块单独调用；
  模块被阻断或 AI 失败时不会产生该模块草稿。
- 发布预览改为固定中文 HTML 结构（出勤、课程/互动、任务、成绩、IELTS、PBL、
  总体/下周支持）；PDF 使用 Chrome/Chromium headless 从同一 HTML 生成。
- 分支 push 在 CI matrix 分别执行十个 selector 与 `all`；manual dispatch 保留
  单段或全链运行。所有 CI 运行使用 fixture adapter，不注入真实 AI 密钥。

## 第三阶段：结构化候选契约

- 课程周摘要、互动、IELTS候选与PBL检查均使用严格JSON契约；可去除完整
  Markdown code fence，但缺少字段、枚举错误或无效JSON均不自动补齐。
- 课程周摘要只消费已确认场次；互动先从纪要/逐字稿候选抽取，再做确定性学生
  匹配。IELTS没有已确认策略不产生候选；PBL没有可读证据或完成标准只能“无法判断”。
- 全部候选仍待老师/负责人确认，不更新正式任务完成状态、PBL阶段或课程事实。

## 第四阶段：家校报告单一模板

- 已接受的`student_weekly_feedback_template.html`视觉和信息架构迁入单一
  `report_template.py`数据渲染器；浏览器页面与Chromium PDF读取同一HTML。
- Payload补充报告元数据、已确认场次透视、实际课程内容与支持、任务明细、
  课程成绩序列、IELTS确认计划、PBL确认阶段/证据卡、人工确认下周行动。
- 模板层再次执行发布过滤：`planned`场次、未确认实际课程、未确认行动不会进入
  对外HTML；AI候选不能因页面渲染而升级为确认事实。
- 屏幕保留来源标注开关、打印和导出控件；A4打印隐藏工具栏、原型注释与来源
  标注，并对表格、课程叙事、模块卡和行动项设置断页规则及中文字体回退。

## 明确未做（需后续授权与规则落地）

- 真实 Feishu/Schoology 适配器与任何写操作；应单独添加 dry-run write-plan
  和经审批的最小权限凭证。
- OpenAI/其他模型线上调用；现由 `mock_ai_response` 测试解析和降级。
- `OPEN-001—004` 所涉正式 Attendance、A&P、Final Grade 规则。
- `OPEN-007/008/009/015/018` 所涉 AI 检查白名单、确认机制、证据粒度、并发
  Base append 策略。它们不能被此实现自行补全。
