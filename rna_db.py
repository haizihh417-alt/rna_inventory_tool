# -*- coding: utf-8 -*-
"""RNA 库存数据层 (SQLite)。

单位约定:
  购入量 nmol; ddH2O 量 / 使用量 / 剩余量 μL; 配制浓度 μM (= 购入量 ÷ ddH2O 量 × 1000)。
数据文件: 同目录 rna_inventory.db (测试时可用环境变量 RNA_DB_PATH 覆盖)。

多台电脑同步:
  每条记录带 sync_id (跨电脑唯一), 导出为 JSON; 导入时按 sync_id 合并:
  不存在则新增, 存在且导出端更新时间更新则更新, 否则跳过。不做删除同步。
"""

import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("RNA_DB_PATH", BASE_DIR / "rna_inventory.db"))

SYNC_FORMAT = 1

# 同步 JSON 中参与合并的字段
POWDER_SYNC_FIELDS = ("rna_name", "purchase_date", "amount")
SOLUTION_SYNC_FIELDS = ("rna_name", "purchase_date", "amount", "prep_date",
                        "water_vol", "concentration", "remaining")
NUMERIC_FIELDS = {"amount", "water_vol", "concentration", "remaining"}


def new_sync_id():
    """跨电脑唯一的记录标识"""
    return uuid.uuid4().hex


def now_ts():
    """UTC 时间戳, 格式与字符串排序一致: 2026-11-10T12:34:56.789Z"""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds") \
        .replace("+00:00", "Z")


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
    # v3 迁移: 多电脑同步所需的 sync_id / updated_at / source_sync_id
    _ensure_sync_columns(conn)
    conn.execute("PRAGMA user_version = 3")
    conn.commit()


def _ensure_sync_columns(conn):
    """为旧数据库补齐同步字段, 并给已有记录生成 sync_id"""
    p_cols = {r[1] for r in conn.execute("PRAGMA table_info(powder)")}
    if "sync_id" not in p_cols:
        conn.execute("ALTER TABLE powder ADD COLUMN sync_id TEXT")
    if "updated_at" not in p_cols:
        conn.execute("ALTER TABLE powder ADD COLUMN updated_at TEXT")

    s_cols = {r[1] for r in conn.execute("PRAGMA table_info(solution)")}
    if "sync_id" not in s_cols:
        conn.execute("ALTER TABLE solution ADD COLUMN sync_id TEXT")
    if "updated_at" not in s_cols:
        conn.execute("ALTER TABLE solution ADD COLUMN updated_at TEXT")
    if "source_sync_id" not in s_cols:
        conn.execute("ALTER TABLE solution ADD COLUMN source_sync_id TEXT DEFAULT ''")

    for table in ("powder", "solution"):
        rows = conn.execute(
            f"SELECT id FROM {table} WHERE sync_id IS NULL OR sync_id = ''").fetchall()
        for r in rows:
            conn.execute(f"UPDATE {table} SET sync_id=? WHERE id=?",
                         (new_sync_id(), r["id"]))
        conn.execute(
            f"UPDATE {table} SET updated_at=? WHERE updated_at IS NULL OR updated_at = ''",
            (now_ts(),))
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_powder_sync ON powder(sync_id)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_solution_sync ON solution(sync_id)")


def fmt_num(x, nd=2):
    """数字显示: 最多保留 nd 位小数, 去掉末尾多余的 0"""
    return f"{x:.{nd}f}".rstrip("0").rstrip(".")


# -- 购入 ----------------------------------------------------------

def add_powder(conn, rna_name, purchase_date, amount):
    cur = conn.execute(
        "INSERT INTO powder(rna_name, purchase_date, amount, sync_id, updated_at) "
        "VALUES(?,?,?,?,?)",
        (rna_name, purchase_date, amount, new_sync_id(), now_ts()))
    conn.commit()
    return cur.lastrowid


def list_powders(conn):
    """按购入日期从晚到早排序(同日按登记先后倒序)"""
    return [dict(r) for r in conn.execute(
        "SELECT * FROM powder ORDER BY purchase_date DESC, id DESC")]


def list_solutions(conn):
    """按购入日期从晚到早排序(同日按登记先后倒序)"""
    return [dict(r) for r in conn.execute(
        "SELECT * FROM solution ORDER BY purchase_date DESC, id DESC")]


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
        "INSERT INTO solution(rna_name, purchase_date, amount, prep_date, water_vol, "
        "concentration, remaining, source_sync_id, sync_id, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (p["rna_name"], p["purchase_date"], p["amount"], prep_date,
         water_vol, concentration, water_vol, p.get("sync_id") or "",
         new_sync_id(), now_ts()))
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
    conn.execute("UPDATE solution SET remaining=?, updated_at=? WHERE id=?",
                 (new_remaining, now_ts(), solution_id))
    conn.commit()
    return True, f"已记录使用, 剩余量 {fmt_num(new_remaining)} μL"


