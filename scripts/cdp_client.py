# -*- coding: utf-8 -*-
"""CDP 后端：不用装任何扩展，直接驱动 Chromium 浏览器。

为什么有这个东西
----------------
自动化只需要三个能力：在页面里跑 JS、点一个元素、导航到某个 URL。
WebBridge 用扩展 + 本地服务提供它们；Chromium 自带的 **DevTools 协议**（CDP）
同样提供，而且**不需要装扩展**——只要启动浏览器时加一个调试端口。

    chrome.exe --remote-debugging-port=9222 --user-data-dir=<某个profile目录>

于是"公司电脑装不了扩展""我用的是 Edge 不是 Chrome"这两类情况，
不再是"只能手动投"，而是换一条同样能自动点的通道。

登录态怎么办
------------
调试端口本身不影响登录：cookie 属于 profile 目录。
  · 默认用独立 profile（<工作目录>/browser-profile），第一次扫码登录一次，之后一直有效；
    好处是完全不干扰你日常用的浏览器。
  · 想复用现有登录，把 BOSS_CDP_PROFILE 指到你真实的 profile 目录
    （注意：浏览器必须全部关掉后由本脚本拉起，否则新进程只会把命令行交给已有实例然后退出）。

实现说明
--------
只用标准库：手写 RFC6455 客户端（握手 + 掩码帧 + 分片 + ping/pong），
上层是 CDP 的 JSON-RPC。没有 playwright / selenium / websocket-client 依赖。

用法：
    python scripts/cdp_client.py --launch          # 起浏览器（人用，命令立刻返回）
    python scripts/cdp_client.py --serve           # 起浏览器并常驻（智能体用，丢后台）
    python scripts/cdp_client.py --launch --url https://www.zhipin.com/web/geek/jobs
    python scripts/cdp_client.py --check           # 端口就绪？列出标签页
    python scripts/cdp_client.py --selftest        # 不需要登录，跑一遍全链路

--launch 与 --serve 的区别（很重要）
------------------------------------
有些宿主（IDE / 智能体 / 沙箱）会在命令结束时把整棵进程树回收，单独 Popen 出去的
浏览器会被一起杀掉，调试端口随之消失——表现为"刚启动就查不到"。`--serve` 会留一个
常驻父进程挡住这次回收。

    · 智能体驱动：`--serve` + 后台任务
    · 人自己在终端跑：`--launch` 就够（终端不关，浏览器就在）
"""
import base64
import hashlib
import json
import os
import random
import socket
import struct
import subprocess
import sys
import time
import urllib.parse
import urllib.request

DEFAULT_PORT = 9222
DEFAULT_TIMEOUT = 30

# 让 `from scripts import ...` 在直接运行本文件时也成立
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ═══════════════════════════════════════════════════════════
# 最小 WebSocket 客户端（RFC6455，仅客户端侧）
# ═══════════════════════════════════════════════════════════

class WSError(Exception):
    pass


