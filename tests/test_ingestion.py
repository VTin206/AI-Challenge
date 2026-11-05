import sqlite3

from openpyxl import Workbook

from datamate.ingestion import discover_files, load_package


def test_loads_csv_excel_and_sqlite_tables(tmp_path):
    (tmp_path / "items.csv").write_text("Tên hàng;Số lượng\nÁo;2\nQuần;3\n", encoding="utf-8")
    book = Workbook()
    sheet = book.active
    sheet.title = "Kho"
    sheet.append(["Mã", "Tồn kho"])
    sheet.append(["A1", 5])
    book.save(tmp_path / "stock.xlsx")
    db = sqlite3.connect(tmp_path / "orders.sqlite")
    db.execute("CREATE TABLE invoices (invoice_id TEXT, total INTEGER)")
    db.execute("INSERT INTO invoices VALUES ('I1', 1200)")
    db.commit()
    db.close()

    package = load_package(tmp_path)
    assert len(discover_files(tmp_path)) == 3
    assert {table.name for table in package.tables} == {"items", "stock_kho", "orders_invoices"}
    csv_table = next(table for table in package.tables if table.name == "items")
    assert csv_table.columns == ("ten_hang", "so_luong")
    assert csv_table.rows[0] == ("Áo", 2)
    sqlite_table = next(table for table in package.tables if table.name == "orders_invoices")
    assert sqlite_table.rows[0] == ("I1", 1200)


def test_ambiguous_number_format_is_not_converted(tmp_path):
    (tmp_path / "prices.csv").write_text('price\n"1.234,56"\n', encoding="utf-8")
    package = load_package(tmp_path)
    assert package.tables[0].rows[0][0] == "1.234,56"

