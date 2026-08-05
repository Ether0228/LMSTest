#!/usr/bin/env python3
from pathlib import Path
import shlex


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / "pipeline" / ".env"
OUT_PATH = ROOT / "repository-secrets-handoff.env"

KEYS = [
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "FEISHU_APP_TOKEN",
    "FEISHU_TABLE_ID",
    "FEISHU_ROSTER_TABLE_ID",
    "FEISHU_LIB_TABLE_ID",
    "FEISHU_MISSING_TABLE_ID",
    "FEISHU_GRADEBOOK_TABLE_ID",
    "FEISHU_CONFIG_TABLE_ID",
    "FEISHU_SUMMARY_TABLE_ID",
    "SCHOOLOGY_COOKIES",
    "SCHOOLOGY_SECTION_NIDS",
    "CURRENT_SEMESTER",
    "ACTIVE_SEMESTERS",
    "DATABASE_URL",
    "CACHE_TENANT_KEY",
    "FEISHU_WEBHOOK_URL",
    "SCHOOLOGY_GRADING_PERIOD",
]


def parse_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.replace("export ", "").strip()
        value = value.strip()
        try:
            parts = shlex.split(value)
            value = parts[0] if parts else ""
        except ValueError:
            value = value.strip('"').strip("'")
        values[key] = value
    return values


def quote_env_value(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def main() -> None:
    if not ENV_PATH.exists():
        raise SystemExit(f"Missing {ENV_PATH}")

    env = parse_env(ENV_PATH)
    lines = [
        "# Repository secrets handoff for LMSTest",
        "# Contains sensitive values. Share only through a trusted channel.",
        "",
    ]
    for key in KEYS:
        value = env.get(key, "")
        if value:
            lines.append(f"{key}={quote_env_value(value)}")
        else:
            lines.append(f"# {key}=  # missing")

    OUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Generated: {OUT_PATH}")


if __name__ == "__main__":
    main()