class WebSocket:
    """够用就好的 WS 客户端：文本帧、分片、ping/pong、close。"""

    def __init__(self, url, timeout=DEFAULT_TIMEOUT):
        # ws://127.0.0.1:9222/devtools/page/XXXX
        if not url.startswith("ws://"):
            raise WSError("只支持 ws:// ：" + url)
        rest = url[5:]
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        self.host = host
        self.port = int(port or 80)
        self.path = "/" + path
        self.timeout = timeout
        self.sock = socket.create_connection((self.host, self.port), timeout=timeout)
        self._buf = b""
        self._handshake()

    # ── 握手 ────────────────────────────────────────────
    def _handshake(self):
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            "GET %s HTTP/1.1\r\n"
            "Host: %s:%d\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: %s\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n" % (self.path, self.host, self.port, key)
        )
        self.sock.sendall(req.encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise WSError("握手时连接被关闭")
            head += chunk
        header, _, tail = head.partition(b"\r\n\r\n")
        self._buf = tail
        text = header.decode("latin-1")
        if "101" not in text.split("\r\n")[0]:
            raise WSError("握手失败：" + text.split("\r\n")[0])
        expect = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()
        if expect not in text:
            raise WSError("Sec-WebSocket-Accept 校验失败")

    # ── 读写 ────────────────────────────────────────────
    def _recv_exact(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(max(4096, n - len(self._buf)))
            if not chunk:
                raise WSError("连接已关闭")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _send_frame(self, opcode, payload=b""):
        """客户端发出的帧必须加掩码。"""
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        head = bytes([0x80 | opcode])
        n = len(payload)
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        self.sock.sendall(head + mask + masked)

    def send_text(self, text):
        self._send_frame(0x1, text.encode("utf-8"))

    def recv_text(self):
        """读一条完整文本消息（自动拼分片、自动回 pong）。"""
        chunks = []
        while True:
            b0, b1 = self._recv_exact(2)
            fin = bool(b0 & 0x80)
            opcode = b0 & 0x0F
            masked = bool(b1 & 0x80)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._recv_exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._recv_exact(8))[0]
            mask = self._recv_exact(4) if masked else b""
            payload = self._recv_exact(n) if n else b""
            if masked:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))

            if opcode == 0x8:                       # close
                raise WSError("服务端关闭连接")
            if opcode == 0x9:                       # ping -> pong
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:                       # pong
                continue
            chunks.append(payload)
            if fin:
                return b"".join(chunks).decode("utf-8", errors="replace")

    def close(self):
        try:
            self._send_frame(0x8)
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
# CDP 会话
# ═══════════════════════════════════════════════════════════

class CDPError(Exception):
    pass


class CDP:
    """连到某个 page target，顺序发送 JSON-RPC。"""

    def __init__(self, ws_url, timeout=DEFAULT_TIMEOUT):
        self.ws = WebSocket(ws_url, timeout=timeout)
        self._id = 0
        self.timeout = timeout

    def send(self, method, params=None, timeout=None):
        self._id += 1
        mid = self._id
        msg = json.dumps({"id": mid, "method": method, "params": params or {}})
        self.ws.send_text(msg)
        deadline = time.time() + (timeout or self.timeout)
        while time.time() < deadline:
            raw = self.ws.recv_text()
            try:
                data = json.loads(raw)
            except Exception:
                continue
            if data.get("id") != mid:
                continue                            # 事件或别的响应，跳过
            if "error" in data:
                raise CDPError("%s -> %s" % (method, data["error"]))
            return data.get("result", {})
        raise CDPError("%s 超时（%.0fs）" % (method, timeout or self.timeout))

    # ── 常用动作 ─────────────────────────────────────────
    def evaluate(self, expression, await_promise=True, timeout=None):
        r = self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": await_promise,
            "userGesture": True,
        }, timeout=timeout)
        if r.get("exceptionDetails"):
            detail = r["exceptionDetails"]
            text = (detail.get("exception") or {}).get("description") or detail.get("text") or ""
            if os.environ.get("BOSS_DEBUG"):
                print("[cdp] JS 异常: " + str(text)[:200], file=sys.stderr)
            return ""
        return (r.get("result") or {}).get("value", "")

    def navigate(self, url, wait_complete=True, timeout=20):
        self.send("Page.navigate", {"url": url}, timeout=timeout)
        if not wait_complete:
            return
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.evaluate("document.readyState", await_promise=False) == "complete":
                return
            time.sleep(0.4)

    def click(self, selector):
        """先按真实鼠标事件点，点不到退回 JS click。

        为什么不一上来就用 element.click()：部分交互会检查事件是否"像人点的"，
        真实鼠标事件通过 Input.dispatchMouseEvent 发出，路径更接近用户操作。
        """
        box = self.evaluate(
            "(function(){var el=document.querySelector(%s);if(!el)return null;"
            "el.scrollIntoView({block:'center',inline:'center'});"
            "var r=el.getBoundingClientRect();"
            "return {x:r.left+r.width/2,y:r.top+r.height/2,w:r.width,h:r.height};})()"
            % json.dumps(selector))
        if isinstance(box, dict) and box.get("w"):
            x, y = float(box["x"]), float(box["y"])
            try:
                self.send("Input.dispatchMouseEvent",
                          {"type": "mouseMoved", "x": x, "y": y})
                self.send("Input.dispatchMouseEvent",
                          {"type": "mousePressed", "x": x, "y": y,
                           "button": "left", "clickCount": 1})
                self.send("Input.dispatchMouseEvent",
                          {"type": "mouseReleased", "x": x, "y": y,
                           "button": "left", "clickCount": 1})
                return True
            except CDPError:
                pass
        return bool(self.evaluate(
            "(function(){var el=document.querySelector(%s);if(!el)return false;el.click();return true;})()"
            % json.dumps(selector)))

    def close(self):
        self.ws.close()


