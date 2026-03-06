# fix_roster_names.py 使用说明

把飞书花名册里 `"Last, First"` 格式的学生姓名批量改为 `"First Last"`。

---

## 环境要求

- Python 3
- `requests` 库（`pip install requests`）
- `pipeline/.env` 里已配置好飞书凭证（本项目已有，直接用）

---

## 运行步骤

### 第一步：预览（不写入飞书）

```bash
cd "/Users/zhujing/Downloads/Gia Zhu/02_Active_Projects/LMSTest"
set -a && source pipeline/.env && set +a
python3 pipeline/fix_roster_names.py --dry-run
```

终端会列出所有将被改名的记录，格式：
```
'Yu, Zhuoran'   →   'Zhuoran Yu'
'Xu, Tsang Yuen'   →   'Tsang Yuen Xu'
```

### 第二步：确认无误后正式写入

```bash
cd "/Users/zhujing/Downloads/Gia Zhu/02_Active_Projects/LMSTest"
set -a && source pipeline/.env && set +a
python3 pipeline/fix_roster_names.py
```

脚本会再次列出所有改动并提示 `确认写入飞书？(y/N)`，输入 `y` 后才开始写入。

---

## 转换规则

| 原格式 | 转换后 |
|---|---|
| `Yu, Zhuoran` | `Zhuoran Yu` |
| `Xu, Tsang Yuen` | `Tsang Yuen Xu` |
| `Zhuoran Yu` | 原样保留（无逗号不处理） |

- 只有含逗号的名字会被修改
- 多字名（如 `Tsang Yuen`）完整保留在前面
- 已经是正常格式的名字不会被误改

---

## 下学年新生入学时重复使用

新学期导入新生名单后，直接重跑即可。已经是 `First Last` 格式的老记录不会被重复处理。

```bash
set -a && source pipeline/.env && set +a
python3 pipeline/fix_roster_names.py --dry-run   # 先预览
python3 pipeline/fix_roster_names.py              # 确认后写入
```

---

## 相关文件

- 脚本：`pipeline/fix_roster_names.py`
- 环境变量：`pipeline/.env`（`FEISHU_ROSTER_TABLE_ID` 指向花名册表）
