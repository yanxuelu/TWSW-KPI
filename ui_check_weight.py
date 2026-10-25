# -*- coding: utf-8 -*-
"""自评表权重修改后被重置 Bug 的修复验证（CDP + 真实 Chrome）
复现路径：修改权重% → 勾选其他行（触发重渲染）→ 权重显示跳变（20 变 2000）
修复后：权重视图显示保持输入值；本地暂存/恢复一致；修改权重后可正常提交。
使用临时数据库与本地 Flask，不污染 perf.db。
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
FLASK_PORT = 8792
CDP_PORT = 9224
APP = "http://127.0.0.1:%d" % FLASK_PORT
HDR = {"X-Requested-With": "XMLHttpRequest"}
# TASK_ID 在服务启动后动态获取（临时库 ID 与本地库不同）

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
tmpdir = tempfile.mkdtemp(prefix="perf_w_")
db_path = os.path.join(tmpdir, "test.db")
env = dict(os.environ, PERF_DB=db_path)
r = subprocess.run([PY, os.path.join(BASE, "seed.py"), "--reset"],
                   cwd=BASE, env=env, capture_output=True, text=True)
assert r.returncode == 0, r.stderr

flask_proc = subprocess.Popen(
    [PY, os.path.join(BASE, "app.py")],
    cwd=BASE, env=dict(os.environ, PERF_DB=db_path, PORT=str(FLASK_PORT)),
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

# 动态获取孙浩的待自评任务 ID（临时库 ID 与本地库不同，不能硬编码）
_sess = requests.Session()
_sess.post(APP + "/api/login", headers=HDR, timeout=5,
           json={"username": "sunhao", "password": "Perf@2026"})
_tasks = _sess.get(APP + "/api/my/tasks", headers=HDR, timeout=5).json()["data"]
TASK_ID = next(t["id"] for t in _tasks if t["status"] == "pending_self")
assert TASK_ID, "未找到孙浩的待自评任务"
print("孙浩待自评任务 ID: %d" % TASK_ID)

# ---------- 2. Chrome ----------
chrome_dir = os.path.join(tmpdir, "chrome")
chrome_proc = subprocess.Popen(
    [CHROME, "--headless=new", "--no-sandbox", "--disable-gpu",
     "--remote-debugging-port=%d" % CDP_PORT, "--remote-allow-origins=*",
     "--user-data-dir=" + chrome_dir, "--window-size=1440,900", "about:blank"],
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


def set_input(sel, val):
    """设置输入框值并触发 input 事件（模拟用户输入）"""
    js("(() => { const el = document.querySelector(%r); if (!el) return false;"
       "el.value = %r; el.dispatchEvent(new Event('input', {bubbles: true})); return true; })()"
       % (sel, str(val)))


W0 = ".ind-w[data-i='0']"

try:
    cdp("Page.enable")
    cdp("Runtime.enable")

    print("== 自评表权重 Bug 修复验证 ==")

    # ---------- 3. 登录并打开自评表 ----------
    cdp("Page.navigate", {"url": APP + "/"})
    wait_js("!!document.querySelector('#lgUser')", 10)
    js("document.querySelector('#lgUser').value='sunhao';"
       "document.querySelector('#lgPwd').value='Perf@2026';"
       "document.querySelector('#loginForm button[type=submit]').click();")
    wait_js("!document.querySelector('#lgUser')", 10)
    js("location.hash='#/my/tasks/%d'" % TASK_ID)
    wait_js("!!document.querySelector('.ind-w')", 15)
    check("自评表打开（含 4 项指标）",
          js("document.querySelectorAll('.ind-w').length") == 4)
    check("初始权重显示 35/25/20/20",
          js("[...document.querySelectorAll('.ind-w')].map(e => e.value).join(',')") == "35,25,20,20",
          js("[...document.querySelectorAll('.ind-w')].map(e => e.value).join(',')"))
    check("初始权重合计 100%", (js("document.querySelector('#wsumWeight').textContent") or "").strip() == "100%")

    # ---------- 4. 核心 Bug：改权重后勾选其他行 ----------
    print("\n-- 核心场景：修改权重后选中其他项 --")
    set_input(W0, "40")
    time.sleep(0.3)
    check("修改第一项权重为 40 后合计显示 105%",
          (js("document.querySelector('#wsumWeight').textContent") or "").strip() == "105%")
    # 勾选其他行（触发 renderBody 重渲染）——Bug 复现点
    js("document.querySelectorAll('.chk-row')[1].click()")
    time.sleep(0.4)
    check("勾选其他行后第一项权重仍显示 40（不再跳变为 4000）",
          js("document.querySelector(%r).value" % W0) == "40",
          js("document.querySelector(%r).value" % W0))
    check("勾选其他行后权重合计仍为 105%",
          (js("document.querySelector('#wsumWeight').textContent") or "").strip() == "105%")
    # 全选再取消，进一步验证重渲染不丢值
    js("document.querySelector('#chkAll').click(); document.querySelector('#chkAll').click()")
    time.sleep(0.4)
    check("全选/取消全选后权重仍显示 40",
          js("document.querySelector(%r).value" % W0) == "40",
          js("document.querySelector(%r).value" % W0))
    # 在其他输入框输入（input 事件路径）
    set_input(".ind-completion[data-i='1']", "完成市场拓展与客户拜访")
    time.sleep(0.3)
    check("在其他字段输入后权重仍显示 40",
          js("document.querySelector(%r).value" % W0) == "40",
          js("document.querySelector(%r).value" % W0))
    # 截图：修改权重并勾选其他行后的稳定状态（Bug 修复效果）
    import base64  # noqa: F401
    os.makedirs(os.path.join(BASE, "screenshots"), exist_ok=True)
    _res = cdp("Page.captureScreenshot", {"format": "png"})
    with open(os.path.join(BASE, "screenshots", "ui_weight_fixed.png"), "wb") as _f:
        _f.write(base64.b64decode(_res["result"]["data"]))

    # ---------- 5. 本地暂存与恢复 ----------
    print("\n-- 本地暂存/恢复一致性 --")
    js("document.querySelector('#btnSaveDraft').click()")
    time.sleep(0.5)
    js("location.reload()")
    wait_js("!!document.querySelector('.ind-w')", 15)
    check("刷新页面后暂存的权重恢复为 40/25/20/20",
          js("[...document.querySelectorAll('.ind-w')].map(e => e.value).join(',')") == "40,25,20,20",
          js("[...document.querySelectorAll('.ind-w')].map(e => e.value).join(',')"))

    # ---------- 6. 修改权重后完整提交 ----------
    print("\n-- 修改权重后提交 --")
    set_input(W0, "40")
    set_input(".ind-w[data-i='3']", "15")  # 40+25+20+15 = 100
    time.sleep(0.3)
    check("调整后权重合计 100%",
          (js("document.querySelector('#wsumWeight').textContent") or "").strip() == "100%")
    js("""[...document.querySelectorAll('.ind-completion')].forEach((el, i) => {
      if (!el.value) { el.value = '第' + (i+1) + '项指标已完成既定目标'; el.dispatchEvent(new Event('input', {bubbles:true})); }
    });
    [...document.querySelectorAll('.ind-score')].forEach(el => {
      el.value = '105'; el.dispatchEvent(new Event('input', {bubbles:true}));
    });""")
    js("document.querySelector('#saConfirm').checked = true;"
       "document.querySelector('#saSign').value = '孙浩';")
    js("document.querySelector('#btnSubmit').click()")
    ok = wait_js("[...document.querySelectorAll('.toast')].some(t => t.textContent.includes('自评已提交'))", 10)
    check("修改权重后提交成功", bool(ok))
    # 接口校验：任务进入评分阶段，且入库权重为小数
    res = js("fetch('/api/my/tasks/%d',{headers:{'X-Requested-With':'XMLHttpRequest'}})"
             ".then(r=>r.json()).then(j=>j.data)" % TASK_ID, await_promise=True)
    check("任务状态已进入评分阶段", bool(res) and res.get("status") == "pending_score",
          str(res and res.get("status")))
    sa = (res or {}).get("self_assessment") or {}
    ws_ = [round(it["weight"], 4) for it in (sa.get("items") or [])]
    check("入库权重为小数且合计 100%", ws_ == [0.4, 0.25, 0.2, 0.15], str(ws_))
    scores = [it["self_score"] for it in (sa.get("items") or [])]
    check("自评分为数字且为 105", scores == [105, 105, 105, 105], str(scores))
    check("签字已保存", sa.get("signature") == "孙浩", str(sa.get("signature")))

    # ---------- 7. 提交后跳转列表，再进入只读表单 ----------
    print("\n-- 提交后只读态 --")
    wait_js("location.hash === '#/my/tasks' || (location.hash.startsWith('#/my/tasks') "
            "&& !location.hash.includes('my/tasks/'))", 8)
    time.sleep(0.5)
    js("[...document.querySelectorAll('a,button')].find(e => e.textContent.includes('查看'))?.click()")
    wait_js("!!document.querySelector('.tpl-tbl') && !document.querySelector('.ind-w')", 8)
    check("提交后表单切换为只读态", not js("!!document.querySelector('.ind-w')"))
    check("只读态权重显示 40%/25%/20%/15%",
          js("[...document.querySelectorAll('.tpl-tbl tbody tr')]"
             ".map(tr => tr.children[5].textContent.trim()).join(',')") == "40%,25%,20%,15%",
          js("[...document.querySelectorAll('.tpl-tbl tbody tr')]"
             ".map(tr => tr.children[5].textContent.trim()).join(',')"))

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