# ═══════════════════════════════════════════════════════════
# 目标（标签页）发现与连接
# ═══════════════════════════════════════════════════════════

def _http_json(port, path, timeout=3, method="GET"):
    url = "http://127.0.0.1:%d%s" % (port, path)
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8", errors="replace")
    return json.loads(body) if body.strip() else {}


def version(port=DEFAULT_PORT, timeout=2):
    """调试端口是否可用。返回 /json/version 的内容，或 None。"""
    try:
        return _http_json(port, "/json/version", timeout=timeout)
    except Exception:
        return None


def available(port=DEFAULT_PORT):
    return version(port) is not None


def targets(port=DEFAULT_PORT):
    """所有 page 目标：[{id, url, title, webSocketDebuggerUrl}]"""
    try:
        raw = _http_json(port, "/json/list")
    except Exception:
        return []
    return [t for t in raw if t.get("type") == "page"]


_BAD_SCHEMES = ("chrome://", "edge://", "devtools://", "chrome-extension://")


def page_target(port=DEFAULT_PORT, url_contains=None):
    """挑一个可操作的页面。

    · 跳过浏览器自己的内部页（edge://settings、chrome://newtab 这类连不上 DOM）
    · about:blank 是可用的（能 evaluate、能导航），只是排在真实网页后面
    · 都没有才退回第一个目标
    """
    ts = targets(port)
    if url_contains:
        for t in ts:
            if url_contains in (t.get("url") or ""):
                return t
    usable = [t for t in ts if not (t.get("url") or "").startswith(_BAD_SCHEMES)]
    real = [t for t in usable if not (t.get("url") or "").startswith("about:")]
    if real:
        return real[0]
    if usable:
        return usable[0]
    return ts[0] if ts else None


def connect(port=DEFAULT_PORT, url_contains=None, timeout=DEFAULT_TIMEOUT):
    t = page_target(port, url_contains)
    if not t:
        return None
    return CDP(t["webSocketDebuggerUrl"], timeout=timeout)


def new_tab(port=DEFAULT_PORT, url="about:blank"):
    """开新标签并返回 target 信息（CDP 的 /json/new 需要 PUT）。"""
    try:
        return _http_json(port, "/json/new?" + urllib.parse.quote(url, safe=":/?=&"), method="PUT")
    except Exception:
        return None


def close_browser(port=DEFAULT_PORT, timeout=5):
    """让浏览器自己退出（用 CDP 的 Browser.close，比 taskkill 温和）。"""
    cdp = connect(port)
    if not cdp:
        return False
    try:
        cdp.send("Browser.close", timeout=timeout)
        return True
    except Exception:
        return False
    finally:
        try:
            cdp.close()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
# 启动浏览器（带调试端口）
# ═══════════════════════════════════════════════════════════

def default_profile_dir():
    try:
        from scripts import paths
        return os.path.join(paths.WORKDIR, "browser-profile")
    except Exception:
        return os.path.join(os.path.expanduser("~"), ".boss-daily-apply", "browser-profile")


