"""SQL security validation via sqlglot AST analysis."""

from __future__ import annotations

import sqlglot
from sqlglot import exp


class SQLValidationError(Exception):
    """Raised when SQL fails security validation."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"SQL validation failed: {reason}")


_FORBIDDEN_STATEMENTS: tuple[type, ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Replace,
    exp.Create,
    exp.Alter,
    exp.Drop,
    exp.TruncateTable,
    exp.Grant,
    exp.Revoke,
)

_FORBIDDEN_FUNCTIONS: frozenset[str] = frozenset({
    "LOAD_FILE",
})

_FORBIDDEN_INTO_KEYWORDS: frozenset[str] = frozenset({
    "OUTFILE",
    "DUMPFILE",
})


class SQLValidator:
    """Validates that a SQL statement is a safe, read-only SELECT."""

    def validate(self, sql: str, max_limit: int = 1000) -> str:
        """Validate *sql*, returning a sanitised SQL string.

        Raises SQLValidationError on any rule violation.
        """
        tree = self._parse_single(sql)
        self._check_statement_type(tree)
        self._check_forbidden_functions(tree)
        self._check_into_clauses(tree)
        tree = self._ensure_limit(tree, max_limit)
        return tree.sql(dialect="mysql")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_single(sql: str) -> exp.Expression:
        """Parse *sql* into exactly one AST node."""
        statements = sqlglot.parse(sql, read="mysql")
        if len(statements) != 1 or statements[0] is None:
            raise SQLValidationError("Only a single SQL statement is allowed")
        return statements[0]

    @staticmethod
    def _check_statement_type(tree: exp.Expression) -> None:
        """Ensure the root is a SELECT (or UNION of SELECTs) with no forbidden subtrees."""
        if not isinstance(tree, (exp.Select, exp.Union)):
            raise SQLValidationError("Only SELECT statements are allowed")

        for forbidden in _FORBIDDEN_STATEMENTS:
            if tree.find(forbidden):
                raise SQLValidationError(
                    f"Forbidden statement type: {forbidden.__name__}"
                )

    @staticmethod
    def _check_forbidden_functions(tree: exp.Expression) -> None:
        """Walk the AST and reject calls to dangerous functions."""
        for func in tree.find_all(exp.Func):
            name = getattr(func, "name", "") or func.__class__.__name__
            if name.upper() in _FORBIDDEN_FUNCTIONS:
                raise SQLValidationError(f"Forbidden function: {name}")

    @staticmethod
    def _check_into_clauses(tree: exp.Expression) -> None:
        """Reject SELECT ... INTO OUTFILE / INTO DUMPFILE."""
        for into in tree.find_all(exp.Into):
            raw = into.sql(dialect="mysql").upper()
            for keyword in _FORBIDDEN_INTO_KEYWORDS:
                if keyword in raw:
                    raise SQLValidationError(f"Forbidden clause: INTO {keyword}")

        sql_text = tree.sql(dialect="mysql").upper()
        for keyword in _FORBIDDEN_INTO_KEYWORDS:
            if f"INTO {keyword}" in sql_text:
                raise SQLValidationError(f"Forbidden clause: INTO {keyword}")

    @staticmethod
    def _ensure_limit(tree: exp.Expression, max_limit: int) -> exp.Expression:
        """Guarantee a LIMIT clause exists and does not exceed *max_limit*.

        For UNION queries, enforces LIMIT on the outermost level.
        """
        if isinstance(tree, exp.Union):
            limit_node = tree.args.get("limit")
            if limit_node is None:
                tree.set("limit", exp.Limit(expression=exp.Literal.number(max_limit)))
            elif isinstance(limit_node, exp.Limit):
                limit_val = limit_node.expression
                if isinstance(limit_val, exp.Literal):
                    try:
                        val = int(limit_val.this)
                    except (ValueError, TypeError):
                        pass
                    else:
                        if val > max_limit:
                            limit_node.set("expression", exp.Literal.number(max_limit))
            return tree

        limit_node = tree.find(exp.Limit)

        if limit_node is None:
            tree.set("limit", exp.Limit(expression=exp.Literal.number(max_limit)))
            return tree

        limit_val = limit_node.expression
        if isinstance(limit_val, exp.Literal):
            try:
                val = int(limit_val.this)
            except (ValueError, TypeError):
                return tree
            if val > max_limit:
                limit_node.set("expression", exp.Literal.number(max_limit))

        return tree
