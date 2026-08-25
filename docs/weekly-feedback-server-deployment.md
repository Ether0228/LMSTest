# 周反馈静态发布：服务器最小部署

本部署只服务已确认并冻结的 HTML/PDF；不把 Base 导出、课程纪要正文、AI 候选或老师预览目录公开到互联网。

## 目录

- 应用代码：`/srv/lmstest`
- 对外冻结文件：`/srv/weekly-feedback/public/<随机token>/weekly_feedback.{html,pdf}`
- 内部预览与运行中间件：应用目录下受权限控制的 `var/`；不得配置 Nginx alias。

创建目录并授权给运行账户：

```bash
sudo install -d -o <运行用户> -g <运行组> -m 0750 /srv/lmstest
sudo install -d -o <运行用户> -g <运行组> -m 0750 /srv/weekly-feedback/public
```

## 配置

1. 将仓库检出到`/srv/lmstest`，切到 `codex/workflow-pipeline` 或合并后的受保护分支。
2. 复制 [weekly-feedback.env.example](../deploy/weekly-feedback.env.example) 为服务器私有环境文件，并填入公网域名；文件权限为 `0600`。不要把任何 Token、Cookie 或 API Key 写回仓库。
3. 把 [nginx-weekly-feedback.conf.example](../deploy/nginx-weekly-feedback.conf.example) 的域名替换为实际域名，放入现有 Nginx `conf.d`，然后执行：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

4. 由运行账户确认 `python3`、`lark-cli`、Chrome/Chromium 均可执行，且已登录被授权的 Lark profile。使用 `lark-cli auth status --profile <profile>` 检查身份，不输出凭据。

## DeepSeek AI 配置

周反馈的 AI 适配器是 OpenAI-compatible Chat Completions 客户端，因此无需为 DeepSeek 新增 SDK 或改动工作流。服务器私有环境文件填写：

```bash
AI_API_KEY=<在此粘贴 DeepSeek API Key>
AI_BASE_URL=https://api.deepseek.com
AI_MODEL=deepseek-v4-flash
```

本机已准备`pipeline/.env.weekly_feedback`（被 Git 忽略）。填写 Key 后，以如下方式仅对当前 shell 导入，再运行 live 模式：

```bash
set -a
source pipeline/.env.weekly_feedback
set +a
python3 pipeline/run_student_ops.py --workflow session_content \
  --fixture <真实周输入JSON> --output-dir var/ai-smoke-test --ai-mode live
```

该 smoke test 只生成本地候选工件，不写 Base；通过后才按“单学生单周运行顺序”写入草稿。DeepSeek 的 OpenAI-compatible base URL 和当前模型名以其官方文档为准。

## Schoology 只读探测

仓库已有`Schoology Master Pipeline`，其按计划运行时会写入旧的学业运营 Base；不要用它测试周反馈来源。新建的`Schoology Read-only Process Probe`只读取 GitHub Secrets 中的`SCHOOLOGY_COOKIES`和`SCHOOLOGY_SECTION_NIDS`，不传递飞书或 PostgreSQL 凭据，不会写入外部系统。它会打印匿名化的课程与计数摘要，并上传仅保留 1 天的私有原始快照供稳定 ID/任务映射审核。

## Schoology 稳定 ID 的一次性补录

在首次同步前，以实际 Schoology 后台显示的数字 ID 人工填写模板；不要用姓名或标题做自动匹配。导出和首次核对均不写 Base：

```bash
cd /srv/lmstest
source /etc/lmstest/weekly-feedback.env

python3 pipeline/export_schoology_mapping_template.py \
  --base-token <BaseToken> --output-dir var/schoology-mapping \
  --as "$LARK_IDENTITY" --profile "$LARK_PROFILE"

# 在 CSV 中仅填写 Schoology学生UID、SchoologySectionNID、Schoology作业NID 三列。
python3 pipeline/apply_schoology_mapping.py \
  --students var/schoology-mapping/schoology_students_mapping.csv \
  --course-tasks var/schoology-mapping/schoology_course_tasks_mapping.csv \
  --base-token <BaseToken> --as "$LARK_IDENTITY" --profile "$LARK_PROFILE"
```

确认 dry-run 的更新数和异常为空后，才由授权人员在最后一条命令添加`--apply`。脚本会拒绝格式错误或重复映射，并且只写入这三个稳定 ID 字段。

## 单学生单周运行顺序

在课程结束、课程内容已确认后运行。示例中的值均需替换；这四个命令不会自行改变业务事实。

```bash
cd /srv/lmstest
source /etc/lmstest/weekly-feedback.env

python3 pipeline/collect_weekly_feedback_base_facts.py \
  --base-token <BaseToken> --student-term-record-id <学生学期RecordID> \
  --student-name '<学生姓名>' --week '第1周' --week-start YYYY-MM-DD --week-end YYYY-MM-DD \
  --as-of YYYY-MM-DD --term '<学期>' --educator '<智育师>' \
  --output-dir var/weeks/<学生学期RecordID>-1/input --as "$LARK_IDENTITY" --profile "$LARK_PROFILE"

python3 pipeline/run_student_ops.py --workflow all \
  --fixture var/weeks/<学生学期RecordID>-1/input/weekly_feedback_input.json \
  --output-dir var/weeks/<学生学期RecordID>-1/run --ai-mode live

# 默认 dry-run：先生成确切 Base 写入计划；核对后才加 --apply。
python3 pipeline/sync_weekly_feedback_base.py --result var/weeks/<学生学期RecordID>-1/run/all_result.json \
  --base-token <BaseToken> --student-term-record-id <学生学期RecordID> --as "$LARK_IDENTITY" --profile "$LARK_PROFILE"
```

生产草稿写入与发布会检查该运行工件的`ai_mode`，默认只接受`live`。`fixture`仅可用于本地演示，不能通过普通`sync`或`publish`命令写入真实 Base 或生成对外版本。

老师在`学生周反馈`记录中修改草稿字段后，生成内部预览：

```bash
python3 pipeline/render_weekly_feedback_preview.py --result var/weeks/<学生学期RecordID>-1/run/all_result.json \
  --base-token <BaseToken> --feedback-record-id <周反馈RecordID> \
  --output-dir var/weeks/<学生学期RecordID>-1/preview --as "$LARK_IDENTITY" --profile "$LARK_PROFILE"
```

老师将`反馈状态`设为`已确认`后，使用上述预览快照冻结发布。`publish_weekly_feedback.py`会拒绝未确认快照；`apply_weekly_publication.py`也会再次拒绝仍为`草稿`的记录，并要求版本、发布时间、网页链接和 PDF 链接完整，随后才更新该条周反馈的发布字段。

```bash
python3 pipeline/publish_weekly_feedback.py --result var/weeks/<学生学期RecordID>-1/run/all_result.json \
  --drafts-file var/weeks/<学生学期RecordID>-1/preview/weekly_feedback_preview_snapshot.json \
  --approved-at 'YYYY-MM-DD HH:mm' --version v1 \
  --storage-dir "$WEEKLY_FEEDBACK_PUBLIC_DIR" --public-base-url "$WEEKLY_FEEDBACK_PUBLIC_BASE_URL"

python3 pipeline/apply_weekly_publication.py --manifest <上一步输出的weekly_feedback_snapshot.json> \
  --base-token <BaseToken> --record-id <周反馈RecordID> --as "$LARK_IDENTITY" --profile "$LARK_PROFILE"
```

前两个 Base 写入/回写命令均先默认 dry-run；只有核对 record ID、反馈唯一键、状态和 URL 后才加`--apply`。发布后不修改冻结文件；更新必须创建新版本和新 token。
