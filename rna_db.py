# -*- coding: utf-8 -*-
"""RNA 库存数据层 (SQLite)。

单位约定:
  购入量 nmol; ddH2O 量 / 使用量 / 剩余量 μL; 配制浓度 μM (= 购入量 ÷ ddH2O 量 × 1000)。
数据文件: 同目录 rna_inventory.db (测试时可用环境变量 RNA_DB_PATH 覆盖)。
"""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("RNA_DB_PATH", BASE_DIR / "rna_inventory.db"))


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db():
    conn = get_conn()
    try:
        yield conn
    finally:
        conn.close()


def init_db(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS powder(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rna_name TEXT NOT NULL,
        purchase_date TEXT NOT NULL,
        amount REAL NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS solution(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rna_name TEXT NOT NULL,
        purchase_date TEXT NOT NULL,
        amount REAL NOT NULL,
        prep_date TEXT NOT NULL,
        water_vol REAL NOT NULL,
        concentration REAL NOT NULL,
        remaining REAL NOT NULL)""")
    # v2 迁移: 浓度单位由 nmol/μL 改为 μM, 旧数值 ×1000 (一次性)
    ver = conn.execute("PRAGMA user_version").fetchone()[0]
    if ver < 2:
        conn.execute("UPDATE solution SET concentration = round(concentration * 1000, 6)")
        conn.execute("PRAGMA user_version = 2")
    conn.commit()


def fmt_num(x, nd=2):
    """数字显示: 最多保留 nd 位小数, 去掉末尾多余的 0"""
    return f"{x:.{nd}f}".rstrip("0").rstrip(".")


# -- 购入 ----------------------------------------------------------

def add_powder(conn, rna_name, purchase_date, amount):
    cur = conn.execute(
        "INSERT INTO powder(rna_name, purchase_date, amount) VALUES(?,?,?)",
        (rna_name, purchase_date, amount))
    conn.commit()
    return cur.lastrowid


def list_powders(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM powder ORDER BY id")]


def list_solutions(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM solution ORDER BY id")]


def get_powder(conn, pid):
    r = conn.execute("SELECT * FROM powder WHERE id=?", (pid,)).fetchone()
    return dict(r) if r else None


def get_solution(conn, sid):
    r = conn.execute("SELECT * FROM solution WHERE id=?", (sid,)).fetchone()
    return dict(r) if r else None


def delete_powder(conn, pid):
    conn.execute("DELETE FROM powder WHERE id=?", (pid,))
    conn.commit()


def delete_solution(conn, sid):
    conn.execute("DELETE FROM solution WHERE id=?", (sid,))
    conn.commit()


# -- 配制 ----------------------------------------------------------

def prepare(conn, powder_id, prep_date, water_vol):
    """干粉 → 溶液: 浓度(μM) = 购入量(nmol) ÷ ddH2O 量(μL) × 1000; 剩余量初始 = ddH2O 量; 原干粉条目删除"""
    p = get_powder(conn, powder_id)
    if p is None:
        return False, "所选干粉条目不存在, 请重新选择"
    if water_vol <= 0:
        return False, "ddH2O 量必须大于 0"
    concentration = round(p["amount"] / water_vol * 1000, 6)
    conn.execute(
        "INSERT INTO solution(rna_name, purchase_date, amount, prep_date, water_vol, concentration, remaining) "
        "VALUES(?,?,?,?,?,?,?)",
        (p["rna_name"], p["purchase_date"], p["amount"], prep_date,
         water_vol, concentration, water_vol))
    conn.execute("DELETE FROM powder WHERE id=?", (powder_id,))
    conn.commit()
    return True, (f"配制完成: 浓度 {fmt_num(concentration, 4)} μM, "
                  f"初始剩余量 {fmt_num(water_vol)} μL")


# -- 使用 ----------------------------------------------------------

def use_solution(conn, solution_id, usage):
    """使用: 剩余量 = 当前剩余量 − 使用量 (首次使用时当前剩余量即 ddH2O 量)"""
    s = get_solution(conn, solution_id)
    if s is None:
        return False, "所选溶液条目不存在, 请重新选择"
    if usage <= 0:
        return False, "使用量必须大于 0"
    if usage > s["remaining"] + 1e-9:
        return False, f"使用量({fmt_num(usage)} μL)超过当前剩余量({fmt_num(s['remaining'])} μL)"
    new_remaining = round(s["remaining"] - usage, 6)
    conn.execute("UPDATE solution SET remaining=? WHERE id=?", (new_remaining, solution_id))
    conn.commit()
    return True, f"已记录使用, 剩余量 {fmt_num(new_remaining)} μL"
