from datamate.ingestion.loader import _table_from_rows
from datamate.rules import load_rulebook
from datamate.schema import profile_tables


def test_profiler_finds_primary_and_foreign_key_candidates(tmp_path):
    customer = _table_from_rows(tmp_path / "a.csv", "customers", [["customer_id", "name"], [1, "A"], [2, "B"]])
    orders = _table_from_rows(tmp_path / "b.csv", "orders", [["order_id", "customer_id"], [10, 1], [11, 1], [12, 2]])
    catalog = profile_tables([customer, orders])
    assert any(col.name == "customer_id" and col.primary_key_candidate for col in catalog.tables[0].columns)
    assert any(rel.from_table == "orders" and rel.to_table == "customers" for rel in catalog.relations)


def test_equal_priority_rule_conflict_is_reported(tmp_path):
    (tmp_path / "README.md").write_text(
        "RULE [priority=10]: metric.revenue = quantity * unit_price\n", encoding="utf-8"
    )
    (tmp_path / "RULEBOOK.md").write_text(
        "RULE [priority=10]: metric.revenue = quantity * price\n", encoding="utf-8"
    )
    rules = load_rulebook(tmp_path, "", "")
    value, error = rules.executable("metric.revenue")
    assert value is None
    assert "Conflicting rules" in error

