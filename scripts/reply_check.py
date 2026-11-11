# -*- coding: utf-8 -*-
"""回复检查 / 应答待办：扫 BOSS 会话列表，把「需要我动作」的会话挑出来。

用法：
    python reply_check.py                 # 扫一遍，更新事件流 + 待办台账
    python reply_check.py --json          # 只输出 JSON
    python reply_check.py --list          # 只看待办台账（不碰浏览器）
    python reply_check.py --resolve ab12  # 标记某条待办已处理
    python reply_check.py --dump x.json   # 把抓到的会话原文存下来（可离线回放）
    python reply_check.py --from x.json   # 用存下来的原文跑一遍，不碰浏览器

为什么需要它：
    投递只完成前半段。HR 回复「方便发份简历」「请做网申」之后没人应答，
    前面投的全白费。

相对上一版改了什么（这版是为了让回复率算得出来）：
    1) 匹配不上投递记录的会话，不再拿整段会话原文当公司名（原来会把
       「09:32」这种时间戳写进 reply_log，导致报表里的公司名和投递记录
       永远对不上）；现在记为 `?<短哈希>` 并单独存原文。
    2) 每次扫描追加 reply_events.jsonl（事件流，只增不改）；报表从事件流取
       分子，分母用「已过 72h 观察窗」的投递，两边才可比。
    3) 待办落盘 pending_actions.json。会话列表只渲染最近 ~40 条，
       早的会消失（深投数科就是这么漏的）——落盘之后它还在台账里。
"""
import hashlib
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import paths  # noqa: E402
import metrics  # noqa: E402

PROGRESS = paths.state("stream_progress.json")
REPLY_LOG = paths.state("reply_log.json")
EVENTS = paths.state("reply_events.jsonl")
PENDING = paths.state("pending_actions.json")

ACTIONS = [
    ("要简历", ("发一份简历", "发份简历", "简历发我", "方便发一份", "简历过来", "发个简历", "投简历")),
    ("网申/测评", ("网申", "笔试", "测评", "测试链接", "在线测试", "完善简历")),
    ("约面试", ("面试", "面谈", "电话沟通", "什么时候方便", "约个时间", "聊聊")),
]
REJECT = ("很遗憾", "不合适", "不太合适", "不匹配", "匹配度", "不完全一致",
          "暂不考虑", "招满了", "一切顺利", "不适合", "暂时不适合")
SYSTEM = ("已发送给", "对方已同意", "已收到简历", "简历已发送", "已同意",
          "您正在与", "沟通中", "对方正在输入")

TIME_RE = re.compile(r"^(\d{1,2}:\d{2}|昨天|前天|星期[一二三四五六日]|\d{1,2}月\d{1,2}日)$")


# ---------- 抓取 ----------

def _eval_js(js):
    from scripts.webbridge_client import evaluate
    return evaluate(js) or ""


RAW_JS = """(function(){var ls=document.querySelectorAll('.user-list [role=listitem]');var o=[];
for(var i=0;i<ls.length;i++){var p=ls[i].innerText.split('\\n').map(function(s){return s.trim()})
.filter(function(s){return s});o.push(p.join('~~'));}return o.join('@@@@')})()"""


def fetch_raw():
    from scripts.webbridge_client import evaluate, navigate
    cur = evaluate("location.href") or ""
    if "/web/geek/chat" not in cur:
        navigate("https://www.zhipin.com/web/geek/chat", wait_range=(5, 7))
        time.sleep(2.5)
    for _ in range(6):
        evaluate("(function(){var b=document.querySelector('.user-list');if(b){b.scrollTop=b.scrollHeight;}return 1})()")
        time.sleep(1.0)
    raw = _eval_js(RAW_JS)
    return {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "raw": raw}


def parse_convs(raw):
    """把每个会话的若干行拆成 time / company / status / text。

    原来按固定下标取（parts[0]=时间, parts[1]=公司），一旦某个会话多了未读红点
    或系统提示行，整个顺序就错位——reply_log 里那几条「09:32」就是这么来的。
    这里改成按行内容判断，不依赖位置。
    """
    convs = []
    for it in (raw or "").split("@@@@"):
        lines = [x.strip() for x in it.split("~~") if x.strip()]
        if len(lines) < 2:
            continue
        t = next((x for x in lines if TIME_RE.match(x)), "")
        st = next((x for x in lines if x.startswith("[")), "")
        rest = [x for x in lines if x != t and x != st]
        convs.append({
            "time": t,
            "company": rest[0] if rest else "",
            "lines": rest,
            "status": st,
            "text": rest[-1] if len(rest) > 1 else "",
            "raw": " / ".join(lines),
        })
    return convs


