# -*- coding: utf-8 -*-
"""RNA 库存工具本地服务: 静态页面 + JSON API, 数据存同目录 rna_inventory.db。

启动: python server.py [端口]   (默认端口 8377, 只监听 127.0.0.1)
测试时可设环境变量 RNA_DB_PATH 指向临时数据库。
启动后自动打开浏览器; 若端口被占用(已在运行), 则只打开页面后退出。
"""

import json
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import rna_db as db

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DEFAULT_PORT = 8377

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


def _as_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _path_id(path):
    try:
        return int(path.rsplit("/", 1)[1])
    except (ValueError, IndexError):
        return None


def _solution_values(d):
    """校验并返回溶液条目字段 (name, pdate, amount, prep, water, conc, remain)"""
    name = str(d.get("rna_name", "")).strip()
    pdate = str(d.get("purchase_date", "")).strip()
    prep = str(d.get("prep_date", "")).strip()
    amount = _as_float(d.get("amount"))
    water = _as_float(d.get("water_vol"))
    conc = _as_float(d.get("concentration"))
    remain = _as_float(d.get("remaining"))
    if not name:
        return None, "请输入 RNA 种类"
    if not pdate:
        return None, "请输入购入日期"
    if not prep:
        return None, "请输入配制日期"
    if amount is None or amount <= 0:
        return None, "购入量必须是大于 0 的数字"
    if water is None or water <= 0:
        return None, "ddH2O 量必须大于 0"
    if conc is None or conc <= 0:
        return None, "配制浓度必须大于 0"
    if remain is None or remain < 0:
        return None, "剩余量不能为负数"
    return (name, pdate, amount, prep, water, conc, remain), None


