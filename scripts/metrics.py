# -*- coding: utf-8 -*-
"""指标口径的公共部分：公司名归一、投递记录匹配、回复事件加载、区间估计。

这个模块存在的唯一原因：原来 reply_check.py 和 stats.py 各写一套「公司名怎么算相等」，
结果一边往日志里塞会话原文（连时间一起），另一边拿公司名做精确字符比较——
分子分母对不上，算出来的回复率没有意义。口径只留这里一份。
"""
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import paths  # noqa: E402

PROGRESS = paths.state("stream_progress.json")
REPLY_LOG = paths.state("reply_log.json")
EVENTS = paths.state("reply_events.jsonl")
IMG_MODE_LOG = paths.state("img_mode_log.json")
GREETING_LOG = paths.state("greeting_log.jsonl")

CITY = ("深圳市", "深圳", "北京市", "北京", "上海市", "上海", "广州市", "广州",
        "杭州市", "杭州", "东莞市", "东莞", "惠州市", "惠州", "成都市", "成都")
SUFFIX = ("股份有限公司", "有限责任公司", "有限公司", "分公司", "集团", "控股")

# 算「有回复」的类别（口径见 README-指标.md）
REPLY_KINDS = ("要简历", "网申/测评", "约面试", "对方说话", "系统通知")


def norm(s):
    """只做保守归一：去括号注释、城市前缀、法律后缀、空白标点。

    刻意不删「科技/信息/智能」这类词——删了会让「云思酷科技」和「云思酷信息」
    撞成一个公司，宁可漏配也不要错配。
    """
    s = s or ""
    s = re.sub(r"[（(][^)）]*[)）]", "", s)
    s = re.sub(r"[\s·・\-—_/|]+", "", s)
    for c in CITY:
        if s.startswith(c):
            s = s[len(c):]
            break
    for w in SUFFIX:
        while s.endswith(w):
            s = s[:-len(w)]
    return s


def _lcs(a, b):
    if not a or not b:
        return 0
    m = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        prev = 0
        for j in range(1, len(b) + 1):
            cur = m[j]
            if a[i - 1] == b[j - 1]:
                m[j] = prev + 1
                best = max(best, m[j])
            else:
                m[j] = 0
            prev = cur
    return best


def score(name, text):
    """公司名 name 在 text 里的匹配分。0 = 不匹配。

    100+ 表示完整包含；50+ 表示最长公共子串够长（应对「深圳市新辰知序科技」
    vs 会话里显示成「新辰知序」这类截断）。
    """
    n, t = norm(name), norm(text)
    if len(n) < 2 or not t:
        return 0
    if n in t:
        return 100 + len(n)
    l = _lcs(n, t)
    if l >= 4 and l >= len(n) * 0.6:
        return 50 + l
    return 0


def greeting_index(path=None):
    """jobId / 公司名 → 最近一次「发送」事件（skip 不参与）。

    同一家公司投两个岗位时，公司名这个键会指向最后一条，所以读取端必须
    **先按 jobId 找，找不到再退回公司名**——反过来就又串档了。
    """
    path = path or GREETING_LOG
    idx = {}
    if not os.path.exists(path):
        return idx
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if e.get("event") != "send":
                    continue
                for k in (e.get("jobId"), e.get("company")):
                    if k:
                        idx[k] = e
    except Exception:
        pass
    return idx


def event_for(row, events=None, counts=None):
    """取这条**记录**对应的事件。

    优先 jobId；只有「这家公司在本批里只出现过一次」时才退回公司名。
    为什么加这个限制：一家投两个岗位时，按公司名回退会让没发过的那条
    继承另一条的事件，于是被算成「已完成」永远不再补——和当初的串档是同一类错，
    只是从"发错文案"变成"漏发还被记成发过"。
    """
    events = events if events is not None else greeting_index()
    jid = (row or {}).get("jobId") or ""
    if jid and jid in events:
        return events[jid]
    c = (row or {}).get("company") or ""
    if not c:
        return None
    if counts is not None and counts.get(c, 0) > 1:
        return None
    return events.get(c)


