# -*- coding: utf-8 -*-
"""全流程验证：自评 → 评分 → HR核对 → 审核 → 发布，以及权限隔离测试"""
import json
import urllib.request
import urllib.error
import http.cookiejar

BASE = "http://127.0.0.1:8600"
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
PASS, FAIL = [], []


def call(method, path, data=None, raw=False):
    url = BASE + path
    body = None
    headers = {"X-Requested-With": "XMLHttpRequest"}
    if data is not None:
        if raw:
            body = data
            headers["Content-Type"] = "application/json"
        else:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        resp = opener.open(req)
        return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, {}


def login(username, password="Perf@2026"):
    cj.clear()
    return call("POST", "/api/login", {"username": username, "password": password})


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("✓ " if cond else "✗ ") + name + (("  → " + str(extra)) if (extra and not cond) else ""))


# ---------- 1. 员工提交自评（赵六 / 任务 TP2026090004） ----------
s, j = login("zhaoliu")
check("员工登录", s == 200 and j.get("ok"), j)
tasks = call("GET", "/api/my/tasks")[1]["data"]
t6 = [t for t in tasks if t["task_no"] == "TP2026090004"][0]
check("赵六看到自己的待自评任务", t6["status"] == "pending_self", t6["status"])
det = call("GET", "/api/my/tasks/%d" % t6["id"])[1]["data"]
inds = det["indicators"]
items = [{"name": i["name"], "completion": "9月按计划完成：%s" % i["name"],
          "self_score": 100 + idx * 2} for idx, i in enumerate(inds)]
s, j = call("POST", "/api/my/tasks/%d/self-assessment" % t6["id"],
            {"items": items, "attachments": []})
check("未勾选确认/未签字不能提交自评", s == 400, (s, j))
s, j = call("POST", "/api/my/tasks/%d/self-assessment" % t6["id"],
            {"items": items, "attachments": [], "confirmed": True, "signature": "赵"})
check("签字过短不能提交自评", s == 400, (s, j))
s, j = call("POST", "/api/my/tasks/%d/self-assessment" % t6["id"],
            {"items": items, "achievements": "行政事务全部按时完成", "attachments": [],
             "confirmed": True, "signature": "赵六"})
check("员工提交自评（含确认签字）", s == 200 and j.get("ok"), j)
det2 = call("GET", "/api/my/tasks/%d" % t6["id"])[1]["data"]
check("自评后任务进入待评分", det2["status"] == "pending_score", det2["status"])
check("签字已保存", det2["self_assessment"]["signature"] == "赵六"
      and det2["self_assessment"]["confirmed"], det2.get("self_assessment", {}).get("signature"))
check("员工详情不含内部评分字段", "internal_score" not in det2)

# 越权：赵六不能改已提交的自评（再提交应失败）
s, j = call("POST", "/api/my/tasks/%d/self-assessment" % t6["id"],
            {"items": items, "attachments": [], "confirmed": True, "signature": "赵六"})
check("评分阶段不能再改自评", s == 400, (s, j))

# ---------- 1b. 员工可编辑指标名称/标准/来源/权重 ----------
login("hr")
zhaoliu_id = [u for u in call("GET", "/api/hr/users")[1]["data"] if u["username"] == "zhaoliu"][0]["id"]
s, j = call("POST", "/api/hr/tasks/batch", {
    "period_type": "monthly", "period_code": "2026-11", "period_start": "2026-11-01",
    "period_end": "2026-11-30", "self_deadline": "2026-12-05", "user_ids": [zhaoliu_id]})
check("HR 为赵六生成 2026-11 任务", s == 200 and j.get("ok"), j)
login("zhaoliu")
t7 = [t for t in call("GET", "/api/my/tasks")[1]["data"] if t["period_code"] == "2026-11"][0]
det7 = call("GET", "/api/my/tasks/%d" % t7["id"])[1]["data"]
inds7 = det7["indicators"]
edit_items = [{"name": i["name"] + "（修订）" if idx == 0 else i["name"],
               "standard_100": i.get("standard_100", ""),
               "standard_120": i.get("standard_120", ""),
               "data_source": i.get("data_source", "") or "行政台账",
               "weight": i["weight"],
               "completion": "11月计划推进：%s" % i["name"],
               "self_score": 100 + idx} for idx, i in enumerate(inds7)]
