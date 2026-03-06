# 迁移到 Neon PostgreSQL

**截止日期：2026 年 3 月 31 日**（Render 免费 PostgreSQL 到期删除）

## 步骤

1. 注册 https://neon.tech → 创建项目 → 复制 Connection String
2. Render Web Service → Environment → `DATABASE_URL` 换成 Neon 的
3. GitHub → Settings → Secrets → `DATABASE_URL` 换成 Neon 的 External URL
4. 手动触发一次 pipeline（重新写入数据到新库）
5. 验证：Render server logs 出现 `[pg] hit:`

## 代码改动

**零改动**，`pg` 包兼容标准 PostgreSQL。

## 数据库 Schema（供重建参考）

```sql
CREATE TABLE student_summary (
  tenant       TEXT NOT NULL,
  student_name TEXT NOT NULL,
  data         JSONB NOT NULL,
  updated_at   TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (tenant, student_name)
);
```