# -- 编辑 / 直接添加 -------------------------------------------------

def update_powder(conn, pid, rna_name, purchase_date, amount):
    conn.execute(
        "UPDATE powder SET rna_name=?, purchase_date=?, amount=?, updated_at=? WHERE id=?",
        (rna_name, purchase_date, amount, now_ts(), pid))
    conn.commit()


def update_solution(conn, sid, rna_name, purchase_date, amount, prep_date,
                    water_vol, concentration, remaining):
    conn.execute(
        "UPDATE solution SET rna_name=?, purchase_date=?, amount=?, prep_date=?, "
        "water_vol=?, concentration=?, remaining=?, updated_at=? WHERE id=?",
        (rna_name, purchase_date, amount, prep_date,
         water_vol, concentration, remaining, now_ts(), sid))
    conn.commit()


def add_solution(conn, rna_name, purchase_date, amount, prep_date,
                 water_vol, concentration, remaining):
    """直接添加溶液条目(已有库存, 独立于干粉仓库), 不消耗干粉"""
    cur = conn.execute(
        "INSERT INTO solution(rna_name, purchase_date, amount, prep_date, "
        "water_vol, concentration, remaining, sync_id, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (rna_name, purchase_date, amount, prep_date,
         water_vol, concentration, remaining, new_sync_id(), now_ts()))
    conn.commit()
    return cur.lastrowid


# -- 多电脑同步: 导出 / 导入 ------------------------------------------

def export_data(conn):
    """导出全部条目为可跨电脑合并的 JSON 结构(不含本机自增 id)"""
    powders = [dict(r) for r in conn.execute(
        "SELECT sync_id, rna_name, purchase_date, amount, updated_at "
        "FROM powder ORDER BY purchase_date, id")]
    solutions = [dict(r) for r in conn.execute(
        "SELECT sync_id, rna_name, purchase_date, amount, prep_date, water_vol, "
        "concentration, remaining, source_sync_id, updated_at "
        "FROM solution ORDER BY purchase_date, id")]
    return {
        "app": "rna_inventory",
        "format": SYNC_FORMAT,
        "exported_at": now_ts(),
        "powders": powders,
        "solutions": solutions,
    }


def _same_content_where(fields):
    parts = []
    for f in fields:
        if f in NUMERIC_FIELDS:
            parts.append(f"abs({f} - ?) < 1e-9")
        else:
            parts.append(f"{f} = ?")
    return " AND ".join(parts)


def _merge_row(conn, table, rec, fields, stats):
    """按 sync_id 合并单条记录; 无该 ID 时再按全部字段查重, 避免两边各录一次产生重复"""
    sync_id = rec["sync_id"]
    ts = rec.get("updated_at") or now_ts()
    vals = [rec[f] for f in fields]
    row = conn.execute(f"SELECT * FROM {table} WHERE sync_id=?", (sync_id,)).fetchone()

    if row is None:
        dup = conn.execute(
            f"SELECT id FROM {table} WHERE {_same_content_where(fields)}", vals).fetchone()
        if dup is not None:
            stats["skipped"] += 1
            return
        cols = ["sync_id", *fields, "updated_at"]
        vals_out = [sync_id, *vals, ts]
        if table == "solution":
            cols.append("source_sync_id")
            vals_out.append(rec.get("source_sync_id") or "")
        conn.execute(
            f"INSERT INTO {table}({','.join(cols)}) "
            f"VALUES({','.join('?' * len(cols))})", vals_out)
        stats["added"] += 1
    elif (row["updated_at"] or "") and ts <= row["updated_at"]:
        stats["skipped"] += 1
        return
    else:
        sets = [f"{f}=?" for f in fields] + ["updated_at=?"]
        vals_out = [*vals, ts]
        if table == "solution":
            sets.append("source_sync_id=?")
            vals_out.append(rec.get("source_sync_id") or row["source_sync_id"] or "")
        conn.execute(
            f"UPDATE {table} SET {','.join(sets)} WHERE sync_id=?",
            (*vals_out, sync_id))
        stats["updated"] += 1

    # 溶液由某条干粉配制而来: 若本机还留着那条干粉, 删除它(跨电脑时保持生命周期一致)
    if table == "solution" and rec.get("source_sync_id"):
        conn.execute("DELETE FROM powder WHERE sync_id=?", (rec["source_sync_id"],))


def import_data(conn, powders, solutions):
    """合并导入; 返回新增/更新/跳过计数"""
    stats = {"added": 0, "updated": 0, "skipped": 0}
    for rec in powders:
        _merge_row(conn, "powder", rec, POWDER_SYNC_FIELDS, stats)
    for rec in solutions:
        _merge_row(conn, "solution", rec, SOLUTION_SYNC_FIELDS, stats)
    conn.commit()
    return stats
