# -*- coding: utf-8 -*-
"""图维绩效管理平台 · 后端服务
Flask + SQLite，纯服务端权限校验，员工/主管/HR/管理员分级隔离。
"""
import functools
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import uuid
from datetime import datetime, timedelta

from flask import Flask, g, jsonify, request, send_from_directory

from db import (BASE_DIR, UPLOAD_DIR, close_db, execute, get_db, init_db,
                query_all, query_one, rows_to_dicts, updates)

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.teardown_appcontext(close_db)

# ---------- 常量 ----------
SCORE_MIN, SCORE_MAX = 0, 120
WEIGHT_MIN, WEIGHT_MAX = 0.10, 0.60
SESSION_COOKIE = "tp_session"
SESSION_HOURS = 12
MAX_UPLOAD = 10 * 1024 * 1024
ALLOWED_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".doc", ".docx", ".xls", ".xlsx", ".txt", ".md"}
DEFAULT_BANDS = [{"min": 110, "grade": "S"}, {"min": 100, "grade": "A"},
                 {"min": 90, "grade": "B"}, {"min": 80, "grade": "C"}, {"min": 0, "grade": "D"}]

TASK_STATUS_TEXT = {"pending_self": "待自评", "pending_score": "待评分",
                    "pending_review": "待审核", "published": "已发布", "closed": "已关闭"}
SA_STATUS_TEXT = {"draft": "草稿", "submitted": "已提交", "returned": "已退回"}
ISC_STATUS_TEXT = {"pending": "待评分", "scored": "待HR核对", "hr_checked": "待负责人审核",
                   "approved": "待发布", "published": "已发布", "rejected": "已退回"}

# ---------- 通用响应 ----------

def ok(data=None):
    return jsonify({"ok": True, "data": data})


def fail(msg, code=400):
    return jsonify({"ok": False, "error": msg}), code


def body():
    return request.get_json(force=True, silent=True) or {}


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------- 密码与会话 ----------

