# -*- coding: utf-8 -*-
"""种子数据：周文文 2026-09 真实实例 + 演示账号与全流程状态样例
用法：python seed.py          （仅空库时初始化）
      python seed.py --reset  （清空后重新初始化）
"""
import json
import sys

from app import DEFAULT_BANDS, app, bonus_factor, calc_base_score, grade_of, hash_password
from db import execute, init_db, query_all, query_one

DEFAULT_PW = "Perf@2026"

ZHOU_INDICATORS = [
    {"name": "人事合规与全周期流程管理",
     "standard_100": "1.劳动合同签订与管理；2.组织架构调整与人员任命；3.晋升确认流程规范。",
     "standard_120": "1.劳动合同签订零差错；2.架构调整方案提前输出并获审批，任命公告及时发布，过渡期人员安排零混乱；3.薪资协议确认流程规范、审批完整无遗漏，嘉奖发放及时。",
     "data_source": "公示记录、征询意见、生效文件", "weight": 0.15},
    {"name": "招聘执行与人才质量",
     "standard_100": "1.招聘及时率≥90%，试用期留存率≥80%；2.简历筛选与面试对接无遗漏。",
     "standard_120": "1.招聘及时率≥95%，留存率≥85%，人才入职3个月贡献度评估达标率≥80%；2.建立岗位人才画像/简单人才库。",
     "data_source": "招聘系统、试用期考核记录", "weight": 0.20},
    {"name": "培训组织与落地",
     "standard_100": "1.完成 2 场培训（制度+入职/技能），培训参与率≥85%；2.核心内容认知通过率≥75%；3.培训记录完整归档。",
     "standard_120": "1.完成 3 场培训（制度+入职/技能），培训参与率≥95%；2.核心内容认知通过率≥85%。",
     "data_source": "培训签到表、考核成绩、满意度调研", "weight": 0.15},
    {"name": "绩效流程管理",
     "standard_100": "1.当月绩效考核按时完成率100%，无逾期、漏算情况；2.完成绩效数据汇总与初步核对，确保评分合理，数据准确。",
     "standard_120": "1.绩效考核提前 1 个工作日完成，流程零失误；2.输出绩效流程简易优化建议（1-2条），适配部门工作节奏。",
     "data_source": "绩效考核系统、绩效数据核对表", "weight": 0.20},
    {"name": "沟通与员工体验",
     "standard_100": "1.及时响应员工基础咨询/问题，响应时效≤4小时，解决率≥80%；2.搭建多元化沟通渠道（如定期座谈会等）。",
     "standard_120": "1.响应员工基础咨询/问题，响应时效≤4小时，解决率≥90%；2.搭建多元化沟通渠道并响应提出方案。",
     "data_source": "谈话记录表", "weight": 0.15},
    {"name": "人事实务",
     "standard_100": "1.考勤绩效统计：每月2号前完成全月考勤、绩效数据核算，数据准确率100%，无漏算、错算；2.入离职管理：入离职当日100%完成手续办理，流程合规，零劳动纠纷；3.社保、公积金按时足额缴纳，及时率100%。",
     "standard_120": "1.考勤绩效统计每月1号前完成，准确率100%，同步输出考勤异常分析报表；2.入离职手续办理时效压缩至半天内，零差错，同步完成入职引导、离职面谈，满意度≥95%；3.整理输出事务流程SOP。",
     "data_source": "考勤统计表、绩效统计表、入离职档案、社保公积金增减记录、补贴申请台账", "weight": 0.15},
]

