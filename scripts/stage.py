# -*- coding: utf-8 -*-
"""进度台账：记录「会话里看不出来」的那一段（约面 → 一面 → 二面 → offer）。

为什么单独有这个文件：
    reply_check.py 能从会话里读出「要简历 / 网申 / 约面试」——那是 HR 说的话。
    但约面之后发生了什么，会话里没有结构化信号：几点面试、第几轮、有没有下文、
    挂在哪个环节。不记下来，漏斗就永远停在「待我动作」，也就永远算不出
    「投多少份能换一个 offer」。

    这份台账只记**人已经知道、但机器猜不到**的事实，不参与自动判断，
    也不改写其它任何状态文件。

用法：
    python stage.py log "深投数科" 约面
    python stage.py log "深投数科" 一面 --job 94ed984de062060f0nx_29m4ElVY --note "周四 15:00 腾讯会议"
    python stage.py list
    python stage.py list --json

阶段固定七种，写错会列出可选值并退出 1（不接受自定义阶段：
自定义会让统计口径随人而变，两张表就对不上了）。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import paths  # noqa: E402

LOG = paths.state("interview_log.jsonl")

# 顺序即漏斗顺序：约面 < 一面 < 二面 < 终面 < offer
STAGES = ("约面", "一面", "二面", "终面", "offer")
TERMINAL_FAIL = ("拒", "失联")
ALL_STAGES = STAGES + TERMINAL_FAIL

# 算「已约面」的阶段集合（offer 也算，走到 offer 必然面过）
INTERVIEW_STAGES = STAGES

HELP = __doc__


def load(path=None):
    """读台账，返回列表；文件不存在返回空列表（第一天不该 traceback）。"""
    path = path or LOG
    rows = []
    if not os.path.exists(path):
        return rows
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return rows


def append(company, stage, job_id="", note="", path=None):
    path = path or LOG
    row = {"at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "company": company, "jobId": job_id, "stage": stage, "note": note}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()
    return row


def _key(row):
    """同一岗位的稳定键：优先 jobId，退回公司名。

    为什么不用公司名做主键：一家投两个岗位时，公司名会把两条记录并成一条，
    于是「A 岗约面」会被算成「B 岗也约面」——和补发简历图串档是同一类错。
    """
    return (row.get("jobId") or "").strip() or (row.get("company") or "").strip()


def summarize(rows=None):
    """按岗位聚合，返回 [{key, company, jobId, stage, at, events}]。

    stage = 走得最远的那一站；有「offer」就是 offer，有「拒/失联」且没有更远的
    面试阶段就是终止。同一天同一站重复记录只算一次（幂等），
    因为人可能手滑记两遍，但漏斗只该加一次。
    """
    rows = load() if rows is None else rows
    agg = {}
    for r in rows:
        k = _key(r)
        if not k:
            continue
        d = agg.setdefault(k, {"key": k, "company": r.get("company") or "",
                               "jobId": r.get("jobId") or "",
                               "stage": "", "at": "", "events": 0})
        d["events"] += 1
        d["at"] = max(d["at"], r.get("at") or "")
        st = r.get("stage") or ""
        if st in STAGES:
            if d["stage"] not in STAGES or STAGES.index(st) > STAGES.index(d["stage"]):
                d["stage"] = st
        elif st in TERMINAL_FAIL and d["stage"] not in STAGES:
            d["stage"] = d["stage"] or st
    return sorted(agg.values(), key=lambda x: x["at"], reverse=True)


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(HELP)
        return 0

    cmd = args[0]

    if cmd == "log":
        rest = [a for a in args[1:] if not a.startswith("--")]
        if len(rest) < 2:
            print("用法: python stage.py log \"公司名\" <阶段> [--job <jobId>] [--note \"...\"]")
            print("可选阶段:", " / ".join(ALL_STAGES))
            return 1
        company, stage = rest[0].strip(), rest[1].strip()
        if len(company) < 2:
            print(json.dumps({"error": "BAD_COMPANY",
                              "why": "公司名不足 2 字，会和别的记录混在一起"},
                             ensure_ascii=False))
            return 1
        if stage not in ALL_STAGES:
            print(json.dumps({"error": "BAD_STAGE", "allowed": list(ALL_STAGES),
                              "why": "阶段必须取自固定枚举，否则统计口径会随人而变"},
                             ensure_ascii=False))
            return 1
        job_id, note = "", ""
        if "--job" in args:
            job_id = args[args.index("--job") + 1]
        if "--note" in args:
            note = args[args.index("--note") + 1]

        # 同岗位同阶段已经记过就不重复写：重跑不该把漏斗撑大
        for r in load():
            if _key(r) == (job_id or company) and r.get("stage") == stage:
                print("已存在，未重复记录：%s · %s @ %s" % (company, stage, r.get("at")))
                return 0
        row = append(company, stage, job_id, note)
        print("已记录：%s · %s @ %s" % (row["company"], row["stage"], row["at"]))
        print("台账:", LOG)
        return 0

    if cmd == "list":
        rows = summarize()
        if "--json" in args:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
            return 0
        if not rows:
            print("还没有进度记录。约到面试后用：python stage.py log \"公司\" 约面")
            return 0
        print("%-22s %-6s %-19s %s" % ("公司", "最远阶段", "最近记录", "事件"))
        for d in rows:
            print("%-22s %-6s %-19s %d" % (d["company"][:22], d["stage"] or "-",
                                           d["at"], d["events"]))
        return 0

    print("未知命令:", cmd)
    print(HELP)
    return 1


if __name__ == "__main__":
    sys.exit(main())