def profile_dir():
    return os.path.abspath(os.path.expanduser(
        os.environ.get("BOSS_CDP_PROFILE") or default_profile_dir()))


def launch(port=DEFAULT_PORT, browser_path=None, headless=False, url=None, wait=12):
    """用调试端口拉起浏览器。已在监听就直接返回。

    默认用独立 profile（首次需登录一次）。想复用日常登录，把 BOSS_CDP_PROFILE
    指向真实 profile，并先关掉所有浏览器实例——否则新进程只会把参数交给已有实例，
    调试端口起不来。

    Windows 上必须让子进程脱离当前控制台（DETACHED_PROCESS），否则宿主会话结束时
    浏览器会被一起回收、调试端口随之消失。这是踩过的坑，别改回 Start-Process。
    """
    if available(port):
        return True, "调试端口 %d 已在监听" % port

    if not browser_path:
        try:
            from scripts import browser as _browser
            b = _browser.pick()
            browser_path = b["path"] if b else ""
        except Exception:
            browser_path = ""
    if not browser_path or not os.path.exists(browser_path):
        return False, "没找到可用的 Chromium 系浏览器；先跑 python scripts/browser.py --list"

    prof = profile_dir()
    os.makedirs(prof, exist_ok=True)
    args = [
        browser_path,
        "--remote-debugging-port=%d" % port,
        "--user-data-dir=%s" % prof,
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate",
    ]
    if headless:
        args.append("--headless=new")
    args.append(url or "about:blank")

    cmdline = " ".join('"%s"' % a if " " in a else a for a in args)
    try:
        kwargs = {"close_fds": True}
        if sys.platform.startswith("win"):
            # DETACHED_PROCESS(0x8) | CREATE_NEW_PROCESS_GROUP(0x200)
            kwargs["creationflags"] = 0x00000008 | 0x00000200
        subprocess.Popen(args, **kwargs)
    except Exception as e:
        return False, "启动失败: %s\n手动执行：\n%s" % (e, cmdline)

    deadline = time.time() + wait
    while time.time() < deadline:
        if available(port):
            return True, "已启动 %s（调试端口 %d，profile: %s）" % (
                os.path.basename(browser_path), port, prof)
        time.sleep(0.5)
    return False, (
        "已尝试启动，但 %ds 内调试端口未就绪。\n"
        "常见原因：这个浏览器已用同一个 profile 在运行（先全部关掉），"
        "或该版本不支持 --remote-debugging-port。\n"
        "可手动执行下面这条，成功后再跑 --check：\n%s" % (wait, cmdline))


# ═══════════════════════════════════════════════════════════
# 后端适配层：把 WebBridge 的 action 翻译成 CDP 调用
# ═══════════════════════════════════════════════════════════

