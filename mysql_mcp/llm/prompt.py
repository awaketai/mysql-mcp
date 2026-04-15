"""Prompt construction with two-stage schema filtering."""

from __future__ import annotations

from mysql_mcp.models.schema import ColumnInfo, DatabaseSchema, SchemaCache, TableSchema

SYSTEM_TEMPLATE = """\
You are an expert MySQL SQL generator. Given a natural language query \
and the database schema below, generate a single SELECT statement.

Rules:
- Only generate SELECT statements.
- Never use INTO OUTFILE or INTO DUMPFILE.
- Always include a LIMIT clause (max {max_limit}).
- Use standard MySQL syntax.
- Respond with ONLY the SQL statement, no explanation or markdown.

Database: {database}
"""


class PromptBuilder:
    """Builds LLM prompts with two-stage schema filtering and layered context."""

    def __init__(self, schema_cache: SchemaCache, max_limit: int = 1000) -> None:
        self._cache = schema_cache
        self._max_limit = max_limit

    def build_system_prompt(
        self,
        database: str,
        candidate_tables: list[str] | None = None,
    ) -> str:
        """Assemble the system prompt with layered schema context."""
        db = self._cache.databases.get(database)
        if db is None:
            return SYSTEM_TEMPLATE.format(max_limit=self._max_limit, database=database)

        parts: list[str] = []

        # Index layer: always include full table list for context
        parts.append(self._format_table_index(db))

        # Detail or summary layer for candidate tables
        if candidate_tables:
            if len(candidate_tables) <= 20:
                parts.append(self._format_detailed_schema(candidate_tables, db))
            else:
                parts.append(self._format_summary_schema(candidate_tables, db))

        schema_text = "\n\n".join(parts)
        return SYSTEM_TEMPLATE.format(max_limit=self._max_limit, database=database) + "\n\n" + schema_text

    def find_candidate_tables(self, user_input: str, database: str) -> list[str]:
        """Two-stage candidate-table filtering.

        1. Direct match — tokens that match table or column names.
        2. Keyword match — tokens found in table/column comments.
        3. FK expansion — tables linked via foreign keys.
        4. Fallback — all tables if nothing matches.
        """
        db = self._cache.databases.get(database)
        if db is None:
            return []

        tokens = _tokenize(user_input)
        candidates: set[str] = set()

        for table_name, table in db.tables.items():
            table_lower = table_name.lower()
            comment_blob = _comment_blob(table).lower()

            for token in tokens:
                token_lower = token.lower()
                if token_lower == table_lower:
                    candidates.add(table_name)
                elif any(c.name.lower() == token_lower for c in table.columns):
                    candidates.add(table_name)
                elif token_lower in comment_blob:
                    candidates.add(table_name)

        # FK expansion
        expanded = set(candidates)
        for name in list(candidates):
            table = db.tables.get(name)
            if not table:
                continue
            for fk in table.foreign_keys:
                expanded.add(fk.ref_table)
            for other_name, other_table in db.tables.items():
                for fk in other_table.foreign_keys:
                    if fk.ref_table == name:
                        expanded.add(other_name)
        candidates = expanded

        if not candidates:
            return list(db.tables.keys())

        return sorted(candidates)

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    def _format_detailed_schema(self, tables: list[str], db: DatabaseSchema) -> str:
        """Full DDL-style schema for each table."""
        blocks: list[str] = []
        for name in tables:
            table = db.tables.get(name)
            if not table:
                continue
            blocks.append(_table_to_ddl(table))
        header = "### Relevant table schemas (detailed)\n"
        return header + "\n".join(blocks)

    def _format_summary_schema(self, tables: list[str], db: DatabaseSchema) -> str:
        """Compact column-name-only listing for each table."""
        lines: list[str] = []
        for name in tables:
            table = db.tables.get(name)
            if not table:
                continue
            cols = ", ".join(c.name for c in table.columns)
            comment = f" -- {table.comment}" if table.comment else ""
            lines.append(f"{name}({cols}){comment}")
        header = "### Relevant table schemas (summary)\n"
        return header + "\n".join(lines)

    def _format_table_index(self, db: DatabaseSchema) -> str:
        """All table names as a compact reference."""
        names = ", ".join(sorted(db.tables.keys()))
        return f"### All tables in database\n{names}"


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _table_to_ddl(table: TableSchema) -> str:
    """Render a TableSchema as a CREATE TABLE-style block."""
    col_lines: list[str] = []
    for c in table.columns:
        parts = [f"  {c.name} {c.type}"]
        if not c.nullable:
            parts.append("NOT NULL")
        if c.auto_increment:
            parts.append("AUTO_INCREMENT")
        if c.default is not None:
            parts.append(f"DEFAULT {c.default}")
        if c.comment:
            parts.append(f"COMMENT '{c.comment}'")
        col_lines.append(" ".join(parts))

    if table.indexes:
        for idx in table.indexes:
            cols = ", ".join(idx.columns)
            if idx.unique:
                col_lines.append(f"  UNIQUE INDEX {idx.name} ({cols})")
            else:
                col_lines.append(f"  INDEX {idx.name} ({cols})")

    if table.foreign_keys:
        for fk in table.foreign_keys:
            cols = ", ".join(fk.columns)
            ref_cols = ", ".join(fk.ref_columns)
            col_lines.append(
                f"  FOREIGN KEY {fk.name} ({cols}) REFERENCES {fk.ref_table}({ref_cols})"
            )

    header = f"CREATE TABLE {table.name}"
    if table.comment:
        header += f" -- {table.comment}"
    body = ",\n".join(col_lines)
    return f"{header} (\n{body}\n)"


def _comment_blob(table: TableSchema) -> str:
    """Concatenate all comment text from a table for keyword matching."""
    parts: list[str] = []
    if table.comment:
        parts.append(table.comment)
    for c in table.columns:
        if c.comment:
            parts.append(c.comment)
    return " ".join(parts)


def _tokenize(text: str) -> list[str]:
    """Split user input into candidate tokens."""
    return [t for t in __import__("re").split(r"[\s,;:!?.()\"'`\[\]{}]+", text) if t]
