# -*- coding: utf-8 -*-
"""浏览器适配层：不假设你装的是 Chrome。

为什么需要它
------------
Kimi WebBridge 是 **Chromium 内核**扩展，所以能用的是"Chromium 系浏览器"，
不是"必须是 Chrome"：Edge、Brave、Vivaldi、Chromium、Opera 都能装。
（Firefox / Safari 用的是另一套扩展体系，装不了，这是硬限制。）

这个模块负责三件事：
  1. 找出机器上装了哪些 Chromium 系浏览器（Windows / macOS / Linux）
  2. 判断它是否正在运行
  3. 用"不会被会话回收"的方式把它拉起来

启动方式为什么这么讲究
----------------------
Windows 上 `Start-Process` / `cmd start` 拉起的 Chrome 会在 1~2 分钟内被会话回收，
扩展跟着掉线。让桌面 shell（explorer）去拉才稳。macOS 用 LaunchServices（open -a），
Linux 用 xdg-open 交给桌面环境——都是同一个思路：**别自己 fork 一个孤儿进程**。

用法：
    python scripts/browser.py --list            # 装了哪些、在不在跑
    python scripts/browser.py --launch          # 用第一个可用的拉起来
    python scripts/browser.py --launch edge     # 指定 Edge
    python scripts/browser.py --json            # 给智能体解析
"""
import json
import os
import subprocess
import sys

# Chromium 系浏览器清单：id → 各平台的候选路径 / 可执行名
BROWSERS = [
    {
        "id": "chrome",
        "name": "Google Chrome",
        "win": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
        ],
        "mac": ["/Applications/Google Chrome.app"],
        "linux": ["google-chrome", "google-chrome-stable"],
        "proc": ["chrome.exe", "chrome"],
    },
    {
        "id": "edge",
        "name": "Microsoft Edge",
        "win": [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe",
        ],
        "mac": ["/Applications/Microsoft Edge.app"],
        "linux": ["microsoft-edge", "microsoft-edge-stable"],
        "proc": ["msedge.exe", "msedge"],
    },
    {
        "id": "brave",
        "name": "Brave",
        "win": [
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe",
        ],
        "mac": ["/Applications/Brave Browser.app"],
        "linux": ["brave-browser", "brave"],
        "proc": ["brave.exe", "brave"],
    },
    {
        "id": "vivaldi",
        "name": "Vivaldi",
        "win": [
            r"C:\Program Files\Vivaldi\Application\vivaldi.exe",
            r"%LOCALAPPDATA%\Vivaldi\Application\vivaldi.exe",
        ],
        "mac": ["/Applications/Vivaldi.app"],
        "linux": ["vivaldi", "vivaldi-stable"],
        "proc": ["vivaldi.exe", "vivaldi"],
    },
    {
        "id": "chromium",
        "name": "Chromium",
        "win": [
            r"C:\Program Files\Chromium\Application\chrome.exe",
            r"%LOCALAPPDATA%\Chromium\Application\chrome.exe",
        ],
        "mac": ["/Applications/Chromium.app"],
        "linux": ["chromium", "chromium-browser"],
        "proc": ["chromium.exe", "chromium", "chromium-browser"],
    },
    {
        "id": "opera",
        "name": "Opera",
        "win": [
            r"%LOCALAPPDATA%\Programs\Opera\opera.exe",
            r"C:\Program Files\Opera\opera.exe",
        ],
        "mac": ["/Applications/Opera.app"],
        "linux": ["opera"],
        "proc": ["opera.exe", "opera"],
    },
]

INSTALL_HINT = (
    "没检测到任何 Chromium 系浏览器。有三种走法：\n"
    "  ① Windows 10/11 自带 Edge，直接用：python scripts/browser.py --launch edge\n"
    "  ② 装 Chrome：https://www.google.com/chrome/\n"
    "  ③ 不想装/装不了 → 用无浏览器模式（手动投，脚本只管记账和统计）：\n"
    "     python scripts/ledger.py --help\n"
    "注意：Firefox / Safari 装不了 WebBridge 扩展，不在支持范围内。"
)


def _expand(p):
    return os.path.expandvars(os.path.expanduser(p))


def _which(cmd):
    """跨平台 which，不依赖 shutil.which 对 .exe 后缀的处理差异。"""
    import shutil
    return shutil.which(cmd) or ""


