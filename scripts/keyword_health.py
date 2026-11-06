"""词表健康：记录每个关键词到底还能挖出多少新岗位，连续挖空的词自动退役。

为什么需要（2026-11-06 实测）：
判否台账有 422 条，但它们只被用来「跳过某张卡」，从来没有反馈到搜索策略上。
结果是同一个词今天和前天返回的结果集几乎一模一样，每一轮都要把同样的 15 张卡
重新判一遍（日志里满屏「已判否-跳过」），真正的新候选接近个位数。

这里把「这个词这一轮还剩多少新的」记下来，下次开跑直接跳过已经挖空的词——
把轮次留给还有货的词，而不是在死词上做无用功。

判定口径只用 fresh（从没见过的卡数），不看投递数：
某个词可能一直有卡、但全被判否，那同样是枯竭，只是原因不同（方向不匹配）。
"""

import json
import os
import time

# 连续多少轮 fresh 为 0 判定为枯竭。
# 取 2 而不是 1：BOSS 的搜索结果会抖动，单轮 0 可能只是这一次没刷出来。
EXHAUST_STREAK = 2

# 每个词最多保留多少轮历史，避免文件无限增长
MAX_ROUNDS = 12


def _path(workdir):
    return os.path.join(workdir, "keyword_health.json")


def _load(workdir):
    try:
        with open(_path(workdir), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(workdir, data):
    try:
        tmp = _path(workdir) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, _path(workdir))
        return True
    except Exception:
        return False


def record(workdir, keyword, scanned, fresh, note="", ok=True):
    """记一轮探测结果。scanned = 这一轮看了多少张卡，fresh = 其中多少张是新的。

    ok=False 表示这一轮**没有取得可信结果**（加载失败、翻页没换内容）。
    这种轮次只留档便于排查，绝不参与枯竭判定——否则「浏览器抖一下」
    会和「这个词真没货」记成同一件事，两轮之后把还有货的词永久退役。
    """
    if not keyword:
        return False
    data = _load(workdir)
    entry = data.setdefault(keyword, {})
    rounds = entry.get("rounds") or []
    rounds.append({
        "at": time.strftime("%Y-%m-%d %H:%M"),
        "scanned": int(scanned or 0),
        "fresh": int(fresh or 0),
        "note": note,
        "ok": bool(ok),
    })
    entry["rounds"] = rounds[-MAX_ROUNDS:]
    entry["exhausted"] = _is_exhausted_entry(entry)
    if entry["exhausted"] and not entry.get("exhausted_at"):
        entry["exhausted_at"] = rounds[-1]["at"]
    elif not entry["exhausted"]:
        entry["exhausted_at"] = ""
    data[keyword] = entry
    _save(workdir, data)
    return True


def _is_exhausted_entry(entry, streak=EXHAUST_STREAK):
    """连续 streak 轮**有效**探测都是 0 新增，才算挖空。

    只统计 ok=True 的轮次：失败轮里的 fresh=0 是「没测出结果」，
    不是「测出来没有」，两者混为一谈会把词表一条条错误退役。
    """
    rounds = [r for r in ((entry or {}).get("rounds") or []) if r.get("ok", True)]
    if len(rounds) < streak:
        return False
    return all(int(r.get("fresh") or 0) == 0 for r in rounds[-streak:])


def is_exhausted(workdir, keyword, streak=EXHAUST_STREAK):
    data = _load(workdir)
    entry = data.get(keyword)
    if not entry:
        return False
    return _is_exhausted_entry(entry, streak=streak)


def summarize(workdir, keyword):
    """给单个词一句人话，用在日志里。"""
    data = _load(workdir)
    entry = data.get(keyword) or {}
    rounds = entry.get("rounds") or []
    if not rounds:
        return "未探测过"
    last = rounds[-1]
    txt = "上轮 %d 张 / 新增 %d" % (int(last.get("scanned") or 0), int(last.get("fresh") or 0))
    if entry.get("exhausted"):
        n = 0
        for r in reversed(rounds):
            if int(r.get("fresh") or 0) == 0:
                n += 1
            else:
                break
        txt += "，已连续 %d 轮挖空，建议换词" % n
    return txt


def exhausted_keywords(workdir, keywords=None):
    """返回已经挖空的词（可限定在给定词表内）。"""
    data = _load(workdir)
    pool = keywords if keywords is not None else list(data.keys())
    return [k for k in pool if _is_exhausted_entry(data.get(k) or {})]


def report(workdir):
    """按「还剩多少新的」排序，给出还在产出的词。"""
    data = _load(workdir)
    rows = []
    for kw, entry in data.items():
        rounds = entry.get("rounds") or []
        last = rounds[-1] if rounds else {}
        rows.append({
            "keyword": kw,
            "last_fresh": int(last.get("fresh") or 0),
            "last_scanned": int(last.get("scanned") or 0),
            "exhausted": bool(entry.get("exhausted")),
            "at": last.get("at") or "",
        })
    rows.sort(key=lambda r: (r["exhausted"], -r["last_fresh"], r["keyword"]))
    return rows


def reset(workdir, keyword=None):
    """清掉某个词（或全部）的健康记录，用于「明明还有货却被判枯竭」的误判。"""
    data = _load(workdir)
    if keyword:
        data.pop(keyword, None)
    else:
        data = {}
    _save(workdir, data)
    return True


if __name__ == "__main__":
    import argparse
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from scripts import paths

    ap = argparse.ArgumentParser(description="词表健康：哪些关键词已经挖空了")
    ap.add_argument("--workdir", default=paths.WORKDIR)
    ap.add_argument("--reset", default=None, help="清掉某个词的健康记录；传 ALL 清全部")
    a = ap.parse_args()

    if a.reset:
        reset(a.workdir, None if a.reset.upper() == "ALL" else a.reset)
        print("已重置:", a.reset)
    rows = report(a.workdir)
    if not rows:
        print("还没有探测记录。跑 supply_probe.py 会自动积累。")
    else:
        print("%-22s %8s %8s  %s" % ("关键词", "上轮新增", "上轮卡数", "状态"))
        for r in rows:
            print("%-22s %8d %8d  %s" % (
                r["keyword"], r["last_fresh"], r["last_scanned"],
                "已挖空" if r["exhausted"] else "还有货"))
