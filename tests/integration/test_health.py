"""Integration tests for SQL security validation edge cases."""

from __future__ import annotations

import pytest

from mysql_mcp.security.validator import SQLValidationError, SQLValidator


@pytest.fixture()
def validator() -> SQLValidator:
    return SQLValidator()


class TestSQLSecurityEdgeCases:
    """Exhaustive security boundary testing."""

    def test_nested_subquery(self, validator: SQLValidator) -> None:
        sql = (
            "SELECT * FROM users WHERE id IN "
            "(SELECT user_id FROM orders WHERE total > 100) LIMIT 10"
        )
        result = validator.validate(sql)
        assert "SELECT" in result

    def test_union_all(self, validator: SQLValidator) -> None:
        sql = "SELECT id FROM users UNION ALL SELECT id FROM orders"
        result = validator.validate(sql)
        assert "UNION" in result

    def test_cte(self, validator: SQLValidator) -> None:
        sql = (
            "WITH active AS (SELECT * FROM users WHERE status = 'active') "
            "SELECT * FROM active LIMIT 10"
        )
        result = validator.validate(sql)
        assert "WITH" in result

    def test_case_expression(self, validator: SQLValidator) -> None:
        sql = (
            "SELECT CASE WHEN total > 100 THEN 'high' ELSE 'low' END AS tier "
            "FROM orders LIMIT 10"
        )
        result = validator.validate(sql)
        assert "CASE" in result

    def test_group_concat(self, validator: SQLValidator) -> None:
        sql = "SELECT status, GROUP_CONCAT(name) FROM users GROUP BY status LIMIT 10"
        result = validator.validate(sql)
        assert "GROUP_CONCAT" in result

    def test_having(self, validator: SQLValidator) -> None:
        sql = (
            "SELECT user_id, COUNT(*) AS cnt FROM orders "
            "GROUP BY user_id HAVING cnt > 5 LIMIT 10"
        )
        result = validator.validate(sql)
        assert "HAVING" in result

    def test_left_join_with_group(self, validator: SQLValidator) -> None:
        sql = (
            "SELECT u.name, COUNT(o.id) AS order_count "
            "FROM users u LEFT JOIN orders o ON u.id = o.user_id "
            "GROUP BY u.name LIMIT 10"
        )
        result = validator.validate(sql)
        assert "LEFT JOIN" in result

    def test_date_function(self, validator: SQLValidator) -> None:
        sql = (
            "SELECT DATE(created_at) AS day, COUNT(*) FROM orders "
            "GROUP BY day LIMIT 30"
        )
        result = validator.validate(sql)
        assert "DATE" in result

    def test_if_function(self, validator: SQLValidator) -> None:
        sql = "SELECT IF(total > 100, 'big', 'small') AS size FROM orders LIMIT 10"
        result = validator.validate(sql)
        # sqlglot normalizes IF() to CASE WHEN … THEN … ELSE … END
        assert "CASE" in result

    # Rejection cases
    def test_reject_create_table_as_select(self, validator: SQLValidator) -> None:
        with pytest.raises(SQLValidationError):
            validator.validate("CREATE TABLE new_users AS SELECT * FROM users")

    def test_reject_set_variable(self, validator: SQLValidator) -> None:
        """SET is a non-SELECT statement."""
        with pytest.raises((SQLValidationError, Exception)):
            validator.validate("SET @x = 1")

    def test_reject_multi_statement_with_comment(self, validator: SQLValidator) -> None:
        with pytest.raises(SQLValidationError, match="single"):
            validator.validate("SELECT 1; /* comment */ DROP TABLE users")


class TestSQLLimitEdgeCases:
    def test_limit_zero(self, validator: SQLValidator) -> None:
        result = validator.validate("SELECT * FROM users LIMIT 0")
        assert "LIMIT 0" in result

    def test_limit_one(self, validator: SQLValidator) -> None:
        result = validator.validate("SELECT * FROM users LIMIT 1")
        assert "LIMIT 1" in result

    def test_limit_exactly_max(self, validator: SQLValidator) -> None:
        result = validator.validate("SELECT * FROM users LIMIT 1000")
        assert "LIMIT 1000" in result

    def test_limit_just_over_max(self, validator: SQLValidator) -> None:
        result = validator.validate("SELECT * FROM users LIMIT 1001")
        assert "LIMIT 1000" in result

    def test_no_limit_gets_auto_added(self, validator: SQLValidator) -> None:
        result = validator.validate("SELECT * FROM users WHERE id = 1")
        assert "LIMIT 1000" in result

    def test_custom_max_limit(self, validator: SQLValidator) -> None:
        result = validator.validate("SELECT * FROM users", max_limit=50)
        assert "LIMIT 50" in result
