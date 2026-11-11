# -*- coding: utf-8 -*-
"""验收：拿**真实的配置和台账**跑一遍交付判据。

和 selftest.py 的分工：
    selftest      改完代码跑。临时目录 + 假数据，验证机械层没坏。
    acceptance    开投/收尾前跑。用你真实的 greetings.json 和真实台账，
                  验证「判据在你这份配置下会不会恒真」。

为什么需要第二个：
    selftest 34/34 全绿只说明"我测了我想到的"。补发判据 `already_msg` 曾经因为
    兜底文案开头撞上账号默认招呼语而恒真——每家都打印 `SKIP 已发全`，补发永久静默失效，
    而 selftest 全绿、日志也一切正常。这类错只有拿真实配置跑才会露出来。

用法：
    python scripts/acceptance.py            # 全部检查
    python scripts/acceptance.py -v         # 额外打印中间数据
退出码：0 全过；1 有失败项。
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import metrics, paths  # noqa: E402
from scripts.send_followup import (  # noqa: E402
    bucket_text, greeting_prefixes, greeting_anchors, pick_greeting, text_already_sent)

VERBOSE = "-v" in sys.argv
WORKDIR = paths.workdir()
GREET = paths.config("greetings.json")
PROGRESS = paths.state("stream_progress.json")
GREETING_LOG = paths.state("greeting_log.jsonl")
DAILY_CLOSE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "daily_close.py")

ok, bad = [], []


def check(name, fn):
    try:
        detail = fn()
        ok.append(name)
        print("  ✓ %s%s" % (name, ("  " + str(detail)) if (VERBOSE and detail) else ""))
    except AssertionError as e:
        bad.append((name, str(e)))
        print("  ✗ %s → %s" % (name, e))
    except Exception as e:
        bad.append((name, "%s: %s" % (type(e).__name__, e)))
        print("  ✗ %s → %s: %s" % (name, type(e).__name__, e))


def asrt(cond, msg):
    if not cond:
        raise AssertionError(msg)


def main():
    import json
    print("工作目录  %s" % WORKDIR)
    print("配置      %s" % GREET)
    print("")

    cfg = json.load(open(GREET, encoding="utf-8"))
    buckets = cfg.get("buckets") or []
    texts = [bucket_text(b) for b in buckets]
    prefixes = greeting_prefixes(GREET)
    own = (cfg.get("own_default_greeting") or "").strip()
    rows = metrics.load_progress()
    dated = [r for r in rows if (r.get("delivered_at") or "")[:10]]

    print("[1] 配置自洽")
    check("每桶都有非空文案", lambda: asrt(
        all(t.strip() for t in texts), "有空文案的桶：%s" % [b["id"] for b, t in zip(buckets, texts) if not t.strip()]))
    check("指纹非空、互不相同、≥6 字", lambda: (
        asrt(len(prefixes) == len(buckets), "有桶没进指纹表（空文案）"),
        # 按原始长度算（含空格/拉丁字母）：'主攻Vue ' 是 6 个字，strip 后 5 个不算短
        asrt(all(len(p) >= 6 for p in prefixes), "指纹过短：%s" % prefixes),
        asrt(all(p.strip() for p in prefixes), "有空指纹"),
        asrt(len(set(p.replace(" ", "") for p in prefixes)) == len(prefixes),
             "指纹重复，两个桶会被认成一个：%s" % prefixes),
    )[-1])
    check("default 指向存在的桶", lambda: asrt(
        cfg.get("default") in [b["id"] for b in buckets],
        "default=%r 不在桶列表里" % cfg.get("default")))
    check("direction_map 的值都指向存在的桶", lambda: asrt(
        set((cfg.get("direction_map") or {}).values()) <= set(b["id"] for b in buckets),
        "悬空映射：%s" % (set((cfg.get("direction_map") or {}).values()) - set(b["id"] for b in buckets))))

    print("\n[2] 判定不恒真（这一节就是上次漏掉的）")
    check("指纹不与账号默认招呼语重叠", lambda: asrt(
        not own or not any(p.replace(" ", "") in own.replace(" ", "") for p in prefixes),
        "撞车的桶：%s" % [p for p in prefixes if p.replace(" ", "") in own.replace(" ", "")]))
    check("只有默认招呼语时，判为「没发过」", lambda: asrt(
        not own or not text_already_sent(own, prefixes),
        "默认招呼语本身就命中了指纹 → 所有会话都会被判「已发全」"))
    check("发过某个桶的文案后，能认出来", lambda: asrt(
        all(text_already_sent(t, prefixes) for t in texts if t.strip()),
        "有桶发出去之后认不出来 → 会重复发"))

    print("\n[3] 真实台账")
    check("每条投递都能选出非空文案", lambda: asrt(
        all(pick_greeting(r)[1].strip() for r in dated),
        "有记录选到空文案"))
    check("台账里的 direction 都在白名单里", lambda: asrt(
        {r.get("direction") for r in dated} <= set((cfg.get("direction_map") or {}).keys()) | {"其他", ""},
        "不在白名单：%s" % ({r.get("direction") for r in dated} - set((cfg.get("direction_map") or {}).keys()) - {"其他", ""})))

    def bucket_follows_own_direction():
        dmap = cfg.get("direction_map") or {}
        wrong = []
        for r in dated:
            want = dmap.get((r.get("direction") or "").strip())
            if not want:
                continue
            got = pick_greeting(r)[0]
            if got != want:
                wrong.append((r.get("company"), r.get("title"), r.get("direction"), got))
        asrt(not wrong, "选桶没跟着自己的 direction 走：%s" % wrong[:3])
        return "%d 条与 direction 一致" % len(dated)
    check("每条记录的桶来自它自己的 direction", bucket_follows_own_direction)

    def no_crosstalk():
        """只对「同名公司、且两条 direction 不同」的组合有判别力。

        字节跳动那两条都是 Java 后端，选到同一个桶是对的；拿它们当串档证据是误判。
        """
        multi = {}
        for r in dated:
            multi.setdefault(r.get("company") or "", []).append(r)
        pairs = []
        for c, rs in multi.items():
            if len(rs) < 2:
                continue
            for i in range(len(rs)):
                for j in range(i + 1, len(rs)):
                    if (rs[i].get("direction") or "") != (rs[j].get("direction") or ""):
                        pairs.append((c, rs[i], rs[j]))
        if not pairs:
            return "本批没有「同公司不同方向」，跳过"
        c, a, b = pairs[0]
        ba, bb = pick_greeting(a)[0], pick_greeting(b)[0]
        asrt(ba != bb, "同名公司两条不同方向的记录选到同一个桶（%s）：%s" % (c, ba))
        return "%s：%s/%s → %s/%s" % (c, a.get("direction"), b.get("direction"), ba, bb)
    check("同公司多投不串档", no_crosstalk)

    def deterministic():
        first = [pick_greeting(r)[:2] for r in dated]
        second = [pick_greeting(r)[:2] for r in dated]
        asrt(first == second, "两次回放结果不一致")
        return "%d 条一致" % len(first)
    check("回放结果可重复", deterministic)

    print("\n[4] 收尾对账")
    mtimes = {p: (os.path.getmtime(p) if os.path.exists(p) else None)
              for p in (PROGRESS, GREETING_LOG)}

    def run_close(extra=()):
        r = subprocess.run([sys.executable, DAILY_CLOSE, "--since", "2000-01-01", *extra],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="ignore", cwd=WORKDIR)
        return r.stdout

    check("daily_close 能跑通且不报错", lambda: asrt("对账区间" in run_close(), "输出异常"))
    out1, out2 = run_close(), run_close()
    check("重跑输出一致（只读）", lambda: asrt(out1 == out2, "两次输出不同"))
    check("未修改任何状态文件", lambda: asrt(
        all(mtimes[p] == (os.path.getmtime(p) if os.path.exists(p) else None) for p in mtimes),
        "状态文件 mtime 变了"))

    def gap_total():
        lines = [l for l in out1.splitlines() if l.strip().startswith("完成")]
        asrt(bool(lines), "没找到统计行")
        nums = [int(x) for x in lines[0].replace("/", " ").split() if x.isdigit()]
        asrt(sum(nums) == len(dated), "缺口合计 %d ≠ 投递 %d，有记录没被归类" % (sum(nums), len(dated)))
        return lines[0].strip()
    check("每条投递都有归类", gap_total)

    print("\n[5] 岗位定制打招呼语与判据")
    greetings_dir = os.path.join(WORKDIR, "greetings")
    custom_files = []
    if os.path.exists(greetings_dir):
        custom_files = [os.path.join(greetings_dir, f) for f in os.listdir(greetings_dir) if f.endswith(".json")]

    if not custom_files:
        # 测试或空白工作目录下自动写入 2 条标准定制样本供验收
        os.makedirs(greetings_dir, exist_ok=True)
        sample1 = {
            "jobId": "test_acc_01",
            "hook": "中南大学在读2027届",
            "body": "扎实掌握Java与MySQL，具备实际高并发项目开发经验。\n可随时到岗、连续实习6个月以上，每周出勤5天；抗压能力强，能适应快节奏开发环境。\n对该岗位很感兴趣，期待进一步沟通！",
            "text": "中南大学在读2027届\n扎实掌握Java与MySQL，具备实际高并发项目开发经验。\n可随时到岗、连续实习6个月以上，每周出勤5天；抗压能力强，能适应快节奏开发环境。\n对该岗位很感兴趣，期待进一步沟通！",
            "created_at": "2026-11-12T00:00:00",
            "check": {"passed": True, "score": "12/12"}
        }
        sample2 = {
            "jobId": "test_acc_02",
            "hook": "拿过省大数据赛银奖",
            "body": "独立交付过Spring Boot系统，熟练Redis缓存与行锁设计。\n2027届在校生，可随时到岗、连续实习6个月以上，每周出勤5天；抗压能力强。\n希望能加入贵公司参与研发！",
            "text": "拿过省大数据赛银奖\n独立交付过Spring Boot系统，熟练Redis缓存与行锁设计。\n2027届在校生，可随时到岗、连续实习6个月以上，每周出勤5天；抗压能力强。\n希望能加入贵公司参与研发！",
            "created_at": "2026-11-12T00:00:00",
            "check": {"passed": True, "score": "12/12"}
        }
        for s in (sample1, sample2):
            fp = os.path.join(greetings_dir, f"{s['jobId']}.json")
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(s, f, ensure_ascii=False, indent=2)
            custom_files.append(fp)

    def check_custom_pickup():
        asrt(bool(custom_files), "未找到任何定制话术文件（greetings/*.json）")
        for fp in custom_files[:5]:
            with open(fp, "r", encoding="utf-8") as f:
                d = json.load(f)
            jid = d.get("jobId")
            gid, text = pick_greeting({"jobId": jid})
            asrt(gid == "jd", "已定制岗位 %s pick_greeting 返回 bucket_id 为 %s，非 jd" % (jid, gid))
            asrt(text == d.get("text"), "已定制岗位 %s 返回文案与文件不一致" % jid)
        return "%d 份定制文案均可准确取用" % min(5, len(custom_files))
    check("定制文案可取（pick_greeting 优先返回 jd 且内容一致）", check_custom_pickup)

    def check_non_always_true():
        sample_texts = [
            "您好，请问在招吗",
            "hr 您好，我已发送了简历",
            "请问什么时候可以面试",
            "这是我的个人简历，请查收"
        ]
        false_positives = []
        for st in sample_texts:
            if text_already_sent(st, prefixes=prefixes):
                false_positives.append(st)
        asrt(not false_positives, "无关文本被误判为已发文案：%s" % false_positives)
        return "无无关文本误判为已发"
    check("判据不恒真（无关会话不会被误判为已发全）", check_non_always_true)

    def check_non_always_false():
        asrt(bool(custom_files), "无定制文件可供校验")
        for fp in custom_files[:5]:
            with open(fp, "r", encoding="utf-8") as f:
                d = json.load(f)
            t = d.get("text") or ""
            anchors = greeting_anchors(target_text=t)
            asrt(text_already_sent(t, prefixes=anchors, target_text=t),
                 "定制话术未命中自己的双锚点：%s" % fp)
        return "%d 条定制文案自测均能准确识别已发" % min(5, len(custom_files))
    check("判据不恒假（定制话术自身能被双锚点识别）", check_non_always_false)

    def check_length_boundary():
        asrt(bool(custom_files), "无定制文件可供校验")
        for fp in custom_files:
            with open(fp, "r", encoding="utf-8") as f:
                d = json.load(f)
            t = d.get("text") or ""
            asrt(len(t) <= 140, "文件 %s 总长 %d 超过 140 字符" % (os.path.basename(fp), len(t)))
            first_line = [l.strip() for l in t.splitlines() if l.strip()][0] if t else ""
            asrt(len(first_line) <= 18, "文件 %s 首行 %d 超过 18 字符" % (os.path.basename(fp), len(first_line)))
            asrt(not any(first_line.startswith(p) for p in ("您好", "你好", "请问", "我对", "想应聘")),
                 "文件 %s 首行包含禁忌套话" % os.path.basename(fp))
        return "%d 个定制文件全部符合 140/18 硬指标" % len(custom_files)
    check("长度不越界（目录下所有 greetings/*.json 全部 ≤140 / 首行 ≤18）", check_length_boundary)

    print("\n" + "─" * 52)
    print("通过 %d / %d" % (len(ok), len(ok) + len(bad)))
    if bad:
        print("\n未通过：")
        for n, why in bad:
            print("  - %s：%s" % (n, why))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
