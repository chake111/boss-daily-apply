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


def run(args, workdir, expect_ok=True, extra_env=None):
    env = dict(os.environ, BOSS_WORKDIR=workdir, PYTHONPATH=ROOT, BOSS_DEBUG="")
    if extra_env:
        env.update(extra_env)
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
        # 同公司第二个方向：按记录选桶的回归用例（以前按公司名反查，d4/e5 会互相覆盖）
        {"jobId": "e5", "title": "大数据开发实习生", "company": "云谷信息", "salary": "6-9K",
         "industry": "软件服务", "direction": "数据开发", "keyword": "大数据",
         "delivered_at": ts(2)},
        # 未知方向：兜底桶用例（不该再落到 AI 文案）
        {"jobId": "f6", "title": "计算机专业实习生", "company": "云易证", "salary": "350元/天",
         "industry": "计算机软件", "direction": "其他", "keyword": "React",
         "delivered_at": ts(2)},
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
        check("stage 能记、去重、拒非法阶段", lambda: _stage_e2e(wd))
        check("decide 看到约面并算出断点", lambda: _decide_e2e(wd))

        print("\n[5] 话术与收尾页")
        # 用公司过滤而不是"最近 3 条"：后者会被 fixture 增删记录带偏（以前这条断言
        # 依赖 fixture 的排列顺序，加一条记录就会红）。
        check("send_followup --dry 按方向选桶", lambda: _expect(
            run(["scripts/send_followup.py", "1", "智言科技", "--dry"], wd), "[ai]"))
        check("同公司双投按记录选桶（不串档）", lambda: _expect_all(
            run(["scripts/send_followup.py", "1", "云谷信息", "--dry"], wd),
            ["[backend]", "[python]"]))
        check("未知方向走 generic 兜底", lambda: _expect(
            run(["scripts/send_followup.py", "1", "云易证", "--dry"], wd), "[generic]"))
        check("direction 白名单拒绝未登记方向", lambda: _expect(
            run(["scripts/_live_driver.py", "deliver", "zz9", "某公司",
                 "200元/天", "互联网", "算法工程"], wd), "BAD_DIRECTION"))
        check("daily_close 只读对账能跑通", lambda: _expect(
            run(["scripts/daily_close.py", "--since", "2000-01-01"], wd), "对账区间"))
        check("acceptance 在样例目录全绿", lambda: _not_expect(
            run(["scripts/acceptance.py"], wd), "未通过"))
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

        print("\n[7] 后端选择与补发批次安全")
        check("backend 默认优先 CDP（mock）", _backend_defaults_to_cdp)
        check("CDP bring_to_front 映射 Target.activateTarget", _cdp_bring_to_front_unit)
        check("补发预检区分浏览器死、登录墙、列表未就绪", _preflight_classification)
        check("空标题/EXC 停批，不伪装成标题不符", _header_classification)
        check("--pending 从最旧的积压开始取", _pending_picks_oldest)
        check("--pending 默认跳过无投递时间的历史记录", _pending_skips_legacy)
        check("同公司双岗：定位选对，选不出来就拒绝", _locate_js_picks_right_conv)

        print("\n[8] 无通道时的报错可读")
        # BOSS_BACKEND=none 把两条通道都按掉，保证测的是"没环境"这条分支，
        # 不受本机是否正好开着浏览器 / WebBridge 影响
        check("driver 无通道 -> 修复指引（退出码 2）", lambda: _expect(
            run(["scripts/_live_driver.py", "walk"], wd, expect_ok=False,
                extra_env={"BOSS_BACKEND": "none"}), "不是脚本坏了"))

        print("\n[9] 通用性：换浏览器 / 换智能体 / 无浏览器")
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
        check("首次向导体检模式可用", lambda: _expect(
            run(["scripts/onboard.py", "--check"], wd), "环境可用"))

        print("\n[10] 档案迁移必须显式")
        sentinel = os.path.join(ROOT, "user_profile.json")
        saved = None
        if os.path.exists(sentinel):
            saved = open(sentinel, encoding="utf-8").read()
        try:
            with open(sentinel, "w", encoding="utf-8") as f:
                json.dump({"name": "SELFTEST-SENTINEL", "target_city": "测试城",
                           "city_code": "1", "role_summary": "自制哨兵档案"},
                          f, ensure_ascii=False)
            wd_m1 = tempfile.mkdtemp(prefix="boss-selftest-mig1-")
            wd_m2 = tempfile.mkdtemp(prefix="boss-selftest-mig2-")
            try:
                check("默认不自动迁移（会提示，但不复制）", lambda: _no_migrate(wd_m1))
                check("--migrate 显式迁移才复制", lambda: _yes_migrate(wd_m2))
            finally:
                shutil.rmtree(wd_m1, ignore_errors=True)
                shutil.rmtree(wd_m2, ignore_errors=True)
        finally:
            if saved is None:
                os.remove(sentinel)
            else:
                open(sentinel, "w", encoding="utf-8").write(saved)

        if "--no-browser" not in sys.argv:
            print("\n[11] CDP 后端：免扩展也能自动点（真起一个 headless 浏览器）")
            check("CDP 启动 + 传输层路由 + 点击 + 前台切换", lambda: _cdp_roundtrip(wd))
        else:
            print("\n[11] CDP 后端：已跳过（--no-browser）")

        print("\n[12] 定位器组：改版后还找得到东西")
        check("locators 生成的 JS 全部语法合法", lambda: _locators_js_parse())
        check("结构兜底找到面板，且不会拿左列表冒充", lambda: _locator_structure_fallback())
        check("面板移出 DOM 后旧引用立刻失效", lambda: _detail_ref_drops_dead_node())
        check("面板 ka 校验不认无关岗位", lambda: _panel_ka_false_on_other())

        print("\n[13] 点击有效性：不再「返回 true 但没点动」")
        check("鼠标点了没效果时自动改用 JS 点击", lambda: _click_verified_falls_back())
        check("无通道时 js_click 安静返回 False", lambda: _click_verified_no_backend())
        check("click_card 卡片不存在时返回 absent", lambda: _click_card_absent())

        print("\n[14] 词表健康：挖空的词会被跳过")
        check("record 两轮 fresh=0 后判枯竭", lambda: _kw_exhausted())
        check("加载失败/翻页失效的轮次不算挖空", lambda: _kw_failed_round_ignored())
        check("某一轮又有货就自动解除", lambda: _kw_revive())
        check("reset 能清掉误判", lambda: _kw_reset())
        check("supply_probe 跳过已挖空的词", lambda: _probe_skips_exhausted(wd))
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


