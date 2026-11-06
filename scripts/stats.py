# -*- coding: utf-8 -*-
"""投递/回复周报。这一版的目标不是"多几列"，是让分母和分子真的对得上。

用法：
    python stats.py                 # 打印 + 写 回复率报表.md
    python stats.py --window 72     # 观察窗小时数（默认 72）
    python stats.py --all           # 连旧记录（无时间戳）一起算，仅作参考

口径（和上一版的区别，写在报表顶部一起输出）：
    分母 = 投递时间距今 >= 观察窗 的记录。
           刚投出去的还没到能回复的时间，算进分母会把回复率稀释成假数
           （上一版把 40 份刚投 3 小时的和 217 份旧记录混在一起算，
           再配上一个只覆盖最近 40 条会话的分子，得出「1%」）。
    分子 = reply_events.jsonl 里能匹配到投递记录的公司数。
           匹配不上的会话记为 ?哈希，不参与计算。
    置信区间 = Wilson 95%。样本 < 30 时点估计不能当真，两组的区间经常重叠。
"""
import json
import os
import sys
import time
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import paths  # noqa: E402
import metrics  # noqa: E402

PROGRESS = paths.state("stream_progress.json")
REPLY = paths.state("reply_log.json")
OUT = paths.state("回复率报表.md")


def salary_kind(s):
    s = s or ""
    if "元" in s and "天" in s:
        return "元/天"
    return "K·薪" if "K" in s.upper() else "其他"


def age_hours(r):
    ts = r.get("delivered_at")
    if not ts:
        return None
    try:
        return (time.time() - time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))) / 3600
    except Exception:
        return None


def split_by_window(rows, window):
    mature, watching, undated = [], [], []
    for r in rows:
        a = age_hours(r)
        if a is None:
            undated.append(r)
        elif a >= window:
            mature.append(r)
        else:
            watching.append(r)
    return mature, watching, undated


def group(rows, replied, keyfn, label):
    b = OrderedDict()
    for r in rows:
        k = keyfn(r)
        d = b.setdefault(k, {"n": 0, "k": 0})
        d["n"] += 1
        if r.get("company") in replied:
            d["k"] += 1
    lines = ["### " + label, "",
             "| %s | 投递 | 有回复 | 回复率 | 95%% 区间 |" % label,
             "|---|---|---|---|---|"]
    for k, v in sorted(b.items(), key=lambda x: (-x[1]["n"], x[0])):
        lo, hi = metrics.wilson(v["k"], v["n"])
        note = " ⚠️" if v["n"] < 10 else ""
        lines.append("| %s%s | %d | %d | %s | %s |"
                     % (k, note, v["n"], v["k"], metrics.pct(v["k"], v["n"]),
                        "%.0f–%.0f%%" % (lo, hi)))
    lines.append("")
    lines.append("> ⚠️ = 样本 < 10，区间宽到没有判断价值，只作记录。")
    return "\n".join(lines)