def mode_for(row, modes, counts=None):
    """同理：img_mode 的旧记录是公司名键，多记录公司不猜。"""
    jid = (row or {}).get("jobId") or ""
    if jid and jid in modes:
        return modes[jid]
    c = (row or {}).get("company") or ""
    if not c:
        return None
    if counts is not None and counts.get(c, 0) > 1:
        return None
    return modes.get(c)


def load_progress(path=PROGRESS):
    """投递记录 + 简历图模式（A/B）+ 实际发出的话术。

    这三样都不写回 stream_progress.json（那是投递流程的状态文件，
    多一个写入方就多一个损坏风险），各自放独立日志，这里合并。

    文件不存在时返回空列表而不是抛异常：刚装好的第一天，`reply_check --list`
    和 `stats.py` 都该能正常给出「还没有投递记录」，而不是 traceback。
    """
    rows = []
    try:
        rows = json.load(open(path, encoding="utf-8")).get("delivered", [])
    except FileNotFoundError:
        return []
    except Exception:
        return []
    modes = {}
    if os.path.exists(IMG_MODE_LOG):
        try:
            modes = json.load(open(IMG_MODE_LOG, encoding="utf-8"))
        except Exception:
            modes = {}
    greets = greeting_index()
    counts = {}
    for r in rows:
        c = r.get("company") or ""
        counts[c] = counts.get(c, 0) + 1
    for r in rows:
        m = mode_for(r, modes, counts)
        if m and not r.get("img_mode"):
            r["img_mode"] = m.get("mode")
        g = event_for(r, greets, counts)
        if g:
            r["greeting_bucket"] = g.get("bucket") or ""
            r["greeting_text"] = g.get("text") or ""
            r["greeting_status"] = g.get("status") or ""
            # 分开记：status 是"图字都成"，漏斗要的是"字有没有真的发出去"
            r["greeting_msg_ok"] = bool(g.get("msg_ok"))
            r["greeting_img_ok"] = bool(g.get("img_ok"))
    return rows


def best_match(text, records):
    """返回 (record, score)；score=0 表示没匹配上。"""
    best, bs = None, 0
    for r in records:
        s = score(r.get("company") or "", text)
        if s > bs:
            best, bs = r, s
    return best, bs


def company_of(records, name):
    """按公司名反查投递记录（用于把回复挂回具体岗位）。"""
    return best_match(name, records)[0]


def load_events(path=EVENTS):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    return out


def replied_companies(events=None, reply_log=None):
    """谁算「有回复」——统一从这里取，别在报表里重新定义一遍。

    优先用事件流；没有事件流时退回 reply_log（老数据）。
    UNMATCHED 开头的 key 一律不算——那是没匹配上投递记录的会话，
    拿它当回复会把分母里根本没有的岗位算成"有回复"。
    """
    if events:
        return {e.get("company") for e in events
                if e.get("company") and e.get("kind") in REPLY_KINDS
                and not str(e.get("company")).startswith("?")}
    if reply_log is None:
        try:
            reply_log = json.load(open(REPLY_LOG, encoding="utf-8"))
        except Exception:
            reply_log = {}
    return {k for k, v in reply_log.items()
            if not k.startswith("?") and (v or {}).get("last_kind", (v or {}).get("kind")) in REPLY_KINDS}


def wilson(k, n, z=1.96):
    """Wilson 区间，返回 (low, high) 的百分数。

    小样本（n<30）下别拿点估计当真——2/5=40% 和 3/50=6% 的区间可能是重叠的。
    """
    if not n:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    s = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - s) / d * 100), min(100.0, (c + s) / d * 100))


def pct(k, n):
    return "%.1f%%" % (100.0 * k / n) if n else "-"
