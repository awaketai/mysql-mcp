"""Schema discovery, caching, incremental refresh, and candidate-table filtering."""

from __future__ import annotations

import asyncio
import logging
import re

import aiomysql

from src.config import AppConfig
from src.models.schema import (
    ColumnInfo,
    DatabaseSchema,
    EnumTypeInfo,
    ForeignKeyInfo,
    IndexInfo,
    SchemaCache,
    TableSchema,
    TriggerInfo,
    ViewSchema,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# INFORMATION_SCHEMA queries
# ---------------------------------------------------------------------------

_GET_ACCESSIBLE_DATABASES = """
    SELECT SCHEMA_NAME
    FROM information_schema.SCHEMATA
    WHERE SCHEMA_NAME NOT IN ('information_schema', 'mysql', 'performance_schema', 'sys')
"""

_GET_TABLES = """
    SELECT TABLE_NAME, TABLE_COMMENT,
           COALESCE(UNIX_TIMESTAMP(UPDATE_TIME), 0) AS updated_at
    FROM information_schema.TABLES
    WHERE TABLE_SCHEMA = %s AND TABLE_TYPE = 'BASE TABLE'
"""

_GET_COLUMNS = """
    SELECT COLUMN_NAME, COLUMN_TYPE, COLUMN_DEFAULT, IS_NULLABLE,
           EXTRA, COLUMN_COMMENT
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
    ORDER BY ORDINAL_POSITION
"""

_GET_INDEXES = """
    SELECT INDEX_NAME,
           GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) AS columns,
           NOT NON_UNIQUE AS is_unique, INDEX_TYPE
    FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
    GROUP BY INDEX_NAME, NON_UNIQUE, INDEX_TYPE
"""

_GET_FOREIGN_KEYS = """
    SELECT kcu.CONSTRAINT_NAME,
           GROUP_CONCAT(kcu.COLUMN_NAME ORDER BY kcu.ORDINAL_POSITION) AS columns,
           kcu.REFERENCED_TABLE_NAME,
           GROUP_CONCAT(kcu.REFERENCED_COLUMN_NAME ORDER BY kcu.ORDINAL_POSITION) AS ref_columns,
           rc.DELETE_RULE, rc.UPDATE_RULE
    FROM information_schema.KEY_COLUMN_USAGE kcu
    JOIN information_schema.REFERENTIAL_CONSTRAINTS rc
        ON kcu.CONSTRAINT_NAME = rc.CONSTRAINT_NAME
        AND kcu.TABLE_SCHEMA = rc.CONSTRAINT_SCHEMA
    WHERE kcu.TABLE_SCHEMA = %s AND kcu.TABLE_NAME = %s
      AND kcu.REFERENCED_TABLE_NAME IS NOT NULL
    GROUP BY kcu.CONSTRAINT_NAME, kcu.REFERENCED_TABLE_NAME, rc.DELETE_RULE, rc.UPDATE_RULE
"""

_GET_TRIGGERS = """
    SELECT TRIGGER_NAME, EVENT_MANIPULATION, ACTION_TIMING, ACTION_STATEMENT
    FROM information_schema.TRIGGERS
    WHERE TRIGGER_SCHEMA = %s AND EVENT_OBJECT_TABLE = %s
"""

_GET_VIEWS = """
    SELECT TABLE_NAME, VIEW_DEFINITION
    FROM information_schema.VIEWS
    WHERE TABLE_SCHEMA = %s
"""

_GET_ENUMS = """
    SELECT COLUMN_NAME, TABLE_NAME, COLUMN_TYPE
    FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = %s AND DATA_TYPE = 'enum'
"""

_ENUM_RE = re.compile(r"^enum\((.*)\)$", re.IGNORECASE)


def _parse_enum_values(column_type: str) -> list[str]:
    """Extract values from a MySQL ENUM type string like ``enum('a','b','c')``."""
    m = _ENUM_RE.match(column_type)
    if not m:
        return []
    inner = m.group(1)
    return [v.strip().strip("'\"") for v in inner.split(",")]


class SchemaManager:
    """Manages schema discovery, caching, and incremental refresh."""

    def __init__(self, pool: aiomysql.Pool, config: AppConfig) -> None:
        self._pool = pool
        self._config = config
        self._cache = SchemaCache()
        self._refresh_task: asyncio.Task | None = None

    @property
    def cache(self) -> SchemaCache:
        return self._cache

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def load_all(self) -> None:
        """Load schemas for all accessible databases."""
        databases = await self._get_accessible_databases()
        for db_name in databases:
            self._cache.databases[db_name] = await self._load_database_schema(db_name)
        self._rebuild_table_index()
        total_tables = sum(len(db.tables) for db in self._cache.databases.values())
        logger.info("Schema loaded: %d databases, %d tables", len(self._cache.databases), total_tables)

    async def refresh_incremental(self) -> None:
        """Incrementally refresh only tables whose UPDATE_TIME changed."""
        for db_name, db_schema in list(self._cache.databases.items()):
            current = await self._fetch_current_table_timestamps(db_name)
            # Update or add changed / new tables
            for table_name, (new_ts, comment) in current.items():
                cached = db_schema.tables.get(table_name)
                if cached is None or cached.updated_at < new_ts:
                    await self._refresh_table(db_name, table_name, comment, new_ts)
            # Remove deleted tables
            removed = set(db_schema.tables.keys()) - set(current.keys())
            for table_name in removed:
                del db_schema.tables[table_name]
                logger.debug("Removed table: %s.%s", db_name, table_name)
        self._rebuild_table_index()

    async def start_refresh_if_configured(self) -> asyncio.Task | None:
        """Start a background refresh loop if SCHEMA_REFRESH_INTERVAL > 0."""
        interval = self._config.schema_refresh_interval
        if interval <= 0:
            return None

        async def _loop() -> None:
            while True:
                await asyncio.sleep(interval)
                try:
                    await self.refresh_incremental()
                    logger.info("Schema incremental refresh completed")
                except Exception:
                    logger.exception("Schema refresh failed")

        self._refresh_task = asyncio.create_task(_loop())
        return self._refresh_task

    # ------------------------------------------------------------------
    # Database query helpers
    # ------------------------------------------------------------------

    async def _get_accessible_databases(self) -> list[str]:
        """Return the list of databases the configured user can access."""
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_GET_ACCESSIBLE_DATABASES)
                rows = await cur.fetchall()
                all_dbs = [row[0] for row in rows]

        allowed = self._config.allowed_databases
        if allowed:
            return [db for db in all_dbs if db in allowed]
        return all_dbs

    async def _load_database_schema(self, db_name: str) -> DatabaseSchema:
        """Load full schema for one database."""
        tables = await self._load_tables(db_name)
        views = await self._load_views(db_name)
        enums = await self._load_enums(db_name)
        return DatabaseSchema(name=db_name, tables=tables, views=views, enums=enums)

    async def _load_tables(self, db_name: str) -> dict[str, TableSchema]:
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_GET_TABLES, (db_name,))
                rows = await cur.fetchall()

        tables: dict[str, TableSchema] = {}
        for table_name, comment, updated_at in rows:
            columns = await self._load_table_columns(db_name, table_name)
            indexes = await self._load_table_indexes(db_name, table_name)
            fks = await self._load_table_foreign_keys(db_name, table_name)
            triggers = await self._load_table_triggers(db_name, table_name)
            tables[table_name] = TableSchema(
                name=table_name,
                columns=columns,
                indexes=indexes,
                foreign_keys=fks,
                triggers=triggers,
                comment=comment or None,
                updated_at=float(updated_at),
            )
        return tables

    async def _load_table_columns(self, db_name: str, table_name: str) -> list[ColumnInfo]:
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_GET_COLUMNS, (db_name, table_name))
                rows = await cur.fetchall()
        return [
            ColumnInfo(
                name=row[0],
                type=row[1],
                default=row[2],
                nullable=row[3] == "YES",
                auto_increment="auto_increment" in (row[4] or "").lower(),
                comment=row[5] or None,
            )
            for row in rows
        ]

    async def _load_table_indexes(self, db_name: str, table_name: str) -> list[IndexInfo]:
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_GET_INDEXES, (db_name, table_name))
                rows = await cur.fetchall()
        return [
            IndexInfo(
                name=row[0],
                columns=(row[1] or "").split(","),
                unique=bool(row[2]),
                index_type=row[3] or "BTREE",
            )
            for row in rows
        ]

    async def _load_table_foreign_keys(self, db_name: str, table_name: str) -> list[ForeignKeyInfo]:
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_GET_FOREIGN_KEYS, (db_name, table_name))
                rows = await cur.fetchall()
        return [
            ForeignKeyInfo(
                name=row[0],
                columns=(row[1] or "").split(","),
                ref_table=row[2],
                ref_columns=(row[3] or "").split(","),
                on_delete=row[4] or "RESTRICT",
                on_update=row[5] or "RESTRICT",
            )
            for row in rows
        ]

    async def _load_table_triggers(self, db_name: str, table_name: str) -> list[TriggerInfo]:
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_GET_TRIGGERS, (db_name, table_name))
                rows = await cur.fetchall()
        return [
            TriggerInfo(name=row[0], event=row[1], timing=row[2], statement=row[3])
            for row in rows
        ]

    async def _load_views(self, db_name: str) -> dict[str, ViewSchema]:
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_GET_VIEWS, (db_name,))
                rows = await cur.fetchall()

        views: dict[str, ViewSchema] = {}
        for view_name, definition in rows:
            columns = await self._load_view_columns(db_name, view_name)
            views[view_name] = ViewSchema(
                name=view_name,
                columns=columns,
                definition=definition or None,
            )
        return views

    async def _load_view_columns(self, db_name: str, view_name: str) -> list[ColumnInfo]:
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_GET_COLUMNS, (db_name, view_name))
                rows = await cur.fetchall()
        return [
            ColumnInfo(
                name=row[0],
                type=row[1],
                default=row[2],
                nullable=row[3] == "YES",
                auto_increment="auto_increment" in (row[4] or "").lower(),
                comment=row[5] or None,
            )
            for row in rows
        ]

    async def _load_enums(self, db_name: str) -> list[EnumTypeInfo]:
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_GET_ENUMS, (db_name,))
                rows = await cur.fetchall()
        return [
            EnumTypeInfo(
                name=f"{row[1]}_{row[0]}",
                column_name=row[0],
                table_name=row[1],
                values=_parse_enum_values(row[2]),
            )
            for row in rows
        ]

    async def _fetch_current_table_timestamps(self, db_name: str) -> dict[str, tuple[float, str]]:
        """Return {table_name: (updated_at_unix, comment)} for all tables."""
        async with self._pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(_GET_TABLES, (db_name,))
                rows = await cur.fetchall()
        return {row[0]: (float(row[2]), row[1] or "") for row in rows}

    async def _refresh_table(
        self,
        db_name: str,
        table_name: str,
        comment: str,
        updated_at: float,
    ) -> None:
        columns = await self._load_table_columns(db_name, table_name)
        indexes = await self._load_table_indexes(db_name, table_name)
        fks = await self._load_table_foreign_keys(db_name, table_name)
        triggers = await self._load_table_triggers(db_name, table_name)
        db = self._cache.databases[db_name]
        db.tables[table_name] = TableSchema(
            name=table_name,
            columns=columns,
            indexes=indexes,
            foreign_keys=fks,
            triggers=triggers,
            comment=comment or None,
            updated_at=updated_at,
        )
        logger.debug("Refreshed table: %s.%s", db_name, table_name)

    def _rebuild_table_index(self) -> None:
        """Rebuild the global table_name → [database_names] index."""
        index: dict[str, list[str]] = {}
        for db_name, db in self._cache.databases.items():
            for table_name in db.tables:
                index.setdefault(table_name, []).append(db_name)
        self._cache.table_index = index
