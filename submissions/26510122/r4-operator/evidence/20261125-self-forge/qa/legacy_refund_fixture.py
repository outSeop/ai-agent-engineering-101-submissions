"""Synthetic compatibility fixture and source-only schema export for refund validation."""
import ast
from contextlib import closing, contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

from fixture import MOCK_SKU, Fixture


REFUND_TABLES = (
    "identity", "sale", "refund", "lot", "allocation", "promotion_loss",
    "stock_intent", "stock_plan", "event", "removal",
)
SOURCES = ("dispatcher.py", "price_policy.py", "procurement.py")


def literal_schema(path):
    source = path.read_bytes()
    for statement in ast.parse(source).body:
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "SCHEMA" for target in statement.targets
        ):
            return ast.literal_eval(statement.value), hashlib.sha256(source).hexdigest()
    raise ValueError(f"no literal SCHEMA in {path.name}")


def source_contract(directory):
    schemas = {name: literal_schema(directory / name) for name in SOURCES}
    with closing(sqlite3.connect(":memory:")) as db:
        db.row_factory = sqlite3.Row
        for ddl, _ in schemas.values():
            db.executescript(ddl)
        result = {}
        for table in REFUND_TABLES:
            ddl, = db.execute("SELECT sql FROM sqlite_schema WHERE name=?", (table,)).fetchone()
            result[table] = {
                "ddl": ddl,
                "columns": [dict(r) for r in db.execute(f"PRAGMA table_info({table})")],
                "foreign_keys": [dict(r) for r in db.execute(f"PRAGMA foreign_key_list({table})")],
                "indexes": [dict(r) for r in db.execute(
                    "SELECT name,sql FROM sqlite_schema WHERE type='index' AND tbl_name=? ORDER BY name",
                    (table,),
                )],
            }
    return {"database": "state/r4-benefits/benefits.sqlite3",
            "source_sha256": {name: value[1] for name, value in schemas.items()}, "tables": result}


@contextmanager
def existing_refund_case():
    """Yield a temporary prepopulated ledger and the fixture's existing mock evidence."""
    with TemporaryDirectory(prefix="r4-legacy-refund-") as temp:
        root = Path(temp)
        fixture = Fixture(root)
        fixture.db_path = root / "state/r4-benefits/benefits.sqlite3"
        fixture.add_unit("legacy-fixture-prior")
        first = fixture.call({"text": f"구매 {MOCK_SKU}"})
        right = fixture.right(first)
        prior = fixture.settle(first)
        if not fixture.sync()["current"]:
            raise RuntimeError("synthetic prior purchase did not settle")
        fixture.add_unit("legacy-fixture-claim")
        second = fixture.call({"text": f"구매 {MOCK_SKU} 권리 {right}"})
        sale = fixture.settle(second)
        if not fixture.sync()["current"]:
            raise RuntimeError("synthetic target purchase did not settle")
        fixture.advance(3600)
        fixture.breakage(sale)
        reply = fixture.call({"text": f"환불 {sale['tx_hash']} 권리 {right}"})
        if "검토를 접수" not in reply["reply"]:
            raise RuntimeError("synthetic refund request was not created")
        with closing(fixture.open()) as db:
            ddl, _ = literal_schema(Path(__file__).with_name("procurement.py"))
            db.executescript(ddl)
            case = dict(db.execute("SELECT * FROM refund").fetchone())
            assert case["status"] == "requested"
            assert db.execute("SELECT COUNT(*) FROM allocation WHERE status='spent'").fetchone()[0] == 1
        yield fixture, {"root": root, "claim": case, "sale": sale, "prior": prior,
                        "customer_right": right, "checkout": second}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: legacy_refund_fixture.py SOURCE_DIRECTORY")
    print(json.dumps(source_contract(Path(sys.argv[1])), ensure_ascii=False, indent=2))