def detect():
    """返回已安装的浏览器列表：[{id,name,path}]，按清单顺序（Chrome 优先）。"""
    out = []
    plat = sys.platform
    for b in BROWSERS:
        path = ""
        if plat.startswith("win"):
            for c in b["win"]:
                p = _expand(c)
                if os.path.exists(p):
                    path = p
                    break
        elif plat == "darwin":
            for c in b["mac"]:
                if os.path.exists(c):
                    path = c
                    break
        else:
            for c in b["linux"]:
                w = _which(c)
                if w:
                    path = w
                    break
        if path:
            out.append({"id": b["id"], "name": b["name"], "path": path})
    return out


def is_running(browser):
    """进程是否在跑。查不到就返回 None（未知），不要当成"没开"。"""
    procs = next((b["proc"] for b in BROWSERS if b["id"] == browser["id"]), [])
    try:
        if sys.platform.startswith("win"):
            r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq " + procs[0]],
                               capture_output=True, text=True, timeout=10,
                               encoding="utf-8", errors="ignore")
            return procs[0].lower() in (r.stdout or "").lower()
        r = subprocess.run(["pgrep", "-f", procs[-1]],
                           capture_output=True, text=True, timeout=10)
        return r.returncode == 0 and bool((r.stdout or "").strip())
    except Exception:
        return None


def pick(prefer=""):
    """选一个可用浏览器。prefer 可以是 id 或路径。

    没指定时优先挑**正在运行的**那个：登录态通常在已经开着的浏览器里，
    盲目拉起另一个只会让人在两个窗口之间来回找。
    """
    found = detect()
    if prefer:
        for b in found:
            if prefer.lower() in (b["id"], b["name"].lower()) or prefer == b["path"]:
                return b
        if os.path.exists(_expand(prefer)):
            return {"id": "custom", "name": os.path.basename(prefer), "path": _expand(prefer)}
        return None
    for b in found:
        if is_running(b) is True:
            return b
    return found[0] if found else None


def launch(browser, wait=0.0):
    """拉起浏览器，返回 (ok, message)。

    Windows 用 explorer.exe、macOS 用 open -a、Linux 用 xdg-open ——
    都把进程交给桌面 shell / LaunchServices，避免被当前会话回收。
    """
    path = browser["path"]
    try:
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer.exe", path])
            how = "explorer.exe"
        elif sys.platform == "darwin":
            app = path
            if path.endswith(".app") is False and "/Applications/" in path:
                app = path.split("/Contents/")[0]
            subprocess.Popen(["open", "-a", app])
            how = "open -a"
        else:
            try:
                subprocess.Popen(["xdg-open", path])
                how = "xdg-open"
            except Exception:
                subprocess.Popen([path])
                how = "直接 exec"
    except Exception as e:
        return False, "启动失败: %s" % e
    if wait:
        import time
        time.sleep(wait)
    return True, "已用 %s 启动 %s（%s）" % (how, browser["name"], path)


def resolve(prefer=""):
    """给脚本用的一步到位：返回浏览器信息，没有就返回 None。"""
    return pick(prefer or os.environ.get("BOSS_BROWSER", ""))


def main():
    args = sys.argv[1:]
    prefer = ""
    if "--launch" in args:
        i = args.index("--launch")
        prefer = args[i + 1] if len(args) > i + 1 and not args[i + 1].startswith("-") else ""
        browser = pick(prefer)
        if not browser:
            print(INSTALL_HINT)
            return 3
        ok, msg = launch(browser, wait=3)
        print(("✓ " if ok else "✗ ") + msg)
        return 0 if ok else 1

    found = detect()
    if "--json" in args:
        print(json.dumps({"platform": sys.platform, "found": found},
                         ensure_ascii=False, indent=2))
        return 0 if found else 3

    print("平台:", sys.platform)
    if not found:
        print(INSTALL_HINT)
        return 3
    print("检测到 %d 个 Chromium 系浏览器：\n" % len(found))
    for i, b in enumerate(found, 1):
        run = is_running(b)
        state = "运行中" if run else ("未运行" if run is False else "状态未知")
        print("  %d) %-14s %-10s %s" % (i, b["name"], state, b["path"]))
    print("\n默认用第一个。指定别的：python scripts/browser.py --launch edge")
    print("自定义路径：设环境变量 BOSS_BROWSER=<可执行文件路径>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