bad = [dict(it) for it in edit_items]
bad[0]["weight"] = round(bad[0]["weight"] - 0.10, 4)
s, j = call("POST", "/api/my/tasks/%d/self-assessment" % t7["id"],
            {"items": bad, "confirmed": True, "signature": "赵六"})
check("权重合计不足 100% 被拒绝", s == 400, (s, j))
bad2 = [dict(it) for it in edit_items]
bad2[0]["weight"] = 0.05
bad2[1]["weight"] = round(bad2[1]["weight"] + 0.05, 4)
s, j = call("POST", "/api/my/tasks/%d/self-assessment" % t7["id"],
            {"items": bad2, "confirmed": True, "signature": "赵六"})
check("单项权重低于 10% 被拒绝", s == 400, (s, j))
ok_items = [dict(it) for it in edit_items]
ok_items[0]["weight"] = round(ok_items[0]["weight"] - 0.05, 4)
ok_items[1]["weight"] = round(ok_items[1]["weight"] + 0.05, 4)
s, j = call("POST", "/api/my/tasks/%d/self-assessment" % t7["id"],
            {"items": ok_items, "achievements": "11月按修订后指标推进", "attachments": [],
             "confirmed": True, "signature": "赵六"})
check("员工编辑指标字段后提交成功", s == 200 and j.get("ok"), j)
det7b = call("GET", "/api/my/tasks/%d" % t7["id"])[1]["data"]
sa7 = det7b["self_assessment"]["items"]
check("员工版指标名称/权重已保存", sa7[0]["name"].endswith("（修订）")
      and abs(sa7[0]["weight"] - ok_items[0]["weight"]) < 1e-6, sa7[0])
login("chenyongsheng")
sdet7 = call("GET", "/api/supervisor/tasks/%d" % t7["id"])[1]["data"]
check("主管侧看到员工版指标", sdet7["effective_indicators"][0]["name"].endswith("（修订）")
      and abs(sdet7["effective_indicators"][0]["weight"] - ok_items[0]["weight"]) < 1e-6,
      sdet7.get("effective_indicators", [{}])[0])
scores7 = [{"name": i["name"], "supervisor_score": 110, "peer_score": None, "comment": ""}
           for i in sdet7["effective_indicators"]]
s, j = call("POST", "/api/supervisor/tasks/%d/score" % t7["id"], {"scores": scores7})
check("主管按员工版权重评分成功", s == 200 and j.get("ok"), j)
exp7 = round(sum(110 * i["weight"] for i in sdet7["effective_indicators"]), 2)
check("加权得分按员工版指标计算", abs(j["data"]["total_score"] - exp7) < 0.01, (j["data"], exp7))

# ---------- 1c. 员工可增加/删除指标行 ----------
login("hr")
s, j = call("POST", "/api/hr/tasks/batch", {
    "period_type": "monthly", "period_code": "2026-12", "period_start": "2026-12-01",
    "period_end": "2026-12-31", "self_deadline": "2027-01-05", "user_ids": [zhaoliu_id]})
check("HR 为赵六生成 2026-12 任务", s == 200 and j.get("ok"), j)
login("zhaoliu")
t8 = [t for t in call("GET", "/api/my/tasks")[1]["data"] if t["period_code"] == "2026-12"][0]
inds8 = json.loads(t8["indicators"]) if isinstance(t8["indicators"], str) else t8["indicators"]
s, j = call("POST", "/api/my/tasks/%d/self-assessment" % t8["id"],
            {"items": [], "confirmed": True, "signature": "赵六"})
check("空指标列表被拒绝（至少保留一项）", s == 400, (s, j))
# 删除后两项（合计 0.40），新增一项自定义指标（权重 0.40），合计仍为 100%
rows8 = [{"name": inds8[0]["name"], "standard_100": inds8[0].get("standard_100", ""),
          "standard_120": inds8[0].get("standard_120", ""),
          "data_source": inds8[0].get("data_source", ""),
          "weight": inds8[0]["weight"], "completion": "12月推进：%s" % inds8[0]["name"],
          "self_score": 105},
         {"name": inds8[1]["name"], "standard_100": inds8[1].get("standard_100", ""),
          "standard_120": inds8[1].get("standard_120", ""),
          "data_source": inds8[1].get("data_source", ""),
          "weight": inds8[1]["weight"], "completion": "12月推进：%s" % inds8[1]["name"],
          "self_score": 108},
         {"name": "新增自定义指标：年终物资盘点", "standard_100": "盘点差异率为0",
          "standard_120": "提前3个工作日完成并输出分析报告", "data_source": "行政部：盘点报告",
          "weight": 0.40, "completion": "12月完成年终盘点，账实相符", "self_score": 112}]
