from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ToolError(RuntimeError):
    """Base exception raised by agent tool helpers."""


@dataclass(frozen=True)
class HttpResult:
    """Normalized result returned by `http_request`.

    Attributes:
        status: HTTP status code.
        headers: Response headers as a plain dict.
        text: Raw response body decoded as text.
        json: Parsed JSON body when available, otherwise `None`.
    """

    status: int
    headers: dict[str, str]
    text: str
    json: Any | None


@dataclass(frozen=True)
class SqlResult:
    """Normalized result returned by SQL helpers.

    Attributes:
        rows: Result rows as list of dicts.
        row_count: Number of affected rows when the driver provides it.
    """

    rows: list[dict[str, Any]]
    row_count: int


def http_request(
    url: str,
    *,
    method: str = "GET",
    query: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    json_body: Any | None = None,
    text_body: str | bytes | None = None,
    timeout_seconds: float = 10,
) -> HttpResult:
    """Send one HTTP/HTTPS request for an agent workflow.

    Use this for internal APIs, small webhooks, or tool endpoints. JSON responses are
    parsed automatically when possible.

    Args:
        url: Absolute `http://` or `https://` URL.
        method: HTTP method, such as `GET`, `POST`, `PATCH`, or `DELETE`.
        query: Optional query parameters appended to the URL.
        headers: Optional request headers.
        json_body: Optional JSON-serializable request body. Sets `Content-Type`.
        text_body: Optional raw text/bytes request body. Do not pass with `json_body`.
        timeout_seconds: Network timeout.

    Raises:
        ToolError: On invalid arguments, HTTP errors, or network errors.
    """

    if not url.startswith(("http://", "https://")):
        raise ToolError("http_request url must start with http:// or https://")
    if json_body is not None and text_body is not None:
        raise ToolError("http_request accepts either json_body or text_body, not both")

    request_url = _with_query(url, query)
    request_headers = dict(headers or {})
    body = None

    if json_body is not None:
        body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json; charset=utf-8")
    elif isinstance(text_body, str):
        body = text_body.encode("utf-8")
    elif isinstance(text_body, bytes):
        body = text_body

    request = Request(request_url, data=body, headers=request_headers, method=method.upper())

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            text = response.read().decode(_response_charset(response.headers.get("content-type")), errors="replace")
            return HttpResult(
                status=response.status,
                headers=dict(response.headers.items()),
                text=text,
                json=_parse_json(text),
            )
    except HTTPError as exc:
        text = exc.read().decode(_response_charset(exc.headers.get("content-type")), errors="replace")
        raise ToolError(f"http_request failed with status {exc.code}: {text[:500]}") from exc
    except URLError as exc:
        raise ToolError(f"http_request network error: {exc.reason}") from exc


def execute_sqlite(
    database_path: str,
    sql: str,
    params: tuple[Any, ...] | list[Any] | None = None,
    *,
    read_only: bool = True,
) -> SqlResult:
    """Execute SQL against a SQLite database and return rows as dicts.

    Args:
        database_path: SQLite database file path. Use `:memory:` for tests.
        sql: SQL statement. Defaults to read-only mode and only allows SELECT/WITH.
        params: Parameter values. Always prefer params over string interpolation.
        read_only: When true, reject non-read SQL.

    Raises:
        ToolError: On unsafe SQL or sqlite execution errors.
    """

    if read_only:
        _assert_read_only_sql(sql)

    try:
        connection = sqlite3.connect(database_path)
        connection.row_factory = sqlite3.Row
        try:
            cursor = connection.execute(sql, tuple(params or ()))
            rows = [dict(row) for row in cursor.fetchall()] if cursor.description else []
            if not read_only:
                connection.commit()
            return SqlResult(rows=rows, row_count=cursor.rowcount)
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise ToolError(f"sqlite query failed: {exc}") from exc


def execute_mysql(
    connection_kwargs: dict[str, Any],
    sql: str,
    params: tuple[Any, ...] | list[Any] | None = None,
    *,
    read_only: bool = True,
) -> SqlResult:
    """Execute SQL against MySQL when `pymysql` is installed.

    Args:
        connection_kwargs: Arguments passed to `pymysql.connect`, for example
            `{"host": "...", "user": "...", "password": "...", "database": "..."}`.
        sql: SQL statement. Defaults to read-only mode and only allows SELECT/WITH.
        params: Parameter values. Always prefer params over string interpolation.
        read_only: When true, reject non-read SQL.

    Raises:
        ToolError: If `pymysql` is missing, SQL is unsafe, or execution fails.
    """

    if read_only:
        _assert_read_only_sql(sql)

    try:
        import pymysql
        import pymysql.cursors
    except ImportError as exc:
        raise ToolError("execute_mysql requires optional dependency: pip install pymysql") from exc

    connection = pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **connection_kwargs)
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql, tuple(params or ()))
            rows = list(cursor.fetchall()) if cursor.description else []
            if not read_only:
                connection.commit()
            return SqlResult(rows=rows, row_count=cursor.rowcount)
    except Exception as exc:
        raise ToolError(f"mysql query failed: {exc}") from exc
    finally:
        connection.close()



def _assert_read_only_sql(sql: str) -> None:
    statement = sql.strip().lower()
    if not statement.startswith(("select", "with")):
        raise ToolError("read-only SQL tools only allow SELECT or WITH statements")


def _with_query(url: str, query: dict[str, Any] | None) -> str:
    if not query:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode(query, doseq=True)}"


def _parse_json(text: str) -> Any | None:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _response_charset(content_type: str | None) -> str:
    if not content_type:
        return "utf-8"

    for part in content_type.split(";"):
        part = part.strip()
        if part.lower().startswith("charset="):
            return part.split("=", 1)[1].strip()
    return "utf-8"

