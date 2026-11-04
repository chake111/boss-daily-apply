# -*- coding: utf-8 -*-
"""自检：不碰真实台账，验证机械层没坏（默认含一次 headless 浏览器点击）。

用法：
    python scripts/selftest.py            # 全部跑一遍
    python scripts/selftest.py -v         # 打印每条命令的输出

它会在临时目录里造一份工作目录 + 假数据，然后逐条跑 CLI 并断言结果；
最后一节会真起一个 headless 浏览器，验证"免扩展自动点"这条链路（--no-browser 可跳过）。
适合改完代码、改完配置、以及别人 clone 下来先确认"装对了"。

**不需要 WebBridge，也不会写你的真实工作目录；浏览器用临时 profile、跑完自己退出。**
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

        print("\n[8] 通用性：换浏览器 / 换智能体 / 无浏览器")
        # 记账测的是"全新用户的空台账"，所以另开一个干净目录，别被上面的 fixture 干扰
        wd2 = tempfile.mkdtemp(prefix="boss-selftest-ledger-")
        try:
            check("浏览器检测不依赖 Chrome", lambda: _json_has(
                run(["scripts/browser.py", "--json"], wd, expect_ok=False), "found"))
            check("ledger 空目录可用", lambda: _expect(
                run(["scripts/ledger.py", "status"], wd2), "已投递    0 条"))
            check("ledger add 记账", lambda: _expect(
                run(["scripts/ledger.py", "add", "--title", "前端开发实习生",
                     "--company", "星辰科技", "--direction", "前端开发"], wd2), "已记账"))
            check("ledger 写入后 status 跟上", lambda: _expect(
                run(["scripts/ledger.py", "status"], wd2), "已投递    1 条"))
            check("ledger 去重（同岗位不重复记）", lambda: _expect(
                run(["scripts/ledger.py", "add", "--title", "前端开发实习生",
                     "--company", "星辰科技"], wd2), "已存在同岗位"))
            check("ledger daily 记当日台账", lambda: _expect(
                run(["scripts/ledger.py", "daily", "--n", "3"], wd2), "今日累计 3 份"))
        finally:
            shutil.rmtree(wd2, ignore_errors=True)
        check("安装器能列出目标", lambda: _expect(
            run(["scripts/install.py", "--list"], wd), "workbuddy"))
        check("安装器支持 cursor 规则（dry-run）", lambda: _expect(
            run(["scripts/install.py", "--target", "cursor", "--project", wd, "--dry-run"], wd),
            ".cursor"))

        if "--no-browser" not in sys.argv:
            print("\n[9] CDP 后端：免扩展也能自动点（真起一个 headless 浏览器）")
            check("CDP 启动 + 传输层路由 + 点击", lambda: _cdp_roundtrip(wd))
        else:
            print("\n[9] CDP 后端：已跳过（--no-browser）")
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


def _cdp_roundtrip(wd):
    """真起一个 headless 浏览器，验证"免扩展自动化"这条链路。

    走的是上层脚本用的同一套接口（webbridge_client.evaluate/navigate/click），
    所以它通过 == 换后端不会破坏投递流程。
    """
    import importlib
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import scripts.cdp_client as cdp
    import scripts.webbridge_client as W

    os.environ["BOSS_CDP_PROFILE"] = os.path.join(wd, "cdp-profile")
    port = 9471
    ok, msg = cdp.launch(port=port, headless=True, wait=25)
    if not ok:
        raise AssertionError("起不来（没浏览器？）：" + msg)
    try:
        os.environ["BOSS_CDP_PORT"] = str(port)
        os.environ["BOSS_BACKEND"] = "cdp"

        if W.evaluate("1+1") != 2:
            raise AssertionError("evaluate 没返回 2")

        page = os.path.join(wd, "cdp.html")
        with open(page, "w", encoding="utf-8") as f:
            f.write("<title>cdp-test</title>"
                    "<button id='b' onclick='window.c=(window.c||0)+1'>go</button>")
        W.navigate("file:///" + page.replace("\\", "/"))
        if W.evaluate("document.title") != "cdp-test":
            raise AssertionError("navigate 后标题不对")

        if not W.click("#b"):
            raise AssertionError("click 返回 False")
        if W.evaluate("window.c || 0") != 1:
            raise AssertionError("点击没有触发 onclick")
    finally:
        cdp.close_browser(port)
        os.environ.pop("BOSS_BACKEND", None)
        os.environ.pop("BOSS_CDP_PORT", None)


def _json_has(text, key):
    """输出里含合法 JSON 且带指定字段（浏览器恰好一个都没装时退出码非 0，也要能解析）。"""
    start = text.find("{")
    if start < 0:
        raise AssertionError("没有 JSON 输出：\n%s" % text[-300:])
    data = json.loads(text[start:])
    if key not in data:
        raise AssertionError("JSON 缺字段 %r：%s" % (key, list(data)))


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
