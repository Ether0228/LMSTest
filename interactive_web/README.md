# QEA 互动手册 Web（飞书应用入口）

目标：学生从飞书应用打开网页后，首页直接展示本学期进度（提交/缺交/近期提交），并根据当前状态智能推荐《通关指南》对应章节。

## 重要前提（两家飞书企业）

如果你们有 **两个飞书企业（租户）**，通常一个“自建应用（企业内部应用）”只能在创建它的企业内使用。

推荐做法（最省事、可落地）：

1. 在两个企业各自创建一套“企业内部应用”（共 2 个应用）
2. 两个应用的“网页应用入口 URL”都指向同一个公网地址，但分别带不同参数，例如：
   - 企业 A：`https://your-domain.com/?t=tenant_a`
   - 企业 B：`https://your-domain.com/?t=tenant_b`
3. 后端根据 `t` 选择对应的飞书 `app_id/app_secret` 和 bitable 表配置

这样学生不需要“切换企业”，只要在他们所属企业里能看到应用，就能进入同一个网页。

## 目录结构

- `interactive_web/server.js`：Node 后端（无框架、无依赖）
- `interactive_web/public/`：静态前端（Dashboard + Guide 渲染）

## 本地运行（先用 Mock 身份）

1. 复制一份环境变量模板：
   - `cp interactive_web/.env.example interactive_web/.env`
2. 用 Mock 模式启动：
   - `AUTH_MODE=mock node interactive_web/server.js`
3. 打开：
   - `http://localhost:8787/?t=tenant_a&student=张三`

Mock 模式只用于开发 UI，不具备隐私隔离。

## 常见报错：TENANTS_JSON is not valid JSON

原因：`interactive_web/.env` 里 `TENANTS_JSON=...` 不是合法 JSON（最常见是少了最后一个 `}` 或多了逗号）。

修复方式：

1. 打开 `interactive_web/.env`
2. 确保 `TENANTS_JSON` 这一行是“单行 JSON”，并且以 `}` 结束
3. 只想先试 tenant_a：保留 tenant_a，删除 tenant_b 即可

## 性能建议（很重要）

如果页面慢，最常见原因是“缺交表只有关联学生字段”，导致后端需要全表扫描。

推荐配置：

1. 在缺交表新增一个文本字段（例如 `学生姓名`），通过“查找引用/Lookup”从 `关联学生 -> 学生姓名` 同步出来
2. 在 `.env` 的 `TENANTS_JSON` 里给租户加上：
   - `"missingStudentNameField":"学生姓名"`
3. 保持 `ALLOW_MISSING_FULL_SCAN=0`（默认），避免大表扫描拖慢响应

## 学生汇总表（推荐，速度最快）

你现在的场景更适合“预计算汇总表”：

1. 在多维表格新增一张表（学生汇总表），列名建议与脚本一致：
   - `学生姓名`（文本）
   - `关联学生`（关联到花名册）
   - `课程清单JSON`（文本）
   - `缺交总数`（数字）
   - `已提交总数`（数字）
   - `课程进度JSON`（文本）
   - `缺交按课程JSON`（文本）
   - `缺交明细JSON`（文本）
   - `近期提交JSON`（文本）
   - `推荐JSON`（文本）
   - `最后更新时间`（日期时间或数字都可）
2. 在 `TENANTS_JSON` 里加：
   - `"summaryTableId":"你的学生汇总表ID"`
3. 定时运行脚本（例如每 10 分钟）：
   - `schoology数据转飞书/build_student_summary.py`

脚本环境变量：

- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_APP_TOKEN`
- `FEISHU_TABLE_ID`
- `FEISHU_ROSTER_TABLE_ID`
- `FEISHU_LIB_TABLE_ID`
- `FEISHU_MISSING_TABLE_ID`
- `FEISHU_SUMMARY_TABLE_ID`

网页端检测到 `summaryTableId` 后会优先读取汇总表，接口响应会明显更快。

## 生产模式（飞书免登 / OAuth）

本项目预留了“按租户配置”的接口结构；真正上线必须启用飞书身份（否则学生可伪造姓名）。

你们现状是“两个企业 + 公网 + 只读看板”，建议上线顺序：

1. 先跑通飞书身份（免登或 OAuth）获取 `open_id/union_id`
2. roster 表增加一列 `飞书OpenID`（每个企业单独维护）
3. 后端用 `open_id -> roster` 做映射，彻底避免“姓名撞车/伪造”
4. 再逐步加：历史学期、修课、成绩

## 表与字段（对齐你现有脚本）

从 `schoology数据转飞书/*.md` 读到的关键字段（建议保持一致）：

- 提交记录表：`学生姓名` `作业名称` `提交状态` `提交时间` `作业链接` `唯一ID` `关联作业` `关联学生`
- 学生花名册：`学生姓名` `所属课程`
- 作业库：`作业名称` `作业链接` `所属课程` `作业性质` `统计状态`
- 缺交表：`唯一标识` `关联学生` `关联作业` `所属课程` `处理状态` `手动确认提交` `发现日期` `最后核验时间`
