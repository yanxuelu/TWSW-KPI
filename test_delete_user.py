# -*- coding: utf-8 -*-
"""删除用户功能 API 验证（独立测试）
使用临时数据库（PERF_DB 指向临时文件），不污染项目 perf.db。
覆盖：正常删除及关联清理 / 删自己 / 有考核记录 / 关联他人考核 /
      管理员账号保护 / 权限控制 / 404 / 外键完整性。
"""
import os
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
HDR = {"X-Requested-With": "XMLHttpRequest"}

# ---------- 准备临时库并灌入种子数据 ----------
tmpdir = tempfile.mkdtemp(prefix="perf_del_")
db_path = os.path.join(tmpdir, "test.db")
env = dict(os.environ, PERF_DB=db_path)
r = subprocess.run([PY, os.path.join(BASE, "seed.py"), "--reset"],
                   cwd=BASE, env=env, capture_output=True, text=True)
if r.returncode != 0:
    print(r.stdout)
    print(r.stderr)
    sys.exit("种子数据初始化失败")

os.environ["PERF_DB"] = db_path
sys.path.insert(0, BASE)
import sqlite3  # noqa: E402
from app import app as flask_app  # noqa: E402

flask_app.config["TESTING"] = True

PASS = FAIL = 0
FAILED = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print("  [OK] %s" % name)
    else:
        FAIL += 1
        FAILED.append(name)
        print("  [FAIL] %s %s" % (name, detail))


def q(sql, args=()):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def ex(sql, args=()):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def uid_of(username):
    return q("SELECT id FROM users WHERE username=?", (username,))[0]["id"]


def login(client, username, password="Perf@2026"):
    resp = client.post("/api/login", headers=HDR,
                       json={"username": username, "password": password})
    j = resp.get_json()
    assert j and j.get("ok"), "登录失败: %s -> %s" % (username, resp.data)
    return j


def err_of(resp):
    j = resp.get_json() or {}
    return j.get("error", "")


def create_user(client, username, role="employee", **extra):
    payload = {"username": username, "name": extra.pop("name", "测试" + username),
               "password": extra.pop("password", "Perf@2026"), "role": role}
    payload.update(extra)
    resp = client.post("/api/admin/users", headers=HDR, json=payload)
    j = resp.get_json()
    assert j and j.get("ok"), "创建用户失败: %s -> %s" % (username, resp.data)
    return j["data"]["id"]


print("== 删除用户功能验证（临时库 %s） ==" % db_path)

admin = flask_app.test_client()
login(admin, "admin")
admin_id = uid_of("admin")

# ---------- T1 正常删除（含全部关联清理） ----------
print("\n-- T1 正常删除与关联清理 --")
u2 = create_user(admin, "testdel2")
c2 = flask_app.test_client()
login(c2, "testdel2")  # 产生会话与登录审计
ex("INSERT INTO notifications (user_id, title) VALUES (?, '测试通知')", (u2,))
conn = sqlite3.connect(db_path)
cur = conn.execute("INSERT INTO assessment_configs (user_id, frequency) VALUES (?, 'monthly')", (u2,))
cfg_id = cur.lastrowid
conn.execute("INSERT INTO config_indicators (config_id, period_type, name, weight, sort_order) "
             "VALUES (?, 'monthly', '测试指标', 1.0, 0)", (cfg_id,))
conn.commit()
conn.close()
# 被他人配置引用为月度主管；拥有下属
ex("UPDATE assessment_configs SET monthly_supervisor_id=? WHERE user_id=?", (u2, uid_of("zhouwenwen")))
ex("UPDATE users SET supervisor_id=? WHERE username='zhangsan'", (u2,))

resp = admin.delete("/api/admin/users/%d" % u2, headers=HDR)
check("删除返回成功", resp.status_code == 200 and (resp.get_json() or {}).get("ok"), resp.data)
check("用户已从列表移除", not q("SELECT 1 FROM users WHERE id=?", (u2,)))
check("登录会话已清除", not q("SELECT 1 FROM sessions WHERE user_id=?", (u2,)))
check("站内通知已清除", not q("SELECT 1 FROM notifications WHERE user_id=?", (u2,)))
check("自有考核配置已删除", not q("SELECT 1 FROM assessment_configs WHERE user_id=?", (u2,)))
check("配置指标已级联删除", not q("SELECT 1 FROM config_indicators WHERE config_id=?", (cfg_id,)))
check("他人配置中的主管引用已置空",
      q("SELECT monthly_supervisor_id FROM assessment_configs WHERE user_id=?",
        (uid_of("zhouwenwen"),))[0]["monthly_supervisor_id"] is None)
