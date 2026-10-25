# -*- coding: utf-8 -*-
"""删除用户功能 UI 验证（CDP + 真实 Chrome）
使用临时数据库与本地 Flask 实例，不污染项目 perf.db。
验证：删除按钮渲染 / 确认弹窗文案 / 取消不删除 / 确认删除成功 /
      有考核记录用户删除被拦截并提示。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import requests
import websocket

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
BASE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
FLASK_PORT = 8791
CDP_PORT = 9223
APP = "http://127.0.0.1:%d" % FLASK_PORT
HDR = {"X-Requested-With": "XMLHttpRequest"}
SHOTS = os.path.join(BASE, "screenshots")

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


# ---------- 1. 临时库 + 种子 + 本地服务 ----------
tmpdir = tempfile.mkdtemp(prefix="perf_ui_")
db_path = os.path.join(tmpdir, "test.db")
env = dict(os.environ, PERF_DB=db_path)
r = subprocess.run([PY, os.path.join(BASE, "seed.py"), "--reset"],
                   cwd=BASE, env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

flask_env = dict(os.environ, PERF_DB=db_path, PORT=str(FLASK_PORT))
flask_proc = subprocess.Popen([PY, os.path.join(BASE, "app.py")], cwd=BASE, env=flask_env,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(40):
    try:
        if requests.get(APP + "/api/health", timeout=2).status_code == 200:
            break
    except requests.RequestException:
        time.sleep(0.25)
else:
    flask_proc.kill()
    sys.exit("Flask 启动失败")

# 先登录管理员会话，再创建一个用于 UI 删除验证的测试用户
sess = requests.Session()
sess.post(APP + "/api/login", headers=HDR, timeout=5,
          json={"username": "admin", "password": "Perf@2026"})
resp = sess.post(APP + "/api/admin/users", headers=HDR, timeout=5,
                 json={"username": "uidel1", "name": "界面删除测试", "password": "Perf@2026",
                       "role": "employee"})
assert resp.json().get("ok"), resp.text

# ---------- 2. 启动 Chrome ----------
chrome_dir = os.path.join(tmpdir, "chrome")
chrome_proc = subprocess.Popen(
    [CHROME, "--headless=new", "--no-sandbox", "--disable-gpu",
     "--remote-debugging-port=%d" % CDP_PORT, "--remote-allow-origins=*",
     "--user-data-dir=" + chrome_dir,
     "--window-size=1440,900", "about:blank"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
target = None
for _ in range(40):
    try:
        targets = requests.get("http://127.0.0.1:%d/json" % CDP_PORT, timeout=2).json()
        target = next((t for t in targets if t["type"] == "page"), None)
        if target:
            break
    except requests.RequestException:
        time.sleep(0.25)
if not target:
    chrome_proc.kill()
    flask_proc.kill()
    sys.exit("Chrome CDP 启动失败")

ws = websocket.create_connection(target["webSocketDebuggerUrl"], timeout=30)
msg_id = [0]


def cdp(method, params=None):
    msg_id[0] += 1
    ws.send(json.dumps({"id": msg_id[0], "method": method, "params": params or {}}))
    while True:
        resp = json.loads(ws.recv())
        if resp.get("id") == msg_id[0]:
            return resp


def js(expr, await_promise=False):
    res = cdp("Runtime.evaluate",
              {"expression": expr, "returnByValue": True, "awaitPromise": await_promise})
    if "exceptionDetails" in res.get("result", {}):
        raise RuntimeError("JS 异常: %s" % res["result"]["exceptionDetails"])
    return res["result"]["result"].get("value")


def wait_js(expr, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            v = js(expr)
        except Exception:
            v = None
        if v:
            return v
        time.sleep(0.25)
    return None


def shot(name):
    os.makedirs(SHOTS, exist_ok=True)
    res = cdp("Page.captureScreenshot", {"format": "png"})
    data = res["result"]["data"]
    with open(os.path.join(SHOTS, name), "wb") as f:
        f.write(__import__("base64").b64decode(data))


ROW_JS = ("[...document.querySelectorAll('tbody tr')]"
          ".find(tr => tr.children[0] && tr.children[0].textContent.trim() === '%s')")

try:
    cdp("Page.enable")
    cdp("Runtime.enable")
    print("== 删除用户功能 UI 验证 ==")

    # ---------- 3. 登录 ----------
    cdp("Page.navigate", {"url": APP + "/"})
    wait_js("!!document.querySelector('#lgUser')", 10)
    check("登录页加载", bool(js("!!document.querySelector('#lgUser')")))
    js("document.querySelector('#lgUser').value='admin';"
       "document.querySelector('#lgPwd').value='Perf@2026';"
       "document.querySelector('#loginForm button[type=submit]').click();")
    js("location.hash='#/admin/users'")
    wait_js("!!document.querySelector('#btnAddUser')", 15)
    check("管理员登录并进入用户管理页", bool(js("!!document.querySelector('#btnAddUser')")))

    # ---------- 4. 删除按钮渲染 ----------
    rows = js("document.querySelectorAll('tbody tr').length") or 0
    dels = js("document.querySelectorAll('[data-del]').length") or 0
    check("每行用户均有「删除」按钮", rows == dels and rows > 0, "行数=%s 删除按钮=%s" % (rows, dels))
    check("「删除」按钮为危险样式（红色）",
          js("document.querySelector('[data-del]').classList.contains('danger')"))
    check("测试用户 uidel1 行存在", bool(js("!!(%s)" % ROW_JS % "uidel1")))

    # ---------- 5. 确认弹窗 ----------
    js("(%s).querySelector('[data-del]').click()" % ROW_JS % "uidel1")
    wait_js("!!document.querySelector('.mask .modal')", 5)
    body_txt = js("document.querySelector('.mask .modal .bd').textContent") or ""
    check("点击删除弹出确认框", bool(body_txt))
    check("确认框含删除风险提示", "无法恢复" in body_txt and "停用" in body_txt, body_txt[:60])
    check("确认框含确定/取消按钮",
          bool(js("!!document.querySelector('.mask [data-yes]') && !!document.querySelector('.mask [data-no]')")))
    check("确定按钮为危险样式",
          js("document.querySelector('.mask [data-yes]').classList.contains('danger')"))
    shot("ui_delete_confirm.png")

    # ---------- 6. 取消不删除 ----------
    js("document.querySelector('.mask [data-no]').click()")
    time.sleep(0.4)
    check("取消后弹窗关闭", not js("!!document.querySelector('.mask')"))
    check("取消后用户仍存在", bool(js("!!(%s)" % ROW_JS % "uidel1")))

    # ---------- 7. 确认删除 ----------
    js("(%s).querySelector('[data-del]').click()" % ROW_JS % "uidel1")
    wait_js("!!document.querySelector('.mask [data-yes]')", 5)
    js("document.querySelector('.mask [data-yes]').click()")
    ok = wait_js("[...document.querySelectorAll('.toast')].some(t => t.textContent.includes('已删除'))", 8)
    check("删除成功提示「已删除」", bool(ok))
    wait_js("!(%s)" % ROW_JS % "uidel1", 8)
    check("删除后该行从列表移除", not js("!!(%s)" % ROW_JS % "uidel1"))
    # 通过浏览器端已登录会话查询接口，确认用户已删除
    gone = js("fetch('/api/admin/users',{headers:{'X-Requested-With':'XMLHttpRequest'}})"
              ".then(r=>r.json()).then(j=>!j.data.some(u=>u.username==='uidel1'))",
              await_promise=True)
    check("接口确认用户已删除", gone is True)
    shot("ui_delete_done.png")

    # ---------- 8. 有考核记录用户删除被拦截 ----------
    js("(%s).querySelector('[data-del]').click()" % ROW_JS % "sunhao")
    wait_js("!!document.querySelector('.mask [data-yes]')", 5)
    js("document.querySelector('.mask [data-yes]').click()")
    err = wait_js("[...document.querySelectorAll('.toast.err')].some(t => t.textContent.includes('考核记录'))", 8)
    check("有考核记录用户删除被拦截并提示", bool(err))
    check("孙浩仍在列表中", bool(js("!!(%s)" % ROW_JS % "sunhao")))
    js("document.querySelector('.mask [data-no]') && document.querySelector('.mask [data-no]').click()")
    time.sleep(0.3)
    check("关闭残留弹窗", not js("!!document.querySelector('.mask')"))
    shot("ui_users_page.png")

    # ---------- 9. 其他操作按钮仍正常 ----------
    check("编辑/重置密码/停用按钮仍存在",
          js("document.querySelectorAll('[data-edit]').length") > 0 and
          js("document.querySelectorAll('[data-pwd]').length") > 0 and
          js("document.querySelectorAll('[data-toggle]').length") > 0)

finally:
    try:
        ws.close()
    except Exception:
        pass
    chrome_proc.kill()
    flask_proc.kill()
    shutil.rmtree(tmpdir, ignore_errors=True)

print("\n== 结果：%d 通过，%d 失败 ==" % (PASS, FAIL))
if FAILED:
    print("失败项：%s" % "、".join(FAILED))
sys.exit(1 if FAIL else 0)
