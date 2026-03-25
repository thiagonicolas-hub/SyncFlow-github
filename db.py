import os
import sqlite3
from pathlib import Path

APP_NAME = "SyncFlow"

def get_db_path() -> Path:
    # Salva em AppData (não depende de permissão de "Program Files")
    base = Path(os.getenv("APPDATA", Path.home()))
    data_dir = base / APP_NAME
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "trackflow.db"

def get_conn():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # Coloque aqui os CREATE TABLE do seu sistema
    # Exemplo:
    cur.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE,
        senha_hash TEXT,
        nome TEXT
    );
    """)

    conn.commit()
    conn.close()
