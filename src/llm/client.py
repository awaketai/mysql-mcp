"""AsyncOpenAI wrapper for SQL generation and result verification."""

from __future__ import annotations

import logging
import re

from openai import AsyncOpenAI

from src.config import OpenAIConfig

logger = logging.getLogger(__name__)

# Pattern to extract SQL from markdown code blocks: ```sql\n...\n``` or ```\n...\n```
_CODE_BLOCK_RE = re.compile(r"```(?:sql)?\s*\n?(.*?)```", re.DOTALL)


class LLMClient:
    """Thin wrapper around AsyncOpenAI for SQL generation tasks."""

    def __init__(self, config: OpenAIConfig) -> None:
        self._config = config
        self._client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            max_retries=config.max_retries,
            timeout=config.timeout,
        )

    async def generate_sql(self, system_prompt: str, user_input: str) -> str:
        """Call the LLM to generate SQL from natural language.

        Returns the extracted SQL with surrounding markdown stripped.
        """
        logger.debug("Generating SQL for: %s", user_input[:200])
        response = await self._client.chat.completions.create(
            model=self._config.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            temperature=0,
        )
        raw = response.choices[0].message.content or ""
        sql = _extract_sql(raw)
        logger.debug("Generated SQL: %s", sql[:200])
        return sql

    async def verify_result(
        self,
        user_input: str,
        sql: str,
        sample_rows: list[list] | None = None,
    ) -> bool:
        """Ask the LLM whether the generated SQL / results match user intent."""
        if sample_rows:
            prompt = (
                f"User asked: {user_input}\n\n"
                f"Generated SQL: {sql}\n\n"
                f"Sample results (first 5 rows): {sample_rows[:5]}\n\n"
                "Do the results answer the user's question? Reply ONLY 'yes' or 'no'."
            )
        else:
            prompt = (
                f"User asked: {user_input}\n\n"
                f"Generated SQL: {sql}\n\n"
                "Does this SQL correctly answer the user's question? "
                "Reply ONLY 'yes' or 'no'."
            )

        response = await self._client.chat.completions.create(
            model=self._config.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=10,
        )
        answer = (response.choices[0].message.content or "").strip().lower()
        return answer.startswith("yes")

    async def close(self) -> None:
        await self._client.close()


def _extract_sql(text: str) -> str:
    """Extract SQL from LLM output, stripping markdown code blocks if present."""
    match = _CODE_BLOCK_RE.search(text)
    if match:
        return match.group(1).strip()

    # No code block — strip common prefixes the LLM might add
    lines = text.strip().splitlines()
    # Drop lines that look like explanatory text before the SQL
    sql_lines: list[str] = []
    found_sql = False
    for line in lines:
        stripped = line.strip()
        if not found_sql:
            upper = stripped.upper()
            if upper.startswith("SELECT") or upper.startswith("WITH"):
                found_sql = True
                sql_lines.append(stripped)
        else:
            sql_lines.append(stripped)

    return "\n".join(sql_lines) if sql_lines else text.strip()
