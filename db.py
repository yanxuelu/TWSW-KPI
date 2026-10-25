# -*- coding: utf-8 -*-
"""数据库连接与通用 helper"""
import os
import sqlite3

from flask import g

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("PERF_DB", os.path.join(BASE_DIR, "perf.db"))
SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")


def get_db():
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        g.db = conn
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db(app):
    with app.app_context():
        db = sqlite3.connect(DB_PATH)
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            db.executescript(f.read())
        db.commit()
        # 轻量迁移：为已存在的库补充新列（IF NOT EXISTS 由 try 包裹实现）
        for table, col, ddl in (
            ("self_assessments", "signature", "TEXT"),
            ("self_assessments", "confirmed", "INTEGER NOT NULL DEFAULT 0"),
        ):
            exists = db.execute(
                "SELECT 1 FROM pragma_table_info(?) WHERE name=?", (table, col)).fetchone()
            if not exists:
                db.execute("ALTER TABLE %s ADD COLUMN %s %s" % (table, col, ddl))
        db.commit()
        db.close()
    os.makedirs(UPLOAD_DIR, exist_ok=True)


def query_all(sql, args=()):
    return get_db().execute(sql, args).fetchall()


def query_one(sql, args=()):
    return get_db().execute(sql, args).fetchone()


def execute(sql, args=()):
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur.lastrowid


def updates(sql, args=()):
    db = get_db()
    cur = db.execute(sql, args)
    db.commit()
    return cur.rowcount


def rows_to_dicts(rows):
    return [dict(r) for r in rows]
