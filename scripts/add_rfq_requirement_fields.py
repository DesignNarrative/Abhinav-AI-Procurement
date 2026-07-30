"""
Idempotent migration: add the merged Requirement-context columns to `rfqs`.

Adds priority, required_date, purpose as NULLABLE columns so existing RFQs and
the working send flow are completely unaffected. Safe to run multiple times
(uses ADD COLUMN IF NOT EXISTS — PostgreSQL).

Run once:
    .\.venv\Scripts\python.exe -m scripts.add_rfq_requirement_fields
"""

from sqlalchemy import text

from app.database.database import engine

STATEMENTS = [
    "ALTER TABLE rfqs ADD COLUMN IF NOT EXISTS priority VARCHAR(20)",
    "ALTER TABLE rfqs ADD COLUMN IF NOT EXISTS required_date VARCHAR(50)",
    "ALTER TABLE rfqs ADD COLUMN IF NOT EXISTS purpose TEXT",
]


def main():
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            conn.execute(text(stmt))
            print(f"OK: {stmt}")
    print("Migration complete.")


if __name__ == "__main__":
    main()
