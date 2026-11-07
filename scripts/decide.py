# -*- coding: utf-8 -*-
"""决策看板：把「投递 → 回复 → 推进 → 约面 → offer」连成一条链，指出最紧的那个约束。

和 stats.py 的分工：
    stats.py  回答「回复率是多少」——一张分组表，给你看数据。
    decide.py 回答「下一步该干什么」——哪一段最窄、今天实际能投几份、要不要改简历。

为什么需要后者：283 份投递、8 个回复、0 次面试，如果只看回复率 3.1%，
结论会是「再投 200 份试试」；但把链条摊开就会发现，8 个回复里有 4 家推进到
要简历/网申，却一次面试都没约成——瓶颈在回复之后，继续加量是在放大一个
已经不工作的环节。

用法：
    python decide.py                  # 打印 + 写 决策看板.md
    python decide.py --window 96      # 观察窗小时数（默认 72）
    python decide.py --target 40      # 今天原计划投几份，用来和供给上限对比

判定阈值（写在这里，改之前先想清楚）：
    MIN_N   = 100  分母不足 100 份时，任何比率都不下结论
    THIN_HI = 5%   回复率区间上界低于 5%，说明是转化问题，不是量的问题
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import paths  # noqa: E402
from scripts import stage  # noqa: E402
import metrics  # noqa: E402

PROGRESS = paths.state("stream_progress.json")
WALK = paths.state("walk_state.json")
PENDING = paths.state("pending_actions.json")
SUPPLY = paths.state("supply.json")
KW_HEALTH = paths.state("keyword_health.json")
OUT = paths.state("决策看板.md")

WINDOW_H = 72
MIN_N = 100
THIN_HI = 5.0

ADVANCE_KINDS = ("要简历", "网申/测评", "约面试")


def _json(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def age_hours(ts):
    if not ts:
        return None
    try:
        return (time.time() - time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))) / 3600
    except Exception:
        return None


def split_window(rows, window):
    mature, watching, undated = [], [], []
    for r in rows:
        a = age_hours(r.get("delivered_at"))
        if a is None:
            undated.append(r)
        elif a >= window:
            mature.append(r)
        else:
            watching.append(r)
    return mature, watching, undated


def hit(row, names):
    """这条投递是否落在 names 里。先精确，再走 metrics.norm 归一。

    只做精确比较会漏掉「深圳市云思酷科技」和「云思酷科技」这类差异；
    但也不能上模糊匹配——那会把两家不同的公司算成一家。归一足够。
    """
    c = row.get("company") or ""
    if not c:
        return False
    if c in names:
        return True
    nc = metrics.norm(c)
    return any(nc and nc == metrics.norm(x) for x in names)


def funnel(rows, events, stages, replied):
    adv = {e.get("company") for e in events if e.get("kind") in ADVANCE_KINDS and e.get("company")}
    intro = {e.get("company") for e in events if e.get("kind") == "约面试" and e.get("company")}
    off = set()
    for s in stages:
        c = s.get("company") or ""
        if not c:
            continue
        if s.get("stage") in stage.STAGES:
            intro.add(c)
        if s.get("stage") == "offer":
            off.add(c)
    n = len(rows)
    return {
        "n": n,
        "reply": sum(1 for r in rows if hit(r, replied)),
        "adv": sum(1 for r in rows if hit(r, adv)),
        "intro": sum(1 for r in rows if hit(r, intro)),
        "offer": sum(1 for r in rows if hit(r, off)),
        "rejects": sum(1 for e in events if e.get("kind") == "拒信"),
        "auto": sum(1 for e in events if e.get("kind") == "系统通知"),
        "_adv": adv, "_intro": intro, "_offer": off,
    }


def supply_cap():
    """今天实际能投几份。

    两个数相乘：本轮可见的新卡数 × 历史合格率。
    只看新卡会高估——判否记录里有大量外包/假实习/非技术岗，它们也是「新卡」。
    只看合格率会低估——没有新卡时合格率再高也投不出去。

    「本轮」必须是一次探测，不能把历史所有词的最后一次结果加在一起：
    keyword_health 里每个词都留着最后一次结果，横跨好几天，直接求和会虚高一倍以上。
    跨天的卡早被投过或判否了，算进今天等于给自己虚报供给。
    所以按时间聚成一次会话：取最新一轮的时间，往前 3 小时内的词算同一批。
    """
    kh = _json(KW_HEALTH, {})
    per_kw, dead, when = {}, [], {}
    for kw, v in (kh or {}).items():
        rounds = (v or {}).get("rounds") or []
        if not rounds:
            continue
        last = rounds[-1]
        per_kw[kw] = int(last.get("fresh") or 0)
        when[kw] = last.get("at") or ""
        if last.get("ok") is False:
            dead.append(kw)

    if when:
        newest = max(when.values())
        try:
            t_max = time.mktime(time.strptime(newest, "%Y-%m-%d %H:%M"))
        except Exception:
            t_max = None
        if t_max:
            keep = set()
            for kw, at in when.items():
                try:
                    t = time.mktime(time.strptime(at, "%Y-%m-%d %H:%M"))
                except Exception:
                    continue
                if t_max - t <= 3 * 3600:
                    keep.add(kw)
            per_kw = {k: v for k, v in per_kw.items() if k in keep}
            dead = [k for k in dead if k in keep]
            newest_label = newest
        else:
            newest_label = ""
    else:
        newest_label = ""
    fresh = sum(per_kw.values())

    if not per_kw:
        sp = _json(SUPPLY, {})
        avail = (sp or {}).get("avail") or {}
        per_kw = {k: int(v or 0) for k, v in avail.items()}
        fresh = sum(per_kw.values())
        newest_label = (sp or {}).get("at") or ""

    prog = _json(PROGRESS, {})
    delivered = len((prog or {}).get("delivered") or [])
    rejected = len((_json(WALK, {}) or {}).get("rejected_jids") or [])
    judged = delivered + rejected
    pass_rate = (delivered / judged) if judged else 0.0
    cap = int(round(fresh * pass_rate)) if fresh else 0

    # 这次探测自己配出去的额度（supply_mix + 目标份数算出来的），
    # 和 fresh 上界是两回事：上界说「池子里有多少」，alloc 说「按结构该投几份」。
    alloc = sum(int(v or 0) for v in ((_json(SUPPLY, {}) or {}).get("alloc") or {}).values())

    # 历史上单日最多投出多少——这是「40 份到底投不投得出来」的实测证据，
    # 比任何估算都硬。数据取自 daily_log.json 的当日累计。
    max_daily = 0
    for _, entries in (_json(paths.state("daily_log.json"), {}) or {}).items():
        if isinstance(entries, list):
            max_daily = max(max_daily, sum(int(e.get("n") or 0) for e in entries
                                           if isinstance(e, dict)))

    return {"per_kw": per_kw, "fresh": fresh, "dead": dead,
            "delivered": delivered, "rejected": rejected,
            "pass_rate": pass_rate, "cap": cap, "at": newest_label,
            "alloc": alloc, "max_daily": max_daily}


def open_actions():
    rows = _json(PENDING, [])
    if not isinstance(rows, list):
        return []
    return [r for r in rows if (r or {}).get("status") == "open"]


def verdict(f, sp, actions, target):
    """返回 (结论标题, [下一步])。

    优先级刻意是「先清待办 -> 再看断点 -> 最后谈份数」：
    待办是唯一可能马上变成面试的东西，加量不是。
    推进样本 < 5 家时不下「断点在哪」的结论——2 家推进、0 家约面
    既可能是流程问题，也可能只是运气，这时候指路等于误导。
    """
    live = [a for a in actions if a.get("kind") in ("要简历", "约面试", "对方说话")]
    if not f["n"]:
        head = "还没有投递记录"
        steps = ["先跑 supply_probe.py 看今天有多少可投，再 walk"]
    elif live:
        head = "先清待办：%d 条活口还没回" % len(live)
        steps = ["回掉 %s——回复放着不处理，等于白投"
                 % "、".join((a.get("company") or "?") for a in live[:3])]
    elif f["adv"] == 0:
        head = "还没有回复推进：%d 份投递、0 家要简历/网申/约面" % f["n"]
        steps = ["先看 reply_check.py 有没有漏扫的会话，再谈方向取舍"]
    elif f["adv"] >= 5 and f["intro"] == 0:
        head = "断点在「推进 -> 约面」：%d 家推进、0 家约面" % f["adv"]
        steps = ["别再调投递参数：问题在回复之后，先看这 %d 家的会话停在哪" % f["adv"]]
    elif f["adv"] < 5:
        head = "样本不足：推进环节只有 %d 家，定位不了断点" % f["adv"]
        steps = ["先把这 %d 家的进展记进 stage.py，攒到 5 家再谈方向" % f["adv"]]
    elif f["n"] < MIN_N:
        head = "样本不足：可判断的分母只有 %d 份" % f["n"]
        steps = ["再攒 %d 份过窗记录，之后才谈方向取舍" % max(0, MIN_N - f["n"])]
    elif f["reply"] and metrics.wilson(f["reply"], f["n"])[1] < THIN_HI:
        head = "转化率是瓶颈：回复率上界 %.1f%%" % metrics.wilson(f["reply"], f["n"])[1]
        steps = ["改简历和项目描述，不是加投递量"]
    else:
        head = "加量仍然有效：回复率 %s" % metrics.pct(f["reply"], f["n"])
        steps = ["维持当前节奏，按供给上限投"]

    if f["intro"] == 0 and f["adv"]:
        steps.append("约面这条路一次都没走通：%d 家推进、0 家约面，先确认是没人约还是没记"
                     % f["adv"])
    if actions and not live:
        steps.append("还有 %d 条待办没关（%s），先处理再开新一轮"
                     % (len(actions), "、".join((a.get("company") or "?") for a in actions[:3])))
    if sp["cap"] and target and target > sp["cap"]:
        steps.append("供给封顶：上界 %d 份 < 目标 %d 份，先加词或放宽条件"
                     % (sp["cap"], target))
    elif sp["cap"] and target and sp["max_daily"] >= target:
        steps.append("供给够：历史单日最高 %d 份，%d 份投得出来——问题不在量"
                     % (sp["max_daily"], target))
    elif sp["cap"] and target:
        steps.append("供给吃紧：上界 %d 份、历史单日最高 %d 份，%d 份可能投不满"
                     % (sp["cap"], sp["max_daily"] or 0, target))
    elif sp["cap"]:
        steps.append("今天最多 %d 份（可见新卡 %d x 合格率 %.0f%%）"
                     % (sp["cap"], sp["fresh"], sp["pass_rate"] * 100))
    return head, steps


def main():
    args = sys.argv[1:]
    window = WINDOW_H
    if "--window" in args:
        window = float(args[args.index("--window") + 1])
    target = 0
    if "--target" in args:
        target = int(args[args.index("--target") + 1])

    rows = metrics.load_progress(PROGRESS)
    events = metrics.load_events(metrics.EVENTS)
    replied = metrics.replied_companies(events, _json(metrics.REPLY_LOG, {}))
    stages = stage.summarize()
    mature, watching, undated = split_window(rows, window)
    base = mature + undated

    f = funnel(base, events, stages, replied)
    sp = supply_cap()
    actions = open_actions()
    head, steps = verdict(f, sp, actions, target)

    def row(label, k, n, tip=""):
        if not n:
            return "  %-10s %5d" % (label, k)
        lo, hi = metrics.wilson(k, n)
        return "  %-10s %5d  %6s  [%.0f-%.0f%%]%s" % (
            label, k, metrics.pct(k, n), lo, hi, tip)

    lines = []
    lines.append("决策看板  %s" % time.strftime("%Y-%m-%d %H:%M"))
    lines.append("口径：分母 = 投递 >= %gh 或旧记录（无时间戳）；区间 = Wilson 95%%" % window)
    lines.append("")
    lines.append("转化链（n = %d）" % f["n"])
    lines.append(row("有回复", f["reply"], f["n"]))
    lines.append(row("有效推进", f["adv"], f["n"], "  要简历/网申/约面"))
    lines.append(row("面试", f["intro"], f["n"]))
    lines.append(row("offer", f["offer"], f["n"]))
    lines.append("  %-10s %5d  （不算回复，单独列）" % ("拒信", f["rejects"]))
    if f["auto"]:
        lines.append("  %-10s %5d  （自动回执，不是人回的——回复率被它抬高了一点）"
                     % ("系统通知", f["auto"]))
    lines.append("")
    lines.append("断点")
    lines.append("  投递 -> 回复   %s" % metrics.pct(f["reply"], f["n"]))
    lines.append("  回复 -> 推进   %s  (%d/%d)" % (metrics.pct(f["adv"], f["reply"]), f["adv"], f["reply"]))
    lines.append("  推进 -> 约面   %s  (%d/%d)" % (metrics.pct(f["intro"], f["adv"]), f["intro"], f["adv"]))
    if f["intro"]:
        lines.append("  约面 -> offer  %s  (%d/%d)" % (
            metrics.pct(f["offer"], f["intro"]), f["offer"], f["intro"]))
    lines.append("")

    if actions:
        lines.append("待闭环（%d 条）" % len(actions))
        for a in actions[:5]:
            lines.append("  %s · %s · %s" % (a.get("company") or "?", a.get("kind") or "?",
                                             (a.get("title") or "")[:28]))
        lines.append("")

    if sp["fresh"]:
        items = sorted(sp["per_kw"].items(), key=lambda x: -x[1])
        kw = " / ".join("%s %d" % (k, v) for k, v in items[:6])
        if len(items) > 6:
            kw += " 等 %d 个词" % len(items)
        lines.append("供给（最近一次探测 %s）" % (sp.get("at") or "时间未知"))
        lines.append("  新卡上界 %d：%s" % (sp["fresh"], kw))
        lines.append("  这个数没去词间重复（同一张卡会同时出现在「前端」和「Vue」下），"
                     "所以是上界，不是可用量")
        if sp["dead"]:
            lines.append("  分页失效 %d 个词（真实货量高于显示值，按显示值算是下限）"
                         % len(sp["dead"]))
        lines.append("  历史合格率 %.1f%%（%d 投 / %d 判否）"
                     % (sp["pass_rate"] * 100, sp["delivered"], sp["rejected"]))
        lines.append("  投得出去的上限 ≈ %d 份；这次探测按 %d 份配的额"
                     % (sp["cap"], sp["alloc"]))
        if sp["max_daily"]:
            lines.append("  历史单日最高 %d 份——「一天 40 份」投不投得出来，看这个数"
                         % sp["max_daily"])
        lines.append("")

    lines.append("结论")
    lines.append("  " + head)
    for i, s in enumerate(steps, 1):
        lines.append("  %d. %s" % (i, s))

    text = "\n".join(lines)
    print(text)

    md = ["# 决策看板", "", "生成时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"), "",
          "> 由 `scripts/decide.py` 生成。看数字用 `stats.py`，看下一步用这张。", "",
          "## 转化链", "", "| 阶段 | 份数 | 占比 | 95% 区间 |", "|---|---|---|---|"]
    for label, k in (("投递", f["n"]), ("有回复", f["reply"]), ("有效推进", f["adv"]),
                     ("面试", f["intro"]), ("offer", f["offer"])):
        if label == "投递" or not f["n"]:
            md.append("| %s | %d | - | - |" % (label, k))
        else:
            lo, hi = metrics.wilson(k, f["n"])
            md.append("| %s | %d | %s | %.0f-%.0f%% |"
                      % (label, k, metrics.pct(k, f["n"]), lo, hi))
    md += ["| 拒信 | %d | - | 不算回复 |" % f["rejects"]]
    if f["auto"]:
        md.append("| 系统通知 | %d | - | 自动回执，不是人回的 |" % f["auto"])
    md += ["",
           "## 断点", "",
           "| 环节 | 转化率 | 样本 |", "|---|---|---|",
           "| 投递 -> 回复 | %s | %d/%d |" % (metrics.pct(f["reply"], f["n"]), f["reply"], f["n"]),
           "| 回复 -> 推进 | %s | %d/%d |" % (metrics.pct(f["adv"], f["reply"]), f["adv"], f["reply"]),
           "| 推进 -> 约面 | %s | %d/%d |" % (metrics.pct(f["intro"], f["adv"]), f["intro"], f["adv"]),
           "| 约面 -> offer | %s | %d/%d |" % (metrics.pct(f["offer"], f["intro"]),
                                               f["offer"], f["intro"]), ""]
    if actions:
        md += ["## 待闭环", ""]
        for a in actions[:10]:
            md.append("- %s · %s · %s" % (a.get("company") or "?", a.get("kind") or "?",
                                          a.get("title") or ""))
        md.append("")
    if sp["fresh"]:
        md += ["## 供给", "",
               "- 新卡上界：%d（各词之和，未去词间重复）" % sp["fresh"],
               "- 历史合格率：%.1f%%（%d 投 / %d 判否）"
               % (sp["pass_rate"] * 100, sp["delivered"], sp["rejected"]),
               "- 投得出去的上限：约 %d 份" % sp["cap"],
               "- 这次探测配的额：%d 份" % sp["alloc"]]
        if sp["max_daily"]:
            md.append("- 历史单日最高：%d 份" % sp["max_daily"])
        md.append("")
    md += ["## 结论", "", "**%s**" % head, ""]
    for s in steps:
        md.append("- " + s)
    md.append("")
    open(OUT, "w", encoding="utf-8").write("\n".join(md))
    print("\n已写入", OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