class Backend:
    """冒充 WebBridge 的 /command 接口，让上层脚本一行都不用改。

    只实现真正被用到的动作：evaluate / navigate / click / list_tabs /
    activate_tab / close_tab。其余（snapshot、screenshot）是诊断用的，
    这里直接报错，免得静默返回空让人以为成功。
    """

    name = "cdp"

    def __init__(self, port=DEFAULT_PORT):
        self.port = port
        self.conns = {}          # session -> CDP
        self.owned = {}          # session -> targetId

    # ── 连接管理 ─────────────────────────────────────────
    def _alive(self, session):
        conn = self.conns.get(session)
        if not conn:
            return False
        try:
            return conn.evaluate("1+1", await_promise=False) == 2
        except Exception:
            self.conns.pop(session, None)
            self.owned.pop(session, None)
            return False

    def _connect_id(self, target_id, timeout=DEFAULT_TIMEOUT):
        for t in targets(self.port):
            if t.get("id") == target_id:
                return CDP(t["webSocketDebuggerUrl"], timeout=timeout)
        return None

    def _conn(self, session):
        """拿到该 session 对应的页面连接。

        boss-main 优先认领**用户已经打开的 BOSS 标签页**（登录态在里面），
        其它 session（如补发图用的 boss-img）单独开一个标签，互不打扰。
        """
        if self._alive(session):
            return self.conns[session]

        if session == "boss-main":
            t = page_target(self.port, url_contains="zhipin.com") or page_target(self.port)
            if t:
                conn = CDP(t["webSocketDebuggerUrl"])
                self.conns[session] = conn
                self.owned[session] = t["id"]
                return conn

        # 其它 session，或一个标签页都没有：新建一个
        anchor = next(iter(self.conns.values()), None)
        if anchor is None:
            t = page_target(self.port)
            if not t:
                raise CDPError("浏览器里没有任何标签页，先跑 python scripts/cdp_client.py --launch")
            anchor = CDP(t["webSocketDebuggerUrl"])
            self.conns["__anchor__"] = anchor

        r = anchor.send("Target.createTarget", {"url": "about:blank"})
        tid = r.get("targetId")
        time.sleep(0.4)
        conn = self._connect_id(tid) if tid else None
        if conn is None:
            raise CDPError("新标签页建好了但连不上（targetId=%s）" % tid)
        self.conns[session] = conn
        self.owned[session] = tid
        return conn

    # ── 动作分发 ─────────────────────────────────────────
    def api(self, action, args=None, session="boss-main", timeout=None):
        args = args or {}
        if action == "evaluate":
            return {"data": {"value": self._conn(session).evaluate(args.get("code", ""))}}

        if action == "navigate":
            conn = self._conn(session)
            conn.navigate(args.get("url", ""))
            return {"data": {"ok": True}}

        if action == "click":
            ok = self._conn(session).click(args.get("selector", ""))
            return {"data": {"success": bool(ok)}}

        if action == "list_tabs":
            return {"data": {"tabs": [
                {"tabId": t.get("id"), "url": t.get("url"),
                 "title": t.get("title"), "groupTitle": ""}
                for t in targets(self.port)]}}

        if action == "bring_to_front":
            # 后台标签会被 Chromium 降频：渲染暂停、执行上下文时有时无。
            # CDP 里"切前台"就是 activate 该标签的 target（与 playwright
            # bring_to_front 等价，供 send_followup 第二标签模式用）。
            tid = self.owned.get(session)
            anchor = self.conns.get(session) or next(iter(self.conns.values()), None)
            if anchor is None:
                t = page_target(self.port)
                if not t:
                    return {"data": {"ok": False}}
                anchor = CDP(t["webSocketDebuggerUrl"])
            if not tid:
                t = page_target(self.port, url_contains="zhipin.com") or page_target(self.port)
                tid = (t or {}).get("id")
            if not tid:
                return {"data": {"ok": False}}
            try:
                anchor.send("Target.activateTarget", {"targetId": tid})
            except CDPError:
                return {"data": {"ok": False}}
            return {"data": {"ok": True}}

        if action in ("activate_tab", "close_tab"):
            tid = args.get("tabId")
            anchor = self.conns.get(session) or next(iter(self.conns.values()), None)
            if anchor is None:
                t = page_target(self.port)
                if not t:
                    return {"data": {"ok": False}}
                anchor = CDP(t["webSocketDebuggerUrl"])
            method = "Target.activateTarget" if action == "activate_tab" else "Target.closeTarget"
            try:
                anchor.send(method, {"targetId": tid})
            except CDPError:
                return {"data": {"ok": False}}
            if action == "close_tab":
                for s, t in list(self.owned.items()):
                    if t == tid:
                        self.conns.pop(s, None)
                        self.owned.pop(s, None)
            return {"data": {"ok": True}}

        raise CDPError(
            "CDP 后端不支持动作 %r（WebBridge 专有）。投递主流程不需要它；"
            "诊断类脚本请改用 WebBridge 或 browser.py。" % action)

    def close(self):
        for c in list(self.conns.values()):
            try:
                c.close()
            except Exception:
                pass
        self.conns.clear()
        self.owned.clear()


