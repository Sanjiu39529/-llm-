"""文件导入命令行入口。"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from sqlalchemy import create_engine

from backend.app.config import Settings
from backend.app.services.import_service import ImportService


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(f"参数错误: {message}")


def _parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(description="导入电商 Excel/CSV 数据")
    parser.add_argument("--file", required=True, type=Path, help="Excel/CSV 文件路径")
    parser.add_argument("--table", help="CSV 对应的标准表名")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """执行一次导入，并将报告或错误输出为 JSON。"""
    try:
        args = _parser().parse_args(argv)
        engine = create_engine(Settings().database_url)
        report = ImportService(engine).import_file(args.file, args.table)
        print(json.dumps(asdict(report), ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
