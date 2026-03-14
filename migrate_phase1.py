"""Migration script — Phase 1: ALTER existing tables, then create new tables."""
import sqlite3
import sys

DB_PATH = "smartfood.db"

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

def add_column_if_missing(table, column, col_type):
    cur.execute(f"PRAGMA table_info({table})")
    existing = [row[1] for row in cur.fetchall()]
    if column not in existing:
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            print(f"  + {table}.{column}")
        except Exception as e:
            print(f"  ! {table}.{column}: {e}")
    else:
        print(f"  = {table}.{column} already exists")

print("--- customers ---")
for col, typ in [
    ("cnpj", "TEXT"),
    ("razao_social", "TEXT"),
    ("nome_representante", "TEXT"),
    ("telefone_representante", "TEXT"),
    ("telefone_vendedor", "TEXT"),
    ("endereco_completo", "TEXT"),
]:
    add_column_if_missing("customers", col, typ)

print("--- suppliers ---")
for col, typ in [
    ("cnpj", "TEXT"),
    ("razao_social", "TEXT"),
    ("nome_representante", "TEXT"),
    ("telefone_representante", "TEXT"),
    ("telefone_vendedor", "TEXT"),
    ("endereco_completo", "TEXT"),
]:
    add_column_if_missing("suppliers", col, typ)

print("--- bom_items ---")
add_column_if_missing("bom_items", "perda_processo_kg", "REAL DEFAULT 0.0")

conn.commit()
conn.close()

print("\n--- create_all (new tables) ---")
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

# Load env before importing app modules
from dotenv import load_dotenv
load_dotenv()

from database import engine
import models
models.Base.metadata.create_all(bind=engine)
print("Done.")