def _expect_all(text, needles):
    for n in needles:
        if n not in text:
            raise AssertionError("缺少 %r\n--- 实际输出 ---\n%s" % (n, text))


def _exists(path):
    if not os.path.exists(path):
        raise AssertionError("文件不存在: " + path)


def _stage_e2e(wd):
    """进度台账：能写、重复写不撑大漏斗、非法阶段被拒。"""
    _expect(run(["scripts/stage.py", "log", "星辰科技", "约面"], wd), "已记录")
    _expect(run(["scripts/stage.py", "log", "星辰科技", "约面"], wd), "已存在")
    _expect(run(["scripts/stage.py", "log", "星辰科技", "三面"], wd, expect_ok=False),
            "BAD_STAGE")
    _expect(run(["scripts/stage.py", "list"], wd), "星辰科技")
    lines = [l for l in open(os.path.join(wd, "interview_log.jsonl"),
                             encoding="utf-8").read().splitlines() if l.strip()]
    if len(lines) != 1:
        raise AssertionError("重复记录不该追加行，实际 %d 行" % len(lines))


def _decide_e2e(wd):
    """决策看板：约面要真的进漏斗，否则它和 stats.py 没有区别。"""
    run(["scripts/decide.py"], wd)
    md = open(os.path.join(wd, "决策看板.md"), encoding="utf-8").read()
    _expect_all(md, ["转化链", "| 面试 | 1 |", "| 有效推进 | 1 |", "## 断点"])


def _backend_defaults_to_cdp():
    """不依赖真实端口：CDP 可用时不得被扩展或 Playwright 抢先。"""
    from unittest.mock import patch
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import scripts.webbridge_client as W
    saved_env = os.environ.get("BOSS_BACKEND")
    saved_cache = dict(W._BACKEND)
    os.environ.pop("BOSS_BACKEND", None)
    W._BACKEND.update(name="", at=0.0)
    try:
        with patch.object(W, "_port_up", return_value=True), \
                patch.object(W, "bridge_alive", return_value=True) as bridge:
            if W.backend(force=True) != "cdp":
                raise AssertionError("CDP 可用时 backend() 没选 CDP")
            if bridge.called:
                raise AssertionError("CDP 已可用，不该再探测 WebBridge")
    finally:
        W._BACKEND.clear()
        W._BACKEND.update(saved_cache)
        if saved_env is None:
            os.environ.pop("BOSS_BACKEND", None)
        else:
            os.environ["BOSS_BACKEND"] = saved_env


