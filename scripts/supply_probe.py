# -*- coding: utf-8 -*-
"""开工前的供给探测：哪个关键词还有"没投过、没判否过"的新卡，以及本轮该往哪个方向投多少。

用法：
    python scripts/supply_probe.py                     # 默认 2 页，按 40 份配额分配
    python scripts/supply_probe.py --rounds 30         # 本轮计划投 30 份
    python scripts/supply_probe.py --pages 3           # 每词看 3 页
    python scripts/supply_probe.py --keywords "Java实习,React实习"
    python scripts/supply_probe.py --job-type ""       # 不加实习筛选（默认 1902）
    python scripts/supply_probe.py --reuse             # 不重探，用现有 supply.json 重算配额

输出：每词的 fresh + 每方向的「目标 / 可用 / 实投」+ 建议投放顺序，写 <工作目录>/supply.json。

为什么要它
----------
1) 固定几个词的顺序轮着投，会把时间浪费在早已挖空的词上。先探再投。
2) 更要紧的是**结构**：AI 岗位在 BOSS 上供给天然多，纯按 fresh 降序排，
   实测 40 份里有 20 份落在 AI 方向（50%），而简历里撑 AI 的可能只有 1 个项目
   —— 投得最猛的方向恰好是证据最弱的方向。所以按「证据强度」给目标配额
   （见 config/supply_mix.json），供给不够的方向自动封顶、缺口回补给还有货的方向。

关键参数 jobType
----------------
`jobType=1902` = 求职类型「实习」，筛选生效时页面筛选栏显示"求职类型(1)"。
`1901` 曾被当成实习用过，**实测无效**（筛选栏虽显示已选，卡里混着 5-10 年社招）。
宽词（前端/Java/后端/React/Vue/AI/全栈/Python）配上 1902 才有稳定供给，
旧的"方向+实习"长词在挖空之后基本只返回重复卡。

注意：结果集每次请求会重排，同一页两次加载的卡可能不同 —— 所以 fresh=0 只作参考，
投的过程中仍以 walk 的实际呈现为准。
"""
import argparse
import json
import os
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import paths  # noqa: E402
from scripts.webbridge_client import evaluate, navigate  # noqa: E402
from scripts.config_v3 import load_profile  # noqa: E402

OUT = paths.state("supply.json")

# 关键词矩阵（按历史实测产出排序）
# ⚠️ 实测结论：**"届别 + 方向"这种组合词无效**。
#    `2027届 后端` / `2027届 前端` 这类词返回的是同一批卡片（测试工程师/给排水工程师/
#    结构工程师/管培生/营销专员），说明 BOSS 把"届别"当主词、后面的方向词基本被忽略。
#    届别只能靠 JD 里那句"2027届"来判，不能靠搜索词。真正有效的是"岗位方向 + 实习"。
DEFAULT_KEYWORDS = [
    # 宽词（配 jobType=1902 供给最稳，挖空风险最低）
    "前端", "Java", "后端", "React", "Vue", "AI", "全栈", "Python",
    # 前端 —— 证据强度通常最高
    "前端开发实习", "前端开发实习生", "Web前端实习",
    # 用「React前端实习」而不是「React实习」：后者在 BOSS 上是全文匹配，
    # 实测搜出来的是 go实习生 / 移动端实习生 / python实习生，fresh 看着多但对口率低。
    "React前端实习", "Vue实习", "小程序开发实习",
    # Java 后端
    "Java实习", "Java开发实习", "后端开发实习", "Spring Boot实习",
    # AI 应用
    "AI应用开发实习", "AI应用开发", "Agent开发实习",
    # 全栈 / 通用 / Python
    "全栈开发实习", "软件开发实习", "Python实习",
    # 数据 —— 无生产数据工程证据时建议只探测不主动投
    "数据开发实习",
    # 其他语言（技术栈里没有就别给配额）
    "Node实习", "Go实习",
]

# 默认配比：按「简历证据强度」排，不按「哪边岗位多」排。
# 真实用户请改 config/supply_mix.json（或用 user_profile.json 的 direction_mix 覆盖）。
DEFAULT_MIX = [
    ("前端开发", 0.40),
    ("Java后端", 0.25),
    ("AI应用开发", 0.20),
    ("数据开发", 0.05),
    ("其他", 0.10),
    ("用不上", 0.00),   # 权重 0 = 永不分配，但仍会打印「可用」让你看见供给
]