check("下属的 supervisor_id 已置空",
      q("SELECT supervisor_id FROM users WHERE username='zhangsan'")[0]["supervisor_id"] is None)
audit_kept = q("SELECT user_id FROM audit_logs WHERE target='testdel2' AND action='login'")
check("被删用户的审计日志保留且解除关联", len(audit_kept) >= 1 and all(a["user_id"] is None for a in audit_kept))
check("删除操作已记录审计",
      q("SELECT 1 FROM audit_logs WHERE action='user_delete' AND target='testdel2'"))

# ---------- T2 有考核记录的用户禁止删除 ----------
print("\n-- T2 考核历史保护 --")
resp = admin.delete("/api/admin/users/%d" % uid_of("sunhao"), headers=HDR)
check("有考核记录用户禁止删除", resp.status_code != 200 and "考核记录" in err_of(resp), err_of(resp))
check("孙浩用户仍然存在", bool(q("SELECT 1 FROM users WHERE username='sunhao'")))

# ---------- T3 关联他人考核的用户禁止删除 ----------
print("\n-- T3 他人考核关联保护 --")
cys_id = uid_of("chenyongsheng")
check("孙浩任务的主管是程永升",
      q("SELECT t.supervisor_id FROM assessment_tasks t JOIN users u ON u.id=t.user_id "
        "WHERE u.username='sunhao'")[0]["supervisor_id"] == cys_id)
check("程永升本人无考核任务", not q("SELECT 1 FROM assessment_tasks WHERE user_id=?", (cys_id,)))
resp = admin.delete("/api/admin/users/%d" % cys_id, headers=HDR)
check("关联他人考核用户禁止删除",
      resp.status_code != 200 and "他人的考核记录" in err_of(resp), err_of(resp))
check("程永升用户仍然存在", bool(q("SELECT 1 FROM users WHERE username='chenyongsheng'")))

# ---------- T4 不能删除自己 ----------
print("\n-- T4 自我保护 --")
resp = admin.delete("/api/admin/users/%d" % admin_id, headers=HDR)
check("不能删除当前登录自己", resp.status_code != 200 and "自己" in err_of(resp), err_of(resp))

# ---------- T5 管理员账号保护 ----------
print("\n-- T5 管理员账号保护 --")
check("系统初始仅一名管理员", q("SELECT COUNT(*) c FROM users WHERE role='admin'")[0]["c"] == 1)
admin2_id = create_user(admin, "admin2", role="admin")
check("新建后共两名管理员", q("SELECT COUNT(*) c FROM users WHERE role='admin'")[0]["c"] == 2)
admin2_cli = flask_app.test_client()
login(admin2_cli, "admin2")
resp = admin.delete("/api/admin/users/%d" % admin2_id, headers=HDR)
check("非最后一名管理员可被删除", resp.status_code == 200, resp.data)
check("删除后仍保留一名管理员", q("SELECT COUNT(*) c FROM users WHERE role='admin'")[0]["c"] == 1)
resp = admin.delete("/api/admin/users/%d" % admin_id, headers=HDR)
check("唯一管理员无法删除自己（保证系统始终有管理员）",
      resp.status_code != 200 and "自己" in err_of(resp), err_of(resp))

# ---------- T6 权限与边界 ----------
print("\n-- T6 权限与边界 --")
emp = flask_app.test_client()
login(emp, "zhouwenwen")
u3 = create_user(admin, "testdel3")
resp = emp.delete("/api/admin/users/%d" % u3, headers=HDR)
check("员工角色删除返回 403", resp.status_code == 403, resp.status_code)
resp = admin.delete("/api/admin/users/999999", headers=HDR)
check("删除不存在用户返回 404", resp.status_code == 404, resp.status_code)
resp = admin.delete("/api/admin/users/%d" % u3, headers=HDR)
check("管理员可删除新建用户", resp.status_code == 200, resp.data)

# ---------- T7 数据完整性 ----------
print("\n-- T7 数据完整性 --")
conn = sqlite3.connect(db_path)
fk = conn.execute("PRAGMA foreign_key_check").fetchall()
conn.close()
check("外键完整性检查通过", not fk, fk)
check("考核任务数据未受影响", q("SELECT COUNT(*) c FROM assessment_tasks")[0]["c"] == 10)
check("已发布结果数据未受影响", q("SELECT COUNT(*) c FROM published_results")[0]["c"] >= 1)

print("\n== 结果：%d 通过，%d 失败 ==" % (PASS, FAIL))
if FAILED:
    print("失败项：%s" % "、".join(FAILED))
sys.exit(1 if FAIL else 0)
