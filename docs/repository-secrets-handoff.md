# LMSTest Repository Secrets Handoff

这份文档用于把 LMSTest 项目交接给新的维护者或部署到新的服务器 / GitHub 仓库。

## 1. 交接文件

交接密钥文件位于项目根目录：

```text
repository-secrets-handoff.env
```

这个文件包含真实的飞书应用密钥、飞书 Base 表 ID、Schoology 登录 cookie、当前学期配置等敏感信息。

请不要把它提交到 GitHub，也不要发到公开群。建议通过可信私聊、加密压缩包、AirDrop 或受控云盘分享。

重新生成交接文件：

```bash
cd "/Users/zhujing/Downloads/Gia Zhu/02_Active_Projects/LMSTest"
scripts/generate-env-handoff.py
```

## 2. 当前关键配置

当前学期：

```text
CURRENT_SEMESTER=2025-S6
ACTIVE_SEMESTERS=2025-S6
```

当前 S6 Schoology section 配置应覆盖这 8 门课：

```text
ESLDO
CIA4U
OLC4O
SPH3U
MHF4U
BOH4M
MDM4U
LKBDU
```

对应 `SCHOOLOGY_SECTION_NIDS`：

```json
{
  "8425349469": "ESL Level 4: Section 2526S6N",
  "8425349467": "G12 Analysing Current Economic Issues: Section 2526S6N",
  "8425349464": "G12 Ontario Secondary School Literacy: Section 2526S6N",
  "8425349475": "Grade 11 Physics: Section 2526S6N",
  "8425349463": "Grade 12 Advanced Functions: Section 2526S6N",
  "8425349460": "Grade 12 Business Leadership: Section 2526S6N",
  "8425349462": "Grade 12 Data Management: Section 2526S6N",
  "8425349471": "Grade 12 Simplified Chinese: Section 2526S6N"
}
```

## 3. Secrets 清单

必须配置：

```text
FEISHU_APP_ID
FEISHU_APP_SECRET
FEISHU_APP_TOKEN
FEISHU_TABLE_ID
FEISHU_ROSTER_TABLE_ID
FEISHU_LIB_TABLE_ID
FEISHU_MISSING_TABLE_ID
FEISHU_GRADEBOOK_TABLE_ID
FEISHU_CONFIG_TABLE_ID
FEISHU_SUMMARY_TABLE_ID
SCHOOLOGY_COOKIES
SCHOOLOGY_SECTION_NIDS
CURRENT_SEMESTER
ACTIVE_SEMESTERS
```

可选：

```text
DATABASE_URL
CACHE_TENANT_KEY
FEISHU_WEBHOOK_URL
SCHOOLOGY_GRADING_PERIOD
```

说明：

- `FEISHU_TABLE_ID`：提交记录表。
- `FEISHU_ROSTER_TABLE_ID`：学生花名册。
- `FEISHU_LIB_TABLE_ID`：作业库。
- `FEISHU_MISSING_TABLE_ID`：缺交记录表。
- `FEISHU_GRADEBOOK_TABLE_ID`：Gradebook 表。
- `FEISHU_CONFIG_TABLE_ID`：系统配置表，保存 `course_mapping`、`grading_period` 等配置。
- `FEISHU_SUMMARY_TABLE_ID`：学生汇总表。
- `SCHOOLOGY_COOKIES`：Schoology 登录 cookie，定期更新。
- `SCHOOLOGY_SECTION_NIDS`：本学期 Schoology section NID 到课程标题的映射。
- `CURRENT_SEMESTER`：当前新写入作业应标记的学期。
- `ACTIVE_SEMESTERS`：缺交核验参与计算的学期。

## 4. 本地服务器使用方式

把 `repository-secrets-handoff.env` 放在项目根目录。

安装依赖：

```bash
python3 -m pip install requests selenium webdriver-manager psycopg2-binary
```

加载环境变量：

```bash
set -a
source repository-secrets-handoff.env
set +a
```

推荐运行顺序：

```bash
python3 pipeline/scrape_gradebook.py
python3 pipeline/check_missing_sync.py
```

如果只想明确跑当前 S6 缺交核验：

```bash
ACTIVE_SEMESTERS=2025-S6 REQUIRE_SEMESTER_TAG_FOR_MISSING=1 python3 pipeline/check_missing_sync.py
```

## 5. GitHub Actions 使用方式

如果要把这些变量导入新 GitHub 仓库，先安装并登录 GitHub CLI：

```bash
gh auth login
```

然后在项目根目录运行：

```bash
scripts/export-repository-secrets.sh OWNER/REPO
```

把 `OWNER/REPO` 替换成目标仓库，例如：

```bash
scripts/export-repository-secrets.sh colleague/lmstest
```

这个脚本会从本地 `pipeline/.env` 读取可用变量，并写入目标仓库的 Repository Secrets。

## 6. Cookie 更新方式

Schoology cookie 会过期，需要定期更新。

本项目有一个本地 cookie 同步服务：

```bash
node scripts/cookie-env-server.js
```

打开：

```text
http://127.0.0.1:8792/
```

然后用浏览器插件读取当前 `queenscanada.schoology.com` cookie，提交到本地服务。

服务会尝试同时更新：

```text
pipeline/.env
GitHub Secret: SCHOOLOGY_COOKIES
```

如果 macOS 阻止写入本地 `.env`，服务会提示，并把 cookie 临时写入：

```text
/tmp/lmstest-schoology-cookies.json
```

## 7. 正确性检查

交接前建议做一次只读检查：

```bash
set -a
source pipeline/.env
set +a
python3 - <<'PY'
import json, os

sections = json.loads(os.environ["SCHOOLOGY_SECTION_NIDS"])
print("CURRENT_SEMESTER =", os.environ.get("CURRENT_SEMESTER"))
print("ACTIVE_SEMESTERS =", os.environ.get("ACTIVE_SEMESTERS"))
print("sections =", len(sections))
for nid, title in sections.items():
    print(nid, title)
PY
```

应看到：

```text
CURRENT_SEMESTER = 2025-S6
ACTIVE_SEMESTERS = 2025-S6
sections = 8
```

并且课程标题应对应：

```text
ESL Level 4
G12 Analysing Current Economic Issues
G12 Ontario Secondary School Literacy
Grade 11 Physics
Grade 12 Advanced Functions
Grade 12 Business Leadership
Grade 12 Data Management
Grade 12 Simplified Chinese
```

## 8. 重要注意事项

- 不要直接从 GitHub 拉取 secrets 的明文值。GitHub 只允许查看 secret 名称，不允许读取明文。
- `SCHOOLOGY_COOKIES` 最好由实际运行账号自己登录 Schoology 后生成，不建议长期共用个人登录态。
- 换学期时必须更新 `SCHOOLOGY_SECTION_NIDS`、`CURRENT_SEMESTER`、`ACTIVE_SEMESTERS`。
- 缺交核验现在优先使用 `scrape_gradebook.py` 生成的 `pipeline/section_enrollment.json`，不要再依赖手工维护花名册 S1-S6 选课字段作为主数据源。
- 正确运行顺序是先 `scrape_gradebook.py`，再 `check_missing_sync.py`。