# 关键词 -> 方向的兜底规则。config/supply_mix.json 的 keyword_direction 优先。
KW_RULES = [
    ("前端开发", ("前端", "React", "Vue", "小程序", "Web")),
    ("Java后端", ("Java", "后端", "Spring", "MyBatis")),
    ("AI应用开发", ("AI", "Agent", "大模型", "LLM", "智能体", "算法")),
    ("数据开发", ("数据", "ETL", "数仓")),
    ("Python开发", ("Python",)),
]
NO_QUOTA = ("Go",)   # 技术栈里没有的方向：照常探测，不给配额

JIDS_JS = """(function(){var s=document.querySelectorAll('a[href*="job_detail"]'),o=[];
for(var i=0;i<s.length;i++){var m=s[i].href.match(/job_detail\\/([^.]+)\\.html/);if(m)o.push(m[1]);}
return o.join(',')})()"""


def load_mix():
    """配比与词表：user_profile.direction_mix > config/supply_mix.json > 内置默认。"""
    profile = load_profile() or {}
    mix, keywords, kw_dir = DEFAULT_MIX, DEFAULT_KEYWORDS, {}
    try:
        cfg = json.load(open(paths.config("supply_mix.json"), encoding="utf-8"))
        if isinstance(cfg.get("mix"), list) and cfg["mix"]:
            mix = [(d, float(w)) for d, w in cfg["mix"]]
        if isinstance(cfg.get("keywords"), list) and cfg["keywords"]:
            keywords = cfg["keywords"]
        kw_dir = dict(cfg.get("keyword_direction") or {})
    except Exception:
        pass
    dm = profile.get("direction_mix")
    if isinstance(dm, dict) and dm:
        # 跳过以 _ 开头的注释键，并容忍写错的权重（别为一个笔误整轮跑不动）
        try:
            parsed = [(d, float(w)) for d, w in dm.items() if not str(d).startswith("_")]
        except (TypeError, ValueError):
            parsed = []
        if parsed:
            mix = parsed
    for kw in keywords:
        if kw in kw_dir:
            continue
        if any(k in kw for k in NO_QUOTA):
            kw_dir[kw] = "用不上"
        else:
            for d, keys in KW_RULES:
                if any(k in kw for k in keys):
                    kw_dir[kw] = d
                    break
            else:
                kw_dir[kw] = "其他"
    return mix, keywords, kw_dir


def load_seen():
    seen = set()
    try:
        p = json.load(open(paths.state("stream_progress.json"), encoding="utf-8"))
        seen |= {x.get("jobId") for x in p.get("delivered", [])}
        seen |= {x.get("jobId") for x in p.get("failed", [])}
    except Exception:
        pass
    try:
        w = json.load(open(paths.state("walk_state.json"), encoding="utf-8"))
        seen |= set(w.get("rejected_jids") or [])
    except Exception:
        pass
    seen.discard(None)
    return seen


def make_url(keyword, city, page, job_type):
    url = ("https://www.zhipin.com/web/geek/jobs?query=%s&city=%s&page=%s"
           % (urllib.parse.quote(keyword), city, page))
    return url + ("&jobType=%s" % job_type if job_type else "")


def _fetch_page(url):
    """取一页的 jobId 列表。取不到就返回 None，由调用方决定要不要重试。"""
    try:
        navigate(url, wait_range=(4, 6))
    except Exception:
        return None
    time.sleep(1.6)
    return [x for x in (evaluate(JIDS_JS) or "").split(",") if x]