def _cdp_bring_to_front_unit():
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import scripts.cdp_client as cdp

    class Anchor:
        def __init__(self):
            self.calls = []

        def send(self, method, params):
            self.calls.append((method, params))
            return {}

    backend = cdp.Backend()
    anchor = Anchor()
    backend.conns["boss-main"] = anchor
    backend.owned["boss-main"] = "target-1"
    result = backend.api("bring_to_front", {}, session="boss-main")
    if not result.get("data", {}).get("ok"):
        raise AssertionError("bring_to_front 返回失败")
    expected = [("Target.activateTarget", {"targetId": "target-1"})]
    if anchor.calls != expected:
        raise AssertionError("CDP 调用不对：%r" % (anchor.calls,))


def _preflight_classification():
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from scripts.send_followup import classify_batch_state
    chat = "https://www.zhipin.com/web/geek/chat"
    cases = [
        (("", 0, "", ""), "BROWSER_DEAD"),
        ((chat, 0, "EXC: websocket closed", ""), "BROWSER_DEAD"),
        (("https://passport.zhipin.com/login", 0, "", ""), "LOGIN_REQUIRED"),
        (("https://www.zhipin.com/verify?x=1", 0, "", ""), "LOGIN_REQUIRED"),
        ((chat, 4, "", "请完成安全验证后继续"), "LOGIN_REQUIRED"),
        ((chat, 0, "", ""), "LIST_NOT_READY"),
        ((chat, 4, "", ""), "OK"),
    ]
    for args, want in cases:
        got = classify_batch_state(*args)[0]
        if got != want:
            raise AssertionError("%r 应判 %s，实际 %s" % (args, want, got))


def _header_classification():
    """ok=True 但标题为空/EXC 必须停批，不能伪装成「标题不符」继续下一家。"""
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from scripts.send_followup import classify_header_state as cls
    cases = [
        (("腾讯", "腾讯 | 前端实习生", "", ""), "OK"),
        (("深圳用图科技有限公司", "深圳用图科技 | AI开发实习生", "", ""), "OK"),
        (("腾讯", "", "", ""), "LIST_NOT_READY"),
        (("腾讯", "   ", "", ""), "LIST_NOT_READY"),
        (("腾讯", "EXC: Execution context was destroyed", "", ""), "LIST_NOT_READY"),
        (("腾讯", "", "BROWSER_DEAD", "CDP 不可用"), "BROWSER_DEAD"),
        (("腾讯", "", "LOGIN_REQUIRED", "检测到安全验证"), "LOGIN_REQUIRED"),
        (("腾讯", "字节跳动 | 后端开发", "", ""), "TITLE_MISMATCH"),
        # 右侧标题栏可能不显示公司名，只要岗位片段一致就放行（点击前已按公司键命中）
        (("ONES", "冯斌 / 联合创始人 / AI Agent 开发实习生", "", "", "AI Agent 开发实习生"), "OK"),
        (("ONES", "冯斌 / 联合创始人 / 前端实习生", "", "", "AI Agent 开发实习生"), "TITLE_MISMATCH"),
        # 同公司两个岗位只差【】里的标签：4 字前缀会让「【实习】」同时命中两条
        (("Shopee", "【实习】大数据开发 / HR / 在线", "", "", "【实习】大数据开发"), "OK"),
        (("Shopee", "【实习】前端开发 / HR / 在线", "", "", "【实习】大数据开发"), "TITLE_MISMATCH"),
        (("Anker", "大数据开发实习生", "", "", "AI应用开发实习生"), "TITLE_MISMATCH"),
    ]
    for args, want in cases:
        got, why = cls(*args)
        if got != want:
            raise AssertionError("%r 应判 %s，实际 %s（%s）" % (args, want, got, why))


