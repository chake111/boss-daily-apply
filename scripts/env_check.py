#!/usr/bin/env python3
"""环境检测模块 —— 启动时自动检查运行前置条件。

检测项：
  ① 任意 Chromium 系浏览器是否已安装（不要求 Chrome）
  ② 自动化通道：内置 CDP（默认）/ Kimi WebBridge 扩展
  ③ Boss 直聘页面是否已登录（复用用户登录态）
  ④ 页面结构：详情面板 / 岗位卡片 / 「立即沟通」按钮是否还找得到
     （BOSS 改版会让前三项全绿但流程静默失效，所以单独有一项）

用法：
    from scripts.env_check import check_env, EnvResult
    result = check_env()
    if not result.ok:
        print(result.message)   # 含修复指引
        sys.exit(1)
    print("✅ 环境检测全部通过")
"""

import sys
import os
import subprocess
import socket
import json

# 路径引导：确保 scripts 包可导入（无论以脚本直接运行还是被其它模块导入）
_HERE = os.path.dirname(os.path.abspath(__file__))
# 兼容 Git Bash 的 /c/... UNIX 风格路径：Windows Python 会把 /c 误算成 C:\c
if len(_HERE) >= 3 and _HERE[0] == "/" and _HERE[1].isalpha() and _HERE[2] == "/":
    _HERE = _HERE[1].upper() + ":" + _HERE[2:]
SKILL_DIR = os.path.dirname(_HERE)
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)

# ── 检测结果 ──────────────────────────────────────
class EnvResult:
    """单次环境检测结果。"""
    def __init__(self):
        self.ok = True
        self.items = []   # [(name, passed, detail), ...]
        self.message = ""

    def add(self, name, passed, detail=""):
        self.items.append((name, passed, detail))
        if not passed:
            self.ok = False

    def build_message(self):
        lines = []
        for name, passed, detail in self.items:
            icon = "✅" if passed else "❌"
            lines.append(f"  {icon} {name}: {detail or ('通过' if passed else '未通过')}")
        if not self.ok:
            lines.append("")
            lines.append("⚠️  环境未就绪，请按上方指引完成准备后重试。")
        self.message = "\n".join(lines)
        return self.message


# ── 浏览器检测（Chromium 系，不限定 Chrome）─────────
def _check_browser():
    """检测任意 Chromium 系浏览器。

    WebBridge 是 Chromium 扩展，Edge / Brave / Vivaldi / Chromium / Opera 都能装，
    没必要强制别人装 Chrome（Windows 自带 Edge 就够）。Firefox / Safari 装不了，
    会在提示里说明。
    """
    try:
        from scripts import browser as _browser
        found = _browser.detect()
    except Exception as e:
        return False, f"浏览器检测失败: {e}"

    if not found:
        return False, _browser.INSTALL_HINT

    running = [b for b in found if _browser.is_running(b) is True]
    names = "、".join(b["name"] for b in found)
    if running:
        return True, "%s（运行中：%s）" % (names, running[0]["name"])
    return True, "%s（都没在运行；开工前先启动其中一个）" % names


# ── WebBridge 检测 ─────────────────────────────────
_WEBBRIDGE_HOST = "127.0.0.1"
_WEBBRIDGE_PORT = 10086