def probe(keyword, pages, seen, city, job_type):
    """探一个词。0 张卡要分两种：真没结果、还是页面没加载出来。

    实测教训：首轮某个词返回 p1:0/0 被记成「已挖空」，复测同一词 fresh=11 ——
    那次是加载失败。把失败当挖空，会让配额分配凭空少一个方向，
    而且下一轮还会被告知「别再花时间」。
    """
    per_page, fresh_all, total = [], [], 0
    load_failed = False
    for page in range(1, pages + 1):
        url = make_url(keyword, city, page, job_type)
        jids = _fetch_page(url)
        if jids is None:
            per_page.append("p%d:NAV_ERR" % page)
            load_failed = True
            break
        if page == 1 and not jids:
            time.sleep(2.0)
            jids = _fetch_page(url) or []       # 首屏 0 张，多半是没加载完，重试一次
            if not jids:
                load_failed = True
                per_page.append("p1:0/0?")
                break
        fresh = [x for x in jids if x not in seen]
        fresh_all.extend(fresh)
        total += len(jids)
        per_page.append("p%d:%d/%d" % (page, len(fresh), len(jids)))
        if not jids:
            break
        if not fresh and page >= 2:
            break          # 连着一页没新卡就别再翻
    return {"keyword": keyword, "fresh": len(set(fresh_all)),
            "cards": total, "pages": per_page,
            "error": "load_failed" if (load_failed and not fresh_all) else ""}


def pad(s, width):
    """按终端显示宽度补齐：中文算 2 列，不然表头永远对不齐。"""
    import unicodedata
    w = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)
    return s + " " * max(0, width - w)


