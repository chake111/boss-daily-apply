# -*- coding: utf-8 -*-
"""无浏览器 / 无扩展模式的记账本：手动投，脚本管统计。

为什么需要它
------------
自动化那条链路（WebBridge + 浏览器）不是所有人都愿意搭：公司电脑装不了扩展、
只用 Firefox、或者就是不想让脚本碰账号。这些情况下 skill 仍然有用——
判断标准、去重规则、回复率口径都还在，只是"点投递"这一步由你自己做。

那就需要一个地方记：投了谁、拒了谁。这个文件就是它，写的是和 driver
**完全一样**的 schema，所以 stats.py / phase_stream.py 不用改就能出报表。

用法：
    python scripts/ledger.py add --title "前端开发实习生" --company "某某科技" \\
        --salary "200-300元/天" --industry 互联网 --direction 前端开发 --keyword 前端
    python scripts/ledger.py reject --title "销售实习生" --company "某贸易"
    python scripts/ledger.py list --limit 20
    python scripts/ledger.py today
    python scripts/ledger.py import jobs.csv      # 表头：title,company,salary,industry,direction,keyword

配套：
    python scripts/stats.py                       # 直接出回复率报表（口径与自动模式一致）
    python scripts/phase_stream.py --mode report --workdir <工作目录>
"""
import argparse
import csv
import datetime
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import paths  # noqa: E402

PROGRESS = "stream_progress.json"
WALK = "walk_state.json"


def _load(name, default):
    p = paths.state(name)
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception:
        return default


def _save(name, data):
    """先写临时文件再 replace：中途断掉也不会留下半个 JSON。"""
    paths.ensure_workdir()
    p = paths.state(name)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def manual_id(company, title):
    """手动记录没有 jobId，用「公司+岗位」的短哈希占位。

    为什么不用随机 id：重复执行同一条命令时要能被认出来是同一个岗位，
    否则去重和「同公司最多 2 个」的规则都会失效。
    """
    h = hashlib.md5((company + "|" + title).encode("utf-8")).hexdigest()[:8]
    return "manual-" + h


def _warn_direction(direction):
    """方向不在白名单只警告不拦。

    手动补录时常见「旧标签」和批量 csv 导入，硬拒会让一份百行台账在第 3 行夭折，
    反而留下半份数据。警告足够——真正决定话术的是补发那一刻的记录。
    """
    d = (direction or "").strip()
    try:
        cfg = json.load(open(paths.config("greetings.json"), encoding="utf-8"))
        allowed = list((cfg.get("direction_map") or {}).keys()) + ["其他", ""]
    except Exception:
        return
    if d not in allowed:
        print("⚠️ direction「%s」不在白名单里，补发会走 generic 兜底。可选：%s"
              % (direction, "、".join(x for x in allowed if x)))


def cmd_add(a):
    prog = _load(PROGRESS, {"delivered": []})
    rows = prog.setdefault("delivered", [])
    jid = a.job_id or manual_id(a.company, a.title)

    for r in rows:
        if r.get("jobId") == jid or (r.get("company") == a.company and r.get("title") == a.title):
            if not a.force:
                print("已存在同岗位记录，跳过（要强制再加一条用 --force）：")
                print("  %s / %s  @ %s" % (r.get("company"), r.get("title"), r.get("delivered_at", "?")))
                return 0

    same_company = sum(1 for r in rows if r.get("company") == a.company)
    if same_company >= 2 and not a.force:
        print("⚠️ 该公司已有 %d 条记录，按「同公司本轮最多 2 个」的规则建议跳过。" % same_company)
        print("   确定要记就用 --force。")

    _warn_direction(a.direction)

    rec = {
        "jobId": jid,
        "title": a.title,
        "company": a.company,
        "salary": a.salary,
        "industry": a.industry,
        "direction": a.direction,
        "keyword": a.keyword,
        "city": a.city,
        "delivered_at": a.at or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "manual",
    }
    rows.append(rec)
    _save(PROGRESS, prog)
    print("✓ 已记账 #%d  %s / %s  @ %s" % (len(rows), a.company, a.title, rec["delivered_at"]))
    return 0