def _pending_picks_oldest():
    """--pending 必须从**最旧**的积压开始，而不是每次都盯台账最新几条。

    2026-11-05 的真实故障：resolve_targets 先 rows[-limit:] 截尾、后过滤已完成，
    于是 `5 --pending` 永远只看最新 5 条；那 5 条补齐后每批都"没有记录"，
    积压 50 条一条不补就收工。这个用例把顺序钉死。
    """
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import tempfile
    import scripts.send_followup as S

    d = tempfile.mkdtemp(prefix="pending-")
    prog = os.path.join(d, "stream_progress.json")
    glog = os.path.join(d, "greeting_log.jsonl")
    rows = [{"jobId": "j%d" % i, "company": "c%d" % i, "title": "岗%d" % i,
             "delivered_at": "2026-11-03 10:00:%02d" % i} for i in range(1, 11)]
    with open(prog, "w", encoding="utf-8") as f:
        json.dump({"delivered": rows}, f, ensure_ascii=False)
    with open(glog, "w", encoding="utf-8") as f:
        for i in (1, 2, 3):      # 最旧的三条已补齐
            f.write(json.dumps({"event": "send", "status": "OK", "jobId": "j%d" % i,
                                "company": "c%d" % i}, ensure_ascii=False) + "\n")

    old_prog, old_log = S.PROGRESS, S.GREETING_LOG
    S.PROGRESS, S.GREETING_LOG = prog, glog
    try:
        got = [r["jobId"] for r in S.resolve_targets(2, pending=True)]
        if got != ["j4", "j5"]:
            raise AssertionError("limit=2 应从最旧积压取 j4,j5，实际 %r" % (got,))
        got_all = [r["jobId"] for r in S.resolve_targets(0, pending=True)]
        if got_all != ["j%d" % i for i in range(4, 11)]:
            raise AssertionError("不限量应给出全部 7 条积压，实际 %r" % (got_all,))
    finally:
        S.PROGRESS, S.GREETING_LOG = old_prog, old_log


def _pending_skips_legacy():
    """无 delivered_at 的历史记录默认不算积压，否则会一直啃几周前的老岗位。"""
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import tempfile
    import scripts.send_followup as S

    d = tempfile.mkdtemp(prefix="legacy-")
    prog = os.path.join(d, "stream_progress.json")
    glog = os.path.join(d, "greeting_log.jsonl")
    old_rows = [{"jobId": "old%d" % i, "company": "老%d" % i, "title": "旧岗"} for i in range(2)]
    new_rows = [{"jobId": "new%d" % i, "company": "新%d" % i, "title": "新岗",
                 "delivered_at": "2026-11-04 09:00:00"} for i in range(2)]
    with open(prog, "w", encoding="utf-8") as f:
        json.dump({"delivered": old_rows + new_rows}, f, ensure_ascii=False)
    open(glog, "w", encoding="utf-8").close()

    old_prog, old_log = S.PROGRESS, S.GREETING_LOG
    S.PROGRESS, S.GREETING_LOG = prog, glog
    try:
        got = [r["jobId"] for r in S.resolve_targets(5, pending=True)]
        if got != ["new0", "new1"]:
            raise AssertionError("默认应排除无日期历史记录，实际 %r" % (got,))
        got2 = [r["jobId"] for r in S.resolve_targets(5, pending=True, include_legacy=True)]
        if got2 != ["old0", "old1", "new0", "new1"]:
            raise AssertionError("--include-legacy 应把历史记录排在最前，实际 %r" % (got2,))
        # --job 是显式寻址，历史记录也要能选中
        got3 = [r["jobId"] for r in S.resolve_targets(5, job_id="old1", pending=True)]
        if got3 != ["old1"]:
            raise AssertionError("--job 应能选中历史记录，实际 %r" % (got3,))
    finally:
        S.PROGRESS, S.GREETING_LOG = old_prog, old_log