ZHOU_SELF_ITEMS = [
    {"completion": "1.新签劳动合同：刘子琦、陈龙和巢晓亮；续签劳动合同：梁宝中和刘宏；晋升合同变更：丁鹏程，签订率100%；续签提醒提前30天完成，合同条款审核零差错。2.架构调整方案提前输出并获审批，任命公告及时发布，过渡期人员安排零混乱。3.研发部、生产部晋升确认流程规范、审批完整无遗漏。", "self_score": 110},
    {"completion": "1、招聘及时率：市场部销售负责人发出offer 1份，确认入职1人，10月8日入职；研发部核苷工程师发出offer 1份，确认入职1人；研发部生物工程师助理发出offer 2份，确认入职2人；研发部自动化工程师发出offer 2份，确认入职2人；生产部工程师发出offer 1份，确认入职1人，均10月8日入职。2、招聘中HC：5个岗位。3、严格执行员工入职前背调、入职后续定期访谈。", "self_score": 120},
    {"completion": "1、培训场次：本月共培训2场次（入职+制度）；2、培训参与和满意度良好；3、培训课件、签到记录等完整归档。", "self_score": 100},
    {"completion": "1、9月月度考核完成率100%，无逾期、漏算情况；2、绩效数据汇总数据准确无误；3、跟踪生产订单事故的调查及责任分配，并将其纳入当月绩效考核。", "self_score": 108},
    {"completion": "1、针对员工制度咨询、班次咨询、工作中的摩擦等及时响应；2、生产部、研发部临时调班及综合管理部《IT维修单》《工程验收单》审批流程设置等事项，响应时效≤1小时，解决率≥100%；3、定期与新老员工交流（入职一周、1个月、一年访谈）。", "self_score": 110},
    {"completion": "1.考勤绩效统计：每月1号前完成全月考勤、绩效数据核算，数据准确率100%，无漏算、错算；2.基础事务合规：社保、公积金、商保按时足额缴纳，缴纳及时率100%，无断缴、错缴；3.入职管理：入职手续办理时效压缩至半天内，流程零差错，同步完成新人入职引导，档案信息完整准确；4.整理入职指南一份，用于新员工入职流程更加顺畅。", "self_score": 110},
]