def cmd_reject(a):
    st = _load(WALK, {})
    rj = list(st.get("rejected_jids") or [])
    jid = a.job_id or manual_id(a.company or "", a.title or "")
    if not a.job_id and not (a.company or a.title):
        print("要么给 --job-id，要么给 --company / --title（用来生成占位 id）")
        return 2
    if jid in rj:
        print("已经在判否名单里了：", jid)
        return 0
    rj.append(jid)
    st["rejected_jids"] = rj
    _save(WALK, st)
    print("✓ 已判否 %s（累计 %d 条）" % (jid, len(rj)))
    return 0


def _pad(s, width):
    """按显示宽度补齐：中文占 2 列，用 ljust 会对不齐。"""
    import unicodedata
    s = (s or "")
    w = sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)
    return s + " " * max(0, width - w)


def cmd_status(a):
    """开工基线：投了多少、拒了多少、今天记了几条。

    收尾时再跑一次，两个数字相减就是本轮成果——比数总数可靠，
    因为旧记录没有 delivered_at，光看"今天几条"会漏。
    """
    prog = _load(PROGRESS, {"delivered": []})
    st = _load(WALK, {})
    rows = prog.get("delivered", [])
    today = datetime.date.today().isoformat()
    dated = [r for r in rows if r.get("delivered_at")]
    print("工作目录  " + paths.WORKDIR)
    print("已投递    %d 条（其中 %d 条带时间戳）" % (len(rows), len(dated)))
    print("已判否    %d 条" % len(st.get("rejected_jids") or []))
    print("今日已记  %d 条" % sum(1 for r in dated if (r.get("delivered_at") or "")[:10] == today))
    if len(rows) - len(dated):
        print("          （%d 条旧记录无时间戳，不计入今日）" % (len(rows) - len(dated)))
    return 0


def cmd_list(a):
    prog = _load(PROGRESS, {"delivered": []})
    rows = prog.get("delivered", [])[-a.limit:]
    if not rows:
        print("还没有投递记录。用 add 记第一条：")
        print('  python scripts/ledger.py add --title "前端开发实习生" --company "某某科技"')
        return 0
    print(_pad("#", 4) + _pad("公司", 24) + _pad("岗位", 24) + _pad("薪资", 16)
          + _pad("方向", 12) + "投递时间")
    for i, r in enumerate(rows, 1):
        print(_pad(str(i), 4) + _pad((r.get("company") or "")[:22], 24)
              + _pad((r.get("title") or "")[:22], 24)
              + _pad((r.get("salary") or "")[:14], 16)
              + _pad((r.get("direction") or "")[:10], 12)
              + (r.get("delivered_at") or "（无时间戳）"))
    st = _load(WALK, {})
    print("\n合计 %d 条投递 / %d 条判否" % (len(prog.get("delivered", [])),
                                        len(st.get("rejected_jids") or [])))
    return 0


def cmd_today(a):
    prog = _load(PROGRESS, {"delivered": []})
    today = datetime.date.today().isoformat()
    rows = [r for r in prog.get("delivered", []) if (r.get("delivered_at") or "")[:10] == today]
    legacy = sum(1 for r in prog.get("delivered", []) if not r.get("delivered_at"))
    print("今日已记 %d 条" % len(rows))
    for r in rows:
        print("  - %s / %s" % (r.get("company"), r.get("title")))
    if legacy:
        print("（另有 %d 条旧记录没有时间戳，不计入今日）" % legacy)
    return 0


