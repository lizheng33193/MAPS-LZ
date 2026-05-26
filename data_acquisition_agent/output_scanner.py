"""L2 output safety scan. See Design Doc §7.1/§7.2/§7.3."""

from __future__ import annotations

import re


# CRED_PATTERNS：基于 L1 PATTERNS 的相同 family，但允许 ' 或 " 包裹（输出层更宽松）
CRED_PATTERNS = {
    "host": re.compile(r"\bhost\s*=\s*['\"](?:\d{1,3}\.){3}\d{1,3}['\"]"),
    "port": re.compile(r"\bport\s*=\s*\d{2,6}\b"),
    "user": re.compile(r"\buser\s*=\s*['\"]e_[A-Za-z0-9_]+['\"]"),
    "password": re.compile(r"\bpassword\s*=\s*['\"][^'\"]+['\"]"),
    "database": re.compile(r"\bdatabase\s*=\s*['\"]dm_[A-Za-z0-9_]+['\"]"),
    "token": re.compile(r"\btoken\s*=\s*['\"][^'\"]+['\"]"),
    "api_key": re.compile(r"\bapi_key\s*=\s*['\"][^'\"]+['\"]"),
    "access_token": re.compile(r"\baccess_token\s*=\s*['\"][^'\"]+['\"]"),
    "secret": re.compile(r"\bsecret\s*=\s*['\"][^'\"]+['\"]"),
    "key": re.compile(r"\bkey\s*=\s*['\"][^'\"]+['\"]"),
    "bearer": re.compile(r"(?i)\bAuthorization\s*:\s*Bearer\s+\S+"),
}


def scan_credentials(text: str) -> list[str]:
    return [name for name, pat in CRED_PATTERNS.items() if pat.search(text)]


def scan_python_dangerous(code: str) -> list[str]:
    return [pat.pattern for pat in DANGEROUS if pat.search(code)]


DANGEROUS = [
    re.compile(r"\bos\.system\("),
    re.compile(r"subprocess\.[A-Za-z_]+\([^)]*shell\s*=\s*True"),
    re.compile(r"\beval\("),
    re.compile(r"\bexec\("),
    re.compile(r"__import__\(\s*['\"]os['\"]"),
    re.compile(r"\bshutil\.rmtree\("),
    re.compile(r"\bos\.remove\("),
    re.compile(r"urllib\.request\.urlretrieve\("),
]


def check_sql_policy(sql: str, sql_kind: str, analyst_private_prefix: str) -> None:
    stripped = _strip_sql_comments(sql)
    if sql_kind == "query_only":
        if DDL_KW.search(stripped):
            raise ValueError("query_only contains DDL/DML keyword")
        return
    if sql_kind == "build_table_script":
        if not DDL_KW.search(stripped):
            raise ValueError("build_table_script must contain DDL")
        for stmt in _split_statements(stripped):
            m = _ALLOWED_BUILD_STMT.match(stmt)
            if not m:
                raise ValueError("build_table_script disallows non-allowlisted statement")
            target = m.group(1) or m.group(2)
            if _QUOTED_IDENT.search(target):
                raise ValueError("build_table_script disallows quoted identifier")
            if not target.startswith(analyst_private_prefix):
                raise ValueError("DDL target not in analyst_private_prefix")
        return
    raise ValueError("unknown sql_kind")


DDL_KW = re.compile(r"\b(CREATE|DROP|ALTER|TRUNCATE|INSERT|UPDATE|DELETE)\b", re.IGNORECASE)
# build_table_script 仅允许 CREATE TABLE [IF NOT EXISTS] <ident> AS SELECT ... 与 DROP TABLE [IF EXISTS] <ident>
_ALLOWED_BUILD_STMT = re.compile(
    r"(?is)^\s*(?:CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+([A-Za-z_][\w.]*)\s+AS\s+(?:WITH\s+|SELECT\s+).+"
    r"|DROP\s+TABLE(?:\s+IF\s+EXISTS)?\s+([A-Za-z_][\w.]*)\s*;?\s*)$"
)
_QUOTED_IDENT = re.compile(r"`|\"")


def _strip_sql_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def _split_statements(sql: str) -> list[str]:
    return [s for s in (s.strip() for s in sql.split(";")) if s]