DEMO_INDICATORS = {
    "zhangsan_monthly": [
        {"name": "订单签约", "standard_100": "月度新签订单≥3单，合同额≥100万", "standard_120": "月度新签订单≥4单，合同额≥130万", "data_source": "CRM系统、合同台账", "weight": 0.30},
        {"name": "回款管理", "standard_100": "月度回款率≥90%，逾期账款清零", "standard_120": "月度回款率≥95%，提前回收2笔以上", "data_source": "财务系统、银行流水", "weight": 0.25},
        {"name": "客户推进", "standard_100": "重点客户拜访≥8次，商机转化率≥30%", "standard_120": "重点客户拜访≥10次，商机转化率≥40%", "data_source": "CRM拜访记录", "weight": 0.25},
        {"name": "团队协作", "standard_100": "跨部门协作事项按时响应率100%", "standard_120": "主动输出协作优化建议1条以上", "data_source": "协作平台记录", "weight": 0.20},
    ],
    "lisi_quarterly": [
        {"name": "项目里程碑", "standard_100": "负责模块按计划交付，里程碑达成率100%", "standard_120": "提前1周交付且零缺陷", "data_source": "项目管理系统", "weight": 0.35},
        {"name": "研发质量", "standard_100": "实验记录完整率100%，数据可追溯", "standard_120": "一次通过率≥95%，无返工", "data_source": "实验记录本、QA检查", "weight": 0.30},
        {"name": "技术文档与分享", "standard_100": "季度输出技术文档≥2份，分享≥1次", "standard_120": "文档≥3份，分享≥2次并形成SOP", "data_source": "文档平台", "weight": 0.20},
        {"name": "合规与安全", "standard_100": "EHS合规零事故，危化品管理规范", "standard_120": "主动排查隐患≥2项并闭环", "data_source": "EHS检查表", "weight": 0.15},
    ],
    "wangwu_monthly": [
        {"name": "设备运行", "standard_100": "设备故障停机≤4小时，OEE≥85%", "standard_120": "零故障停机，OEE≥90%", "data_source": "设备管理系统", "weight": 0.35},
        {"name": "维护保养", "standard_100": "保养计划执行率100%，记录完整", "standard_120": "预测性维护落地1项以上", "data_source": "保养工单", "weight": 0.30},
        {"name": "安全管理", "standard_100": "安全隐患整改及时率100%", "standard_120": "零隐患遗留，主动培训1次", "data_source": "安全检查表", "weight": 0.20},
        {"name": "跨部门支持", "standard_100": "生产支持响应≤2小时", "standard_120": "支持满意度≥95%", "data_source": "工单系统", "weight": 0.15},
    ],
    "wangwu_quarterly": [
        {"name": "技改项目", "standard_100": "季度技改项目按计划完成率100%", "standard_120": "提前完成且效益达标", "data_source": "项目报告", "weight": 0.40},
        {"name": "备件与成本", "standard_100": "备件库存周转达标，维修成本≤预算", "standard_120": "成本节约≥5%", "data_source": "ERP", "weight": 0.30},
        {"name": "团队培训", "standard_100": "季度培训≥2次，覆盖率100%", "standard_120": "认证考核通过率≥90%", "data_source": "培训记录", "weight": 0.30},
    ],
    "zhaoliu_monthly": [
        {"name": "行政事务", "standard_100": "办公保障及时率100%，投诉≤1次", "standard_120": "零投诉，主动优化流程1项", "data_source": "行政台账", "weight": 0.30},
        {"name": "资产与采购", "standard_100": "资产账实相符率100%，采购按时交付≥95%", "standard_120": "采购成本节约≥3%", "data_source": "资产系统", "weight": 0.30},
        {"name": "会务与接待", "standard_100": "会务支持零失误", "standard_120": "接待满意度≥95%", "data_source": "会务记录", "weight": 0.20},
        {"name": "后勤服务", "standard_100": "员工后勤问题响应≤4小时", "standard_120": "响应≤1小时，解决率≥95%", "data_source": "服务台账", "weight": 0.20},
    ],
    "hr_monthly": [
        {"name": "人事合规与全周期流程管理", "standard_100": "劳动合同签订与管理零差错；组织架构调整与人员任命流程规范", "standard_120": "合同签订零差错，架构调整提前输出并获审批，任命公告及时发布", "data_source": "公示记录、生效文件", "weight": 0.25},
        {"name": "招聘执行与人才质量", "standard_100": "招聘及时率≥90%，试用期留存率≥80%", "standard_120": "招聘及时率≥95%，留存率≥85%，建立岗位人才画像", "data_source": "招聘系统、试用期考核记录", "weight": 0.25},
        {"name": "绩效流程管理", "standard_100": "当期绩效考核按时完成率100%，数据汇总准确", "standard_120": "考核提前完成且零失误，输出流程优化建议", "data_source": "绩效考核系统、数据核对表", "weight": 0.20},
        {"name": "员工关系与沟通", "standard_100": "员工咨询响应≤4小时，解决率≥80%", "standard_120": "响应≤1小时，解决率≥95%，定期访谈全覆盖", "data_source": "谈话记录表", "weight": 0.15},
        {"name": "人事实务", "standard_100": "考勤绩效数据准确率100%，入离职手续当日办结", "standard_120": "手续办理压缩至半天内，零劳动纠纷", "data_source": "考勤统计表、入离职档案", "weight": 0.15},
    ],
    "sunhao_monthly": [
        {"name": "销售目标达成", "standard_100": "月度销售额≥300万，回款率≥90%", "standard_120": "月度销售额≥360万，回款率≥95%", "data_source": "CRM、财务系统", "weight": 0.35},
        {"name": "客户开发与维护", "standard_100": "新客户开发≥3家，老客户复购率≥80%", "standard_120": "新客户≥5家，复购率≥90%", "data_source": "CRM客户档案", "weight": 0.25},
        {"name": "团队管理", "standard_100": "团队例会按时召开，下属指标达成率≥85%", "standard_120": "下属达成率≥95%，输出培养计划", "data_source": "例会纪要、考核数据", "weight": 0.20},
        {"name": "市场信息反馈", "standard_100": "月度竞品与市场报告≥1份", "standard_120": "报告≥2份且被产品部门采纳", "data_source": "市场报告", "weight": 0.20},
    ],
    "zhaokai_monthly": [
        {"name": "项目交付", "standard_100": "在研项目按计划推进，里程碑达成率≥90%", "standard_120": "里程碑达成率100%，关键节点提前", "data_source": "项目管理系统", "weight": 0.30},
        {"name": "研发质量", "standard_100": "实验记录完整率100%，数据可追溯", "standard_120": "一次通过率≥95%，无返工", "data_source": "实验记录本、QA检查", "weight": 0.25},
        {"name": "技术文档与分享", "standard_100": "月度输出技术文档≥1份，分享≥1次", "standard_120": "文档≥2份并形成SOP", "data_source": "文档平台", "weight": 0.20},
        {"name": "团队与合规", "standard_100": "EHS合规零事故，实验安全管理规范", "standard_120": "主动排查隐患≥2项并闭环", "data_source": "EHS检查表", "weight": 0.25},
    ],
    "zhoujie_monthly": [
        {"name": "生产计划达成", "standard_100": "月度生产计划完成率≥95%，交付及时率≥98%", "standard_120": "完成率100%，提前交付≥2批", "data_source": "MES、生产报表", "weight": 0.35},
        {"name": "质量与安全", "standard_100": "批次合格率≥99%，安全事故零发生", "standard_120": "合格率≥99.5%，隐患整改闭环率100%", "data_source": "质检记录、安全检查表", "weight": 0.30},
        {"name": "现场与成本", "standard_100": "现场5S检查达标，物料损耗≤预算", "standard_120": "损耗节约≥3%，5S评为标杆", "data_source": "5S检查表、成本报表", "weight": 0.20},
        {"name": "团队与梯队", "standard_100": "岗位培训覆盖率100%，多能工达标", "standard_120": "关键岗位后备≥2人", "data_source": "培训记录", "weight": 0.15},
    ],
}