def cmd_import(a):
    if not os.path.exists(a.file):
        print("文件不存在:", a.file)
        return 2
    prog = _load(PROGRESS, {"delivered": []})
    rows = prog.setdefault("delivered", [])
    have = {(r.get("company"), r.get("title")) for r in rows}
    n = skipped = 0
    with open(a.file, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            title = (row.get("title") or "").strip()
            company = (row.get("company") or "").strip()
            if not title or not company:
                continue
            if (company, title) in have and not a.force:
                skipped += 1
                continue
            rows.append({
                "jobId": row.get("jobId") or manual_id(company, title),
                "title": title,
                "company": company,
                "salary": (row.get("salary") or "").strip(),
                "industry": (row.get("industry") or "").strip(),
                "direction": (row.get("direction") or "").strip(),
                "keyword": (row.get("keyword") or "").strip(),
                "city": (row.get("city") or "").strip(),
                "delivered_at": (row.get("delivered_at") or "").strip()
                                or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "source": "import",
            })
            have.add((company, title))
            n += 1
    _save(PROGRESS, prog)
    print("✓ 导入 %d 条（跳过重复 %d 条）" % (n, skipped))
    return 0


def cmd_daily(a):
    """当日台账：记一笔本轮份数，并打印今日累计。

    "今日累计"必须靠这个文件，不能靠数 stream_progress——旧记录没有 delivered_at，
    数出来会少一截；也不能靠 memory，人会记错。不带 --n 就只读不写。
    """
    p = paths.state("daily_log.json")
    log = _load("daily_log.json", {})
    d = datetime.date.today().isoformat()
    if a.n:
        log.setdefault(d, []).append({
            "n": a.n,
            "at": datetime.datetime.now().strftime("%H:%M"),
        })
        _save("daily_log.json", log)
        print("✓ 已记一笔 %d 份 @ %s" % (a.n, datetime.datetime.now().strftime("%H:%M")))
    rounds = log.get(d) or []
    if not rounds:
        print("今日还没有记录。收尾时用：python scripts/ledger.py daily --n <本轮份数>")
        return 0
    print("今日明细：" + "、".join("%s(%d)" % (r.get("at", "?"), r.get("n", 0)) for r in rounds))
    print("今日累计 %d 份" % sum(int(r.get("n") or 0) for r in rounds))
    if sum(int(r.get("n") or 0) for r in rounds) >= 130:
        print("⚠️ 已过 130 份，再往上容易被平台限流，建议收工。")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="手动记账（无浏览器模式）：投了谁、拒了谁，写进和 driver 相同的台账")
    ap.add_argument("--workdir", default="", help="工作目录（默认 BOSS_WORKDIR）")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("add", help="记一条投递")
    p.add_argument("--title", required=True)
    p.add_argument("--company", required=True)
    p.add_argument("--salary", default="")
    p.add_argument("--industry", default="")
    p.add_argument("--direction", default="", help="方向标签，决定补发话术和报表分组")
    p.add_argument("--keyword", default="", help="从哪个搜索词看到的")
    p.add_argument("--city", default="")
    p.add_argument("--job-id", default="")
    p.add_argument("--at", default="", help="投递时间，默认当前；补录旧数据时用")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("reject", help="记一条判否")
    p.add_argument("--job-id", default="")
    p.add_argument("--title", default="")
    p.add_argument("--company", default="")
    p.set_defaults(fn=cmd_reject)

    p = sub.add_parser("list", help="看最近记录")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("status", help="开工/收尾基线（投递数、判否数、今日数）")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("daily", help="当日台账：记一笔本轮份数 / 看今日累计")
    p.add_argument("--n", type=int, default=0, help="本轮份数；不给就只读")
    p.set_defaults(fn=cmd_daily)

    p = sub.add_parser("today", help="今日计数")
    p.set_defaults(fn=cmd_today)

    p = sub.add_parser("import", help="从 CSV 批量导入")
    p.add_argument("file")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_import)

    a = ap.parse_args()
    if a.workdir:
        # paths 在 import 时就固定了 WORKDIR，这里改环境变量后同步一下即可
        os.environ["BOSS_WORKDIR"] = a.workdir
        paths.WORKDIR = paths.workdir()
    if not getattr(a, "fn", None):
        ap.print_help()
        return 2
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
