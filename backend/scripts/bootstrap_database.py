"""Create the configured MySQL database and apply the fresh schema idempotently."""

from pathlib import Path

import pymysql
from pymysql.constants import CLIENT
from sqlalchemy.engine import make_url

from backend.app.config import Settings


def main() -> None:
    url = make_url(Settings().database_url)
    database = url.database
    if not database or not database.replace("_", "").isalnum():
        raise ValueError("database name must contain only letters, numbers and underscores")
    connection = pymysql.connect(
        host=url.host or "127.0.0.1",
        port=url.port or 3306,
        user=url.username,
        password=url.password,
        charset="utf8mb4",
        client_flag=CLIENT.MULTI_STATEMENTS,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4"
            )
            connection.select_db(database)
            cursor.execute(Path("sql/001_schema.sql").read_text(encoding="utf-8"))
            while cursor.nextset() is not None:
                pass
        connection.commit()
    finally:
        connection.close()
    print("database_and_schema=ready")


if __name__ == "__main__":
    main()