USERS = [
    # username, name, position, department, role, approver, supervisor_username
    ("admin", "系统管理员", "信息技术", "信息技术部", "admin", 0, None),
    ("hr", "韩梅", "人事", "综合管理部", "hr", 0, "chenyongsheng"),
    ("chenyongsheng", "程永升", "总监", "综合管理部", "employee", 1, None),
    ("zhouwenwen", "周文文", "人事", "综合管理部", "employee", 0, "chenyongsheng"),
    ("zhaoliu", "赵六", "行政专员", "综合管理部", "employee", 0, "chenyongsheng"),
    ("sunhao", "孙浩", "销售经理", "市场部", "employee", 0, "chenyongsheng"),
    ("zhangsan", "张三", "销售代表", "市场部", "employee", 0, "sunhao"),
    ("zhaokai", "赵凯", "研发经理", "研发部", "employee", 0, "chenyongsheng"),
    ("lisi", "李四", "生物工程师", "研发部", "employee", 0, "zhaokai"),
    ("zhoujie", "周杰", "生产经理", "生产部", "employee", 0, "chenyongsheng"),
    ("wangwu", "王五", "设备工程师", "生产部", "employee", 0, "zhoujie"),
]

CONFIGS = [
    # username, frequency, monthly_sup, quarterly_sup, indicators
    ("zhouwenwen", "monthly", "chenyongsheng", None, {"monthly": ZHOU_INDICATORS, "quarterly": []}),
    ("zhaoliu", "monthly", "chenyongsheng", None, {"monthly": DEMO_INDICATORS["zhaoliu_monthly"], "quarterly": []}),
    ("zhangsan", "monthly", "sunhao", None, {"monthly": DEMO_INDICATORS["zhangsan_monthly"], "quarterly": []}),
    ("lisi", "quarterly", None, "zhaokai", {"monthly": [], "quarterly": DEMO_INDICATORS["lisi_quarterly"]}),
    ("wangwu", "both", "zhoujie", "zhoujie", {"monthly": DEMO_INDICATORS["wangwu_monthly"], "quarterly": DEMO_INDICATORS["wangwu_quarterly"]}),
    ("hr", "monthly", "chenyongsheng", None, {"monthly": DEMO_INDICATORS["hr_monthly"], "quarterly": []}),
    ("sunhao", "monthly", "chenyongsheng", None, {"monthly": DEMO_INDICATORS["sunhao_monthly"], "quarterly": []}),
    ("zhaokai", "monthly", "chenyongsheng", None, {"monthly": DEMO_INDICATORS["zhaokai_monthly"], "quarterly": []}),
    ("zhoujie", "monthly", "chenyongsheng", None, {"monthly": DEMO_INDICATORS["zhoujie_monthly"], "quarterly": []}),
]