def hash_password(pw):
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(pw.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$%s$%s" % (salt.hex(), dk.hex())


def verify_password(pw, stored):
    try:
        _, salt_hex, hash_hex = stored.split("$")
        dk = hashlib.scrypt(pw.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                            n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


def public_user(u):
    if not u:
        return None
    d = dict(u)
    d.pop("password_hash", None)
    return d


def current_user():
    if hasattr(g, "_user"):
        return g._user
    g._user = None
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        row = query_one(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token = ? AND s.expires_at > ? AND u.is_active = 1",
            (token, now_str()))
        if row:
            g._user = dict(row)
    return g._user


def create_session(user_id):
    token = secrets.token_urlsafe(32)
    expires = datetime.now() + timedelta(hours=SESSION_HOURS)
    execute("INSERT INTO sessions (token, user_id, expires_at) VALUES (?,?,?)",
            (token, user_id, expires.strftime("%Y-%m-%d %H:%M:%S")))
    resp = jsonify({"ok": True})
    resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="Lax",
                    max_age=SESSION_HOURS * 3600, path="/")
    return resp


# ---------- 装饰器 ----------

def login_required(view):
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return fail("未登录或会话已过期", 401)
        g.user = user
        return view(*args, **kwargs)
    return wrapper


def require_roles(*roles):
    def deco(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            if g.user["role"] not in roles:
                return fail("无权限执行该操作", 403)
            return view(*args, **kwargs)
        return wrapper
    return deco


# ---------- 前置检查 ----------

@app.before_request
def global_checks():
    if request.path.startswith("/api/") and request.method in ("POST", "PUT", "DELETE", "PATCH"):
        if request.headers.get("X-Requested-With") != "XMLHttpRequest":
            return fail("非法请求来源", 403)
    # 清理过期会话
    if request.path.startswith("/api/") and request.method != "OPTIONS":
        try:
            updates("DELETE FROM sessions WHERE expires_at <= ?", (now_str(),))
        except Exception:
            pass


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    return resp


@app.errorhandler(404)
def not_found(_e):
    if request.path.startswith("/api/"):
        return fail("接口不存在", 404)
    return send_from_directory(app.static_folder, "index.html")


@app.errorhandler(405)
def method_not_allowed(_e):
    return fail("方法不允许", 405)


@app.errorhandler(500)
def server_error(e):
    app.logger.exception("server error")
    return fail("服务器内部错误", 500)


# ---------- 审计与通知 ----------

def audit(action, target=None, detail=None):
    uid = g.user["id"] if hasattr(g, "user") else None
    execute("INSERT INTO audit_logs (user_id, action, target, detail, ip) VALUES (?,?,?,?,?)",
            (uid, action, target, detail, request.remote_addr))


def notify(user_id, type_, title, body_text="", link=""):
    execute("INSERT INTO notifications (user_id, type, title, body, link) VALUES (?,?,?,?,?)",
            (user_id, type_, title, body_text, link))


def notify_hr(title, body_text="", link=""):
    for r in query_all("SELECT id FROM users WHERE role IN ('hr','admin') AND is_active = 1"):
        notify(r["id"], "hr", title, body_text, link)


# ---------- 业务计算 ----------

def calc_base_score(snapshot, score_map):
    """score_map: {指标名: 分数}"""
    total = 0.0
    for ind in snapshot:
        v = score_map.get(ind["name"])
        if v is None:
            return None
        total += float(v) * float(ind["weight"])
    return round(total, 2)


def calc_base_score_by_index(items, score_values):
    """按索引对齐计算加权得分，避免员工修改指标名称后按名称匹配错位"""
    total = 0.0
    for ind, v in zip(items, score_values):
        total += float(v) * float(ind["weight"])
    return round(total, 2)


def effective_items(task_row, sa_row):
    """员工自评中实际生效的指标版本：员工可增删行并编辑名称/标准/来源/权重，
    自评已提交则以员工版为准（数量可与任务快照不同）；未提交或旧数据缺字段时
    按索引回退任务快照对应项。"""
    snapshot = json.loads(task_row["indicators"])
    if not sa_row:
        return snapshot
    try:
        sa_items = json.loads(sa_row["items"])
    except Exception:
        return snapshot
    if not isinstance(sa_items, list) or not sa_items:
        return snapshot
    merged = []
    for i, src in enumerate(sa_items):
        ind = snapshot[i] if i < len(snapshot) else {}
        merged.append({
            "name": src.get("name") or ind.get("name", ""),
            "standard_100": src.get("standard_100") or ind.get("standard_100", ""),
            "standard_120": src.get("standard_120") or ind.get("standard_120", ""),
            "data_source": src.get("data_source") or ind.get("data_source", ""),
            "weight": float(src.get("weight", ind.get("weight", 0)) or 0),
        })
    return merged


def grade_of(total, bands):
    for b in bands:
        if total >= b["min"]:
            return b["grade"]
    return bands[-1]["grade"] if bands else "D"


def bonus_factor(total):
    return round(min(total, SCORE_MAX) / 100.0, 3)


def get_settings():
    d = {r["key"]: r["value"] for r in query_all("SELECT key, value FROM settings")}
    if "grade_bands" not in d:
        d["grade_bands"] = json.dumps(DEFAULT_BANDS, ensure_ascii=False)
    try:
        bands = json.loads(d["grade_bands"])
    except Exception:
        bands = DEFAULT_BANDS
    bands = sorted(bands, key=lambda b: -float(b["min"]))
    d["grade_bands_parsed"] = bands
    return d


def gen_task_no(period_type, period_code):
    prefix = "TP" + period_code.replace("-", "")
    row = query_one("SELECT task_no FROM assessment_tasks WHERE task_no LIKE ? "
                    "ORDER BY task_no DESC LIMIT 1", (prefix + "%",))
    seq = int(row["task_no"][len(prefix):]) + 1 if row else 1
    return "%s%04d" % (prefix, seq)


def user_display(u):
    return "%s（%s·%s）" % (u["name"], u.get("department") or "未填部门", u.get("position") or "")


def validate_weight_sum(indicators, label):
    if not indicators:
        return "%s指标不能为空" % label
    total = 0.0
    for ind in indicators:
        if not str(ind.get("name", "")).strip():
            return "%s存在未填名称的指标" % label
        try:
            w = float(ind.get("weight"))
        except (TypeError, ValueError):
            return "%s指标「%s」权重不是有效数字" % (label, ind.get("name"))
        if w < WEIGHT_MIN - 1e-9 or w > WEIGHT_MAX + 1e-9:
            return "%s指标「%s」权重须在 10%%-60%% 之间" % (label, ind.get("name"))
        total += w
    if abs(total - 1.0) > 0.001:
        return "%s指标权重合计须为 100%%（当前 %.1f%%）" % (label, total * 100)
    return None


def parse_indicators(raw):
    out = []
    for i, ind in enumerate(raw or []):
        out.append({
            "name": str(ind.get("name", "")).strip(),
            "standard_100": str(ind.get("standard_100", "") or ""),
            "standard_120": str(ind.get("standard_120", "") or ""),
            "data_source": str(ind.get("data_source", "") or ""),
            "weight": round(float(ind.get("weight", 0)), 4),
            "sort_order": i,
        })
    return out


# ================= 认证 =================

_login_fails = {}


def login_rate_limited(ip):
    rec = _login_fails.get(ip)
    if not rec:
        return False
    count, first_ts = rec
    if time.time() - first_ts > 600:
        _login_fails.pop(ip, None)
        return False
    return count >= 10


@app.route("/api/login", methods=["POST"])
def login():
    ip = request.remote_addr or "-"
    if login_rate_limited(ip):
        return fail("失败次数过多，请 10 分钟后再试", 429)
    data = body()
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    if not username or not password:
        return fail("请输入账号和密码")
    user = query_one("SELECT * FROM users WHERE username = ? AND is_active = 1", (username,))
    if not user or not verify_password(password, user["password_hash"]):
        rec = _login_fails.setdefault(ip, [0, time.time()])
        rec[0] += 1
        audit("login_fail", username)
        return fail("账号或密码错误", 401)
    _login_fails.pop(ip, None)
    resp = create_session(user["id"])
    audit("login", user["username"])
    resp.set_data(json.dumps({"ok": True, "data": {
        "user": public_user(user),
        "must_change_password": bool(user["must_change_password"])}}))
    return resp


@app.route("/api/logout", methods=["POST"])
def logout():
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        updates("DELETE FROM sessions WHERE token = ?", (token,))
    resp = jsonify({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@app.route("/api/me")
@login_required
def me():
    u = g.user
    sup = query_one(
        "SELECT COUNT(*) AS c FROM assessment_configs WHERE participate = 1 "
        "AND (monthly_supervisor_id = ? OR quarterly_supervisor_id = ?)", (u["id"], u["id"]))
    unread = query_one("SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND is_read = 0",
                       (u["id"],))
    resp = ok({
        "user": public_user(u),
        "perms": {
            "supervisor": sup["c"] > 0 or u["role"] in ("hr", "admin"),
            "hr": u["role"] in ("hr", "admin"),
            "admin": u["role"] == "admin",
            "approver": bool(u["is_final_approver"]) or u["role"] in ("hr", "admin"),
        },
        "unread": unread["c"],
        "must_change_password": bool(u["must_change_password"]),
    })
    return resp


@app.route("/api/change-password", methods=["POST"])
@login_required
def change_password():
    data = body()
    old_pw = str(data.get("old_password", ""))
    new_pw = str(data.get("new_password", ""))
    if not verify_password(old_pw, g.user["password_hash"]):
        return fail("原密码错误")
    if len(new_pw) < 8 or not re.search(r"[A-Za-z]", new_pw) or not re.search(r"\d", new_pw):
        return fail("新密码至少 8 位，且须同时包含字母和数字")
    updates("UPDATE users SET password_hash = ?, must_change_password = 0, updated_at = ? WHERE id = ?",
            (hash_password(new_pw), now_str(), g.user["id"]))
    audit("change_password")
    return ok()


# ================= 通知 =================

@app.route("/api/notifications")
@login_required
def notifications():
    rows = query_all("SELECT * FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 50",
                     (g.user["id"],))
    updates("UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0", (g.user["id"],))
    return ok(rows_to_dicts(rows))


# ================= 员工端 =================

@app.route("/api/my/tasks")
@login_required
def my_tasks():
    rows = query_all(
        "SELECT t.*, s.name AS supervisor_name FROM assessment_tasks t "
        "LEFT JOIN users s ON s.id = t.supervisor_id WHERE t.user_id = ? "
        "ORDER BY t.period_code DESC, t.id DESC", (g.user["id"],))
    out = []
    for r in rows:
        d = dict(r)
        sa = query_one("SELECT status, submitted_at FROM self_assessments WHERE task_id = ?", (r["id"],))
        d["sa_status"] = sa["status"] if sa else None
        res = query_one("SELECT id, total_score, grade FROM published_results WHERE task_id = ?", (r["id"],))
        d["result_id"] = res["id"] if res else None
        d["result_score"] = res["total_score"] if res else None
        d["result_grade"] = res["grade"] if res else None
        d["overdue"] = (r["status"] == "pending_self" and r["self_deadline"]
                       and r["self_deadline"] < datetime.now().strftime("%Y-%m-%d"))
        out.append(d)
    return ok(out)


@app.route("/api/my/tasks/<int:task_id>")
@login_required
def my_task_detail(task_id):
    task = query_one(
        "SELECT t.*, s.name AS supervisor_name, f.name AS approver_name "
        "FROM assessment_tasks t LEFT JOIN users s ON s.id = t.supervisor_id "
        "LEFT JOIN users f ON f.id = t.final_approver_id WHERE t.id = ?", (task_id,))
    if not task or task["user_id"] != g.user["id"]:
        return fail("任务不存在", 404)
    d = dict(task)
    d["indicators"] = json.loads(task["indicators"])
    sa = query_one("SELECT * FROM self_assessments WHERE task_id = ?", (task_id,))
    if sa:
        raw_items = json.loads(sa["items"])
        snapshot = json.loads(task["indicators"])
        # 员工版为准（含增删行），缺定义字段时回退任务快照同索引项
        merged_items = []
        for i, src in enumerate(raw_items):
            ind = snapshot[i] if i < len(snapshot) else {}
            merged = {
                "name": src.get("name") or ind.get("name", ""),
                "standard_100": src.get("standard_100") or ind.get("standard_100", ""),
                "standard_120": src.get("standard_120") or ind.get("standard_120", ""),
                "data_source": src.get("data_source") or ind.get("data_source", ""),
                "weight": float(src.get("weight", ind.get("weight", 0)) or 0),
                "completion": src.get("completion", ""),
                "self_score": src.get("self_score"),
            }
            merged_items.append(merged)
        d["self_assessment"] = {
            "items": merged_items,
            "achievements": sa["achievements"], "unfinished_reason": sa["unfinished_reason"],
            "support_needed": sa["support_needed"],
            "attachments": json.loads(sa["attachments"] or "[]"),
            "signature": sa["signature"] if "signature" in sa.keys() else None,
            "confirmed": bool(sa["confirmed"]) if "confirmed" in sa.keys() else False,
            "status": sa["status"], "supervisor_comment": sa["supervisor_comment"],
            "submitted_at": sa["submitted_at"],
        }
    res = query_one("SELECT * FROM published_results WHERE task_id = ?", (task_id,))
    if res:
        d["result"] = dict(res)
    return ok(d)


@app.route("/api/my/tasks/<int:task_id>/self-assessment", methods=["POST"])
@login_required
def submit_self_assessment(task_id):
    task = query_one("SELECT * FROM assessment_tasks WHERE id = ?", (task_id,))
    if not task or task["user_id"] != g.user["id"]:
        return fail("任务不存在", 404)
    if task["status"] != "pending_self":
        return fail("任务已进入评分阶段，不能修改自评")
    data = body()
    items_in = data.get("items") or []
    snapshot = json.loads(task["indicators"])
    # 员工可自行增加/删除指标行：至少保留 1 项，数量不必与任务快照一致；
    # 超出快照索引的新增行完全以员工填写为准。
    if not items_in:
        return fail("至少需要保留一项指标")
    items = []
    weight_sum = 0.0
    for i, src in enumerate(items_in):
        ind = snapshot[i] if i < len(snapshot) else {}
        name = str(src.get("name", "")).strip() or ind.get("name", "")
        if not name:
            return fail("第 %d 项指标的名称不能为空" % (i + 1))
        if len(name) > 60:
            return fail("指标名称不能超过 60 字")
        std100 = str(src.get("standard_100", "")).strip() or ind.get("standard_100", "")
        std120 = str(src.get("standard_120", "")).strip() or ind.get("standard_120", "")
        source = str(src.get("data_source", "")).strip() or ind.get("data_source", "")
        for label, val in (("100% 目标值", std100), ("120% 目标值", std120), ("数据来源", source)):
            if len(val) > 500:
                return fail("指标「%s」的%s不能超过 500 字" % (name, label))
        # 权重：员工可修改，单项须在 10%-60%，合计须为 100%
        try:
            weight = float(src.get("weight"))
        except (TypeError, ValueError):
            weight = float(ind.get("weight", 0) or 0)
        if not (0.10 - 1e-9 <= weight <= 0.60 + 1e-9):
            return fail("指标「%s」的权重须在 10%%-60%% 之间" % name)
        weight = round(weight, 4)
        weight_sum += weight
        completion = str(src.get("completion", "")).strip()
        if not completion:
            return fail("指标「%s」的实际完成情况不能为空" % name)
        try:
            score = float(src.get("self_score"))
        except (TypeError, ValueError):
            return fail("指标「%s」的自评分必须是 0-120 的数字" % name)
        if not (SCORE_MIN <= score <= SCORE_MAX):
            return fail("指标「%s」的自评分须在 0-120 之间" % name)
        items.append({"name": name, "standard_100": std100, "standard_120": std120,
                      "data_source": source, "weight": weight,
                      "completion": completion, "self_score": score})
    if abs(weight_sum - 1.0) > 0.001:
        return fail("各指标权重合计须为 100%%，当前为 %d%%" % round(weight_sum * 100))
    # 员工确认签字（对应 Excel 模板「员工确认签字」，提交时必填）
    signature = str(data.get("signature", "")).strip()
    confirmed = bool(data.get("confirmed"))
    if not confirmed:
        return fail("请先勾选确认「本人确认以上自评内容真实有效」")
    if len(signature) < 2:
        return fail("请填写员工确认签字（签名）")
    attachments = data.get("attachments") or []
    sa = query_one("SELECT * FROM self_assessments WHERE task_id = ?", (task_id,))
    payload = (json.dumps(items, ensure_ascii=False),
               str(data.get("achievements", "")).strip(),
               str(data.get("unfinished_reason", "")).strip(),
               str(data.get("support_needed", "")).strip(),
               json.dumps(attachments, ensure_ascii=False),
               signature, 1 if confirmed else 0,
               "submitted", now_str())
    if sa:
        execute("UPDATE self_assessments SET items=?, achievements=?, unfinished_reason=?, "
                "support_needed=?, attachments=?, signature=?, confirmed=?, status=?, "
                "submitted_at=?, updated_at=?, supervisor_comment=NULL WHERE task_id=?",
                payload + (now_str(), task_id))
    else:
        execute("INSERT INTO self_assessments (task_id, user_id, items, achievements, "
                "unfinished_reason, support_needed, attachments, signature, confirmed, "
                "status, submitted_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (task_id, g.user["id"]) + payload)
    updates("UPDATE assessment_tasks SET status='pending_score', updated_at=? WHERE id=?",
            (now_str(), task_id))
    if task["supervisor_id"]:
        notify(task["supervisor_id"], "score", "有新的员工自评待评分",
               "%s 的 %s 考核已提交自评" % (g.user["name"], task["period_code"]),
               "#/supervisor/tasks")
    audit("self_assessment_submit", task["task_no"])
    return ok()


@app.route("/api/my/results")
@login_required
def my_results():
    rows = query_all(
        "SELECT id, period_type, period_code, total_score, grade, bonus_factor, "
        "published_at, version FROM published_results WHERE user_id = ? "
        "ORDER BY period_code DESC, id DESC", (g.user["id"],))
    return ok(rows_to_dicts(rows))


@app.route("/api/my/results/<int:result_id>")
@login_required
def my_result_detail(result_id):
    r = query_one("SELECT * FROM published_results WHERE id = ?", (result_id,))
    if not r or r["user_id"] != g.user["id"]:
        return fail("结果不存在", 404)
    d = dict(r)
    d["items"] = json.loads(r["items"])
    return ok(d)


# ================= 附件 =================

@app.route("/api/upload", methods=["POST"])
@login_required
def upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return fail("未选择文件")
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_EXT:
        return fail("仅支持 %s 格式" % "、".join(sorted(ALLOWED_EXT)))
    data = f.read()
    if len(data) > MAX_UPLOAD:
        return fail("文件不能超过 10MB")
    stored = uuid.uuid4().hex + ext
    with open(os.path.join(UPLOAD_DIR, stored), "wb") as fp:
        fp.write(data)
    audit("upload", f.filename)
    return ok({"stored_name": stored, "filename": os.path.basename(f.filename), "size": len(data)})


@app.route("/api/files/<path:stored>")
@login_required
def download_file(stored):
    if not re.fullmatch(r"[0-9a-f]{32}\.[a-z0-9]+", stored):
        return fail("非法文件名", 400)
    allowed = g.user["role"] in ("hr", "admin")
    if not allowed:
        for r in query_all("SELECT sa.task_id, sa.attachments FROM self_assessments sa "
                           "JOIN assessment_tasks t ON t.id = sa.task_id"):
            try:
                atts = json.loads(r["attachments"] or "[]")
            except Exception:
                atts = []
            if any(a.get("stored_name") == stored for a in atts):
                task = query_one("SELECT user_id, supervisor_id FROM assessment_tasks WHERE id = ?",
                                 (r["task_id"],))
                if task and (task["user_id"] == g.user["id"] or task["supervisor_id"] == g.user["id"]):
                    allowed = True
                break
    if not allowed:
        return fail("无权限访问该附件", 403)
    return send_from_directory(UPLOAD_DIR, stored)


# ================= 主管端 =================

@app.route("/api/supervisor/tasks")
@login_required
def supervisor_tasks():
    rows = query_all(
        "SELECT t.*, u.name AS user_name, u.department, u.position, "
        "isc.status AS isc_status FROM assessment_tasks t "
        "JOIN users u ON u.id = t.user_id "
        "LEFT JOIN internal_scores isc ON isc.task_id = t.id "
        "WHERE t.supervisor_id = ? AND t.status IN ('pending_self','pending_score','pending_review') "
        "ORDER BY t.period_code DESC, t.id DESC", (g.user["id"],))
    return ok(rows_to_dicts(rows))


def task_full(task_id, include_internal):
    task = query_one(
        "SELECT t.*, u.name AS user_name, u.department, u.position, "
        "s.name AS supervisor_name, f.name AS approver_name FROM assessment_tasks t "
        "JOIN users u ON u.id = t.user_id "
        "LEFT JOIN users s ON s.id = t.supervisor_id "
        "LEFT JOIN users f ON f.id = t.final_approver_id WHERE t.id = ?", (task_id,))
    if not task:
        return None
    d = dict(task)
    d["indicators"] = json.loads(task["indicators"])
    sa = query_one("SELECT * FROM self_assessments WHERE task_id = ?", (task_id,))
    if sa:
        d["self_assessment"] = {
            "items": json.loads(sa["items"]), "achievements": sa["achievements"],
            "unfinished_reason": sa["unfinished_reason"], "support_needed": sa["support_needed"],
            "attachments": json.loads(sa["attachments"] or "[]"), "status": sa["status"],
            "signature": sa["signature"] if "signature" in sa.keys() else None,
            "confirmed": bool(sa["confirmed"]) if "confirmed" in sa.keys() else False,
            "supervisor_comment": sa["supervisor_comment"], "submitted_at": sa["submitted_at"],
        }
        # 员工可能已修改指标名称/标准/权重：主管与 HR 侧以员工版为显示与计算基准
        d["effective_indicators"] = effective_items(task, sa)
    if include_internal:
        isc = query_one("SELECT * FROM internal_scores WHERE task_id = ?", (task_id,))
        if isc:
            d["internal_score"] = dict(isc)
            d["internal_score"]["scores"] = json.loads(isc["scores"] or "[]")
    res = query_one("SELECT * FROM published_results WHERE task_id = ?", (task_id,))
    if res:
        d["result"] = dict(res)
    return d


@app.route("/api/supervisor/tasks/<int:task_id>")
@login_required
def supervisor_task_detail(task_id):
    task = query_one("SELECT * FROM assessment_tasks WHERE id = ?", (task_id,))
    if not task:
        return fail("任务不存在", 404)
    if task["supervisor_id"] != g.user["id"] and g.user["role"] not in ("hr", "admin"):
        return fail("无权查看该任务", 403)
    d = task_full(task_id, include_internal=True)
    return ok(d)


@app.route("/api/supervisor/tasks/<int:task_id>/score", methods=["POST"])
@login_required
def submit_score(task_id):
    task = query_one("SELECT * FROM assessment_tasks WHERE id = ?", (task_id,))
    if not task:
        return fail("任务不存在", 404)
    if task["supervisor_id"] != g.user["id"] and g.user["role"] != "admin":
        return fail("只有评分主管可以评分", 403)
    if task["status"] not in ("pending_score", "pending_review"):
        return fail("当前状态不能评分")
    isc = query_one("SELECT * FROM internal_scores WHERE task_id = ?", (task_id,))
    if isc and isc["status"] == "published":
        return fail("结果已发布，不能修改评分")
    data = body()
    sa = query_one("SELECT * FROM self_assessments WHERE task_id = ?", (task_id,))
    eff = effective_items(task, sa)
    scores_in = data.get("scores") or []
    if len(scores_in) != len(eff):
        return fail("评分指标数量与任务不一致")
    scores = []
    for src, ind in zip(scores_in, eff):
        try:
            s = float(src.get("supervisor_score"))
        except (TypeError, ValueError):
            return fail("指标「%s」的主管评分不能为空" % ind["name"])
        if not (SCORE_MIN <= s <= SCORE_MAX):
            return fail("指标「%s」的主管评分须在 0-120 之间" % ind["name"])
        peer = src.get("peer_score")
        if peer not in (None, ""):
            try:
                peer = float(peer)
                if not (SCORE_MIN <= peer <= SCORE_MAX):
                    return fail("指标「%s」的同级评分须在 0-120 之间" % ind["name"])
            except (TypeError, ValueError):
                return fail("指标「%s」的同级评分不是有效数字" % ind["name"])
        else:
            peer = None
        scores.append({"name": ind["name"], "standard_100": ind.get("standard_100", ""),
                       "standard_120": ind.get("standard_120", ""),
                       "data_source": ind.get("data_source", ""), "weight": ind["weight"],
                       "supervisor_score": s, "peer_score": peer,
                       "comment": str(src.get("comment", "")).strip()})
    try:
        bonus = float(data.get("bonus_score") or 0)
        penalty = float(data.get("penalty_score") or 0)
    except (TypeError, ValueError):
        return fail("加减分必须是数字")
    if not (0 <= bonus <= 10):
        return fail("加分须在 0-10 之间")
    if not (-10 <= penalty <= 0):
        return fail("减分须在 -10-0 之间")
    base = calc_base_score_by_index(eff, [x["supervisor_score"] for x in scores])
    total = round(base + bonus + penalty, 2)
    settings = get_settings()
    grade = grade_of(total, settings["grade_bands_parsed"])
    fields = (json.dumps(scores, ensure_ascii=False),
              str(data.get("bonus_items", "")).strip(), bonus,
              str(data.get("penalty_items", "")).strip(), penalty,
              str(data.get("suggested_grade", "")).strip() or grade,
              str(data.get("supervisor_comment", "")).strip(),
              base, total, now_str())
    if isc:
        execute("UPDATE internal_scores SET scores=?, bonus_items=?, bonus_score=?, "
                "penalty_items=?, penalty_score=?, suggested_grade=?, supervisor_comment=?, "
                "base_score=?, total_score=?, status='scored', hr_comment=NULL, hr_user_id=NULL, "
                "hr_checked_at=NULL, approver_comment=NULL, approver_user_id=NULL, approved_at=NULL, "
                "updated_at=? WHERE task_id=?", fields + (task_id,))
    else:
        execute("INSERT INTO internal_scores (task_id, user_id, scores, bonus_items, bonus_score, "
                "penalty_items, penalty_score, suggested_grade, supervisor_comment, base_score, "
                "total_score, status) VALUES (?,?,?,?,?,?,?,?,?,?,?, 'scored')",
                (task_id, task["user_id"]) + fields[:-1])
    updates("UPDATE assessment_tasks SET status='pending_review', updated_at=? WHERE id=?",
            (now_str(), task_id))
    notify_hr("有评分待核对", "%s 的 %s 考核已完成主管评分" %
              (query_one("SELECT name FROM users WHERE id=?", (task["user_id"],))["name"],
               task["period_code"]), "#/hr/scores")
    audit("score_submit", task["task_no"], "总分 %s" % total)
    return ok({"base_score": base, "total_score": total, "grade": grade})


@app.route("/api/supervisor/tasks/<int:task_id>/return", methods=["POST"])
@login_required
def return_self_assessment(task_id):
    task = query_one("SELECT * FROM assessment_tasks WHERE id = ?", (task_id,))
    if not task:
        return fail("任务不存在", 404)
    if task["supervisor_id"] != g.user["id"] and g.user["role"] not in ("hr", "admin"):
        return fail("无权操作", 403)
    if task["status"] != "pending_score":
        return fail("仅待评分状态可退回")
    comment = str(body().get("comment", "")).strip()
    if not comment:
        return fail("请填写退回原因")
    execute("UPDATE self_assessments SET status='returned', supervisor_comment=?, updated_at=? "
            "WHERE task_id=?", (comment, now_str(), task_id))
    updates("UPDATE assessment_tasks SET status='pending_self', updated_at=? WHERE id=?",
            (now_str(), task_id))
    notify(task["user_id"], "return", "自评已被退回", comment, "#/my/tasks")
    audit("self_assessment_return", task["task_no"], comment)
    return ok()


# ================= HR 端 =================

@app.route("/api/hr/overview")
@login_required
@require_roles("hr", "admin")
def hr_overview():
    def cnt(status):
        return query_one("SELECT COUNT(*) AS c FROM assessment_tasks WHERE status=?", (status,))["c"]
    return ok({
        "pending_self": cnt("pending_self"), "pending_score": cnt("pending_score"),
        "pending_review": cnt("pending_review"), "published": cnt("published"),
        "closed": cnt("closed"),
        "ready_publish": query_one("SELECT COUNT(*) AS c FROM internal_scores WHERE status='approved'")["c"],
        "users_active": query_one("SELECT COUNT(*) AS c FROM users WHERE is_active=1")["c"],
        "recent": [dict(r) for r in query_all(
            "SELECT t.task_no, t.period_code, t.status, t.updated_at, u.name AS user_name "
            "FROM assessment_tasks t JOIN users u ON u.id=t.user_id "
            "ORDER BY t.updated_at DESC LIMIT 8")],
    })


@app.route("/api/hr/users")
@login_required
def hr_users():
    if g.user["role"] not in ("hr", "admin"):
        rows = [dict(r) for r in query_all(
            "SELECT id, name, department, position FROM users WHERE is_active=1 ORDER BY name")]
        return ok(rows)
    rows = query_all("SELECT id, username, name, department, position, role, supervisor_id, "
                     "is_final_approver, is_active FROM users ORDER BY name")
    return ok(rows_to_dicts(rows))


@app.route("/api/hr/configs")
@login_required
@require_roles("hr", "admin")
def hr_configs():
    rows = query_all(
        "SELECT c.*, u.name AS user_name, u.department, u.position, "
        "ms.name AS monthly_supervisor_name, qs.name AS quarterly_supervisor_name, "
        "fa.name AS final_approver_name FROM assessment_configs c "
        "JOIN users u ON u.id = c.user_id "
        "LEFT JOIN users ms ON ms.id = c.monthly_supervisor_id "
        "LEFT JOIN users qs ON qs.id = c.quarterly_supervisor_id "
        "LEFT JOIN users fa ON fa.id = c.final_approver_id ORDER BY u.name")
    out = []
    for r in rows:
        d = dict(r)
        inds = query_all("SELECT * FROM config_indicators WHERE config_id=? ORDER BY period_type, sort_order",
                         (r["id"],))
        d["indicators"] = {"monthly": [], "quarterly": []}
        for i in inds:
            d["indicators"][i["period_type"]].append(dict(i))
        out.append(d)
    return ok(out)


@app.route("/api/hr/configs", methods=["POST"])
@login_required
@require_roles("hr", "admin")
def hr_save_config():
    data = body()
    user_id = data.get("user_id")
    user = query_one("SELECT * FROM users WHERE id=?", (user_id,))
    if not user:
        return fail("员工不存在")
    frequency = data.get("frequency")
    if frequency not in ("monthly", "quarterly", "both"):
        return fail("考核频率无效")
    indicators = data.get("indicators") or {}
    monthly = parse_indicators(indicators.get("monthly"))
    quarterly = parse_indicators(indicators.get("quarterly"))
    if frequency in ("monthly", "both"):
        err = validate_weight_sum(monthly, "月度")
        if err:
            return fail(err)
    else:
        monthly = []
    if frequency in ("quarterly", "both"):
        err = validate_weight_sum(quarterly, "季度")
        if err:
            return fail(err)
    else:
        quarterly = []
    cfg = query_one("SELECT * FROM assessment_configs WHERE user_id=?", (user_id,))
    vals = (frequency, data.get("monthly_supervisor_id") or None,
            data.get("quarterly_supervisor_id") or None,
            data.get("final_approver_id") or None,
            data.get("effective_date") or None,
            1 if data.get("participate") else 0,
            str(data.get("note", "")).strip(), now_str())
    if cfg:
        execute("UPDATE assessment_configs SET frequency=?, monthly_supervisor_id=?, "
                "quarterly_supervisor_id=?, final_approver_id=?, effective_date=?, participate=?, "
                "note=?, updated_at=? WHERE user_id=?", vals + (user_id,))
        cfg_id = cfg["id"]
        execute("DELETE FROM config_indicators WHERE config_id=?", (cfg_id,))
    else:
        cfg_id = execute("INSERT INTO assessment_configs (user_id, frequency, monthly_supervisor_id, "
                         "quarterly_supervisor_id, final_approver_id, effective_date, participate, "
                         "note, created_by) VALUES (?,?,?,?,?,?,?,?,?)",
                         (user_id,) + vals[:-1] + (g.user["id"],))
    for ind in monthly:
        execute("INSERT INTO config_indicators (config_id, period_type, name, standard_100, "
                "standard_120, data_source, weight, sort_order) VALUES (?,?,?,?,?,?,?,?)",
                (cfg_id, "monthly", ind["name"], ind["standard_100"], ind["standard_120"],
                 ind["data_source"], ind["weight"], ind["sort_order"]))
    for ind in quarterly:
        execute("INSERT INTO config_indicators (config_id, period_type, name, standard_100, "
                "standard_120, data_source, weight, sort_order) VALUES (?,?,?,?,?,?,?,?)",
                (cfg_id, "quarterly", ind["name"], ind["standard_100"], ind["standard_120"],
                 ind["data_source"], ind["weight"], ind["sort_order"]))
    audit("config_save", user["username"])
    return ok({"id": cfg_id})


@app.route("/api/hr/tasks")
@login_required
@require_roles("hr", "admin")
def hr_tasks():
    sql = ("SELECT t.*, u.name AS user_name, u.department, s.name AS supervisor_name "
           "FROM assessment_tasks t JOIN users u ON u.id=t.user_id "
           "LEFT JOIN users s ON s.id=t.supervisor_id WHERE 1=1")
    args = []
    if request.args.get("period_code"):
        sql += " AND t.period_code = ?"
        args.append(request.args["period_code"])
    if request.args.get("status"):
        sql += " AND t.status = ?"
        args.append(request.args["status"])
    if request.args.get("user_id"):
        sql += " AND t.user_id = ?"
        args.append(request.args["user_id"])
    if request.args.get("period_type"):
        sql += " AND t.period_type = ?"
        args.append(request.args["period_type"])
    sql += " ORDER BY t.period_code DESC, t.id DESC LIMIT 500"
    return ok(rows_to_dicts(query_all(sql, args)))


@app.route("/api/hr/tasks/<int:task_id>")
@login_required
@require_roles("hr", "admin")
def hr_task_detail(task_id):
    d = task_full(task_id, include_internal=True)
    if not d:
        return fail("任务不存在", 404)
    logs = query_all("SELECT * FROM audit_logs WHERE target = ? ORDER BY id DESC LIMIT 30",
                     (d["task_no"],))
    d["logs"] = rows_to_dicts(logs)
    return ok(d)


@app.route("/api/hr/tasks/batch", methods=["POST"])
@login_required
@require_roles("hr", "admin")
def hr_batch_create_tasks():
    data = body()
    period_type = data.get("period_type")
    period_code = str(data.get("period_code", "")).strip()
    if period_type not in ("monthly", "quarterly"):
        return fail("周期类型无效")
    if not re.fullmatch(r"\d{4}-\d{2}|\d{4}-Q[1-4]", period_code):
        return fail("周期编号格式应为 2026-10 或 2026-Q4")
    if period_type == "monthly" and not re.fullmatch(r"\d{4}-\d{2}", period_code):
        return fail("月度周期编号应为 2026-10 格式")
    if period_type == "quarterly" and not re.fullmatch(r"\d{4}-Q[1-4]", period_code):
        return fail("季度周期编号应为 2026-Q4 格式")
    user_ids = data.get("user_ids") or []
    if not user_ids:
        return fail("请选择员工")
    self_deadline = str(data.get("self_deadline", "")).strip() or None
    period_start = str(data.get("period_start", "")).strip() or None
    period_end = str(data.get("period_end", "")).strip() or None
    created, skipped = [], []
    for uid in user_ids:
        cfg = query_one("SELECT * FROM assessment_configs WHERE user_id=? AND participate=1", (uid,))
        user = query_one("SELECT * FROM users WHERE id=? AND is_active=1", (uid,))
        if not cfg or not user:
            skipped.append({"user": user["name"] if user else str(uid), "reason": "无有效考核配置"})
            continue
        if cfg["frequency"] == "monthly" and period_type != "monthly":
            skipped.append({"user": user["name"], "reason": "该员工仅月度考核"})
            continue
        if cfg["frequency"] == "quarterly" and period_type != "quarterly":
            skipped.append({"user": user["name"], "reason": "该员工仅季度考核"})
            continue
        exists = query_one("SELECT id FROM assessment_tasks WHERE user_id=? AND period_type=? "
                           "AND period_code=?", (uid, period_type, period_code))
        if exists:
            skipped.append({"user": user["name"], "reason": "该周期任务已存在"})
            continue
        supervisor_id = cfg["monthly_supervisor_id"] if period_type == "monthly" else cfg["quarterly_supervisor_id"]
        approver_id = cfg["final_approver_id"]
        inds = query_all("SELECT * FROM config_indicators WHERE config_id=? AND period_type=? "
                         "ORDER BY sort_order", (cfg["id"], period_type))
        if not inds:
            skipped.append({"user": user["name"], "reason": "缺少%s指标配置" % period_type})
            continue
        snapshot = [{"name": i["name"], "standard_100": i["standard_100"],
                     "standard_120": i["standard_120"], "data_source": i["data_source"],
                     "weight": i["weight"]} for i in inds]
        task_no = gen_task_no(period_type, period_code)
        tid = execute(
            "INSERT INTO assessment_tasks (task_no, user_id, period_type, period_code, "
            "period_start, period_end, self_deadline, supervisor_id, final_approver_id, "
            "indicators, status, created_by) VALUES (?,?,?,?,?,?,?,?,?,?,'pending_self',?)",
            (task_no, uid, period_type, period_code, period_start, period_end, self_deadline,
             supervisor_id, approver_id, json.dumps(snapshot, ensure_ascii=False), g.user["id"]))
        notify(uid, "task", "新的考核任务待完成",
               "%s %s 考核已发起，请及时填写自评" % (period_code, "月度" if period_type == "monthly" else "季度"),
               "#/my/tasks")
        created.append({"task_no": task_no, "user": user["name"], "id": tid})
    audit("tasks_batch_create", period_code, "创建 %d 条，跳过 %d 条" % (len(created), len(skipped)))
    return ok({"created": created, "skipped": skipped})


@app.route("/api/hr/tasks/<int:task_id>/close", methods=["POST"])
@login_required
@require_roles("hr", "admin")
def hr_close_task(task_id):
    task = query_one("SELECT * FROM assessment_tasks WHERE id=?", (task_id,))
    if not task:
        return fail("任务不存在", 404)
    if task["status"] == "published":
        return fail("已发布的任务不能关闭")
    updates("UPDATE assessment_tasks SET status='closed', updated_at=? WHERE id=?", (now_str(), task_id))
    audit("task_close", task["task_no"])
    return ok()


@app.route("/api/hr/scores")
@login_required
def hr_scores():
    if g.user["role"] not in ("hr", "admin") and not g.user["is_final_approver"]:
        return fail("无权限", 403)
    status = request.args.get("status")
    sql = ("SELECT isc.*, t.period_code, t.period_type, t.task_no, u.name AS user_name, "
           "u.department FROM internal_scores isc "
           "JOIN assessment_tasks t ON t.id = isc.task_id "
           "JOIN users u ON u.id = isc.user_id WHERE 1=1")
    args = []
    if status:
        sql += " AND isc.status = ?"
        args.append(status)
    if g.user["role"] == "employee" and g.user["is_final_approver"]:
        sql += " AND t.final_approver_id = ?"
        args.append(g.user["id"])
    sql += " ORDER BY isc.updated_at DESC LIMIT 300"
    return ok(rows_to_dicts(query_all(sql, args)))


@app.route("/api/hr/scores/<int:task_id>", methods=["GET"])
@login_required
def hr_score_detail(task_id):
    task = query_one("SELECT * FROM assessment_tasks WHERE id=?", (task_id,))
    if not task:
        return fail("任务不存在", 404)
    isc = query_one("SELECT * FROM internal_scores WHERE task_id=?", (task_id,))
    if not isc:
        return fail("尚未评分", 404)
    if g.user["role"] not in ("hr", "admin"):
        if task["supervisor_id"] != g.user["id"] and task["final_approver_id"] != g.user["id"]:
            return fail("无权查看", 403)
    d = task_full(task_id, include_internal=True)
    d["internal_score"]["scores"] = json.loads(isc["scores"] or "[]")
    return ok(d)


@app.route("/api/hr/scores/<int:task_id>/check", methods=["POST"])
@login_required
@require_roles("hr", "admin")
def hr_check_score(task_id):
    task = query_one("SELECT * FROM assessment_tasks WHERE id=?", (task_id,))
    isc = query_one("SELECT * FROM internal_scores WHERE task_id=?", (task_id,))
    if not task or not isc:
        return fail("记录不存在", 404)
    if isc["status"] != "scored":
        return fail("当前状态不能核对")
    data = body()
    scores = json.loads(isc["scores"] or "[]")
    adj = data.get("scores")
    if adj:
        by_name = {x["name"]: x for x in scores}
        for item in adj:
            t = by_name.get(item.get("name"))
            if not t:
                continue
            try:
                v = float(item.get("supervisor_score"))
            except (TypeError, ValueError):
                return fail("校准分数必须是数字")
            if not (SCORE_MIN <= v <= SCORE_MAX):
                return fail("校准分数须在 0-120 之间")
            if abs(v - float(t["supervisor_score"])) > 1e-9:
                t["_orig"] = t["supervisor_score"]
                t["supervisor_score"] = v
                t["comment"] = (str(t.get("comment") or "") + "［HR校准：原 %s 分］" % t["_orig"]).strip()
                t.pop("_orig", None)
        # 员工可能修改过指标名称/权重：按索引计算，不依赖名称匹配
        base = calc_base_score_by_index(scores, [x["supervisor_score"] for x in scores])
        total = round(base + float(isc["bonus_score"]) + float(isc["penalty_score"]), 2)
        execute("UPDATE internal_scores SET scores=?, base_score=?, total_score=? WHERE task_id=?",
                (json.dumps(scores, ensure_ascii=False), base, total, task_id))
    has_approver = bool(task["final_approver_id"])
    new_status = "hr_checked" if has_approver else "approved"
    execute("UPDATE internal_scores SET hr_comment=?, hr_user_id=?, hr_checked_at=?, status=?, "
            "updated_at=? WHERE task_id=?",
            (str(data.get("hr_comment", "")).strip(), g.user["id"], now_str(), new_status,
             now_str(), task_id))
    if has_approver:
        notify(task["final_approver_id"], "approve", "有绩效结果待最终审核",
               "%s 的 %s 考核待审核" % (query_one("SELECT name FROM users WHERE id=?",
                                              (task["user_id"],))["name"], task["period_code"]),
               "#/hr/scores")
    else:
        notify_hr("绩效结果待发布", "HR 核对完成，等待发布结果", "#/hr/results")
    audit("hr_check", task["task_no"])
    return ok({"status": new_status})


@app.route("/api/approval/scores/<int:task_id>/approve", methods=["POST"])
@login_required
def approve_score(task_id):
    task = query_one("SELECT * FROM assessment_tasks WHERE id=?", (task_id,))
    isc = query_one("SELECT * FROM internal_scores WHERE task_id=?", (task_id,))
    if not task or not isc:
        return fail("记录不存在", 404)
    if task["final_approver_id"] != g.user["id"] and g.user["role"] != "admin":
        return fail("只有最终审核人可以审核", 403)
    if isc["status"] != "hr_checked":
        return fail("当前状态不能审核")
    comment = str(body().get("approver_comment", "")).strip()
    execute("UPDATE internal_scores SET approver_comment=?, approver_user_id=?, approved_at=?, "
            "status='approved', updated_at=? WHERE task_id=?",
            (comment, g.user["id"], now_str(), now_str(), task_id))
    notify_hr("绩效结果待发布", "审核已通过，等待发布结果", "#/hr/results")
    audit("approve", task["task_no"], comment)
    return ok()


@app.route("/api/approval/scores/<int:task_id>/reject", methods=["POST"])
@login_required
def reject_score(task_id):
    task = query_one("SELECT * FROM assessment_tasks WHERE id=?", (task_id,))
    isc = query_one("SELECT * FROM internal_scores WHERE task_id=?", (task_id,))
    if not task or not isc:
        return fail("记录不存在", 404)
    if task["final_approver_id"] != g.user["id"] and g.user["role"] != "admin":
        return fail("只有最终审核人可以审核", 403)
    if isc["status"] != "hr_checked":
        return fail("当前状态不能审核")
    comment = str(body().get("approver_comment", "")).strip()
    if not comment:
        return fail("请填写退回原因")
    execute("UPDATE internal_scores SET approver_comment=?, approver_user_id=?, status='scored', "
            "hr_comment=NULL, hr_user_id=NULL, hr_checked_at=NULL, updated_at=? WHERE task_id=?",
            (comment, g.user["id"], now_str(), task_id))
    if task["supervisor_id"]:
        notify(task["supervisor_id"], "score", "评分被退回，请修改后重新提交",
               "%s 考核被退回：%s" % (task["period_code"], comment), "#/supervisor/tasks")
    notify_hr("绩效审核被退回", "%s 考核被最终审核退回" % task["period_code"], "#/hr/scores")
    audit("approve_reject", task["task_no"], comment)
    return ok()


@app.route("/api/hr/results")
@login_required
@require_roles("hr", "admin")
def hr_results():
    rows = query_all(
        "SELECT r.*, u.name AS user_name, u.department FROM published_results r "
        "JOIN users u ON u.id=r.user_id ORDER BY r.published_at DESC LIMIT 300")
    return ok(rows_to_dicts(rows))


@app.route("/api/hr/results/publish", methods=["POST"])
@login_required
@require_roles("hr", "admin")
def publish_result():
    data = body()
    task_id = data.get("task_id")
    task = query_one("SELECT * FROM assessment_tasks WHERE id=?", (task_id,))
    isc = query_one("SELECT * FROM internal_scores WHERE task_id=?", (task_id,))
    if not task or not isc:
        return fail("记录不存在", 404)
    if isc["status"] != "approved":
        return fail("仅审核通过的结果可以发布")
    if query_one("SELECT id FROM published_results WHERE task_id=?", (task_id,)):
        return fail("该任务结果已发布")
    public_feedback = str(data.get("public_feedback", "")).strip()
    if not public_feedback:
        return fail("请填写对员工公开的反馈")
    settings = get_settings()
    grade = grade_of(isc["total_score"], settings["grade_bands_parsed"])
    items = []
    for s in json.loads(isc["scores"] or "[]"):
        items.append({"name": s["name"], "weight": s["weight"],
                      "score": s["supervisor_score"],
                      "weighted": round(float(s["supervisor_score"]) * float(s["weight"]), 2)})
    rid = execute(
        "INSERT INTO published_results (task_id, user_id, period_type, period_code, items, "
        "base_score, bonus_score, penalty_score, total_score, grade, public_feedback, "
        "improvement, bonus_factor, published_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (task_id, task["user_id"], task["period_type"], task["period_code"],
         json.dumps(items, ensure_ascii=False), isc["base_score"], isc["bonus_score"],
         isc["penalty_score"], isc["total_score"], grade, public_feedback,
         str(data.get("improvement", "")).strip(), bonus_factor(isc["total_score"]),
         g.user["id"]))
    updates("UPDATE internal_scores SET status='published', public_feedback=?, updated_at=? "
            "WHERE task_id=?", (public_feedback, now_str(), task_id))
    updates("UPDATE assessment_tasks SET status='published', updated_at=? WHERE id=?",
            (now_str(), task_id))
    notify(task["user_id"], "result", "绩效结果已发布",
           "%s 考核结果已发布，总分 %s，等级 %s" % (task["period_code"], isc["total_score"], grade),
           "#/my/results")
    audit("result_publish", task["task_no"], "总分 %s 等级 %s" % (isc["total_score"], grade))
    return ok({"id": rid, "grade": grade})


# ================= 管理端 =================

@app.route("/api/admin/users", methods=["GET"])
@login_required
@require_roles("admin")
def admin_users():
    return ok(rows_to_dicts(query_all("SELECT * FROM users ORDER BY name")))


@app.route("/api/admin/users", methods=["POST"])
@login_required
@require_roles("admin")
def admin_create_user():
    data = body()
    username = str(data.get("username", "")).strip().lower()
    if not re.fullmatch(r"[a-z0-9._]{3,32}", username):
        return fail("账号须为 3-32 位小写字母、数字、点或下划线")
    if query_one("SELECT id FROM users WHERE username=?", (username,)):
        return fail("账号已存在")
    name = str(data.get("name", "")).strip()
    if not name:
        return fail("姓名不能为空")
    role = data.get("role")
    if role not in ("employee", "hr", "admin"):
        return fail("角色无效")
    pw = str(data.get("password", "")).strip() or "Perf@2026"
    if len(pw) < 8 or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        return fail("密码至少 8 位且包含字母和数字")
    uid = execute(
        "INSERT INTO users (username, password_hash, name, position, department, supervisor_id, "
        "role, is_final_approver, must_change_password) VALUES (?,?,?,?,?,?,?,?,1)",
        (username, hash_password(pw), name, str(data.get("position", "")).strip(),
         str(data.get("department", "")).strip(), data.get("supervisor_id") or None, role,
         1 if data.get("is_final_approver") else 0))
    audit("user_create", username)
    return ok({"id": uid})


@app.route("/api/admin/users/<int:user_id>", methods=["PUT"])
@login_required
@require_roles("admin")
def admin_update_user(user_id):
    u = query_one("SELECT * FROM users WHERE id=?", (user_id,))
    if not u:
        return fail("用户不存在", 404)
    data = body()
    if data.get("role") not in ("employee", "hr", "admin", None):
        return fail("角色无效")
    if u["id"] == g.user["id"] and data.get("role") not in (None, "admin"):
        return fail("不能修改自己的管理员角色")
    execute("UPDATE users SET name=?, position=?, department=?, supervisor_id=?, role=?, "
            "is_final_approver=?, updated_at=? WHERE id=?",
            (str(data.get("name", u["name"])).strip() or u["name"],
             str(data.get("position", u["position"] or "")).strip(),
             str(data.get("department", u["department"] or "")).strip(),
             data.get("supervisor_id") if "supervisor_id" in data else u["supervisor_id"],
             data.get("role") or u["role"],
             1 if data.get("is_final_approver") else 0, now_str(), user_id))
    audit("user_update", u["username"])
    return ok()


@app.route("/api/admin/users/<int:user_id>/reset-password", methods=["POST"])
@login_required
@require_roles("admin")
def admin_reset_password(user_id):
    u = query_one("SELECT * FROM users WHERE id=?", (user_id,))
    if not u:
        return fail("用户不存在", 404)
    pw = str(body().get("password", "")).strip() or "Perf@2026"
    if len(pw) < 8 or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        return fail("密码至少 8 位且包含字母和数字")
    updates("UPDATE users SET password_hash=?, must_change_password=1, updated_at=? WHERE id=?",
            (hash_password(pw), now_str(), user_id))
    updates("DELETE FROM sessions WHERE user_id=?", (user_id,))
    audit("user_reset_password", u["username"])
    return ok()


@app.route("/api/admin/users/<int:user_id>/toggle-active", methods=["POST"])
@login_required
@require_roles("admin")
def admin_toggle_active(user_id):
    u = query_one("SELECT * FROM users WHERE id=?", (user_id,))
    if not u:
        return fail("用户不存在", 404)
    if u["id"] == g.user["id"]:
        return fail("不能停用自己")
    new = 0 if u["is_active"] else 1
    updates("UPDATE users SET is_active=?, updated_at=? WHERE id=?", (new, now_str(), user_id))
    if not new:
        updates("DELETE FROM sessions WHERE user_id=?", (user_id,))
    audit("user_toggle_active", u["username"], "active=%d" % new)
    return ok({"is_active": new})


@app.route("/api/admin/users/<int:user_id>", methods=["DELETE"])
@login_required
@require_roles("admin")
def admin_delete_user(user_id):
    u = query_one("SELECT * FROM users WHERE id=?", (user_id,))
    if not u:
        return fail("用户不存在", 404)
    if u["id"] == g.user["id"]:
        return fail("不能删除当前登录的自己")
    if u["role"] == "admin" and \
            query_one("SELECT COUNT(*) AS c FROM users WHERE role='admin'")["c"] <= 1:
        return fail("系统至少需要保留一名管理员，无法删除该账号")
    # 已有本人考核记录的用户禁止删除，保护绩效历史数据（可停用替代）
    if query_one("SELECT COUNT(*) AS c FROM assessment_tasks WHERE user_id=?", (user_id,))["c"]:
        return fail("该用户已有考核记录，不能删除；如需禁止其登录，请使用「停用」")
    # 仍关联他人考核记录（担任主管/审核人/发布人）的用户禁止删除，需先调整相关任务
    if query_one("SELECT COUNT(*) AS c FROM assessment_tasks WHERE supervisor_id=? "
                 "OR final_approver_id=? OR created_by=?", (user_id, user_id, user_id))["c"] \
            or query_one("SELECT COUNT(*) AS c FROM internal_scores WHERE hr_user_id=? "
                         "OR approver_user_id=?", (user_id, user_id))["c"] \
            or query_one("SELECT COUNT(*) AS c FROM published_results WHERE published_by=?",
                         (user_id,))["c"]:
        return fail("该用户还关联着他人的考核记录（主管/审核/发布），请先调整相关任务后再删除")
    # 通过校验后清理外键引用再删除：会话/通知清除；考核配置级联删除；
    # 其下属与配置中的主管/审核人关联置空；审计日志保留但解除用户关联
    updates("DELETE FROM sessions WHERE user_id=?", (user_id,))
    updates("DELETE FROM notifications WHERE user_id=?", (user_id,))
    updates("UPDATE users SET supervisor_id=NULL WHERE supervisor_id=?", (user_id,))
    updates("UPDATE assessment_configs SET monthly_supervisor_id=NULL WHERE monthly_supervisor_id=?", (user_id,))
    updates("UPDATE assessment_configs SET quarterly_supervisor_id=NULL WHERE quarterly_supervisor_id=?", (user_id,))
    updates("UPDATE assessment_configs SET final_approver_id=NULL WHERE final_approver_id=?", (user_id,))
    updates("UPDATE assessment_configs SET created_by=NULL WHERE created_by=?", (user_id,))
    updates("DELETE FROM assessment_configs WHERE user_id=?", (user_id,))
    updates("UPDATE audit_logs SET user_id=NULL WHERE user_id=?", (user_id,))
    updates("DELETE FROM users WHERE id=?", (user_id,))
    audit("user_delete", u["username"])
    return ok()


@app.route("/api/admin/settings", methods=["GET"])
@login_required
def admin_get_settings():
    s = get_settings()
    return ok({"company_name": s.get("company_name", "图维生物医药"),
               "grade_bands": s["grade_bands_parsed"]})


@app.route("/api/admin/settings", methods=["PUT"])
@login_required
@require_roles("admin")
def admin_save_settings():
    data = body()
    bands = data.get("grade_bands") or []
    parsed = []
    for b in bands:
        try:
            parsed.append({"min": float(b["min"]), "grade": str(b["grade"]).strip()})
        except (KeyError, TypeError, ValueError):
            return fail("等级规则格式错误")
    if not parsed:
        return fail("等级规则不能为空")
    parsed.sort(key=lambda x: -x["min"])
    execute("INSERT INTO settings (key, value) VALUES ('grade_bands', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (json.dumps(parsed, ensure_ascii=False),))
    execute("INSERT INTO settings (key, value) VALUES ('company_name', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(data.get("company_name", "图维生物医药")).strip(),))
    audit("settings_save")
    return ok()


@app.route("/api/admin/audit-logs")
@login_required
@require_roles("admin")
def admin_audit_logs():
    page = max(1, int(request.args.get("page", 1) or 1))
    size = min(100, max(10, int(request.args.get("size", 50) or 50)))
    rows = query_all("SELECT a.*, u.name AS user_name FROM audit_logs a "
                     "LEFT JOIN users u ON u.id = a.user_id ORDER BY a.id DESC LIMIT ? OFFSET ?",
                     (size, (page - 1) * size))
    total = query_one("SELECT COUNT(*) AS c FROM audit_logs")["c"]
    return ok({"items": rows_to_dicts(rows), "total": total, "page": page, "size": size})


@app.route("/api/health")
def health():
    return ok({"status": "up", "time": now_str()})


# ================= 前端 =================

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    init_db(app)
    port = int(os.environ.get("PORT", 8600))
    app.run(host="0.0.0.0", port=port, threaded=True)