def _locate_js_picks_right_conv():
    """同公司两岗位名只差前缀时，定位必须选对，选不出来要报 ambiguous。

    真跑 send_followup._locate_js 生成的 JS（不是另写一份逻辑），用 node 加载。
    2026-11-05 的串档就是 title[:4] = 「【实习】」两条都命中，点了第一条。
    """
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    import shutil
    import tempfile
    from scripts.send_followup import _locate_js, company_keys, title_probes

    node = shutil.which("node")
    if not node:
        print("    (skip: 本机没有 node)")
        return

    fixture = [
        {"brandName": "Shopee", "jobName": "【实习】前端开发"},
        {"brandName": "Shopee", "jobName": "【实习】大数据开发"},
        {"brandName": "Anker", "jobName": "大数据开发实习生"},
        {"brandName": "Anker", "jobName": "AI应用开发实习生"},
        {"brandName": "腾讯", "jobName": "前端实习生"},
        {"brandName": "双岗同司", "jobName": "后端开发"},
        {"brandName": "双岗同司", "jobName": "后端开发"},
    ]
    cases = [
        ("Shopee", "【实习】大数据开发", 1, "same_shopee"),
        ("Anker", "AI应用开发实习生", 3, "same_anker"),
        ("腾讯", "前端实习生", 4, "single"),
        ("双岗同司", "后端开发", -1, "tie"),          # 两条一样像 -> 不许猜
        ("不存在的公司", "前端实习生", -1, "missing"),
        ("腾讯", "", 4, "no_title_single"),            # 不传岗位名：唯一会话可直接选
        ("双岗同司", "", -1, "no_title_multi"),        # 不传岗位名 + 两个会话 -> 拒绝
    ]
    d = tempfile.mkdtemp(prefix="locate-")
    try:
        for company, title, want, tag in cases:
            js = _locate_js(company_keys(company), title_probes(title))
            path = os.path.join(d, tag + ".js")
            with open(path, "w", encoding="utf-8") as f:
                f.write("const dataSources = %s;\n" % json.dumps(fixture, ensure_ascii=False))
                f.write("global.document = {querySelector: s => s === '.user-list-content'"
                        " ? {__vue__: {$props: {dataSources}}} : null};\n")
                f.write("console.log(%s);\n" % js)
            out = subprocess.run([node, path], capture_output=True, text=True,
                                 encoding="utf-8", timeout=30)
            raw = (out.stdout or "").strip().splitlines()
            if not raw:
                raise AssertionError("%s: node 无输出 %s" % (tag, (out.stderr or "")[:200]))
            info = json.loads(raw[-1])
            if want >= 0:
                if info.get("idx") != want:
                    raise AssertionError("%s: 应选 idx=%d，实际 %r" % (tag, want, info))
                if info.get("best") == info.get("second"):
                    raise AssertionError("%s: 唯一命中不该是平局 %r" % (tag, info))
            else:
                if info.get("idx", -1) >= 0 and info.get("best") != info.get("second"):
                    raise AssertionError("%s: 该拒绝定位却选了 idx=%r" % (tag, info))
    finally:
        shutil.rmtree(d, ignore_errors=True)


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
        front = W.api("bring_to_front", {})
        if not front.get("data", {}).get("ok"):
            raise AssertionError("bring_to_front 没有激活当前 target")

        if not W.click("#b"):
            raise AssertionError("click 返回 False")
        if W.evaluate("window.c || 0") != 1:
            raise AssertionError("点击没有触发 onclick")
    finally:
        cdp.close_browser(port)
        os.environ.pop("BOSS_BACKEND", None)
        os.environ.pop("BOSS_CDP_PORT", None)


def _no_migrate(wd):
    """默认行为：可以提示"发现旧档案"，但不能把内容复制进来。"""
    out = run(["scripts/bootstrap.py"], wd)
    if "发现旧档案" not in out:
        raise AssertionError("没提示旧档案：\n%s" % out[-400:])
    prof = json.load(open(os.path.join(wd, "user_profile.json"), encoding="utf-8"))
    if prof.get("name") == "SELFTEST-SENTINEL":
        raise AssertionError("竟然自动复制了旧档案（共用电脑会串身份）")


def _yes_migrate(wd):
    """显式 --migrate 才复制。"""
    run(["scripts/bootstrap.py", "--migrate"], wd)
    prof = json.load(open(os.path.join(wd, "user_profile.json"), encoding="utf-8"))
    if prof.get("name") != "SELFTEST-SENTINEL":
        raise AssertionError("--migrate 没有迁移档案")


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


# ═══════════════════════════════════════════════════════════
# [12]-[14] 定位器组 / 点击有效性 / 词表健康
# ═══════════════════════════════════════════════════════════
def _node_bin():
    node = shutil.which("node")
    if not node:
        raise AssertionError("本机没有 node，无法验证 JS")
    return node


