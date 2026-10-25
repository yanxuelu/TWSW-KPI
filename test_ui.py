# -*- coding: utf-8 -*-
"""CDP 真实浏览器验证：多角色登录后检查页面渲染与 JS 运行时错误
标记词只取页面内容区独有文本，避免侧边栏菜单造成虚假通过。"""
import asyncio
import base64
import http.cookiejar
import json
import os
import subprocess
import urllib.request

import websockets

CHROME = "C:/Program Files/Google/Chrome/Application/chrome.exe"
PORT = 9222
APP = "http://127.0.0.1:8600"
OUT = "E:/WorkBuddy/2026-10-23-21-19-08/tuwei-perf/screenshots"

_errors = []
_sess_opener = None


def api(method, path, data=None):
    """带 HR 会话的 API 调用（用于测试准备数据）"""
    global _sess_opener
    if _sess_opener is None:
        cj = http.cookiejar.CookieJar()
        _sess_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        req = urllib.request.Request(
            APP + "/api/login", data=json.dumps({"username": "hr", "password": "Perf@2026"}).encode(),
            headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
            method="POST")
        _sess_opener.open(req).read()
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(APP + path, data=body,
                                 headers={"Content-Type": "application/json",
                                          "X-Requested-With": "XMLHttpRequest"}, method=method)
    return json.loads(_sess_opener.open(req).read().decode())["data"]