def main():
    args = sys.argv[1:]
    window = 72
    if "--window" in args:
        window = float(args[args.index("--window") + 1])
    include_legacy = "--strict" not in args   # 旧记录默认算进来：它们本来就够老了

    rows = metrics.load_progress(PROGRESS)
    events = metrics.load_events(metrics.EVENTS)
    try:
        reply_log = json.load(open(REPLY, encoding="utf-8"))
    except Exception:
        reply_log = {}
    replied = metrics.replied_companies(events, reply_log)
    src = "reply_events.jsonl" if events else "reply_log.json（老格式）"

    mature, watching, undated = split_by_window(rows, window)
    # 无时间戳的 217 条都是 10 月的老投递，早过了观察窗；排除它们等于把唯一
    # 能看的样本扔掉。所以默认并入，但在报表里单列一行、并说明覆盖不全。
    base = mature + (undated if include_legacy else [])
    # 本批 = 有时间戳的那批。为什么单列：这 61 条全在观察窗内，被 base 排除，
    # 于是"送达完成率"和"按话术桶"两张表在 base 上永远是空的（旧报表里
    # 「按简历图」一直显示 217 条未标注，就是这个原因）。
    batched = [r for r in rows if (r.get("delivered_at") or "")[:10]]
    # 「有图」= 有选图记录（含 21 条只有 img_mode_log 的旧记录，那是唯一证据）；
    # 「有话术」只认 greeting_log 里 msg_ok=true —— 有 bucket 不等于字发出去了。
    with_img = sum(1 for r in batched if r.get("img_mode") or r.get("greeting_img_ok"))
    with_msg = sum(1 for r in batched if r.get("greeting_msg_ok"))

    k = sum(1 for r in base if r.get("company") in replied)
    print("观测窗 %gh" % window)
    print("  已过窗  %3d 份 / 有回复 %d  → %s  (区间 %s)"
          % (len(mature), sum(1 for r in mature if r.get("company") in replied),
             metrics.pct(sum(1 for r in mature if r.get("company") in replied), len(mature)),
             "%.0f–%.0f%%" % metrics.wilson(sum(1 for r in mature if r.get("company") in replied), len(mature))))
    print("  观察中  %3d 份（投出去不足 %gh，不计入分母）" % (len(watching), window))
    print("  无时间戳 %3d 份（旧记录，老口径，单独列）" % len(undated))
    print("  本批送达 %3d 份投递 → 有简历图 %d → 有话术 %d" % (len(batched), with_img, with_msg))
    print("  分子来源 %s，命中公司 %d 家" % (src, len(replied)))
    if len(mature) < 30:
        print("  ⚠️ 已过窗样本 %d < 30，回复率还不能当结论用" % len(mature))

    md = ["# 投递 / 回复统计", "",
          "生成时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"), "",
          "## 口径（先看这个，不然数字会误导）", "",
          "- **分母**：投递距今 ≥ %g 小时的记录。刚投出去的不进分母——还没到能回复的时间。" % window,
          "- **分子**：%s 中能匹配到投递记录的公司。匹配不上的会话记 `?哈希`，不算回复。" % src,
          "- **不算回复**：「已读未回」「我方最后发言」；「对方已同意 / 已收到简历」算。",
          "- **置信区间**：Wilson 95%。样本 < 30 时点估计不可靠。", "",
          "## 总览", "",
          "| 组 | 投递 | 有回复 | 回复率 | 95% 区间 |", "|---|---|---|---|---|"]

    for label, rs in (("已过观察窗（可下结论）", mature),
                      ("观察中（不计入）", watching),
                      ("无时间戳旧记录", undated)):
        kk = sum(1 for r in rs if r.get("company") in replied)
        lo, hi = metrics.wilson(kk, len(rs))
        md.append("| %s | %d | %d | %s | %s |" % (label, len(rs), kk,
                                                  metrics.pct(kk, len(rs)),
                                                  "%.0f–%.0f%%" % (lo, hi) if rs else "-"))
    md.append("")
    md.append("## 送达漏斗（本批：有时间戳的 %d 份）" % len(batched))
    md.append("")
    md.append("| 环节 | 份数 | 占比 |")
    md.append("|---|---|---|")
    md.append("| 投递 | %d | 100%% |" % len(batched))
    md.append("| 有简历图 | %d | %s |" % (with_img, metrics.pct(with_img, len(batched))))
    md.append("| 有话术 | %d | %s |" % (with_msg, metrics.pct(with_msg, len(batched))))
    md.append("")
    md.append("> 「有话术」只认 `greeting_log.jsonl` 里 `msg_ok=true` 的事件。"
              "`img_mode_log` 写在 inject 之前，是「打算发哪张图」，不是送达证据。")
    md.append("")
    if batched:
        md.append(group(batched, replied, lambda r: r.get("greeting_bucket") or "（无话术记录）",
                        "按话术桶（本批）"))
        md.append("")
        md.append(group(batched, replied,
                        lambda r: (r.get("img_mode") or "（未标注）").split(":")[0],
                        "按简历图 A/B（本批）"))
        md.append("")

    if base:
        md.append("## 分组（%d 份%s）" % (len(base),
                                         "：已过窗 + 无时间戳旧记录" if undated and include_legacy else "：仅已过窗"))
        md.append("")
        md.append("> 旧记录没有 `keyword`/`direction` 字段，这两张表基本只有今天的 40 份在支撑；"
                  "行业和薪资形态是唯一能覆盖全样本的两维。\n")
        md.append(group(base, replied, lambda r: r.get("keyword") or "（无关键词）", "按来源关键词")); md.append("")
        md.append(group(base, replied, lambda r: salary_kind(r.get("salary")), "按薪资形态")); md.append("")
        md.append(group(base, replied, lambda r: r.get("direction") or "（未标）", "按投递方向")); md.append("")
        md.append(group(base, replied, lambda r: r.get("img_mode") or "（未标注）", "按简历图（A/B）")); md.append("")
        md.append(group(base, replied, lambda r: r.get("industry") or "未知", "按行业"))
    else:
        md.append("_已过观察窗的样本为 0：目前所有投递都在 %g 小时内，等 1~3 天再看。_" % window)

    text = "\n".join(md)
    open(OUT, "w", encoding="utf-8").write(text)
    print("\n已写入", OUT)


if __name__ == "__main__":
    main()
