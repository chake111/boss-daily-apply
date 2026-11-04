# -*- coding: utf-8 -*-
"""离线自检：不碰浏览器、不碰真实台账，验证机械层没坏。

用法：
    python scripts/selftest.py            # 全部跑一遍
    python scripts/selftest.py -v         # 打印每条命令的输出

它会在临时目录里造一份工作目录 + 假数据，然后逐条跑 CLI 并断言结果。
适合改完代码、改完配置、以及别人 clone 下来先确认"装对了"。

**不需要 WebBridge，也不会写你的真实工作目录。**
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
VERBOSE = "-v" in sys.argv

passed, failed = [], []


def run(args, workdir, expect_ok=True):
    env = dict(os.environ, BOSS_WORKDIR=workdir, PYTHONPATH=ROOT, BOSS_DEBUG="")
    p = subprocess.run([PY] + args, cwd=ROOT, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="ignore")
    out = (p.stdout or "") + (p.stderr or "")
    if VERBOSE:
        print("    $", " ".join(args[-3:]))
        for line in out.strip().splitlines()[:8]:
            print("      " + line)
    if expect_ok and p.returncode != 0:
        raise AssertionError("命令失败(%d): %s\n%s" % (p.returncode, " ".join(args), out[:600]))
    return out


def check(name, fn):
    try:
        fn()
        passed.append(name)
        print("  ✓", name)
    except Exception as e:
        failed.append((name, str(e)))
        print("  ✗", name, "→", str(e)[:300])


def make_fixture(wd):
    now = datetime.datetime.now()

    def ts(d):
        return (now - datetime.timedelta(days=d)).strftime("%Y-%m-%d %H:%M:%S")

    delivered = [
        {"jobId": "a1", "title": "前端开发实习生", "company": "星辰科技", "salary": "200-300元/天",
         "industry": "互联网", "direction": "前端开发", "keyword": "前端", "delivered_at": ts(5)},
        {"jobId": "b2", "title": "Java开发实习", "company": "云谷信息", "salary": "6-8K",
         "industry": "软件服务", "direction": "Java后端", "keyword": "Java", "delivered_at": ts(4)},
        {"jobId": "c3", "title": "AI应用开发实习", "company": "智言科技", "salary": "180-260元/天",
         "industry": "人工智能", "direction": "AI应用开发", "keyword": "AI", "delivered_at": ts(1)},
        {"jobId": "d4", "title": "后端开发实习生", "company": "云谷信息", "salary": "5-7K",
         "industry": "软件服务", "direction": "Java后端", "keyword": "后端"},
    ]
    json.dump({"delivered": delivered},
              open(os.path.join(wd, "stream_progress.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump({"rejected_jids": ["x1"], "keyword": "前端", "recommend_exhausted": True},
              open(os.path.join(wd, "walk_state.json"), "w", encoding="utf-8"),
              ensure_ascii=False)
    events = [
        {"company": "星辰科技", "kind": "要简历", "text": "发份简历", "date": ts(3)[:10]},
        {"company": "智言科技", "kind": "拒信", "text": "不太合适", "date": ts(1)[:10]},
    ]
    with open(os.path.join(wd, "reply_events.jsonl"), "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    rows = [
        {"keyword": "前端", "fresh": 12, "cards": 15, "pages": ["p1:8/15", "p2:4/15"], "error": ""},
        {"keyword": "Java", "fresh": 9, "cards": 15, "pages": ["p1:9/15"], "error": ""},
        {"keyword": "AI", "fresh": 14, "cards": 15, "pages": ["p1:9/15", "p2:5/15"], "error": ""},
        {"keyword": "Go实习", "fresh": 13, "cards": 15, "pages": ["p1:13/15"], "error": ""},
        {"keyword": "React实习", "fresh": 0, "cards": 0, "pages": ["p1:0/0?"], "error": "load_failed"},
    ]
    json.dump({"at": "fixture", "city": "101280600", "pages": 2, "rounds": 10,
               "rows": rows, "avail": {}, "alloc": {}, "plan": []},
              open(os.path.join(wd, "supply.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


def main():
    wd = tempfile.mkdtemp(prefix="boss-selftest-")
    try:
        print("临时工作目录:", wd, "\n")

        print("[1] 安装与配置")
        check("bootstrap 建目录 + 拷配置", lambda: (
            run(["scripts/bootstrap.py"], wd),
            os.path.exists(os.path.join(wd, "config", "blacklist.json")) or _raise("缺 blacklist.json"),
            os.path.exists(os.path.join(wd, "user_profile.json")) or _raise("缺 user_profile.json"),
        ))
        check("配置 JSON 全部合法", lambda: [
            json.load(open(os.path.join(wd, "config", f), encoding="utf-8"))
            for f in ("blacklist.json", "greetings.json")
        ] and json.load(open(os.path.join(ROOT, "config", "supply_mix.json"), encoding="utf-8")))

        print("\n[2] 机械否决")
        check("REJECT：外包公司", lambda: _expect(
            run(["scripts/screen.py", "--title", "AI应用开发", "--company", "科锐国际"], wd), "REJECT"))
        check("PASS：对口岗位", lambda: _expect(
            run(["scripts/screen.py", "--title", "前端开发实习生", "--company", "星辰科技"], wd), "PASS"))
        check("REVIEW：模糊词", lambda: _expect(
            run(["scripts/screen.py", "--title", "具身智能实习", "--company", "某科技"], wd), "REVIEW"))

        print("\n[3] 供给配额")
        make_fixture(wd)
        check("配额总数守恒（rounds=10）", lambda: _assert_sum(
            run(["scripts/supply_probe.py", "--reuse", "--rounds", "10"], wd), 10))
        check("权重 0 的方向不给份数（用不上）", lambda: _expect(
            run(["scripts/supply_probe.py", "--reuse", "--rounds", "10"], wd), "用不上"))
        check("加载失败不被当成挖空", lambda: _expect(
            run(["scripts/supply_probe.py", "--reuse", "--rounds", "10"], wd), "加载失败"))

        print("\n[4] 指标与台账")
        check("stats 产出报表", lambda: _exists(
            (run(["scripts/stats.py"], wd), os.path.join(wd, "回复率报表.md"))[1]))
        check("stats 分母只算已过窗", lambda: _expect(run(["scripts/stats.py"], wd), "观察中"))
        check("reply_check --list 不碰浏览器", lambda: _expect(
            run(["scripts/reply_check.py", "--list"], wd), "没有待办"))

        print("\n[5] 话术与收尾页")
        check("send_img2 --dry 按方向选桶", lambda: _expect(
            run(["scripts/send_img2.py", "3", "--msg", "--dry"], wd), "[ai]"))
        check("summary 页生成", lambda: _exists(
            (run(["scripts/phase_stream.py", "--mode", "report", "--workdir", wd], wd),
             os.path.join(wd, "投递汇总.html"))[1]))
        check("summary 页含投递记录", lambda: _expect(
            open(os.path.join(wd, "投递汇总.html"), encoding="utf-8").read(), "星辰科技"))
        check("未放赞赏码时不渲染打赏区块", lambda: _not_expect(
            open(os.path.join(wd, "投递汇总.html"), encoding="utf-8").read(), "打赏环节"))

        print("\n[6] 清理不伤台账")
        check("cleanup dry-run 不列台账文件", lambda: _not_expect(
            run(["scripts/cleanup.py", "--dry-run"], wd), "stream_progress.json"))
        check("cleanup dry-run 能认出诊断文件", lambda: _expect(
            (open(os.path.join(wd, "diag_1.json"), "w").close(),
             run(["scripts/cleanup.py", "--dry-run"], wd))[1], "diag_1.json"))

        print("\n[7] 无桥时的报错可读")
        check("driver 无桥 -> 修复指引（退出码 2）", lambda: _expect(
            run(["scripts/_live_driver.py", "walk"], wd, expect_ok=False), "不是脚本坏了"))
    finally:
        shutil.rmtree(wd, ignore_errors=True)

    print("\n" + "─" * 52)
    print("通过 %d / %d" % (len(passed), len(passed) + len(failed)))
    for name, err in failed:
        print("  ✗", name, "→", err[:200])
    return 0 if not failed else 1


def _raise(msg):
    raise AssertionError(msg)


def _expect(text, needle):
    if needle not in text:
        raise AssertionError("输出里没有 %r：\n%s" % (needle, text[-400:]))


def _not_expect(text, needle):
    if needle in text:
        raise AssertionError("不该出现 %r 却出现了" % needle)


def _exists(path):
    if not os.path.exists(path):
        raise AssertionError("文件不存在: " + path)


def _assert_sum(text, rounds):
    """从分配表里把「实投」列加起来，必须等于 rounds。"""
    total = 0
    seen = False
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0] not in ("方向",) and parts[1].isdigit() \
                and parts[2].isdigit() and parts[3].isdigit():
            total += int(parts[3])
            seen = True
    if not seen:
        raise AssertionError("没解析到分配表：\n%s" % text[-400:])
    if total != rounds:
        raise AssertionError("实投合计 %d ≠ rounds %d" % (total, rounds))


if __name__ == "__main__":
    sys.exit(main())