class Handler(BaseHTTPRequestHandler):
    server_version = "RNAStock/1.0"

    # ---- 基础工具 ------------------------------------------------

    def send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0:
                return {}
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            raise ValueError("请求数据不是有效的 JSON")

    def log_message(self, fmt, *args):
        if self.command in ("POST", "DELETE"):
            sys.stdout.write(f"[{self.command}] {self.path}\n")
            sys.stdout.flush()

    # ---- 路由 ----------------------------------------------------

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self.send_static(STATIC_DIR / "index.html")
        if path.startswith("/static/"):
            return self.send_static((STATIC_DIR / path[len("/static/"):]).resolve())
        try:
            if path == "/api/powders":
                with db.db() as conn:
                    return self.send_json({"ok": True, "powders": db.list_powders(conn)})
            if path == "/api/solutions":
                with db.db() as conn:
                    return self.send_json({"ok": True, "solutions": db.list_solutions(conn)})
            return self.send_json({"ok": False, "msg": "接口不存在"}, 404)
        except Exception as e:
            return self.send_json({"ok": False, "msg": str(e)}, 500)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            data = self.read_json()
            if path == "/api/powders":
                return self._add_powder(data)
            if path == "/api/prepare":
                return self._prepare(data)
            if path == "/api/use":
                return self._use(data)
            if path == "/api/solutions":
                return self._add_solution(data)
            return self.send_json({"ok": False, "msg": "接口不存在"}, 404)
        except ValueError as e:
            return self.send_json({"ok": False, "msg": str(e)}, 400)
        except Exception as e:
            return self.send_json({"ok": False, "msg": str(e)}, 500)

    def do_DELETE(self):
        path = urlparse(self.path).path
        try:
            if path.startswith("/api/powders/"):
                pid = int(path.rsplit("/", 1)[1])
                with db.db() as conn:
                    if db.get_powder(conn, pid) is None:
                        return self.send_json({"ok": False, "msg": "条目不存在"}, 404)
                    db.delete_powder(conn, pid)
                return self.send_json({"ok": True, "msg": "干粉条目已删除"})
            if path.startswith("/api/solutions/"):
                sid = int(path.rsplit("/", 1)[1])
                with db.db() as conn:
                    if db.get_solution(conn, sid) is None:
                        return self.send_json({"ok": False, "msg": "条目不存在"}, 404)
                    db.delete_solution(conn, sid)
                return self.send_json({"ok": True, "msg": "溶液条目已删除"})
            return self.send_json({"ok": False, "msg": "接口不存在"}, 404)
        except ValueError:
            return self.send_json({"ok": False, "msg": "无效的编号"}, 400)
        except Exception as e:
            return self.send_json({"ok": False, "msg": str(e)}, 500)

    def do_PUT(self):
        path = urlparse(self.path).path
        try:
            data = self.read_json()
            if path.startswith("/api/powders/"):
                pid = _path_id(path)
                if pid is None:
                    return self.send_json({"ok": False, "msg": "无效的编号"}, 400)
                return self._update_powder(pid, data)
            if path.startswith("/api/solutions/"):
                sid = _path_id(path)
                if sid is None:
                    return self.send_json({"ok": False, "msg": "无效的编号"}, 400)
                return self._update_solution(sid, data)
            return self.send_json({"ok": False, "msg": "接口不存在"}, 404)
        except ValueError as e:
            return self.send_json({"ok": False, "msg": str(e)}, 400)
        except Exception as e:
            return self.send_json({"ok": False, "msg": str(e)}, 500)

    # ---- 业务 ----------------------------------------------------

    def _add_powder(self, d):
        name = str(d.get("rna_name", "")).strip()
        pdate = str(d.get("purchase_date", "")).strip()
        amount = _as_float(d.get("amount"))
        if not name:
            return self.send_json({"ok": False, "msg": "请输入 RNA 种类"}, 400)
        if not pdate:
            return self.send_json({"ok": False, "msg": "请输入购入日期"}, 400)
        if amount is None or amount <= 0:
            return self.send_json({"ok": False, "msg": "购入量必须是大于 0 的数字"}, 400)
        with db.db() as conn:
            pid = db.add_powder(conn, name, pdate, amount)
        return self.send_json({"ok": True,
                               "msg": f"已登记干粉: {name} · {pdate} · {db.fmt_num(amount)} nmol"})

    def _prepare(self, d):
        powder_id = _as_int(d.get("powder_id"))
        pdate = str(d.get("prep_date", "")).strip()
        water = _as_float(d.get("water_vol"))
        if powder_id is None:
            return self.send_json({"ok": False, "msg": "请先选择干粉条目"}, 400)
        if not pdate:
            return self.send_json({"ok": False, "msg": "请输入配制日期"}, 400)
        if water is None:
            return self.send_json({"ok": False, "msg": "ddH2O 量必须是数字"}, 400)
        with db.db() as conn:
            ok, msg = db.prepare(conn, powder_id, pdate, water)
        return self.send_json({"ok": ok, "msg": msg}, 200 if ok else 400)

    def _use(self, d):
        solution_id = _as_int(d.get("solution_id"))
        usage = _as_float(d.get("usage"))
        if solution_id is None:
            return self.send_json({"ok": False, "msg": "请先选择溶液条目"}, 400)
        if usage is None:
            return self.send_json({"ok": False, "msg": "使用量必须是数字"}, 400)
        with db.db() as conn:
            ok, msg = db.use_solution(conn, solution_id, usage)
        return self.send_json({"ok": ok, "msg": msg}, 200 if ok else 400)

    def _add_solution(self, d):
        """直接添加溶液条目(已有库存), 独立于干粉仓库"""
        vals, err = _solution_values(d)
        if err:
            return self.send_json({"ok": False, "msg": err}, 400)
        with db.db() as conn:
            sid = db.add_solution(conn, *vals)
        return self.send_json({"ok": True, "msg": f"已添加溶液条目: {vals[0]}"})

    def _update_powder(self, pid, d):
        name = str(d.get("rna_name", "")).strip()
        pdate = str(d.get("purchase_date", "")).strip()
        amount = _as_float(d.get("amount"))
        if not name:
            return self.send_json({"ok": False, "msg": "请输入 RNA 种类"}, 400)
        if not pdate:
            return self.send_json({"ok": False, "msg": "请输入购入日期"}, 400)
        if amount is None or amount <= 0:
            return self.send_json({"ok": False, "msg": "购入量必须是大于 0 的数字"}, 400)
        with db.db() as conn:
            if db.get_powder(conn, pid) is None:
                return self.send_json({"ok": False, "msg": "条目不存在"}, 404)
            db.update_powder(conn, pid, name, pdate, amount)
        return self.send_json({"ok": True, "msg": "干粉条目已更新"})

    def _update_solution(self, sid, d):
        vals, err = _solution_values(d)
        if err:
            return self.send_json({"ok": False, "msg": err}, 400)
        with db.db() as conn:
            if db.get_solution(conn, sid) is None:
                return self.send_json({"ok": False, "msg": "条目不存在"}, 404)
            db.update_solution(conn, sid, *vals)
        return self.send_json({"ok": True, "msg": "溶液条目已更新"})

    # ---- 静态文件 ------------------------------------------------

    def send_static(self, file_path):
        try:
            file_path = file_path.resolve()
            if not str(file_path).startswith(str(STATIC_DIR.resolve())):
                return self.send_json({"ok": False, "msg": "禁止访问"}, 403)
            body = file_path.read_bytes()
        except Exception:
            return self.send_json({"ok": False, "msg": "文件不存在"}, 404)
        self.send_response(200)
        self.send_header("Content-Type",
                         MIME.get(file_path.suffix.lower(), "application/octet-stream"))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    with db.db() as conn:
        db.init_db(conn)
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        print(f"端口 {port} 已被占用(服务可能已在运行), 直接打开页面")
        webbrowser.open(f"http://localhost:{port}")
        return
    url = f"http://localhost:{port}"
    print(f"RNA 库存工具已启动: {url}")
    print("关闭本窗口或按 Ctrl+C 退出")
    webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")


if __name__ == "__main__":
    main()