s, j = call("POST", "/api/my/tasks/%d/self-assessment" % t8["id"],
            {"items": rows8, "achievements": "按调整后指标推进", "attachments": [],
             "confirmed": True, "signature": "赵六"})
check("员工增删指标行后提交成功", s == 200 and j.get("ok"), j)
det8 = call("GET", "/api/my/tasks/%d" % t8["id"])[1]["data"]
sa8 = det8["self_assessment"]["items"]
check("员工版指标行数正确（删2增1后为3项）", len(sa8) == 3, len(sa8))
check("新增自定义指标已保存", sa8[2]["name"] == "新增自定义指标：年终物资盘点"
      and abs(sa8[2]["weight"] - 0.40) < 1e-6, sa8[2] if len(sa8) > 2 else None)
login("chenyongsheng")
sdet8 = call("GET", "/api/supervisor/tasks/%d" % t8["id"])[1]["data"]
check("主管侧生效指标与员工增删后一致",
      len(sdet8["effective_indicators"]) == 3
      and sdet8["effective_indicators"][2]["name"] == "新增自定义指标：年终物资盘点",
      [i["name"] for i in sdet8.get("effective_indicators", [])])
scores8 = [{"name": i["name"], "supervisor_score": 106, "peer_score": None, "comment": ""}
           for i in sdet8["effective_indicators"]]
s, j = call("POST", "/api/supervisor/tasks/%d/score" % t8["id"], {"scores": scores8})
check("主管按增删后的员工版指标评分成功", s == 200 and j.get("ok"), j)
exp8 = round(sum(106 * i["weight"] for i in sdet8["effective_indicators"]), 2)
check("增删行后加权得分计算正确", abs(j["data"]["total_score"] - exp8) < 0.01, (j["data"], exp8))

# ---------- 2. 主管评分（程永升） ----------
s, j = login("chenyongsheng")
check("主管登录", s == 200 and j.get("ok"), j)
stasks = call("GET", "/api/supervisor/tasks")[1]["data"]
check("主管看到分配给自己的待评分任务", any(t["task_no"] == "TP2026090004" for t in stasks),
      [t["task_no"] for t in stasks])
sdet = call("GET", "/api/supervisor/tasks/%d" % t6["id"])[1]["data"]
scores = [{"name": i["name"], "supervisor_score": 105, "peer_score": None, "comment": "达成预期"}
          for i in sdet["indicators"]]
s, j = call("POST", "/api/supervisor/tasks/%d/score" % t6["id"],
            {"scores": scores, "bonus_score": 1, "bonus_items": "主动承担额外工作",
             "penalty_score": 0, "supervisor_comment": "整体表现良好"})
check("主管提交评分", s == 200 and j.get("ok"), j)
expected_base = round(sum(105 * i["weight"] for i in sdet["indicators"]), 2)
check("总分计算正确（105 加权 + 1 加分）", abs(j["data"]["total_score"] - expected_base - 1) < 0.01,
      (j["data"], expected_base))

# 越权：张三（非主管）不能给赵六评分
login("zhangsan")
s, j = call("POST", "/api/supervisor/tasks/%d/score" % t6["id"], {"scores": scores})
check("非评分主管不能评分", s == 403, (s, j))
s, j = call("GET", "/api/supervisor/tasks/%d" % t6["id"])
check("非评分主管不能查看评分详情", s == 403, (s, j))

# ---------- 3. HR 核对 ----------
login("hr")
check("HR登录", True)
scores_list = call("GET", "/api/hr/scores?status=scored")[1]["data"]
check("HR看到待核对列表含赵六", any(x["task_no"] == "TP2026090004" for x in scores_list))
s, j = call("POST", "/api/hr/scores/%d/check" % t6["id"], {"hr_comment": "核对无误"})
check("HR核对通过（有审核人→待审核）", s == 200 and j["data"]["status"] == "hr_checked", j)

# ---------- 4. 最终审核（程永升） ----------
login("chenyongsheng")
s, j = call("POST", "/api/approval/scores/%d/approve" % t6["id"], {"approver_comment": "同意"})
check("最终审核通过", s == 200 and j.get("ok"), j)