# ---------- 判定 ----------

def _own_prefixes():
    """判断「最后一条是我方发言」用的前缀。

    以前这里写死了某一句招呼语的开头，换个人 / 换套文案就失效，会把
    「我发了但对方没回」误判成「对方说话」，回复率虚高。现在改成：
      ① greetings.json 里各方向话术的开头
      ② user_profile.json 的 own_greeting_prefix（你自己设的默认招呼语开头）
    两个都空时只剩 [已读] 标记可用，这时部分会话会被归成「对方说话」——
    所以强烈建议在档案里填 own_greeting_prefix。
    """
    out = []
    try:
        cfg = json.load(open(paths.config("greetings.json"), encoding="utf-8"))
        out += [b["text"][:8] for b in cfg.get("buckets", []) if b.get("text")]
    except Exception:
        pass
    try:
        from scripts.config import load_profile
        p = load_profile() or {}
        if p.get("own_greeting_prefix"):
            out.append(str(p["own_greeting_prefix"]))
    except Exception:
        pass
    return tuple(x for x in out if x)


OWN_PREFIXES = _own_prefixes()


def classify(c):
    ours = c["status"].startswith("[") or any(
        c["text"].startswith(p) for p in OWN_PREFIXES)
    if ours:
        return ("已读未回" if c["status"].startswith("[已读]") else "我方最后发言"), ""
    text = c["text"]
    blob = " ".join(c["lines"])
    if any(k in blob for k in REJECT):
        return "拒信", text[:90]
    for label, kws in ACTIONS:
        if any(k in text for k in kws):
            return label, text[:90]
    if any(k in text for k in SYSTEM):
        return "系统通知", text[:90]
    if text:
        return "对方说话", text[:90]
    return "未回复", ""


def slug(s):
    return hashlib.md5((s or "").encode("utf-8")).hexdigest()[:6]


# ---------- 落地 ----------

def append_events(rows):
    """事件流只增不改；同一天同一公司同一类同一句话只记一次。"""
    seen = set()
    if os.path.exists(EVENTS):
        for e in metrics.load_events():
            seen.add((e.get("date"), e.get("company"), e.get("kind"), e.get("text")))
    today = time.strftime("%Y-%m-%d")
    n = 0
    with open(EVENTS, "a", encoding="utf-8") as f:
        for r in rows:
            key = (today, r["company"], r["kind"], r["text"])
            if key in seen:
                continue
            ev = dict(r, date=today, at=time.strftime("%Y-%m-%d %H:%M:%S"))
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
            seen.add(key)
            n += 1
    return n


def load_pending():
    if not os.path.exists(PENDING):
        return []
    try:
        return json.load(open(PENDING, encoding="utf-8"))
    except Exception:
        return []