def uid(username):
    return query_one("SELECT id FROM users WHERE username=?", (username,))["id"]


def add_indicators(config_id, period_type, indicators):
    for i, ind in enumerate(indicators):
        execute("INSERT INTO config_indicators (config_id, period_type, name, standard_100, "
                "standard_120, data_source, weight, sort_order) VALUES (?,?,?,?,?,?,?,?)",
                (config_id, period_type, ind["name"], ind["standard_100"], ind["standard_120"],
                 ind["data_source"], ind["weight"], i))


def snapshot_of(config_id, period_type):
    rows = []
    for r in query_all("SELECT * FROM config_indicators WHERE config_id=? AND period_type=? "
                       "ORDER BY sort_order", (config_id, period_type)):
        rows.append({"name": r["name"], "standard_100": r["standard_100"],
                     "standard_120": r["standard_120"], "data_source": r["data_source"],
                     "weight": r["weight"]})
    return rows


def create_task(task_no, username, period_type, period_code, start, end, deadline,
                supervisor, status, created_by="hr"):
    config_id = query_one("SELECT id FROM assessment_configs WHERE user_id=?", (uid(username),))["id"]
    snap = json.dumps(snapshot_of(config_id, period_type), ensure_ascii=False)
    tid = execute(
        "INSERT INTO assessment_tasks (task_no, user_id, period_type, period_code, period_start, "
        "period_end, self_deadline, supervisor_id, final_approver_id, indicators, status, created_by, "
        "updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'))",
        (task_no, uid(username), period_type, period_code, start, end, deadline,
         uid(supervisor) if supervisor else None, uid("chenyongsheng"), snap, status, uid(created_by)))
    return tid


def save_self(task_id, username, items, achievements="", unfinished="", support="",
              signature=None, confirmed=1):
    snap = json.loads(query_one("SELECT indicators FROM assessment_tasks WHERE id=?", (task_id,))["indicators"])
    payload = []
    for it, ind in zip(items, snap):
        payload.append({"name": it["name"],
                        "standard_100": it.get("standard_100") or ind.get("standard_100", ""),
                        "standard_120": it.get("standard_120") or ind.get("standard_120", ""),
                        "data_source": it.get("data_source") or ind.get("data_source", ""),
                        "weight": it["weight"], "completion": it["completion"],
                        "self_score": it["self_score"]})
    execute("INSERT INTO self_assessments (task_id, user_id, items, achievements, "
            "unfinished_reason, support_needed, attachments, signature, confirmed, status, "
            "submitted_at) VALUES (?,?,?,?,?,?,?,?,?,'submitted',datetime('now','localtime'))",
            (task_id, uid(username), json.dumps(payload, ensure_ascii=False),
             achievements, unfinished, support, "[]", signature, confirmed))


def save_score(task_id, username, score_map, comments=None, bonus=0, bonus_items="",
               penalty=0, penalty_items="", suggested="", sup_comment="", status="scored"):
    task = query_one("SELECT * FROM assessment_tasks WHERE id=?", (task_id,))
    snap = json.loads(task["indicators"])
    scores = []
    for ind in snap:
        scores.append({"name": ind["name"], "weight": ind["weight"],
                       "supervisor_score": score_map[ind["name"]],
                       "peer_score": None,
                       "comment": (comments or {}).get(ind["name"], "")})
    base = calc_base_score(snap, score_map)
    total = round(base + bonus + penalty, 2)
    execute("INSERT INTO internal_scores (task_id, user_id, scores, bonus_items, bonus_score, "
            "penalty_items, penalty_score, suggested_grade, supervisor_comment, base_score, "
            "total_score, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (task_id, uid(username), json.dumps(scores, ensure_ascii=False), bonus_items, bonus,
             penalty_items, penalty, suggested or grade_of(total, DEFAULT_BANDS), sup_comment,
             base, total, status))
    return base, total