def _run_node(src):
    import tempfile as _tf
    node = _node_bin()
    fd, path = _tf.mkstemp(suffix=".js")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(src)
        out = subprocess.run([node, path], capture_output=True, text=True, timeout=40)
        if out.returncode != 0:
            raise AssertionError("node 跑挂了：%s" % ((out.stderr or "")[:300]))
        return out.stdout.strip()
    finally:
        try:
            os.remove(path)
        except Exception:
            pass


# 极简 DOM stub：够跑 locators 的定位逻辑，不引 jsdom。
_DOM_STUB = r"""
function mkEl(over){
  const e = Object.assign({
    tagName:'DIV', className:'', textContent:'', id:'',
    isConnected:true,
    parentElement:null,
    getBoundingClientRect:()=>({width:0,height:0,left:0,top:0,right:0,bottom:0}),
    querySelector:()=>null, querySelectorAll:()=>[],
    getAttribute:()=>null, closest:()=>null,
    scrollIntoView:()=>{}, click:function(){ this.__clicked = true; }
  }, over||{});
  return e;
}
"""


def _locators_js_parse():
    """每个 locators 产出的 JS 都必须能被解析——语法错就等于整条链路哑火。"""
    from scripts import locators as L
    blobs = {
        "detail_ref_probe": L.detail_ref_probe_js(),
        "chat_button": L.chat_button_js(),
        "click_chat": L.click_chat_js(),
        "panel_ka": L.panel_ka_js(),
        "panel_shows_job": L.panel_shows_job_js("abc123"),
        "delivered_state": L.delivered_state_js(),
        "page_health": L.page_health_js(),
        "click_card": L.click_card_js("abc123"),
    }
    src = _DOM_STUB + "\nglobal.window={};global.document={querySelector:()=>null,querySelectorAll:()=>[]};\n"
    for name, js in blobs.items():
        src += "try{ new Function(%s); console.log('OK %s'); }catch(e){ console.log('ERR %s '+e.message); }\n" % (
            json.dumps(js), name, name)
    out = _run_node(src)
    bad = [ln for ln in out.splitlines() if ln.startswith("ERR ")]
    if bad:
        raise AssertionError("；".join(bad)[:400])
    if out.count("OK ") != len(blobs):
        raise AssertionError("有用例没跑到：\n%s" % out[:400])


def _locator_structure_fallback():
    """class 全被改名时，靠「从立即沟通按钮往上找」兜住；且绝不能命中左列表。

    两个子案例缺一不可：
      A. 有面板 → 必须找到 id='panel' 那个容器（只断言"找到了"不够，
         命中左列表同样会返回 true，而那时候读到的 JD 是整页文本）。
      B. 只有左列表（含多个岗位链接）→ 必须找不到，不能拿列表冒充面板。
    """
    from scripts import locators as L
    src = _DOM_STUB + r"""
const btn = mkEl({tagName:'BUTTON', textContent:'立即沟通'});
const card1 = mkEl({tagName:'LI'}), card2 = mkEl({tagName:'LI'});
const list = mkEl({id:'list', getBoundingClientRect:()=>({width:420,height:600}),
                   querySelectorAll:(sel)=> (sel.indexOf('job_detail')>=0 ? [card1, card2] : [])});
const panel = mkEl({id:'panel', getBoundingClientRect:()=>({width:520,height:420}),
                    querySelectorAll:(sel)=> (sel.indexOf('job_detail')>=0 ? [] : [btn])});

// —— 案例 A：面板挂在列表里，按钮挂在面板里 ——
btn.parentElement = panel;
panel.parentElement = list;
global.window = {};
global.document = {
  querySelector: () => null,                       // 没有任何 class 命中
  querySelectorAll: (sel) => (sel === 'button, a' ? [btn] : [])
};
const a = JSON.parse(""" + L.detail_ref_probe_js() + r""");

// —— 案例 B：只有列表，没有面板（按钮直接挂在列表下） ——
btn.parentElement = list;
global.window = {};
global.document = {
  querySelector: () => null,
  querySelectorAll: (sel) => (sel === 'button, a' ? [btn] : [])
};
const b = JSON.parse(""" + L.detail_ref_probe_js() + r""");

if (!(a.ok && a.id === 'panel')) console.log('FAIL_A ' + JSON.stringify(a));
else if (b.ok) console.log('FAIL_B ' + JSON.stringify(b));
else console.log('OK');
"""
    out = _run_node(src)
    if out != "OK":
        raise AssertionError("结构兜底不合格：%s" % out[:300])