def save_pending(rows):
    json.dump(rows, open(PENDING, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def upsert_pending(rows):
    """按公司+类别合并；同一件事只留一条，刷新 last_seen。

    没在本轮出现的老待办不删——它可能只是滑出了会话列表。
    """
    pend = load_pending()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    by_key = {(p["company"], p["kind"]): p for p in pend}
    for r in rows:
        k = (r["company"], r["kind"])
        if k in by_key:
            p = by_key[k]
            p["last_seen"] = now
            p["text"] = r["text"]
            p["seen_in_scan"] = True
        else:
            # 匹配不上投递记录时，company 是 ?哈希（不参与指标），
            # 但台账里得让人认得出是谁，所以另存 display
            p = {"id": slug(r["company"] + r["kind"]), "company": r["company"],
                 "display": r.get("raw_company") if r["company"].startswith("?")
                            else r["company"],
                 "unmatched": r["company"].startswith("?"),
                 "jobId": r.get("jobId", ""), "title": r.get("title", ""),
                 "kind": r["kind"], "text": r["text"],
                 "first_seen": now, "last_seen": now, "status": "open",
                 "seen_in_scan": True}
            pend.append(p)
            by_key[k] = p
    for p in pend:
        if (p["company"], p["kind"]) not in {(r["company"], r["kind"]) for r in rows}:
            p["seen_in_scan"] = False
    save_pending(pend)
    return pend


# ---------- 主流程 ----------

def scan(convs, records):
    out = []
    for c in convs:
        kind, text = classify(c)
        hit, sc = metrics.best_match(c["raw"], records)
        if hit:
            company, jid, title = hit.get("company"), hit.get("jobId", ""), hit.get("title", "")
        else:
            company, jid, title = "?" + slug(c["company"] or c["raw"]), "", ""
        out.append({"company": company, "jobId": jid, "title": title,
                    "kind": kind, "text": text, "time": c["time"],
                    "matched": bool(hit), "score": sc,
                    "raw_company": c["company"], "raw": c["raw"][:200]})
    return out


def show_todo(pend):
    open_ = [p for p in pend if p.get("status") == "open"]
    if not open_:
        print("没有待办。")
        return
    now = time.time()
    print("\n【待我动作 · 台账】共 %d 条" % len(open_))
    for p in sorted(open_, key=lambda x: x.get("first_seen") or ""):
        try:
            age = (now - time.mktime(time.strptime(p["first_seen"], "%Y-%m-%d %H:%M:%S"))) / 3600
        except Exception:
            age = 0
        flag = "" if p.get("seen_in_scan") else "  ⚠️ 已滑出会话列表，需手动搜"
        who = p.get("display") or p["company"]
        if p.get("unmatched"):
            who += "（未匹配岗位）"
        print(" %s  %-18s %-8s %4.1fh  %s%s" % (p["id"], who[:18], p["kind"],
                                                 age, p["text"][:40], flag))


def main():
    args = sys.argv[1:]
    records = metrics.load_progress(PROGRESS)

    if "--list" in args:
        show_todo(load_pending())
        return

    if "--resolve" in args:
        rid = args[args.index("--resolve") + 1]
        pend = load_pending()
        hit = [p for p in pend if p["id"] == rid]
        if not hit:
            print("没有这条待办:", rid)
            return
        hit[0]["status"] = "resolved"
        hit[0]["resolved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        save_pending(pend)
        print("已标记处理:", rid, hit[0]["company"], hit[0]["kind"])
        return

    if "--from" in args:
        data = json.load(open(args[args.index("--from") + 1], encoding="utf-8"))
        convs = parse_convs(data.get("raw", ""))
    else:
        from scripts.webbridge_client import require_bridge
        require_bridge()          # 抓会话必须连桥；连不上就给出修复指引，别甩堆栈
        data = fetch_raw()
        if "--dump" in args:
            path = args[args.index("--dump") + 1]
            json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            print("已存会话原文:", path)
        convs = parse_convs(data["raw"])

    rows = scan(convs, records)
    # 进事件流的：算「有回复」的类别（含系统通知，用于指标）
    acted = [r for r in rows if r["kind"] in metrics.REPLY_KINDS]
    # 进待办台账的：只有真的要我做点什么的那几类
    todo_rows = [r for r in rows if r["kind"] in ("要简历", "网申/测评", "约面试", "对方说话")]
    rejects = [r for r in rows if r["kind"] == "拒信"]

    n_ev = append_events(acted + rejects)

    # 兼容老格式：公司名一定来自投递记录（或 ?哈希），不再写会话原文
    log = {}
    if os.path.exists(REPLY_LOG):
        try:
            log = json.load(open(REPLY_LOG, encoding="utf-8"))
        except Exception:
            log = {}
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    for r in acted + rejects:
        e = log.setdefault(r["company"], {"first_seen": now, "kind": r["kind"],
                                          "text": r["text"], "handled": False})
        e["last_kind"] = r["kind"]
        e["last_text"] = r["text"]
        e["last_check"] = now
        if not r["matched"]:
            e["unmatched"] = True
            e["raw_company"] = r["raw_company"]
    json.dump(log, open(REPLY_LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    pend = upsert_pending(todo_rows)

    if "--json" in args:
        print(json.dumps({"rows": rows, "pending": pend}, ensure_ascii=False))
        return

    unmatched = [r for r in rows if not r["matched"] and r["kind"] not in ("我方最后发言", "已读未回", "未回复")]
    print("会话 %d 条 / 有动静 %d 条 / 新增事件 %d 条 / 待我动作 %d 条"
          % (len(convs), len(acted) + len(rejects), n_ev,
             len([p for p in pend if p.get("status") == "open"])))
    if rejects:
        print("【已拒，可归档】%s" % "、".join(x["company"][:14] for x in rejects))
    if unmatched:
        print("【未匹配到投递记录】%d 条（已记 ?哈希，不参与回复率）" % len(unmatched))
        for r in unmatched[:5]:
            print("   -", (r["raw_company"] or r["raw"])[:40], "|", r["kind"])
    show_todo(pend)


if __name__ == "__main__":
    main()