def publish(task_id, username, public_feedback, improvement):
    task = query_one("SELECT * FROM assessment_tasks WHERE id=?", (task_id,))
    isc = query_one("SELECT * FROM internal_scores WHERE task_id=?", (task_id,))
    items = [{"name": s["name"], "weight": s["weight"], "score": s["supervisor_score"],
              "weighted": round(float(s["supervisor_score"]) * float(s["weight"]), 2)}
             for s in json.loads(isc["scores"])]
    grade = grade_of(isc["total_score"], DEFAULT_BANDS)
    execute("INSERT INTO published_results (task_id, user_id, period_type, period_code, items, "
            "base_score, bonus_score, penalty_score, total_score, grade, public_feedback, "
            "improvement, bonus_factor, published_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (task_id, uid(username), task["period_type"], task["period_code"],
             json.dumps(items, ensure_ascii=False), isc["base_score"], isc["bonus_score"],
             isc["penalty_score"], isc["total_score"], grade, public_feedback, improvement,
             bonus_factor(isc["total_score"]), uid("hr")))
    execute("UPDATE internal_scores SET status='published' WHERE task_id=?", (task_id,))
    execute("UPDATE assessment_tasks SET status='published' WHERE id=?", (task_id,))


def seed(reset=False):
    init_db(app)
    if query_one("SELECT id FROM users WHERE username='admin'"):
        if not reset:
            print("数据库已初始化，如需重置请运行：python seed.py --reset")
            return
        import sqlite3
        from db import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        for t in ("published_results", "internal_scores", "self_assessments",
                  "assessment_tasks", "config_indicators", "assessment_configs",
                  "notifications", "audit_logs", "sessions", "users"):
            conn.execute("DELETE FROM %s" % t)
        conn.commit()
        conn.close()
        print("已清空旧数据")

    # 用户（先建账号，再绑定上下级，避免顺序依赖）
    for username, name, position, dept, role, approver, sup in USERS:
        execute("INSERT INTO users (username, password_hash, name, position, department, "
                "role, is_final_approver, must_change_password) VALUES (?,?,?,?,?,?,?,0)",
                (username, hash_password(DEFAULT_PW), name, position, dept, role, approver))
    for username, name, position, dept, role, approver, sup in USERS:
        if sup:
            execute("UPDATE users SET supervisor_id=? WHERE username=?",
                    (uid(sup), username))

    # 考核配置
    for username, freq, msup, qsup, indicators in CONFIGS:
        cid = execute("INSERT INTO assessment_configs (user_id, frequency, monthly_supervisor_id, "
                      "quarterly_supervisor_id, final_approver_id, effective_date, participate, "
                      "created_by) VALUES (?,?,?,?,?, '2026-01-01', 1, ?)",
                      (uid(username), freq, uid(msup) if msup else None,
                       uid(qsup) if qsup else None, uid("chenyongsheng"), uid("hr")))
        if indicators["monthly"]:
            add_indicators(cid, "monthly", indicators["monthly"])
        if indicators["quarterly"]:
            add_indicators(cid, "quarterly", indicators["quarterly"])

    # 任务 1：周文文 2026-09 月度（真实数据，已自评待评分）
    t1 = create_task("TP2026090001", "zhouwenwen", "monthly", "2026-09",
                     "2026-09-01", "2026-09-30", "2026-10-10", "chenyongsheng", "pending_score")
    snap1 = json.loads(query_one("SELECT indicators FROM assessment_tasks WHERE id=?", (t1,))["indicators"])
    items1 = [dict(name=ind["name"], weight=ind["weight"], **it)
              for ind, it in zip(snap1, ZHOU_SELF_ITEMS)]
    save_self(t1, "zhouwenwen", items1,
              achievements="9月人事工作按计划完成：劳动合同签订率100%，5个HC全部落地，培训2场完整归档，月度考核按时完成率100%。",
              unfinished="岗位人才库建设尚未启动，计划10月推进。",
              support="需要各部门面试官配合，提升面试反馈时效。",
              signature="周文文")

    # 任务 2：张三 2026-09 月度（全流程已发布）
    t2 = create_task("TP2026090002", "zhangsan", "monthly", "2026-09",
                     "2026-09-01", "2026-09-30", "2026-10-10", "sunhao", "pending_self")
    snap2 = json.loads(query_one("SELECT indicators FROM assessment_tasks WHERE id=?", (t2,))["indicators"])
    items2 = [
        {"name": snap2[0]["name"], "weight": snap2[0]["weight"],
         "completion": "9月新签3单，合同额118万，达到100%目标。", "self_score": 108},
        {"name": snap2[1]["name"], "weight": snap2[1]["weight"],
         "completion": "回款率93%，逾期账款已全部清零。", "self_score": 104},
        {"name": snap2[2]["name"], "weight": snap2[2]["weight"],
         "completion": "重点客户拜访9次，商机转化率32%。", "self_score": 110},
        {"name": snap2[3]["name"], "weight": snap2[3]["weight"],
         "completion": "跨部门协作事项均按时响应。", "self_score": 102},
    ]
    save_self(t2, "zhangsan", items2, achievements="季度冲刺起步良好，签约与回款双达标。",
              signature="张三")
    save_score(t2, "zhangsan", {"订单签约": 108, "回款管理": 105, "客户推进": 110, "团队协作": 102},
               comments={"订单签约": "签约结构健康，回款跟进及时。", "回款管理": "建议加强临期账款预警。"},
               bonus=1.5, bonus_items="国庆期间主动支援市场活动筹备",
               suggested="A", sup_comment="整体达成预期，保持客户拜访节奏。")
    execute("UPDATE internal_scores SET hr_comment='核对无误，加分事项属实。', hr_user_id=?, "
            "hr_checked_at=datetime('now','localtime'), status='hr_checked' WHERE task_id=?",
            (uid("hr"), t2))
    execute("UPDATE internal_scores SET approver_comment='同意。', approver_user_id=?, "
            "approved_at=datetime('now','localtime'), status='approved' WHERE task_id=?",
            (uid("chenyongsheng"), t2))
    publish(t2, "zhangsan",
            "9月总分108.05，等级A。签约与回款均达成100%目标，客户拜访量超出计划，加分项已确认。",
            "1. 加强临期账款预警，力争回款率≥95%；2.  Q4重点突破2家战略客户。")

    # 任务 3：李四 2026-Q3 季度（待自评）
    create_task("TP2026Q30001", "lisi", "quarterly", "2026-Q3",
                "2026-07-01", "2026-09-30", "2026-10-15", "zhaokai", "pending_self")

    # 任务 4：王五 2026-09 月度（已自评待评分）
    t4 = create_task("TP2026090003", "wangwu", "monthly", "2026-09",
                     "2026-09-01", "2026-09-30", "2026-10-10", "zhoujie", "pending_self")
    snap4 = json.loads(query_one("SELECT indicators FROM assessment_tasks WHERE id=?", (t4,))["indicators"])
    items4 = [
        {"name": snap4[0]["name"], "weight": snap4[0]["weight"],
         "completion": "9月设备故障停机2.5小时，OEE 87%。", "self_score": 112},
        {"name": snap4[1]["name"], "weight": snap4[1]["weight"],
         "completion": "保养计划执行率100%，记录完整。", "self_score": 108},
        {"name": snap4[2]["name"], "weight": snap4[2]["weight"],
         "completion": "排查隐患3项，整改及时率100%。", "self_score": 115},
        {"name": snap4[3]["name"], "weight": snap4[3]["weight"],
         "completion": "生产支持平均响应1.5小时。", "self_score": 105},
    ]
    save_self(t4, "wangwu", items4, achievements="设备运行稳定，安全管理零遗漏。", signature="王五")
    execute("UPDATE assessment_tasks SET status='pending_score' WHERE id=?", (t4,))

    # 任务 5：王五 2026-Q3 季度（已评分待审核）
    t5 = create_task("TP2026Q30002", "wangwu", "quarterly", "2026-Q3",
                     "2026-07-01", "2026-09-30", "2026-10-15", "zhoujie", "pending_self")
    snap5 = json.loads(query_one("SELECT indicators FROM assessment_tasks WHERE id=?", (t5,))["indicators"])
    items5 = [
        {"name": snap5[0]["name"], "weight": snap5[0]["weight"],
         "completion": "3项技改全部按计划完成，其中1项提前2周。", "self_score": 115},
        {"name": snap5[1]["name"], "weight": snap5[1]["weight"],
         "completion": "维修成本较预算节约6%。", "self_score": 112},
        {"name": snap5[2]["name"], "weight": snap5[2]["weight"],
         "completion": "季度培训3次，覆盖率100%。", "self_score": 105},
    ]
    save_self(t5, "wangwu", items5, achievements="技改项目全面达成，成本控制超额完成。", signature="王五")
    execute("UPDATE assessment_tasks SET status='pending_score' WHERE id=?", (t5,))
    save_score(t5, "wangwu", {"技改项目": 110, "备件与成本": 112, "团队培训": 100},
               comments={"技改项目": "提前交付且运行平稳。"}, suggested="A",
               sup_comment="季度表现优秀，技改效益明显。")
    execute("UPDATE assessment_tasks SET status='pending_review' WHERE id=?", (t5,))

    # 任务 6：赵六 2026-09 月度（待自评）
    create_task("TP2026090004", "zhaoliu", "monthly", "2026-09",
                "2026-09-01", "2026-09-30", "2026-10-10", "chenyongsheng", "pending_self")

    # 任务 7-10：2026-11 月度待自评（覆盖 HR / 销售 / 研发 / 生产，登录即可见填写入口）
    create_task("TP2026110001", "hr", "monthly", "2026-11",
                "2026-11-01", "2026-11-30", "2026-12-05", "chenyongsheng", "pending_self")
    create_task("TP2026110002", "sunhao", "monthly", "2026-11",
                "2026-11-01", "2026-11-30", "2026-12-05", "chenyongsheng", "pending_self")
    create_task("TP2026110003", "zhaokai", "monthly", "2026-11",
                "2026-11-01", "2026-11-30", "2026-12-05", "chenyongsheng", "pending_self")
    create_task("TP2026110004", "zhoujie", "monthly", "2026-11",
                "2026-11-01", "2026-11-30", "2026-12-05", "chenyongsheng", "pending_self")

    # 通知
    execute("INSERT INTO notifications (user_id, type, title, body, link) VALUES "
            "((SELECT id FROM users WHERE username='zhouwenwen'),'task','新的考核任务待完成',"
            "'2026-09 月度考核已发起，请及时填写自评','#/my/dashboard')")
    execute("INSERT INTO notifications (user_id, type, title, body, link) VALUES "
            "((SELECT id FROM users WHERE username='hr'),'task','新的考核任务待完成',"
            "'2026-11 月度考核已发起，请及时填写自评','#/my/dashboard')")
    execute("INSERT INTO notifications (user_id, type, title, body, link) VALUES "
            "((SELECT id FROM users WHERE username='sunhao'),'score','有新的员工自评待评分',"
            "'张三 的 2026-09 考核已提交自评','#/supervisor/tasks')")
    execute("INSERT INTO notifications (user_id, type, title, body, link) VALUES "
            "((SELECT id FROM users WHERE username='hr'),'hr','有评分待核对',"
            "'王五 的 2026-Q3 考核已完成主管评分','#/hr/scores')")
    execute("INSERT INTO notifications (user_id, type, title, body, link) VALUES "
            "((SELECT id FROM users WHERE username='zhangsan'),'result','绩效结果已发布',"
            "'2026-09 考核结果已发布，总分 108.05，等级 A','#/my/results')")

    # 审计种子
    execute("INSERT INTO audit_logs (user_id, action, target, detail) VALUES "
            "((SELECT id FROM users WHERE username='hr'),'tasks_batch_create','2026-09','创建 4 条，跳过 0 条')")
    execute("INSERT INTO audit_logs (user_id, action, target, detail) VALUES "
            "((SELECT id FROM users WHERE username='hr'),'result_publish','TP2026090002','总分 108.05 等级 A')")

    # 设置
    execute("INSERT INTO settings (key, value) VALUES ('company_name','图维生物医药') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value")
    execute("INSERT INTO settings (key, value) VALUES ('grade_bands',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(DEFAULT_BANDS, ensure_ascii=False),))

    print("种子数据初始化完成")
    print("账号（初始密码均为 %s）：" % DEFAULT_PW)
    for username, name, position, dept, role, approver, sup in USERS:
        print("  %-14s %-8s %-10s %s" % (username, name, dept, role))


if __name__ == "__main__":
    with app.app_context():
        seed(reset="--reset" in sys.argv)