def api_login(username, password="Perf@2026"):
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    req = urllib.request.Request(
        APP + "/api/login", data=json.dumps({"username": username, "password": password}).encode(),
        headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"}, method="POST")
    op.open(req).read()
    for c in cj:
        if c.name == "tp_session":
            return c.value
    raise RuntimeError("no session cookie for " + username)


class CDP:
    def __init__(self, ws):
        self.ws = ws
        self._id = 0

    async def send(self, method, params=None):
        self._id += 1
        mid = self._id
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError("%s: %s" % (method, msg["error"]))
                return msg.get("result", {})
            if msg.get("method") == "Runtime.exceptionThrown":
                _errors.append("JS异常: " + json.dumps(msg["params"], ensure_ascii=False)[:300])


async def _page_ws():
    for _ in range(30):
        try:
            data = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/json/list" % PORT, timeout=3).read())
            pages = [t for t in data if t.get("type") == "page"]
            if pages:
                return pages[0]["webSocketDebuggerUrl"]
        except Exception:
            pass
        await asyncio.sleep(0.5)
    raise RuntimeError("chrome devtools not ready")


async def run_check(token, hash_path, markers, name, shot=True, js_check=None):
    _errors.clear()
    ws_url = await _page_ws()
    async with websockets.connect(ws_url, max_size=50 * 1024 * 1024) as ws:
        cdp = CDP(ws)
        await cdp.send("Network.enable")
        await cdp.send("Runtime.enable")
        await cdp.send("Page.enable")
        await cdp.send("Network.clearBrowserCookies")
        await cdp.send("Network.setCookie", {"name": "tp_session", "value": token, "url": APP + "/"})
        await cdp.send("Page.navigate", {"url": "about:blank"})
        await asyncio.sleep(0.4)
        await cdp.send("Page.navigate", {"url": APP + "/" + hash_path})
        await asyncio.sleep(2.5)
        r = await cdp.send("Runtime.evaluate", {
            "expression": "document.querySelector('#app').innerText.replace(/\\s+/g,' ')",
            "returnByValue": True})
        text = r.get("result", {}).get("value", "")
        ok = all(mk in text for mk in markers)
        if ok and js_check:
            rj = await cdp.send("Runtime.evaluate", {"expression": js_check, "returnByValue": True})
            jv = rj.get("result", {}).get("value", "")
            ok = bool(jv)
            if not ok:
                print("   JS校验值:", repr(jv))
        print(("✓ " if ok and not _errors else "✗ ") + name)
        if not ok:
            print("   页面文本:", text[:400])
            print("   期望包含:", markers)
        for e in _errors:
            print("   " + e)
        if shot:
            s = await cdp.send("Page.captureScreenshot", {"format": "png"})
            os.makedirs(OUT, exist_ok=True)
            with open("%s/%s.png" % (OUT, name.replace("/", "_").replace(" ", "_").replace("(", "").replace(")", "")), "wb") as f:
                f.write(base64.b64decode(s["data"]))
        return ok and not _errors


async def fill_and_submit(token, task_id, name):
    """在自评表单页填写内容、勾选确认、签名并提交"""
    _errors.clear()
    ws_url = await _page_ws()
    async with websockets.connect(ws_url, max_size=50 * 1024 * 1024) as ws:
        cdp = CDP(ws)
        await cdp.send("Network.enable")
        await cdp.send("Runtime.enable")
        await cdp.send("Page.enable")
        await cdp.send("Network.clearBrowserCookies")
        await cdp.send("Network.setCookie", {"name": "tp_session", "value": token, "url": APP + "/"})
        await cdp.send("Page.navigate", {"url": "about:blank"})
        await asyncio.sleep(0.4)
        await cdp.send("Page.navigate", {"url": APP + "/#/my/tasks/%d" % task_id})
        await asyncio.sleep(2.5)
        # 增删指标行交互：增加一行 → 勾选删除 → 序号重排
        js_rows = """(() => {
          const rowCount = () => document.querySelectorAll('#tplBody tr').length;
          const seqs = () => Array.from(
            document.querySelectorAll('#tplBody tr td:nth-child(2)')).map(td => td.textContent.trim());
          const before = rowCount();
          document.querySelector('#btnAddRow').click();
          const afterAdd = rowCount();
          const chks = document.querySelectorAll('.chk-row');
          chks[chks.length - 1].click();           // 勾选最后一行（新增行）
          document.querySelector('#btnDelRow').click();
          const afterDel = rowCount();
          return before + '|' + afterAdd + '|' + afterDel + '|' + seqs().join(',');
        })()"""
        r = await cdp.send("Runtime.evaluate", {"expression": js_rows, "returnByValue": True})
        rows_info = r.get("result", {}).get("value", "")
        before, afterAdd, afterDel, seqs = rows_info.split("|")
        ok_rows = (afterAdd == str(int(before) + 1) and afterDel == before
                   and seqs == ",".join(str(i + 1) for i in range(int(before))))
        print(("✓ " if ok_rows and not _errors else "✗ ") + name + "-增删指标行  [" + rows_info + "]")
        if not ok_rows:
            print("   期望: 行数 %s → +1 → 回到 %s，序号 1..%s" % (before, before, before))
        for e in _errors:
            print("   " + e)
        if not ok_rows:
            return False
        js = """(() => {
          const fire = (el) => el.dispatchEvent(new Event('input', {bubbles: true}));
          // 员工编辑指标定义字段（名称/100%标准/120%标准/数据来源）
          const names = document.querySelectorAll('.ind-name');
          if (names[0]) { names[0].value = names[0].value + '（测试修订）'; fire(names[0]); }
          document.querySelectorAll('.ind-100').forEach((el) => {
            el.value = '测试100%衡量标准'; fire(el); });
          document.querySelectorAll('.ind-120').forEach((el) => {
            el.value = '测试120%衡量标准'; fire(el); });
          document.querySelectorAll('.ind-src').forEach((el) => {
            el.value = '测试部门：测试文档'; fire(el); });
          document.querySelectorAll('.ind-completion').forEach((el, i) => {
            el.value = '第' + (i + 1) + '项指标已完成，达成 100% 目标。'; fire(el); });
          document.querySelectorAll('.ind-score').forEach((el, i) => {
            el.value = String(100 + i * 2); fire(el); });
          const ach = document.querySelector('#fAch');
          if (ach) { ach.value = '本月各项目标均按计划达成。'; fire(ach); }
          const ck = document.querySelector('#saConfirm'); if (ck) ck.checked = true;
          const sg = document.querySelector('#saSign'); if (sg) sg.value = '孙浩';
          return document.querySelector('#btnSubmit') ? true : false;
        })()"""
        r = await cdp.send("Runtime.evaluate", {"expression": js, "returnByValue": True})
        if not r.get("result", {}).get("value"):
            print("✗ " + name + "（表单未渲染出提交按钮）")
            for e in _errors:
                print("   " + e)
            return False
        await cdp.send("Runtime.evaluate", {"expression": "document.querySelector('#btnSubmit').click()"})
        await asyncio.sleep(2.5)
        r = await cdp.send("Runtime.evaluate", {
            "expression": "location.hash + '|' + Array.from(document.querySelectorAll('.toast')).map(t => t.textContent).join(';')",
            "returnByValue": True})
        info = r.get("result", {}).get("value", "")
        ok = "my/tasks" in info and "自评已提交" in info
        print(("✓ " if ok and not _errors else "✗ ") + name + "  [" + info[:90] + "]")
        if not ok:
            t = await cdp.send("Runtime.evaluate", {
                "expression": "document.querySelector('#app').innerText.slice(0,200)",
                "returnByValue": True})
            print("   页面文本:", t.get("result", {}).get("value", ""))
        for e in _errors:
            print("   " + e)
        return ok and not _errors


async def main():
    proc = subprocess.Popen([
        CHROME, "--headless=new", "--remote-debugging-port=%d" % PORT, "--no-sandbox",
        "--disable-gpu", "--window-size=1440,900",
        "--user-data-dir=E:/WorkBuddy/2026-10-23-21-19-08/_inputs/chrome_tmp",
        "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        await _page_ws()
        results = []

        # 准备数据：王五 Q3 推到「待负责人审核」；王五 9 月月度由主管评分后推到「待HR核对」
        tasks = {t["task_no"]: t for t in api("GET", "/api/hr/tasks")}
        q3 = [t for t in tasks.values() if t["task_no"] == "TP2026Q30002"][0]
        api("POST", "/api/hr/scores/%d/check" % q3["id"], {"hr_comment": "核对无误"})
        m9 = [t for t in tasks.values() if t["task_no"] == "TP2026090003"][0]
        inds = [i["name"] for i in api("GET", "/api/supervisor/tasks/%d" % m9["id"])["indicators"]]
        # 以评分主管（周杰）身份提交评分
        cj2 = http.cookiejar.CookieJar()
        op2 = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj2))
        op2.open(urllib.request.Request(
            APP + "/api/login", data=json.dumps({"username": "zhoujie", "password": "Perf@2026"}).encode(),
            headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"}, method="POST")).read()
        op2.open(urllib.request.Request(
            APP + "/api/supervisor/tasks/%d/score" % m9["id"],
            data=json.dumps({"scores": [{"name": n, "supervisor_score": 105} for n in inds],
                             "bonus_score": 0, "penalty_score": 0, "supervisor_comment": "测试评分"}).encode(),
            headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
            method="POST")).read()

        # 未登录 → 登录页
        ws_url = await _page_ws()
        async with websockets.connect(ws_url, max_size=50 * 1024 * 1024) as ws:
            cdp = CDP(ws)
            await cdp.send("Network.enable")
            await cdp.send("Runtime.enable")
            await cdp.send("Network.clearBrowserCookies")
            await cdp.send("Page.navigate", {"url": "about:blank"})
            await asyncio.sleep(0.4)
            await cdp.send("Page.navigate", {"url": APP + "/"})
            await asyncio.sleep(2)
            r = await cdp.send("Runtime.evaluate", {
                "expression": "document.querySelector('#app').innerText.replace(/\\s+/g,' ')",
                "returnByValue": True})
            t = r.get("result", {}).get("value", "")
            ok = "图维绩效管理平台" in t and "登 录" in t
            print(("✓ " if ok else "✗ ") + "未登录显示登录页")
            results.append(ok)
            for e in _errors:
                print("   " + e)

        tokens = {u: api_login(u) for u in ["zhouwenwen", "zhangsan", "chenyongsheng", "hr", "admin", "lisi", "sunhao"]}
        my = {t["task_no"]: t for t in api("GET", "/api/my/tasks")} if False else None

        # 动态取任务 ID（周文文的 9 月任务、王五的 Q3 任务）
        zw_task = None
        cj = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        req = urllib.request.Request(APP + "/api/login",
                                     data=json.dumps({"username": "zhouwenwen", "password": "Perf@2026"}).encode(),
                                     headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
                                     method="POST")
        op.open(req).read()
        for t in json.loads(op.open(urllib.request.Request(
                APP + "/api/my/tasks", headers={"X-Requested-With": "XMLHttpRequest"})).read())["data"]:
            if t["task_no"] == "TP2026090001":
                zw_task = t["id"]
        ww_q3 = q3["id"]
        sun_task = [t for t in api("GET", "/api/hr/tasks") if t["task_no"] == "TP2026110002"][0]

        results.append(await run_check(tokens["zhouwenwen"], "#/my/dashboard",
            ["我的工作台", "待填写自评", "评分进行中"], "员工-我的工作台"))
        results.append(await run_check(tokens["sunhao"], "#/my/dashboard",
            ["2026-11", "立即填写自评"], "员工-工作台待办入口"))
        results.append(await run_check(tokens["zhouwenwen"], "#/my/tasks",
            ["TP2026090001", "待评分", "自评截止"], "员工-我的任务"))
        results.append(await run_check(tokens["zhouwenwen"], "#/my/tasks/%d" % zw_task,
            ["业务目标设定及评估", "员工姓名", "直属主管", "100%目标值", "120%目标值",
             "数据来源", "评估结果", "员工自评", "加权自评总分", "员工确认签字"], "员工-自评表单已提交态"))
        results.append(await run_check(tokens["sunhao"], "#/my/tasks/%d" % sun_task["id"],
            ["目标/关键业务领域", "100%目标值", "120%目标值", "数据来源", "权重",
             "评估结果", "员工自评", "（0-120分）", "合计", "加权自评总分", "本期成果",
             "本人确认以上自评内容真实有效", "提交自评"], "员工-自评表单可编辑态",
            js_check="(() => { const n = document.querySelectorAll('.ind-name').length;"
                     " const c100 = document.querySelectorAll('.ind-100').length;"
                     " const c120 = document.querySelectorAll('.ind-120').length;"
                     " const src = document.querySelectorAll('.ind-src').length;"
                     " const ws = Array.from(document.querySelectorAll('.ind-w')).map(i => Number(i.value));"
                     " return n > 0 && n === c100 && n === c120 && n === src"
                     " && ws.length === n && ws.every(w => w >= 10 && w <= 60); })()"))
        results.append(await run_check(tokens["zhangsan"], "#/my/results",
            ["108.05", "奖金系数"], "员工-我的结果"))
        results.append(await run_check(tokens["chenyongsheng"], "#/supervisor/tasks",
            ["周文文", "待评分"], "主管-评分任务"))
        results.append(await run_check(tokens["chenyongsheng"], "#/supervisor/tasks/%d" % zw_task,
            ["员工自评", "主管评分（0-120 分）", "提交评分"], "主管-评分表单"))
        results.append(await run_check(tokens["hr"], "#/hr/overview",
            ["待自评", "快捷操作"], "HR-工作台"))
        results.append(await run_check(tokens["hr"], "#/hr/configs",
            ["周文文", "月度＋季度", "编辑"], "HR-考核配置"))
        results.append(await run_check(tokens["hr"], "#/hr/tasks",
            ["TP2026090001", "批量生成任务"], "HR-考核任务"))
        results.append(await run_check(tokens["hr"], "#/hr/scores",
            ["待HR核对", "待负责人审核"], "HR-评分审批"))
        results.append(await run_check(tokens["hr"], "#/hr/scores/%d" % m9["id"],
            ["HR 核对", "核对通过", "校准"], "HR-评分处理"))
        results.append(await run_check(tokens["chenyongsheng"], "#/hr/scores/%d" % q3["id"],
            ["最终审核", "审核通过", "退回修改"], "审核人-最终审核"))
        results.append(await run_check(tokens["hr"], "#/hr/results",
            ["108.05", "全公司发布记录"], "HR-结果发布"))
        results.append(await run_check(tokens["admin"], "#/admin/users",
            ["周文文", "重置密码"], "管理员-用户管理"))
        results.append(await run_check(tokens["admin"], "#/admin/settings",
            ["等级区间", "添加区间"], "管理员-等级规则",
            js_check="Array.from(document.querySelectorAll('.bgrade')).map(i=>i.value).join(',')"))
        results.append(await run_check(tokens["admin"], "#/admin/logs",
            ["操作人", "IP"], "管理员-审计日志"))
        results.append(await run_check(tokens["lisi"], "#/my/tasks",
            ["TP2026Q30001", "待自评"], "季度员工-我的任务"))

        # 交互：孙浩在自评表单中填写（含编辑指标字段）、勾选确认、签名并提交
        results.append(await fill_and_submit(tokens["sunhao"], sun_task["id"], "员工-填写并提交自评"))
        st = [t for t in api("GET", "/api/hr/tasks") if t["id"] == sun_task["id"]][0]
        ok_submit = st["status"] == "pending_score"
        print(("✓ " if ok_submit else "✗ ") + "提交后任务进入待评分  [" + st["status"] + "]")
        results.append(ok_submit)

        # 后端校验：员工编辑后的指标字段已保存
        cj3 = http.cookiejar.CookieJar()
        op3 = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj3))
        op3.open(urllib.request.Request(
            APP + "/api/login", data=json.dumps({"username": "sunhao", "password": "Perf@2026"}).encode(),
            headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
            method="POST")).read()
        det = json.loads(op3.open(urllib.request.Request(
            APP + "/api/my/tasks/%d" % sun_task["id"],
            headers={"X-Requested-With": "XMLHttpRequest"})).read())["data"]
        sa_items = det["self_assessment"]["items"]
        ok_saved = (sa_items[0]["name"].endswith("（测试修订）")
                    and sa_items[0]["standard_100"] == "测试100%衡量标准"
                    and sa_items[0]["data_source"] == "测试部门：测试文档")
        print(("✓ " if ok_saved else "✗ ") + "员工编辑的指标字段已保存至自评")
        results.append(ok_saved)
        # 主管侧看到员工版指标（HR 角色有权查看评分详情）
        cj4 = http.cookiejar.CookieJar()
        op4 = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj4))
        op4.open(urllib.request.Request(
            APP + "/api/login", data=json.dumps({"username": "hr", "password": "Perf@2026"}).encode(),
            headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
            method="POST")).read()
        sup = json.loads(op4.open(urllib.request.Request(
            APP + "/api/supervisor/tasks/%d" % sun_task["id"],
            headers={"X-Requested-With": "XMLHttpRequest"})).read())["data"]
        eff0 = (sup.get("effective_indicators") or [{}])[0]
        ok_eff = eff0.get("name", "").endswith("（测试修订）")
        print(("✓ " if ok_eff else "✗ ") + "主管评分页显示员工版指标  [" + str(eff0.get("name")) + "]")
        results.append(ok_eff)

        print()
        print("通过 %d / %d" % (sum(1 for r in results if r), len(results)))
    finally:
        proc.terminate()


asyncio.run(main())
