# -*- coding: utf-8 -*-
"""收尾对账：这一批投递里，谁还没把「简历图 + 一句话」送到。

只读脚本——不打开浏览器、不写任何状态文件，重跑两次输出完全一致。

    python scripts/daily_close.py                    # 从 daily_log 最后一天算起
    python scripts/daily_close.py --since 2026-11-03 # 指定起始日期
    python scripts/daily_close.py --strict           # 有缺口时退出码 1（默认永远 0）

为什么需要它：
    11-03 投了 41 份，只有 1 家补了图；剩下 40 家是「打算第二天批量补」，
    然后第二天开了新批次，就再没人回头。缺的不是记性，是一个会把缺口列出来的东西。

缺口判据只认 greeting_log.jsonl 里的事件：
    img_ok / msg_ok 都是发送之后回读的，img_mode_log 只是"发送前的选图决策"，
    不能当送达证据（它连图有没有落地都不知道）。
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import metrics, paths  # noqa: E402

IMG_MODE_LOG = paths.state("img_mode_log.json")
DAILY_LOG = paths.state("daily_log.json")
SEND_TIP = "python scripts/send_followup.py --job %s --msg --auto-img"


def last_daily_date():
    try:
        d = json.load(open(DAILY_LOG, encoding="utf-8"))
        keys = sorted(k for k in d.keys() if len(k) == 10)
        if keys:
            return keys[-1]
    except Exception:
        pass
    return (datetime.date.today() - datetime.timedelta(days=7)).isoformat()


def load_img_modes():
    try:
        return json.load(open(IMG_MODE_LOG, encoding="utf-8"))
    except Exception:
        return {}


def classify(row, events, modes, counts):
    """返回 (状态, 说明)。状态：完成 / 缺话术 / 缺简历图 / 图话术都缺 / 旧记录待确认 / 无留痕"""
    e = metrics.event_for(row, events, counts)
    if not e:
        legacy = metrics.mode_for(row, modes, counts)
        if legacy:
            # img_mode_log 是在 inject 之前写的，只说明"打算发哪张"，不说明发成功
            return "旧记录待确认", "只有选图决策(%s)，没有发送结果" % legacy.get("mode", "?")
        return "无留痕", "没有发送记录"
    img_ok = bool(e.get("img_ok"))
    msg_ok = bool(e.get("msg_ok"))
    if img_ok and msg_ok:
        return "完成", ""
    if img_ok and not msg_ok:
        return "缺话术", str(e.get("msg_res") or "")[:40]
    if msg_ok and not img_ok:
        return "缺简历图", str(e.get("img_res") or "")[:40]
    return "图话术都缺", str(e.get("img_res") or "")[:40]


def main():
    args = sys.argv[1:]
    since = ""
    if "--since" in args:
        k = args.index("--since")
        since = args[k + 1] if len(args) > k + 1 else ""
    strict = "--strict" in args
    since = since or last_daily_date()

    rows = [r for r in metrics.load_progress()
            if (r.get("delivered_at") or "")[:10] >= since]
    if not rows:
        print("对账区间 %s 起：没有投递记录，无需补发。" % since)
        return 0

    events = metrics.greeting_index()
    modes = load_img_modes()
    counts = {}
    for r in rows:
        c = r.get("company") or ""
        counts[c] = counts.get(c, 0) + 1

    buckets = {}
    todo = []
    for r in rows:
        state, why = classify(r, events, modes, counts)
        buckets.setdefault(state, []).append(r)
        if state != "完成":
            todo.append((r, state, why))

    print("对账区间：%s 起，投递 %d 条" % (since, len(rows)))
    order = ("完成", "缺话术", "缺简历图", "图话术都缺", "旧记录待确认", "无留痕")
    print("  " + " / ".join("%s %d" % (k, len(buckets.get(k, []))) for k in order))

    custom_m = 0
    bucket_k = 0
    for r in rows:
        e = metrics.event_for(r, events, counts) or {}
        src = e.get("src") or r.get("greeting_src")
        b = e.get("bucket")
        if src == "jd" or b == "jd":
            custom_m += 1
        elif e or r.get("delivered_at"):
            bucket_k += 1
    print("  话术来源：定制 %d / 退回桶 %d" % (custom_m, bucket_k))
    print("")

    if not todo:
        print("全部补齐了。")
        return 0

    print("待补 %d 条（按投递时间正序）：" % len(todo))
    for r, state, why in sorted(todo, key=lambda x: x[0].get("delivered_at") or ""):
        jid = r.get("jobId") or ""
        label = "%s | %s | %s" % ((r.get("delivered_at") or "")[:10],
                                  (r.get("company") or "")[:18],
                                  (r.get("title") or "")[:22])
        print("  [%s] %s  %s" % (state, label, ("(" + why + ")") if why else ""))
        if jid:
            print("        " + SEND_TIP % jid)
        else:
            print('        python scripts/send_followup.py 1 "%s" --msg --auto-img'
                  % (r.get("company") or ""))

    print("")
    print("补发建议：先按 --job 单家跑（同公司多岗位时不会串档），"
          "每 5 家停一次确认 IMG/MSG 都成功；跑完重跑本脚本，缺口应为 0。")
    return 1 if strict else 0


if __name__ == "__main__":
    sys.exit(main())
