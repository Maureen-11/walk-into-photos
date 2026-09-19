"""Create one local experiment case without touching the production app."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Allow `python backend/scripts/new_case.py ...` from the repository root as
# well as `python scripts/new_case.py ...` from the backend directory.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.case_record import CaseRecord, write_case


def main() -> int:
    parser = argparse.ArgumentParser(description="写入一个本地成功／失败案例记录")
    parser.add_argument("--root", type=Path, required=True, help="案例根目录，例如 D:/walk-cases")
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--result", choices=("success", "failure", "partial", "blocked"), required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--actual", required=True)
    parser.add_argument("--note", default="")
    args = parser.parse_args()
    record = CaseRecord(
        case_id=args.case_id,
        result=args.result,
        title=args.title,
        expected=args.expected,
        actual=args.actual,
        notes=args.note,
    )
    try:
        case_dir = write_case(args.root, record)
    except (FileExistsError, OSError, ValueError) as exc:
        print(f"无法写入案例：{exc}", file=sys.stderr)
        return 2
    print(case_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
