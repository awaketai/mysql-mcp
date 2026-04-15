"""Tests for src.security.validator."""

from __future__ import annotations

import pytest

from src.security.validator import SQLValidationError, SQLValidator


@pytest.fixture()
def validator() -> SQLValidator:
    return SQLValidator()


# ---- Pass-through: valid SELECTs ----


class TestValidSelect:
    def test_simple_select(self, validator: SQLValidator) -> None:
        result = validator.validate("SELECT 1")
        assert "SELECT" in result

    def test_select_with_from(self, validator: SQLValidator) -> None:
        result = validator.validate("SELECT id, name FROM users")
        assert "SELECT" in result

    def test_select_with_join(self, validator: SQLValidator) -> None:
        sql = "SELECT u.id, o.total FROM users u JOIN orders o ON u.id = o.user_id"
        result = validator.validate(sql)
        assert "JOIN" in result

    def test_select_with_subquery(self, validator: SQLValidator) -> None:
        sql = "SELECT * FROM (SELECT id FROM users) AS sub"
        result = validator.validate(sql)
        assert "SELECT" in result

    def test_select_with_group_by(self, validator: SQLValidator) -> None:
        sql = "SELECT status, COUNT(*) FROM users GROUP BY status"
        result = validator.validate(sql)
        assert "GROUP BY" in result

    def test_select_with_where_and_order(self, validator: SQLValidator) -> None:
        sql = "SELECT id FROM users WHERE status = 'active' ORDER BY id DESC LIMIT 10"
        result = validator.validate(sql)
        assert "LIMIT 10" in result

    def test_complex_aggregation(self, validator: SQLValidator) -> None:
        sql = (
            "SELECT department_id, AVG(salary) AS avg_salary "
            "FROM employees "
            "GROUP BY department_id "
            "HAVING AVG(salary) > 50000"
        )
        result = validator.validate(sql)
        assert "HAVING" in result


# ---- Auto-append LIMIT ----


class TestAutoLimit:
    def test_no_limit_adds_max_limit(self, validator: SQLValidator) -> None:
        result = validator.validate("SELECT * FROM users")
        assert "LIMIT" in result
        assert "1000" in result

    def test_existing_limit_kept(self, validator: SQLValidator) -> None:
        result = validator.validate("SELECT * FROM users LIMIT 50")
        assert "LIMIT 50" in result

    def test_limit_capped_to_max(self, validator: SQLValidator) -> None:
        result = validator.validate("SELECT * FROM users LIMIT 5000", max_limit=1000)
        assert "LIMIT 1000" in result

    def test_custom_max_limit(self, validator: SQLValidator) -> None:
        result = validator.validate("SELECT * FROM users LIMIT 5000", max_limit=200)
        assert "LIMIT 200" in result

    def test_no_limit_custom_max(self, validator: SQLValidator) -> None:
        result = validator.validate("SELECT * FROM users", max_limit=500)
        assert "LIMIT 500" in result


# ---- Rejected: non-SELECT statements ----


class TestRejectedStatements:
    def test_insert(self, validator: SQLValidator) -> None:
        with pytest.raises(SQLValidationError, match="Only SELECT"):
            validator.validate("INSERT INTO users (id) VALUES (1)")

    def test_update(self, validator: SQLValidator) -> None:
        with pytest.raises(SQLValidationError, match="Only SELECT"):
            validator.validate("UPDATE users SET name = 'x'")

    def test_delete(self, validator: SQLValidator) -> None:
        with pytest.raises(SQLValidationError, match="Only SELECT"):
            validator.validate("DELETE FROM users")

    def test_replace(self, validator: SQLValidator) -> None:
        with pytest.raises(SQLValidationError, match="Only SELECT"):
            validator.validate("REPLACE INTO users (id) VALUES (1)")

    def test_create_table(self, validator: SQLValidator) -> None:
        with pytest.raises(SQLValidationError, match="Only SELECT"):
            validator.validate("CREATE TABLE t (id INT)")

    def test_alter_table(self, validator: SQLValidator) -> None:
        with pytest.raises(SQLValidationError, match="Only SELECT"):
            validator.validate("ALTER TABLE users ADD COLUMN age INT")

    def test_drop_table(self, validator: SQLValidator) -> None:
        with pytest.raises(SQLValidationError, match="Only SELECT"):
            validator.validate("DROP TABLE users")

    def test_truncate(self, validator: SQLValidator) -> None:
        with pytest.raises(SQLValidationError, match="Only SELECT"):
            validator.validate("TRUNCATE TABLE users")

    def test_grant(self, validator: SQLValidator) -> None:
        with pytest.raises(SQLValidationError, match="Only SELECT"):
            validator.validate("GRANT ALL ON *.* TO 'user'@'%'")

    def test_revoke(self, validator: SQLValidator) -> None:
        with pytest.raises(SQLValidationError, match="Only SELECT"):
            validator.validate("REVOKE ALL ON *.* FROM 'user'@'%'")

    def test_select_into_outfile(self, validator: SQLValidator) -> None:
        """INTO OUTFILE cannot be parsed by sqlglot for MySQL — rejected at parse time."""
        with pytest.raises(Exception):
            validator.validate(
                "SELECT * FROM users INTO OUTFILE '/tmp/dump.csv'"
            )


# ---- Rejected: multi-statement ----


class TestMultiStatement:
    def test_semicolon_separated(self, validator: SQLValidator) -> None:
        with pytest.raises(SQLValidationError, match="single SQL statement"):
            validator.validate("SELECT 1; DROP TABLE users")

    def test_empty_string(self, validator: SQLValidator) -> None:
        with pytest.raises(SQLValidationError, match="single SQL statement"):
            validator.validate("")


# ---- Rejected: dangerous functions ----


class TestForbiddenFunctions:
    def test_load_file(self, validator: SQLValidator) -> None:
        with pytest.raises(SQLValidationError, match="Forbidden function"):
            validator.validate("SELECT LOAD_FILE('/etc/passwd')")


# ---- Edge cases ----


class TestEdgeCases:
    def test_select_star(self, validator: SQLValidator) -> None:
        result = validator.validate("SELECT * FROM users")
        assert "SELECT" in result

    def test_select_with_alias(self, validator: SQLValidator) -> None:
        result = validator.validate("SELECT id AS user_id FROM users")
        assert "user_id" in result

    def test_select_with_in_clause(self, validator: SQLValidator) -> None:
        result = validator.validate("SELECT * FROM users WHERE id IN (1, 2, 3)")
        assert "IN" in result

    def test_select_with_between(self, validator: SQLValidator) -> None:
        result = validator.validate("SELECT * FROM users WHERE age BETWEEN 18 AND 65")
        assert "BETWEEN" in result

    def test_select_with_like(self, validator: SQLValidator) -> None:
        result = validator.validate("SELECT * FROM users WHERE name LIKE '%alice%'")
        assert "LIKE" in result

    def test_select_with_union(self, validator: SQLValidator) -> None:
        sql = "SELECT id FROM users UNION SELECT id FROM admins"
        result = validator.validate(sql)
        assert "UNION" in result

    def test_case_insensitive_select(self, validator: SQLValidator) -> None:
        result = validator.validate("select * from users")
        assert "SELECT" in result

    def test_select_with_left_join(self, validator: SQLValidator) -> None:
        sql = (
            "SELECT u.name, o.total "
            "FROM users u "
            "LEFT JOIN orders o ON u.id = o.user_id"
        )
        result = validator.validate(sql)
        assert "LEFT JOIN" in result
