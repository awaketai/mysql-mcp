"""AI-assisted verification of generated SQL and query results."""

from __future__ import annotations

from src.llm.client import LLMClient


class AIResultValidator:
    """Uses the LLM to verify that generated SQL / results match user intent."""

    def __init__(self, llm_client: LLMClient) -> None:
        self._client = llm_client

    async def verify_sql_relevance(self, user_input: str, sql: str) -> bool:
        """Check whether *sql* semantically matches *user_input*."""
        return await self._client.verify_result(user_input, sql)

    async def verify_result_quality(
        self,
        user_input: str,
        sql: str,
        sample_rows: list[list],
    ) -> bool:
        """Check whether *sample_rows* meaningfully answer *user_input*."""
        return await self._client.verify_result(user_input, sql, sample_rows=sample_rows)