def _detail_ref_drops_dead_node():
    """面板被移出 DOM 后必须失效，不能拿旧引用继续报 panel_ok。

    这是「保留上一次引用」这个优化最容易引入的坑：省了查找，代价是读到一个
    已经不在文档里的节点——innerText 还是上一张岗位的 JD，按钮点了也无效。
    """
    from scripts import locators as L
    src = _DOM_STUB + r"""
const btn = mkEl({tagName:'BUTTON', textContent:'立即沟通',
                  getAttribute:(k)=>(k==='ka'?'cpc_job_list_chat_TARGETJID':'')});
const panel = mkEl({id:'panel', getBoundingClientRect:()=>({width:520,height:420}),
                    querySelectorAll:(sel)=>(sel.indexOf('job_detail')>=0?[]:[btn])});
btn.parentElement = panel;
global.window = {};
global.document = {querySelector:()=>null, querySelectorAll:(s)=>(s==='button, a'?[btn]:[])};

const before = JSON.parse(""" + L.detail_ref_probe_js() + r""");
// 面板被移出文档（BOSS 切页/重渲染时的真实情况）
panel.isConnected = false;
const shows = """ + L.panel_shows_job_js("TARGETJID") + r""";
const click = """ + L.click_chat_js() + r""";
if (!before.ok) console.log('FAIL_BEFORE');
else if (shows !== false) console.log('FAIL_SHOWS_STILL_TRUE');
else if (click !== 'NO_PANEL') console.log('FAIL_CLICK ' + click);
else console.log('OK');
"""
    out = _run_node(src)
    if out != "OK":
        raise AssertionError("死节点没被清掉：%s" % out[:300])


def _panel_ka_false_on_other():
    """面板停在别的岗位时必须判 false——这是「投错人」的最后一道闸。"""
    from scripts import locators as L
    src = _DOM_STUB + r"""
const btn = mkEl({tagName:'BUTTON', textContent:'立即沟通',
                  getAttribute:(k) => (k === 'ka' ? 'cpc_job_list_chat_OTHERJID999' : null)});
const box = mkEl({querySelectorAll: (sel) => (sel.indexOf('button') >= 0 ? [btn] : [])});
global.window = {__bossDetail: box};
global.document = {querySelector:()=>null, querySelectorAll:()=>[]};
const hit  = """ + L.panel_shows_job_js("TARGETJID123") + r""";
const miss = """ + L.panel_shows_job_js("OTHERJID999") + r""";
console.log((hit === false && miss === true) ? 'OK' : ('FAIL hit=' + hit + ' miss=' + miss));
"""
    out = _run_node(src)
    if out != "OK":
        raise AssertionError("ka 校验不准：%s" % out[:300])


def _click_verified_falls_back():
    """鼠标点了没效果时，必须自动改用 JS 点击，并如实报告 method='js'。

    这条是今晚最贵的教训：click 返回 true 但页面毫无变化，
    调用方信了就一路「成功」到底。测试要钉住「会兜底」而不是「不报错」。
    """
    from unittest import mock
    from scripts import webbridge_client as W

    seq = {"js_done": False}

    def fake_click(sel, session=None):
        return True                       # 鼠标事件「成功发出」，但没效果

    def fake_js(sel, session=None):
        seq["js_done"] = True             # 真实场景：点完之后页面才会变
        return True

    def fake_eval(code, session=None):
        return "true" if seq["js_done"] else "false"

    with mock.patch.object(W, "click", fake_click), \
            mock.patch.object(W, "js_click", fake_js), \
            mock.patch.object(W, "evaluate", fake_eval):
        ok, method = W.click_verified("#x", expect_js="true", timeout=1.0, poll=0.1)

    if not ok:
        raise AssertionError("兜底后仍判失败")
    if method != "js":
        raise AssertionError("应该报告 method=js，实际 %r" % method)
    if not seq.get("js_done"):
        raise AssertionError("根本没走 JS 点击")


def _click_verified_no_backend():
    """没有自动化通道时，js_click 必须安静返回 False，不能把异常抛给调用方。"""
    from scripts.webbridge_client import js_click
    if js_click("#definitely-not-there") is not False:
        raise AssertionError("无通道时 js_click 应返回 False")


