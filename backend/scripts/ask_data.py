"""通过 OpenAI 兼容模型生成并安全执行一条数据查询。"""

import argparse
import json
import sys
from typing import Sequence

from sqlalchemy import create_engine

from backend.app.config import Settings
from backend.app.nl2sql.openai_compatible import OpenAICompatibleSqlGenerator
from backend.app.nl2sql.service import Nl2SqlService, ReadonlySqlExecutor, SqlGuardError


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="安全自然语言数据查询")
    parser.add_argument("--question", required=True)
    args = parser.parse_args(argv)
    try:
        settings = Settings()
        generator = OpenAICompatibleSqlGenerator(
            settings.llm_base_url or "",
            settings.llm_api_key or "",
            settings.llm_model or "",
        )
        prepared = Nl2SqlService(settings.nl2sql_max_rows).prepare(args.question, generator)
        result = ReadonlySqlExecutor(
            create_engine(settings.database_url), settings.nl2sql_max_rows
        ).execute_prepared(prepared)
        print(json.dumps({"sql": prepared.sql, "columns": result.columns, "rows": result.rows}, default=str, ensure_ascii=False))
        return 0
    except (SqlGuardError, ValueError) as exc:
        print(json.dumps({"error_code": "invalid_query", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
