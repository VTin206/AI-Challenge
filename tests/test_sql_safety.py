import pytest

from datamate.ingestion.loader import _table_from_rows
from datamate.schema import profile_tables
from datamate.sql import SafeSQLiteEngine, SQLSafetyError


def make_engine(tmp_path):
    table = _table_from_rows(tmp_path / "x.csv", "sales", [["id", "amount"], [1, 1.25], [2, 2.75]])
    return SafeSQLiteEngine([table])


def test_decimal_aggregation_and_select(tmp_path):
    engine = make_engine(tmp_path)
    try:
        assert engine.execute('SELECT dm_sum("amount") AS value FROM "sales"') == [{"value": "4.00"}]
    finally:
        engine.close()


@pytest.mark.parametrize("sql", [
    'DELETE FROM "sales"',
    'UPDATE "sales" SET "amount" = 0',
    'ATTACH DATABASE \'x.db\' AS x',
    'PRAGMA database_list',
    'SELECT * FROM sqlite_master',
    'SELECT readfile(\'x\')',
])
def test_rejects_mutation_or_external_access(tmp_path, sql):
    engine = make_engine(tmp_path)
    try:
        with pytest.raises(SQLSafetyError):
            engine.execute(sql)
    finally:
        engine.close()


def test_join_requires_verified_many_to_one_key_direction(tmp_path):
    customers = _table_from_rows(tmp_path / "c.csv", "customers", [["customer_id", "name"], [1, "An"], [2, "Binh"]])
    orders = _table_from_rows(tmp_path / "o.csv", "orders", [["order_id", "customer_id"], [10, 1], [11, 1], [12, 2]])
    catalog = profile_tables([customers, orders])
    engine = SafeSQLiteEngine([customers, orders], relations=catalog.relations)
    try:
        rows = engine.execute("SELECT c.name FROM orders o LEFT JOIN customers c ON o.customer_id = c.customer_id")
        assert [row["name"] for row in rows] == ["An", "An", "Binh"]
        with pytest.raises(SQLSafetyError):
            engine.execute("SELECT o.order_id FROM customers c LEFT JOIN orders o ON c.customer_id = o.customer_id")
        with pytest.raises(SQLSafetyError):
            engine.execute("SELECT c.name FROM orders o LEFT JOIN customers c ON o.order_id = c.customer_id")
    finally:
        engine.close()