# ═══════════════════════════════════════════════════════════
# 自检：不需要登录，起个 headless 打一轮
# ═══════════════════════════════════════════════════════════

def selftest():
    import tempfile
    tmp = tempfile.mkdtemp(prefix="cdp-selftest-")
    page = os.path.join(tmp, "t.html")
    with open(page, "w", encoding="utf-8") as f:
        f.write("""<!doctype html><meta charset="utf-8"><title>cdp-selftest</title>
<body><button id="b" onclick="window.__clicked=(window.__clicked||0)+1">hit</button>
<div id="out">ready</div></body>""")

    port = int(os.environ.get("BOSS_CDP_TEST_PORT") or random.randint(9300, 9800))
    ok, msg = launch(port=port, headless=True, wait=20)
    print(("✓ " if ok else "✗ ") + msg)
    if not ok:
        return 1
    cdp = None
    try:
        cdp = connect(port, timeout=15)
        if not cdp:
            print("✗ 连不上 page target（可能 headless 没建成标签页）")
            return 1
        print("✓ 已连接 page target")

        assert cdp.evaluate("1+1") == 2, "evaluate 算术失败"
        print("✓ Runtime.evaluate")

        cdp.navigate("file:///" + page.replace("\\", "/"))
        assert cdp.evaluate("document.title") == "cdp-selftest", "navigate 失败"
        print("✓ Page.navigate + 标题校验")

        hit = cdp.click("#b")
        assert hit and cdp.evaluate("window.__clicked || 0") == 1, "click 失败"
        print("✓ Input 鼠标点击")

        assert cdp.evaluate("document.querySelector('#out').innerText") == "ready", "DOM 读取失败"
        print("✓ DOM 读取")
        return 0
    finally:
        # 让浏览器自己退出（headless 实例，不留窗口）
        close_browser(port)
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    args = sys.argv[1:]
    if "--selftest" in args:
        return selftest()
    if "--check" in args:
        port = int(os.environ.get("BOSS_CDP_PORT") or DEFAULT_PORT)
        v = version(port)
        if not v:
            print("✗ 端口 %d 没有 CDP 服务" % port)
            print("  起一个：python scripts/cdp_client.py --launch")
            return 2
        print("✓ CDP 就绪: %s %s" % (v.get("Browser"), v.get("Protocol-Version")))
        for t in targets(port):
            print("  - %s  %s" % (t.get("title", "")[:40], (t.get("url") or "")[:70]))
        return 0
    if "--launch" in args or "--serve" in args:
        port = int(os.environ.get("BOSS_CDP_PORT") or DEFAULT_PORT)
        headless = "--headless" in args
        browser = ""
        if "--browser" in args:
            browser = args[args.index("--browser") + 1]
        url = ""
        if "--url" in args:
            url = args[args.index("--url") + 1]
        ok, msg = launch(port=port, browser_path=browser or None,
                         headless=headless, url=url or None)
        print(("✓ " if ok else "✗ ") + msg, flush=True)

        # --serve：启动后自己常驻，浏览器作为子进程跟着活。
        # 为什么需要它：某些宿主（IDE / 智能体 / 沙箱）会在命令结束时回收整棵进程树，
        # 单独 Popen 出来的浏览器会立刻被杀。留一个常驻父进程是最省事、最可靠的办法。
        # 智能体里这样用：把这条命令丢到后台任务里跑，后续命令照常用的调试端口访问。
        if ok and "--serve" in args:
            print("CDP 常驻中（结束本进程浏览器会一起退出）。端口 %d，可用 "
                  "python scripts/cdp_client.py --check 验证。" % port, flush=True)
            try:
                while True:
                    time.sleep(20)
                    if not available(port):
                        print("✗ 端口已消失，浏览器可能被关掉了", flush=True)
                        return 1
            except KeyboardInterrupt:
                return 0

        if ok:
            print("下一步：在打开的窗口里登录 BOSS直聘（只需一次），然后")
            print("  python scripts/env_check.py")
        return 0 if ok else 1
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