def _check_webbridge():
    """检测 Kimi WebBridge 是否在本地端口 10086 可达。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        result = s.connect_ex((_WEBBRIDGE_HOST, _WEBBRIDGE_PORT))
        s.close()
        if result == 0:
            return True, f"WebBridge 已启动 (端口 {_WEBBRIDGE_PORT})"
        _exe = os.path.normpath(os.path.expanduser(
            os.path.join("~", ".kimi-webbridge", "bin", "kimi-webbridge.exe")))
        return False, (
            f"WebBridge 未在端口 {_WEBBRIDGE_PORT} 响应。\n"
            "   请确认：\n"
            "   ① 已安装 Kimi WebBridge 扩展 → https://www.kimi.com/zh-cn/features/webbridge\n"
            "      （Edge / Brave / Vivaldi 也能装：Edge 需先在扩展页打开「允许来自其他商店的扩展」）\n"
            "   ② 在**正在运行的那个浏览器**里启用它，并已登录 BOSS直聘\n"
            f"   ③ 起服务（全路径，它不在 PATH 里）：\"{_exe}\" start --foreground\n"
            "   没装扩展也能用：python scripts/ledger.py（手动投 + 自动统计）"
        )
    except Exception as e:
        return False, f"WebBridge 连接异常: {e}"


# ── Boss 登录检测 ──────────────────────────────────
def _check_boss_login():
    """
    通过当前后端（WebBridge 或 CDP）读取页面，检测 Boss 直聘登录态。
    不绑定任何特定用户名——通用检测：
      - 页面非登录墙（不含"请登录"/"立即登录"等）
      - 页面含已登录标志（导航栏有用户信息 / body 含正常推荐内容）
    """
    try:
        # 延迟导入，避免通道不可用时 import 失败
        from scripts.webbridge_client import api, evaluate as _ev
        import time as _t

        # 先导航到 Boss 推荐页，确保读到的是目标页面（而非其它标签页）。
        # 这里不"睡固定秒数就看结果"——导航可能还没提交，也可能被上一轮的
        # 未完成跳转覆盖。改成：导航 → 轮询落地 URL → 不对就再导航一次。
        RECOMMEND_URL = "https://www.zhipin.com/web/geek/jobs?ka=header-jobs"
        landed = False
        for _ in range(3):
            try:
                api("navigate", {"url": RECOMMEND_URL})
            except Exception as e:
                if os.environ.get("BOSS_DEBUG"):
                    print("[env_check] 导航失败: %s" % str(e)[:160], file=sys.stderr)
            for _ in range(10):
                cur = _ev("location.href") or ""
                if "zhipin.com" in cur:
                    landed = True
                    break
                _t.sleep(0.4)
            if landed:
                break
            _t.sleep(1.0)

        if not landed:
            cur = _ev("location.href") or ""
            return False, ("没打开 BOSS 页面（当前：%s），无法确认登录态。\n"
                           "   先确认浏览器能访问 https://www.zhipin.com" % (cur[:70] or "空"))

        # 等首屏渲染出来再判（SPA 冷启动要几秒，别把"还没渲染"当成"未登录"）
        body_text = ""
        for _ in range(20):
            body_text = _ev("document.body.innerText || ''") or ""
            if len(body_text.strip()) > 100:
                break
            _t.sleep(0.7)

        # 匿名访问时导航栏是"登录/注册"，这是最可靠的未登录信号。
        # 之前漏了它，导致只看 body 长度就判"已登录"——页面上全是岗位文案，
        # 长度永远够，于是未登录也会显示 ✓，直到投递那一步才炸。
        login_wall_kws = ["登录/注册", "请登录", "立即登录", "扫码登录",
                          "账号密码登录", "手机号登录"]
        head = body_text[:400]           # 只看首屏导航区，避免命中岗位描述里的"登录"
        for kw in login_wall_kws:
            if kw in head:
                return False, (
                    "Boss 直聘未登录或登录态已过期（导航栏显示「%s」）。\n"
                    "   请在浏览器中打开 https://www.zhipin.com 扫码登录，\n"
                    "   本流程需复用你的登录数据才能投递。" % kw
                )

        # 已登录的正面信号：导航栏出现了"消息/简历"这类只有登录后才有的入口。
        # 只靠"没有登录入口"就判已登录是不行的——BOSS 的中间页、安全校验页
        # 也不含"登录/注册"，会被误判成已登录。
        positive = ("消息" in head) or ("简历" in head) or ("我的" in head)
        if positive and len(body_text.strip()) > 100:
            return True, "Boss 直聘已登录"

        if len(body_text.strip()) > 100:
            return False, (
                "无法确认登录状态（页面已加载，但没看到登录入口也没看到用户信息）。\n"
                "   如果是刚打开的页面，稍等几秒再试；已登录可忽略这一项继续。"
            )

        return False, (
            "无法确认 Boss 直聘登录状态（页面内容过短）。\n"
            "   请在浏览器中打开 https://www.zhipin.com 确认已登录。"
        )
    except Exception as e:
        return False, f"无法检测登录态: {e}（先让自动化通道就绪：python scripts/cdp_client.py --launch）"


# ── 页面结构（开投前对齐「页面长什么样」和「代码认识什么」）──
def _check_page_structure():
    """按当前 DOM 检查我们还能不能找到详情面板、岗位卡片、立即沟通按钮。

    为什么单独一项（2026-11-06 实测）：BOSS 把右侧详情容器从 `#main .job-detail`
    改成 `.job-detail-box` 之后，整套流程静默失效——panel_ok 恒假、点击落到别处，
    日志里只有满屏 SKIP，一个错误都没有。等到逐张判卡才发现已经浪费了十几分钟。
    这一项开投前跑，把「选不中卡片」变成一条一眼能看懂的红灯。
    """
    try:
        import json as _json
        from scripts.webbridge_client import evaluate
        from scripts import locators
    except Exception as e:
        return False, f"页面结构检测不可用: {e}"

    try:
        import time as _t
        raw = ""
        d = {}
        # 上一步刚导航过，列表可能还没渲染完——轮询到「卡片和面板都在」为止。
        # 只看 cards 是不够的：列表渲染比右侧面板快，面板还没挂载就 break 的话，
        # 会把「还没渲染」误报成「BOSS 改版了」，让人去改没错的选择器。
        for _ in range(8):
            try:
                raw = evaluate(locators.page_health_js()) or ""
                d = _json.loads(raw) if raw.strip().startswith("{") else {}
            except Exception as e:
                return False, f"读取页面结构失败: {e}"
            if (d.get("cards") or 0) > 0 and d.get("detail"):
                break
            _t.sleep(0.8)
    except Exception as e:
        return False, f"页面结构检测不可用: {e}"

    if not d:
        return False, ("读不到页面结构（可能不在岗位列表页）。\n"
                       "   先打开 https://www.zhipin.com/web/geek/jobs 再检测。")

    detail, cards, btn = d.get("detail"), d.get("cards") or 0, d.get("chatBtn")
    if cards and btn and detail:
        return True, f"详情面板可定位 · {cards} 张卡 · 立即沟通按钮在位"
    if cards and btn and not detail:
        return False, ("能看到 %d 张岗位卡和「立即沟通」，但找不到右侧详情面板。\n"
                       "   BOSS 八成又改版了：去 scripts/locators.py 的 _DETAIL_REF "
                       "补一条选择器（SEL 数组）。" % cards)
    if cards and not btn:
        return False, ("能看到 %d 张岗位卡，但没有「立即沟通」按钮。\n"
                       "   可能停在非岗位详情页，或按钮文案改了：检查 locators.CHAT_BUTTON。" % cards)
    return False, ("页面上找不到岗位卡片（%d 张）。\n"
                   "   当前页不是搜索结果页，或者列表没加载出来。" % cards)


# ── 自动化通道 ─────────────────────────────────────
def _kimi_exe():
    return os.path.normpath(os.path.expanduser(
        os.path.join("~", ".kimi-webbridge", "bin", "kimi-webbridge.exe")))


def _check_channel():
    """自动化通道：优先 WebBridge 扩展，没有扩展就看 CDP（免扩展）。

    CDP 不是"降级方案"：evaluate / click / navigate / 开新标签它都有，
    同样能跑完整条投递流程，只是不需要装任何扩展。
    """
    try:
        from scripts.webbridge_client import bridge_alive, cdp_port
        from scripts import cdp_client
    except Exception as e:
        return False, f"通道检测失败: {e}"

    if bridge_alive():
        return True, "Kimi WebBridge 在线（端口 10086）"

    port = cdp_port()
    v = cdp_client.version(port, timeout=2)
    if v:
        return True, "CDP 就绪（调试端口 %d，%s，无需扩展）" % (
            port, v.get("Browser", "Chromium"))

    return False, (
        "两条通道都没通，任选一条：\n"
        "     A) 免扩展（推荐）：python scripts/cdp_client.py --launch\n"
        "        用独立 profile 起浏览器，第一次在里面扫码登录一次，之后登录态常驻\n"
        "     B) 扩展：https://www.kimi.com/zh-cn/features/webbridge\n"
        "        装好后运行 \"%s\" start --foreground" % _kimi_exe()
    )


# ── 主入口 ─────────────────────────────────────────
def check_env(verbose=True):
    """执行全部环境检测，返回 EnvResult。

    Args:
        verbose: 是否打印每项结果到 stdout
    """
    result = EnvResult()

    # ① 浏览器（不要求 Chrome：任何 Chromium 系都能装 WebBridge）
    passed, detail = _check_browser()
    result.add("浏览器", passed, detail)

    # ② 自动化通道：WebBridge 扩展，或 CDP（免扩展）
    passed, detail = _check_channel()
    result.add("自动化通道", passed, detail)

    # 仅当通道就绪时才检测登录（需要能读页面）
    if passed:
        passed2, detail2 = _check_boss_login()
        result.add("Boss 直聘登录", passed2, detail2)
        if passed2:
            # 登录了才有意义：按当前 DOM 检查代码还认不认得这个页面
            passed3, detail3 = _check_page_structure()
            result.add("页面结构", passed3, detail3)

    result.build_message()
    if verbose:
        print("\n🔍 BOSS 直聘投递技能 — 环境检测")
        print(result.message)
        print()
    return result


# ── CLI 入口 ───────────────────────────────────────
if __name__ == "__main__":
    r = check_env()
    sys.exit(0 if r.ok else 1)