def _click_card_absent():
    """卡片不在 DOM 时必须返回 absent（该跳过），而不是含糊的 False。"""
    from unittest import mock
    from scripts import webbridge_client as W
    with mock.patch.object(W, "evaluate", lambda code, session=None: "ABSENT"):
        ok, method = W.click_card("nosuchjid")
    if ok or method != "absent":
        raise AssertionError("期望 (False,'absent')，实际 (%r,%r)" % (ok, method))


def _kw_exhausted():
    import tempfile as _tf
    from scripts import keyword_health as K
    d = _tf.mkdtemp(prefix="kw-")
    try:
        K.record(d, "前端开发实习", 15, 0)
        if K.is_exhausted(d, "前端开发实习"):
            raise AssertionError("只挖空 1 轮就判枯竭，太激进")
        K.record(d, "前端开发实习", 15, 0)
        if not K.is_exhausted(d, "前端开发实习"):
            raise AssertionError("连续 2 轮 fresh=0 仍未判枯竭")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _kw_failed_round_ignored():
    """加载失败 / 翻页没换内容的轮次，绝不能算进「挖空」。

    这是最容易把词表错误退役的一条：后台标签页（文档推荐的 B 路工况）
    翻页拿不到新内容，每轮都会记 0；如果 0 都算数，两天就把还有货的词砍掉。
    """
    import tempfile as _tf
    from scripts import keyword_health as K
    d = _tf.mkdtemp(prefix="kw-")
    try:
        K.record(d, "后端", 15, 0, ok=True)
        K.record(d, "后端", 0, 0, note="load_failed", ok=False)
        K.record(d, "后端", 0, 0, note="paging_dead", ok=False)
        if K.is_exhausted(d, "后端"):
            raise AssertionError("失败轮被算进枯竭（只有 1 个有效轮，不该判）")
        K.record(d, "后端", 15, 0, ok=True)
        if not K.is_exhausted(d, "后端"):
            raise AssertionError("两个有效轮都为空，应该判枯竭")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _kw_revive():
    import tempfile as _tf
    from scripts import keyword_health as K
    d = _tf.mkdtemp(prefix="kw-")
    try:
        K.record(d, "Java后端实习", 15, 0)
        K.record(d, "Java后端实习", 15, 0)
        if not K.is_exhausted(d, "Java后端实习"):
            raise AssertionError("前置条件不成立")
        K.record(d, "Java后端实习", 15, 7)      # 又刷出新岗位
        if K.is_exhausted(d, "Java后端实习"):
            raise AssertionError("重新有货后应自动解除枯竭")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _kw_reset():
    import tempfile as _tf
    from scripts import keyword_health as K
    d = _tf.mkdtemp(prefix="kw-")
    try:
        K.record(d, "全栈开发实习", 15, 0)
        K.record(d, "全栈开发实习", 15, 0)
        K.reset(d, "全栈开发实习")
        if K.is_exhausted(d, "全栈开发实习"):
            raise AssertionError("reset 之后仍被判枯竭")
        rows = K.report(d)
        if any(r["keyword"] == "全栈开发实习" for r in rows):
            raise AssertionError("reset 之后 report 里还留着")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _probe_skips_exhausted(wd):
    """supply_probe 必须真的会跳过已挖空的词（参数与调用都要在）。"""
    import tempfile as _tf
    from scripts import keyword_health as K
    d = _tf.mkdtemp(prefix="kw-")
    try:
        K.record(d, "前端开发实习", 15, 0)
        K.record(d, "前端开发实习", 15, 0)
        K.record(d, "Java后端实习", 15, 6)
        dead = K.exhausted_keywords(d, ["前端开发实习", "Java后端实习", "AI应用开发实习"])
        if dead != ["前端开发实习"]:
            raise AssertionError("枯竭词判定错：%r" % (dead,))
    finally:
        shutil.rmtree(d, ignore_errors=True)
    src = open(os.path.join(ROOT, "scripts", "supply_probe.py"), encoding="utf-8").read()
    for needle in ("include-exhausted", "exhausted_keywords", "paging_dead"):
        if needle not in src:
            raise AssertionError("supply_probe 缺 %r：跳过枯竭词/翻页校验没接上" % needle)


if __name__ == "__main__":
    sys.exit(main())