def allocate(rows, rounds, mix, kw_dir):
    """按目标结构把 rounds 份分到各方向，再分到具体关键词。

    先按权重给目标，再看每方向还有多少 fresh；不够的方向按实际能力封顶，
    余量回补给还有货的方向（优先小数部分大的），最后在方向内部按 fresh 比例拆到词。

    为什么要归一化 + 逐个补余量：权重和可能不等于 1（比如配比表里没有
    `Python开发`，它沿用「其他」的权重后总和变成 1.1），直接 round 会让总数超过
    rounds；而某方向被可用量封顶后，余量又必须回补。两者都不能靠一次 round 解决。
    """
    avail = {}
    for r in rows:
        d = kw_dir.get(r["keyword"], "其他")
        avail[d] = avail.get(d, 0) + max(0, r["fresh"])

    weight = dict(mix)
    # 词表里出现了配比表没列的方向时，沿用「其他」的权重，而不是给 0——
    # 否则探测到了却永远分不到份数，看起来像 bug。
    for d in avail:
        weight.setdefault(d, weight.get("其他", 0.0))

    active = [d for d in avail if weight.get(d, 0.0) > 0 and avail[d] > 0]
    wsum = sum(weight[d] for d in active) or 1.0
    raw = {d: rounds * weight[d] / wsum for d in active}

    alloc = {d: 0 for d in avail}
    for d in active:
        alloc[d] = min(int(raw[d]), avail[d])

    # 余量回补：最大余数法——先按小数部分给每个方向补 1 份（不重复给同一方向，
    # 否则小方向会吃掉本该属于主方向的名额）；还有剩（说明有方向被可用量封顶了）
    # 再按同样顺序循环补，直到补满或被全部封顶。
    left = rounds - sum(alloc.values())
    by_frac = sorted(active, key=lambda d: -(raw[d] - int(raw[d])))
    for d in by_frac:
        if left <= 0:
            break
        if alloc[d] < avail[d]:
            alloc[d] += 1
            left -= 1
    guard = 0
    while left > 0 and guard < 500:
        guard += 1
        cands = [d for d in by_frac if alloc[d] < avail[d]]
        if not cands:
            break
        alloc[cands[0]] += 1
        left -= 1

    # 方向内部：按 fresh 比例拆到词（最大余数法）
    plan = []
    for d in avail:
        slots = alloc.get(d, 0)
        kws = [r for r in rows if kw_dir.get(r["keyword"], "其他") == d and r["fresh"] > 0]
        if not slots or not kws:
            continue
        kws.sort(key=lambda x: -x["fresh"])
        tot = sum(k["fresh"] for k in kws)
        frac = [(k, slots * k["fresh"] / tot) for k in kws]
        give = {k["keyword"]: int(v) for k, v in frac}
        rest = slots - sum(give.values())
        for k, v in sorted(frac, key=lambda x: -(x[1] - int(x[1])))[:max(0, rest)]:
            give[k["keyword"]] += 1
        for k in kws:
            if give.get(k["keyword"], 0) > 0:
                plan.append({"keyword": k["keyword"], "dir": d,
                             "fresh": k["fresh"], "take": give[k["keyword"]]})
    plan.sort(key=lambda x: (-x["take"], -x["fresh"]))
    return avail, alloc, plan, raw, wsum


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--keywords", default="")
    ap.add_argument("--top", type=int, default=0)
    ap.add_argument("--rounds", type=int, default=40, help="本轮计划投几份，用于配额分配")
    ap.add_argument("--job-type", default="1902",
                    help="求职类型筛选，1902=实习（默认）；传空串则不加筛选")
    ap.add_argument("--city", default="", help="城市编码，默认取 user_profile.city_code")
    ap.add_argument("--reuse", action="store_true", help="不重新探测，直接用现有 supply.json 重算配额")
    a = ap.parse_args()

    paths.ensure_workdir()
    if not a.reuse:
        from scripts.webbridge_client import require_bridge
        require_bridge()          # 桥没起来就没必要逐词导航，先给出修复指引
    profile = load_profile() or {}
    city = a.city or profile.get("city_code") or ""
    if not city:
        print("⚠️ 没有城市编码：在 user_profile.json 里填 city_code（深圳=101280600），"
              "否则搜的是全国，fresh 会失真。")
    mix, default_kws, kw_dir = load_mix()

    if a.reuse:
        if not os.path.exists(OUT):
            print("没有 supply.json，先跑一次完整探测")
            return
        rows = json.load(open(OUT, encoding="utf-8"))["rows"]
        print("复用 %s 的探测结果（%d 个词，不再访问浏览器）\n" % (OUT, len(rows)), flush=True)
    else:
        rows = None

    kws = [k.strip() for k in a.keywords.split(",") if k.strip()] if a.keywords else default_kws
    seen = load_seen() if rows is None else set()
    if rows is None:
        print("已知投递/判否 %d 条，探测 %d 个词 × %d 页（jobType=%s）\n"
              % (len(seen), len(kws), a.pages, a.job_type or "无"), flush=True)
        rows = []
        for i, kw in enumerate(kws, 1):
            r = probe(kw, a.pages, seen, city, a.job_type)
            rows.append(r)
            flag = " ⚠️加载失败" if r.get("error") else ""
            print("%2d. %s [%s] fresh=%-3d %s%s"
                  % (i, pad(kw, 20), pad(kw_dir.get(kw, "其他"), 10), r["fresh"],
                     " ".join(r["pages"]), flag), flush=True)

    avail, alloc, plan, raw, wsum = allocate(rows, a.rounds, mix, kw_dir)

    print("\n本轮目标 %d 份，按证据强度分配（不是按 fresh 多少）：" % a.rounds)
    print("  %s %5s %5s %5s" % (pad("方向", 12), "目标", "可用", "实投"))
    order = [d for d, _ in mix if d in avail] + [d for d in avail if d not in dict(mix)]
    for d in order:
        target = int(round(raw.get(d, 0.0))) if d in raw else 0
        print("  %s %5d %5d %5d" % (pad(d, 12), target, avail[d], alloc.get(d, 0)))

    print("\n建议投放顺序：")
    for i, p in enumerate(plan[:a.top or len(plan)], 1):
        print("  %2d) %s %s 投 %d 份（可用 %d）"
              % (i, pad(p["keyword"], 20), pad(p["dir"], 10), p["take"], p["fresh"]))

    empty = [r["keyword"] for r in rows if r["fresh"] == 0 and not r.get("error")]
    failed = [r["keyword"] for r in rows if r.get("error")]
    if empty:
        print("\n已挖空（下轮别再花时间）: " + "、".join(empty))
    if failed:
        print("\n⚠️ 加载失败（不是挖空，别据此下结论）: " + "、".join(failed))
        print("   这几个词的配额按 0 算了，实际可能有余量——补测一次再定。")

    total_fresh = sum(r["fresh"] for r in rows)
    if total_fresh < a.rounds:
        print("\n⚠️ 供给不足：全部 fresh 合计 %d 张 < 目标 %d 份。"
              "不要降标准凑数，换宽词 / 提高 pages / 等平台刷新。" % (total_fresh, a.rounds))

    json.dump({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "city": city,
               "pages": a.pages, "rounds": a.rounds, "job_type": a.job_type,
               "rows": rows, "avail": avail, "alloc": alloc, "plan": plan},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\n已写入", OUT)


if __name__ == "__main__":
    main()
