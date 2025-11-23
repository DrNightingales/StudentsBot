import pytest
import sqlite3 as sql
import os
from pathlib import Path

DB_PATH = 'mock.db'
def init_mock_db():
    cwd = Path(os.getcwd())
    db_full_path = cwd / Path(DB_PATH)
    if os.path.exists(db_full_path):
        os.remove(db_full_path)
    with sql.connect(db_full_path) as db:
        for req in db_schemas.values():
            db.execute(req)
        db.commit()
