# -*- coding: utf-8 -*-
"""Playwright 后端：能用成熟库，就别手写协议。

怎么用（配合已启动的浏览器）
----------------------------
Playwright 能 `connect_over_cdp` 连到一个已经开着的浏览器，于是：

    cdp_client.py --serve   ← 只负责"把浏览器起起来、留住调试端口"
    playwright_backend      ← 负责所有页面操作（点击、取值、上传、多标签）

为什么这样分工，而不是让 Playwright 自己 launch
----------------------------------------------
驱动是"一条命令一张卡"的循环（walk / open / deliver / reject 各是一条命令）。
如果每个命令都 `launch_persistent_context`，每张卡要开关浏览器三次——
慢 3~5 秒/次，还会闪窗口。所以浏览器只起一次（`--serve` 常驻），
每条命令用 Playwright 连上去操作。

为什么不干脆手写 CDP
--------------------
手写 WebSocket + JSON-RPC 能跑，但点击的"等元素可点、自动滚动、失败重试"
全要自己实现，而 Playwright 已经把这些做透了，还带 `set_input_files` 这种
上传补发简历图正好用的 API。cdp_client 保留为"既没装 Playwright 也没有
任何库"时的兜底，不再作为首选。

依赖
----
    pip install playwright          # 约 39MB，几秒钟
不需要 `playwright install`：我们连的是系统已装的 Chrome/Edge，不是它自带的核。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_INTERNAL = ("chrome://", "edge://", "devtools://", "chrome-extension://")


def available(port=None):
    """有没有 Playwright，以及调试端口通不通。"""
    try:
        import playwright  # noqa: F401
    except Exception:
        return False
    try:
        from scripts import cdp_client
        return cdp_client.available(port or _port())
    except Exception:
        return False


def installed():
    """只判断库装没装（不看端口），onboard 用。"""
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


def _port():
    return int(os.environ.get("BOSS_CDP_PORT") or 9222)


class Backend:
    """冒充 WebBridge 的 /command 接口，上层脚本一行都不用改。"""

    name = "playwright"

    def __init__(self, port=None):
        self.port = port or _port()
        self._pw = None
        self._browser = None
        self._pages = {}          # session -> Page

    # ── 连接 ─────────────────────────────────────────────
    def _conn(self):
        if self._browser is not None:
            try:
                _ = self._browser.contexts
                return self._browser
            except Exception:
                self._browser = None
                self._pages.clear()

        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            raise RuntimeError(
                "没装 Playwright。装一下：pip install playwright\n"
                "（不想装也行，脚本会自动退回内置 CDP 后端）原始错误: %s" % e)

        if self._pw is None:
            self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.connect_over_cdp(
            "http://127.0.0.1:%d" % self.port)
        return self._browser

    def _ctx(self):
        b = self._conn()
        if not b.contexts:
            raise RuntimeError("连上的浏览器没有可用上下文")
        return b.contexts[0]

    def _page(self, session, new=False):
        p = self._pages.get(session)
        if p is not None:
            try:
                if not p.is_closed():
                    return p
            except Exception:
                pass
            self._pages.pop(session, None)

        ctx = self._ctx()
        if session == "boss-main" and not new:
            # 优先认领用户已经开着的 BOSS 标签（登录态在里面）
            pages = [x for x in ctx.pages if not x.is_closed()]
            pick = next((x for x in pages if "zhipin.com" in (x.url or "")), None)
            if pick is None:
                usable = [x for x in pages if not (x.url or "").startswith(_INTERNAL)]
                pick = usable[0] if usable else (pages[0] if pages else None)
            if pick is None:
                pick = ctx.new_page()
        else:
            # 其它 session（补发图）单独开一个标签，别抢主标签
            pick = ctx.new_page()
        self._pages[session] = pick
        return pick

    # ── 动作分发 ─────────────────────────────────────────
    def api(self, action, args=None, session="boss-main", timeout=None):
        args = args or {}
        t = int(timeout * 1000) if timeout else 30000

        if action == "evaluate":
            try:
                v = self._page(session).evaluate(args.get("code", ""))
                return {"data": {"value": "" if v is None else v}}
            except Exception as e:
                if os.environ.get("BOSS_DEBUG"):
                    print("[playwright] evaluate 失败: %s" % str(e)[:200], file=sys.stderr)
                return {"data": {"value": ""}}

        if action == "navigate":
            from urllib.parse import urlsplit
            url = args.get("url", "")
            host = ""
            want_path = ""
            try:
                sp = urlsplit(url)
                host = sp.netloc.split(":")[0]
                want_path = (sp.path or "/").rstrip("/")
            except Exception:
                pass
            # 刚 connect_over_cdp 时，页面句柄要经过一次往返才"热"起来，
            # 第一次 goto 可能返回成功但 URL 还没提交。所以不信任返回值，
            # 用"落地 URL 是否命中目标"当判据，并在短时间内轮询。
            #
            # 判据必须比到**路径**，不能只比域名：原来只判 host in landed，
            # goto 失败时旧 URL（同一个域名、另一个页面）也会命中，于是
            # 导航失败被报成 ok=True，上层以为已经在目标页，实际停在原地。
            # 这类假阳性会让后续的 open/发送动作全落在错的页面上。
            for attempt in (1, 2):
                page = self._page(session)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=max(t, 20000))
                except Exception as e:
                    if os.environ.get("BOSS_DEBUG"):
                        print("[playwright] navigate 失败(%d) %s: %s"
                              % (attempt, url[:60], str(e)[:200]), file=sys.stderr)
                for _ in range(10):
                    try:
                        landed = page.url or ""
                    except Exception:
                        landed = ""
                    gs = urlsplit(landed)
                    same_host = (not host) or gs.netloc.split(":")[0] == host
                    same_path = (not want_path) or (gs.path or "/").rstrip("/") == want_path
                    if same_host and same_path:
                        return {"data": {"ok": True}}
                    time.sleep(0.3)
                self._pages.pop(session, None)      # 换个标签页再试
            return {"data": {"ok": False}}

        if action == "bring_to_front":
            # 后台标签会被 Chromium 降频：渲染暂停、执行上下文时有时无，
            # evaluate 间歇性拿到空串。上传和读列表之前必须先把它切到前台。
            try:
                self._page(session).bring_to_front()
                return {"data": {"ok": True}}
            except Exception:
                return {"data": {"ok": False}}

        if action == "click":
            try:
                self._page(session).click(args.get("selector", ""), timeout=t)
                return {"data": {"success": True}}
            except Exception:
                return {"data": {"success": False}}

        if action == "list_tabs":
            ctx = self._ctx()
            tabs = []
            for i, x in enumerate(ctx.pages):
                try:
                    tabs.append({"tabId": str(i), "url": x.url,
                                 "title": (x.title() or "")[:80], "groupTitle": ""})
                except Exception:
                    pass
            return {"data": {"tabs": tabs}}

        if action in ("activate_tab", "close_tab"):
            ctx = self._ctx()
            try:
                page = ctx.pages[int(args.get("tabId"))]
            except Exception:
                return {"data": {"ok": False}}
            try:
                if action == "activate_tab":
                    page.bring_to_front()
                else:
                    page.close()
            except Exception:
                return {"data": {"ok": False}}
            return {"data": {"ok": True}}

        if action == "upload":
            # 补发简历图可以直接用 Playwright 的文件上传，比 base64 注入稳
            try:
                page = self._page(session)
                page.set_input_files(args.get("selector", "input[type=file]"),
                                     args.get("path", ""), timeout=t)
                return {"data": {"ok": True}}
            except Exception as e:
                return {"data": {"ok": False, "error": str(e)[:120]}}

        raise RuntimeError(
            "Playwright 后端不支持动作 %r。投递主流程不需要它；"
            "诊断类脚本请用 WebBridge 或 browser.py。" % action)

    def close(self):
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
        self._browser = None
        self._pw = None
        self._pages.clear()
