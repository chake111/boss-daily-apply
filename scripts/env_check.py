#!/usr/bin/env python3
"""环境检测模块 —— 启动时自动检查运行前置条件。

检测项：
  ① Chrome 浏览器是否已安装
  ② Kimi WebBridge 插件是否可用（端口 10086）
  ③ Boss 直聘页面是否已登录（复用用户登录态）

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

        # 先导航到 Boss 推荐页，确保读到的是目标页面（而非其它空白标签页）
        RECOMMEND_URL = "https://www.zhipin.com/web/geek/jobs?ka=header-jobs"
        try:
            _ev  # noqa
            api("navigate", {"url": RECOMMEND_URL})
            _t.sleep(6)
        except Exception:
            pass

        body_text = _ev("document.body.innerText || ''") or ""
        login_wall_kws = ["请登录", "立即登录", "扫码登录", "账号密码登录", "手机号登录"]
        for kw in login_wall_kws:
            # 短文本命中且是主导航区特征（避免误判岗位描述中的"登录"）
            if kw in body_text and body_text.index(kw) < 200:
                return False, (
                    "Boss 直聘未登录或登录态已过期。\n"
                    "   请在浏览器中打开 https://www.zhipin.com 并完成登录，\n"
                    "   本流程需复用您的登录数据才能投递。"
                )

        # 已登录标志：body 足够长（说明已加载推荐内容）且无登录墙
        if len(body_text.strip()) > 100:
            return True, "Boss 直聘已登录"

        return False, (
            "无法确认 Boss 直聘登录状态（页面内容过短）。\n"
            "   请在浏览器中打开 https://www.zhipin.com 确认已登录。"
        )
    except Exception as e:
        return False, f"无法检测登录态: {e}（先让自动化通道就绪：python scripts/cdp_client.py --launch）"


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