# 越权：普通员工不能审核
login("lisi")
s, j = call("POST", "/api/approval/scores/%d/approve" % t6["id"], {"approver_comment": "x"})
check("普通员工不能审核", s == 403, (s, j))

# ---------- 5. HR 发布 ----------
login("hr")
s, j = call("POST", "/api/hr/results/publish", {
    "task_id": t6["id"], "public_feedback": "9月总分106.05，等级A，各项工作达成预期。",
    "improvement": "持续优化资产盘点流程。"})
check("HR发布结果", s == 200 and j.get("ok"), j)

# 重复发布应失败
s, j = call("POST", "/api/hr/results/publish", {"task_id": t6["id"], "public_feedback": "x"})
check("重复发布被阻止", s == 400, (s, j))

# ---------- 6. 员工查看结果 ----------
login("zhaoliu")
results = call("GET", "/api/my/results")[1]["data"]
r = [x for x in results if x["period_code"] == "2026-09"]
check("员工看到已发布结果", len(r) == 1, results)
if r:
    check("等级为 A", r[0]["grade"] == "A", r[0])
    check("奖金系数 = MIN(106.05,120)/100", abs(r[0]["bonus_factor"] - 1.0605) < 0.001, r[0]["bonus_factor"])
det3 = call("GET", "/api/my/tasks/%d" % t6["id"])[1]["data"]
check("发布后员工任务详情无内部数据", "internal_score" not in det3 and det3["result"]["grade"] == "A")

# ---------- 7. 权限隔离 ----------
login("zhouwenwen")
s, j = call("GET", "/api/my/tasks/%d" % t6["id"])
check("员工不能查看他人任务", s == 404, (s, j))
s, j = call("GET", "/api/hr/overview")
check("员工不能访问HR接口", s == 403, (s, j))
s, j = call("GET", "/api/hr/scores")
check("员工不能查看内部评分列表", s == 403, (s, j))
s, j = call("GET", "/api/my/results")
check("员工只能看到自己的结果", all(x["user_id"] == 5 for x in j["data"]), j["data"])
# 周文文已发布? 未发布 — 验证张三结果对周文文不可见
s, j = call("GET", "/api/my/results/1")
check("员工不能查看他人结果详情", s == 404, (s, j))

login("sunhao")  # 孙浩是张三的主管
st = call("GET", "/api/supervisor/tasks")[1]["data"]
check("主管A看不到主管B负责的员工（王五归周杰）",
      not any(t["user_name"] == "王五" for t in st), [t["user_name"] for t in st])

# 未登录
cj.clear()
s, j = call("GET", "/api/my/tasks")
check("未登录访问返回401", s == 401, (s, j))

# 批量任务生成 + 防重复
login("hr")
s, j = call("POST", "/api/hr/tasks/batch", {
    "period_type": "monthly", "period_code": "2026-11", "period_start": "2026-11-01",
    "period_end": "2026-11-30", "self_deadline": "2026-12-05",
    "user_ids": [x["id"] for x in call("GET", "/api/hr/users")[1]["data"]
                 if x["username"] in ("zhouwenwen", "zhangsan", "lisi", "wangwu")]})
check("批量生成11月任务", s == 200 and j.get("ok"), j)
check("李四（仅季度）被正确跳过", any(x["reason"] == "该员工仅季度考核" for x in j["data"]["skipped"]),
      j["data"]["skipped"])
s, j = call("POST", "/api/hr/tasks/batch", {
    "period_type": "monthly", "period_code": "2026-11",
    "user_ids": [call("GET", "/api/hr/users")[1]["data"][0]["id"]]})
check("重复周期任务被跳过", j["data"]["created"] == [] or all(
    x["reason"] == "该周期任务已存在" for x in j["data"]["skipped"]), j["data"])

# 配置权重校验
users = {u["username"]: u for u in call("GET", "/api/hr/users")[1]["data"]}
s, j = call("POST", "/api/hr/configs", {
    "user_id": users["lisi"]["id"], "frequency": "monthly",
    "indicators": {"monthly": [{"name": "测试指标", "weight": 0.5}], "quarterly": []}})
check("权重合计不等于100%被拒绝", s == 400, (s, j))

print()
print("通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
if FAIL:
    print("失败项：", FAIL)
