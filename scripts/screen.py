# -*- coding: utf-8 -*-
"""机械否决：投递前先过一遍，命中的直接 reject、不 open。

用法：
    python screen.py --title "财务实习生" --company "某公司" --industry "互联网"
    python screen.py --title "AI应用开发" --company "科锐国际" --industry "人力资源服务"
    python screen.py --jd-file jd.txt --title ...        # 有 JD 正文时一并过
    echo '{"title":"x","company":"y"}' | python screen.py --json

判定：
    REJECT  命中硬红线，直接 reject，不用读 JD
    REVIEW  只命中"值得看一眼"的模糊词（仿真/多模态/管培生等），去 open 读 JD
    PASS    机械层面干净，正常 open 读 JD

注意：这里只处理无歧义的机械红线。方向是否对口、JD 是不是"标题写开发正文全是装软件"，
仍由智能体读完 JD 判断——不要把语义判断塞进这个文件。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import paths  # noqa: E402

CFG = paths.config("blacklist.json")


def load():
    return json.load(open(CFG, encoding="utf-8"))


def screen(title="", company="", industry="", salary="", jd="", cfg=None):
    cfg = cfg or load()
    hits = []
    t, c, i, j = title or "", company or "", industry or "", jd or ""

    for kw in cfg["company_name_reject"]:
        if kw in c:
            hits.append(("HARD", "公司黑名单:" + kw))
    for kw in cfg["company_suffix_reject"]:
        if kw in c:
            hits.append(("HARD", "公司名含:" + kw))
    for kw in cfg["industry_reject"]:
        if kw and kw in i:
            hits.append(("HARD", "行业:" + kw))
    for kw in cfg["title_reject"]:
        if kw in t:
            hits.append(("HARD", "标题含:" + kw))
    for kw in cfg["jd_hard_reject"]:
        if kw and kw in j:
            hits.append(("HARD", "JD含:" + kw))

    for kw in cfg["title_review"]:
        if kw in t:
            hits.append(("SOFT", "标题含模糊词:" + kw))
    for kw in cfg["jd_soft_flags"]:
        if kw and kw in j:
            hits.append(("SOFT", "JD提示:" + kw))

    hard = [h for h in hits if h[0] == "HARD"]
    soft = [h for h in hits if h[0] == "SOFT"]
    verdict = "REJECT" if hard else ("REVIEW" if soft else "PASS")
    return {"verdict": verdict, "hits": hits}


def main():
    if "--json" in sys.argv:
        data = json.load(sys.stdin)
        print(json.dumps(screen(**{k: data.get(k, "") for k in
                                   ("title", "company", "industry", "salary", "jd")}),
                         ensure_ascii=False))
        return

    args = {}
    key = None
    for a in sys.argv[1:]:
        if a.startswith("--"):
            key = a[2:].replace("-", "_")
            args.setdefault(key, "")
        elif key:
            args[key] = (args[key] + " " + a).strip()

    jd = args.get("jd", "")
    if args.get("jd_file") and os.path.exists(args["jd_file"]):
        jd = open(args["jd_file"], encoding="utf-8", errors="ignore").read()

    r = screen(title=args.get("title", ""), company=args.get("company", ""),
               industry=args.get("industry", ""), salary=args.get("salary", ""), jd=jd)
    print(r["verdict"])
    for sev, why in r["hits"]:
        print("  -", sev, why)


if __name__ == "__main__":
    main()
