# -*- coding: utf-8 -*-
"""发简历图 + 按方向附一句（greetings.json）。WorkBuddy 沙箱推荐 CDP + 当前标签。

用法（WorkBuddy 沙箱）：
    BOSS_BACKEND=cdp python send_img2.py 5 --msg --same-tab       # 最近 5 家：发图 + 一句话
    BOSS_BACKEND=cdp python send_img2.py 5 --msg --same-tab --dry # 只打印「谁配哪句」，不动浏览器
    BOSS_BACKEND=cdp python send_img2.py 1 "深投数科" --msg --same-tab
    BOSS_BACKEND=cdp python send_img2.py --job <jobId> --msg --auto-img --same-tab
    python send_img2.py 1 "某某实业" --msg --same-tab --img resume/out/简历-fe-vue-某某实业-20261103.png
                                                                  # 送按 JD 定制的那张图

第二标签模式（不传 --same-tab，session=boss-img）目前暂停使用 / 实验性：
    WorkBuddy 沙箱里第二标签可能丢失登录态；真实补发不要新建第二标签。
    普通终端确需隔离搜索页时才可显式实验，并必须先通过批次预检。

批次安全：主循环前强制预检；BROWSER_DEAD / LOGIN_REQUIRED / LIST_NOT_READY
均终止整批，绝不伪装成公司级 SKIP。只有真正的 NOT_FOUND 才跳过当前公司。

为什么不用 fetch 取图：
    新版 Chrome 的「本地网络访问」权限会拦掉 https 页面 fetch http://127.0.0.1，
    报 TypeError: Failed to fetch（补 PNA 预检头也无效）。改成 base64 分片推进页面
    内组装 Blob，实测 17/17 成功。

发送按钮：textarea.input + div.btn-v2.btn-sure-v2（空内容带 disabled）。
填入内容后 class 去掉 disabled —— 以此为「可点」判据，不盲点。
"""
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.dirname(_HERE))
from scripts import paths  # noqa: E402
import send_img as S  # noqa: E402
import scripts.webbridge_client as W  # noqa: E402

IMG = paths.resume_img()
RENDER = os.path.join(paths.resume_variants(), "render.py")
VARIANTS_JSON = os.path.join(paths.resume_variants(), "variants.json")
IMG_MODE_LOG = paths.state("img_mode_log.json")
AUTO_IMG = False
IMG_OVERRIDE = ""
CHUNK = 120000
GREET = paths.config("greetings.json")
PROGRESS = paths.state("stream_progress.json")
LOG = paths.state("resume_bundle_log.json")
GREETING_LOG = paths.state("greeting_log.jsonl")
CHAT_URL = "https://www.zhipin.com/web/geek/chat"
TAB2 = "boss-img"
TAB2_ID = None


def ensure_foreground():
    """把正在用的标签切到前台。

    踩过的坑：第二个标签在后台时，图片上传的 change 事件会被忽略——注入返回 'OK'、
    会话条数却不变，而按「图片张数」判定的旧 verify 会把历史图片数成成功（假阳性）。
    same-tab 模式同样需要：浏览器窗口/标签在后台时上传也会静默失败。
    """
    global TAB2_ID
    if SESSION_NAME == W.SESSION:
        try:
            W.api('bring_to_front', {})
            time.sleep(1.2)
            return True
        except Exception:
            return False
    if not TAB2_ID:
        try:
            for t in W.api('list_tabs', {}).get('data', {}).get('tabs', []):
                if (t.get('groupTitle') or '').endswith(SESSION_NAME):
                    TAB2_ID = t.get('tabId')
                    break
        except Exception:
            pass
    if not TAB2_ID:
        return False
    try:
        W.api('activate_tab', {'tabId': TAB2_ID})
        time.sleep(1.2)
        return True
    except Exception:
        return False

FILL_JS = """(function(){var msg=%s;
var ta=document.querySelector('textarea.input');
if(ta&&ta.offsetParent){var d=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value');
 d.set.call(ta,msg);ta.dispatchEvent(new Event('input',{bubbles:true}));return 'FILLED:'+ta.value.length;}
var ce=document.querySelector('#chat-input');
if(!ce){return 'NO_INPUT';}
ce.focus();
try{document.execCommand('selectAll',false,null);document.execCommand('delete',false,null);}catch(e){}
var ok=false;
try{ok=document.execCommand('insertText',false,msg);}catch(e){}
if(ok&&ce.innerText.trim().length){return 'FILLED_CE:'+ce.innerText.length;}
ce.innerText=msg;ce.dispatchEvent(new InputEvent('input',{bubbles:true}));
return 'FILLED_NATIVE:'+ce.innerText.length;})()"""

# 注意：页面上有两个 .btn-sure-v2，不带 btn-send 的那个是隐藏控件（点了会触发「请求交换电话」等动作）。
# 必须同时满足「带 btn-send」「可见」「未 disabled」才允许点。
BTN_JS = """(function(){var bs=document.querySelectorAll('.btn-sure-v2.btn-send');if(!bs.length)return 'NO_BTN';
for(var i=0;i<bs.length;i++){var b=bs[i];if(b.offsetParent&&b.className.indexOf('disabled')<0)return 'READY';}
return 'NOT_READY';})()"""
CLICK_JS = """(function(){var bs=document.querySelectorAll('.btn-sure-v2.btn-send');
for(var i=0;i<bs.length;i++){var b=bs[i];if(b.offsetParent&&b.className.indexOf('disabled')<0){b.click();return 'clicked';}}
return 'not-ready';})()"""
CLEAR_JS = """(function(){var ta=document.querySelector('textarea.input');
if(ta&&ta.offsetParent){var d=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value');
 d.set.call(ta,'');ta.dispatchEvent(new Event('input',{bubbles:true}));return 'CLEARED';}
var ce=document.querySelector('#chat-input');
if(ce){ce.focus();
 try{document.execCommand('selectAll',false,null);document.execCommand('delete',false,null);}catch(e){}
 return 'CLEARED';}
return 'NO_INPUT';})()"""
LAST_JS = """(function(){var c=document.querySelector('.chat-conversation');if(!c)return '';
var it=c.querySelectorAll('.message-item');var l=it[it.length-1];if(!l)return '';
return l.className+'|'+l.querySelectorAll('img').length+'|'+((l.innerText||'').trim().slice(0,30));})()"""
# 我发的图片只能按 item-myself 里的 img 数判断（对方消息里的 img 是头像，不可靠）。
# 再加一道 naturalHeight 过滤：头像尺寸很小，真简历图是长图，避免将来 DOM 改版把头像算进来。
MY_IMG_JS = """(function(){var it=document.querySelectorAll('.message-item.item-myself img'),n=0;
for(var i=0;i<it.length;i++){if(it[i].naturalHeight>100)n++;}return String(n)})()"""
MY_TEXT_JS = """(function(){var it=document.querySelectorAll('.message-item.item-myself');var o=[];
for(var i=0;i<it.length;i++){o.push((it[i].innerText||'').replace(/\\s+/g,''));}return o.join('|')})()"""
MSG_COUNT_JS = """(function(){return String(document.querySelectorAll('.chat-conversation .message-item').length)})()"""
ALL_MSG_JS = """(function(){var c=document.querySelector('.chat-conversation');if(!c)return '';
var it=c.querySelectorAll('.message-item');var o=[];
for(var i=Math.max(0,it.length-3);i<it.length;i++){o.push(it[i].className.replace('message-item','').trim()+'~'+((it[i].innerText||'').trim().slice(0,26).replace(/\\n/g,' ')));}
return o.join(' ;; ')})()"""
# 最近 3 条的 class+文本，供「发出去了吗」判定用（容忍尾部系统提示）
RECENT_JS = ALL_MSG_JS


def bind_tab(session):
    """把 send_img 模块里的 evaluate/click/navigate 整体切到指定 session。"""
    S.evaluate = lambda code, session=None: W.evaluate(code, session=session or SESSION_NAME)
    S.click = lambda sel, session=None: W.click(sel, session=session or SESSION_NAME)
    S.navigate = lambda url, wait_range=(4, 6), session=None: W.navigate(
        url, wait_range, session or SESSION_NAME)


SESSION_NAME = W.SESSION


def stage_blob(path=None):
    b64 = base64.b64encode(open(path or IMG, 'rb').read()).decode()
    S.ev("window.__b64='';window.__rb=null;window.__rbe=null;")
    for i in range(0, len(b64), CHUNK):
        if not S.ev("window.__b64+='" + b64[i:i + CHUNK] + "';window.__b64.length"):
            return False
    r = S.ev(
        "(function(){try{var s=atob(window.__b64);var u=new Uint8Array(s.length);"
        "for(var i=0;i<s.length;i++)u[i]=s.charCodeAt(i);"
        "window.__rb=new Blob([u],{type:'image/png'});return String(window.__rb.size);}"
        "catch(e){window.__rbe=String(e);return ''}})()"
    )
    return bool(r and r.isdigit())


S.stage_blob = stage_blob


def load_variants():
    try:
        return json.load(open(VARIANTS_JSON, encoding="utf-8")).get("map", {})
    except Exception:
        return {}


def render_for(variant, company):
    """调 render.py 出一张定制图；失败返回空串（调用方退回通用图）。"""
    if not os.path.exists(RENDER):
        return ""
    try:
        r = subprocess.run([sys.executable, RENDER, "--variant", variant,
                            "--company", company or "无公司"],
                           capture_output=True, text=True, timeout=120,
                           encoding="utf-8", errors="ignore")
        info = json.loads(r.stdout or "{}")
        if info.get("ok") and not info.get("overflow"):
            return info.get("png") or ""
    except Exception:
        pass
    return ""


def choose_image(rec):
    """返回 (图片路径, 模式标签)。模式标签会落盘，供 A/B 统计分组。

    收的是**投递记录**而不是公司名：同一家投两个岗位时，按公司名反查会拿到后投的那条，
    于是两个岗位都被分进同一个方向、发同一张图（即"串档"）。按记录取 direction 才准。

    A/B 仍按公司名的 md5 分桶（不是 jobId）：同一家公司要固定在同一组，
    重发时不会跨组。
    """
    if IMG_OVERRIDE:
        return IMG_OVERRIDE, "manual"
    if not AUTO_IMG:
        return IMG, "generic:static"

    rec = rec or {}
    company = rec.get("company") or ""
    if not rec.get("jobId"):
        # 没匹配到投递记录就别分桶——A/B 只对有台账的投递成立
        return IMG, "unknown"
    bucket = "A" if int(hashlib.md5(company.encode("utf-8")).hexdigest(), 16) % 2 == 0 else "B"
    if bucket == "B":
        return IMG, "B:generic"          # 对照组：照旧发通用图

    variant = load_variants().get(rec.get("direction") or "")
    if not variant:
        return IMG, "A:no-variant"       # A 组但这个方向还没有变体
    png = render_for(variant, company)
    if not png:
        return IMG, "A:render-failed"
    return png, "A:" + variant


def log_img_mode(rec, mode, path):
    """记「这一条投递打算发哪张图」。

    键用 jobId（回退公司名）：按公司名做键时，同公司第二个岗位会覆盖第一个，
    A/B 分组表里两条记录会拿到同一个 mode，把分组统计污染掉。
    旧文件是公司名键，读取端先按 jobId 再按公司名回退，不迁移。
    """
    log = {}
    if os.path.exists(IMG_MODE_LOG):
        try:
            log = json.load(open(IMG_MODE_LOG, encoding="utf-8"))
        except Exception:
            log = {}
    rec = rec or {}
    company = rec.get("company") or ""
    key = (rec.get("jobId") or company).strip()
    log[key] = {"mode": mode, "img": path, "company": company,
                "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    json.dump(log, open(IMG_MODE_LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def load_records(limit=150):
    """台账里的投递记录列表（不是按公司去重的 dict）。

    去重后的 dict 会让同公司的后一条覆盖前一条——那是串档的根因。这里保持列表。
    """
    try:
        return json.load(open(PROGRESS, encoding='utf-8')).get('delivered', [])[-limit:]
    except Exception:
        return []


def bucket_text(b):
    """v1 只有 text，v2 有 text(成品) 与 lead(中间量)。任一存在即可，绝不 KeyError。"""
    return b.get('text') or b.get('lead') or ''


def pick_greeting(rec):
    """按**投递记录**选桶。

    以前是「先命中先用」，导致「AI应用开发（后端/数据方向）」被 java 桶抢先命中
    （因为 java 的 match 里有泛化的"后端"）。现在改成按词权重累加：
    具体技术词（Java/Python/AI/Agent/大模型/前端）权重高，泛化词（后端/数据/应用开发）权重低，
    分数最高且 >0 的桶胜出，全 0 才走 default。
    """
    cfg = json.load(open(GREET, encoding='utf-8'))
    rec = rec or {}

    # ① direction 是投递时人工标的，直接映射最准
    dmap = cfg.get('direction_map') or {}
    want = dmap.get((rec.get('direction') or '').strip())
    if want:
        b = next((x for x in cfg['buckets'] if x['id'] == want), None)
        if b:
            return b['id'], bucket_text(b)

    # ② 没标方向的才退回加权打分。keyword 刻意不参与——
    #    那是搜索词不是岗位属性，会把「AI Agent实习」这类词带进不相干的岗位
    blob = " ".join([rec.get('title') or '', rec.get('company') or '']).lower()

    best, best_score = None, 0
    detail = []
    for b in cfg['buckets']:
        score = 0
        m = b.get('match') or {}
        items = m.items() if isinstance(m, dict) else [(k, 1) for k in m]
        for kw, w in items:
            if kw.lower() in blob:
                score += int(w)
        detail.append("%s=%d" % (b['id'], score))
        if score > best_score:
            best, best_score = b, score
    if best is None:
        # default 指向一个不存在的桶（旧配置里可能是 backend）时，退到 generic，再退到第一个
        best = (next((b for b in cfg['buckets'] if b['id'] == cfg.get('default')), None)
                or next((b for b in cfg['buckets'] if b['id'] == 'generic'), None)
                or cfg['buckets'][0])
    return best['id'], bucket_text(best)


def greeting_prefixes(path=None):
    """用于判断"这句话是不是我发过"，取每桶文案的开头做指纹。

    两个必须守住的点：
    1. 空文案绝不能进来——`"" in 任意字符串` 恒真，会让 already_msg 永远成立，
       于是所有"发过图没发字"的会话都被判成"已发全"永久跳过。
    2. 开头几个字不能撞上**账号里的默认招呼语**。MY_TEXT_JS 收集的是这个会话里
       我发过的全部文字，默认招呼语也在里面；如果某个桶的头 6 个字恰好是
       "2027届本科"这种默认招呼语也有的片段，already_msg 会对所有人成立。
       所以每个桶的文案都要用一句默认招呼语不会有的开头（见 pitfalls #31）。
    3. 两个桶的开头若重复（python 与 algo 都从"拿过省大数据赛"开头），
       6 字区分不了，自动拉长到 10 字。
    """
    cfg = json.load(open(path or GREET, encoding='utf-8'))
    texts = [t for t in (bucket_text(b)[:10] for b in cfg['buckets']) if t]
    six = [t[:6] for t in texts]
    n = 10 if len(set(six)) < len(six) else 6
    out = [t[:n] for t in texts]
    own = (cfg.get("own_default_greeting") or "").replace(" ", "")
    if own:
        for p in out:
            if p.replace(" ", "") in own:
                print("WARN 文案前缀「%s」出现在账号默认招呼语里 → already_msg 会恒真，"
                      "这一桶将永远被判成'已发过'。改这一桶的开头（保持 6 个字内不重叠）。"
                      % p.strip(), flush=True)
    return out


def text_already_sent(my_text, prefixes):
    """这段会话文字里，是否已经有我发过的方向文案。

    单独抽出来是为了能被验收脚本直接调用：这个判据一旦在真实配置下恒真，
    整个补发会静默失效（每家都 SKIP 已发全），而界面和日志都看不出来。
    """
    t = (my_text or "").replace(" ", "")
    return any((p or "").replace(" ", "") and p.replace(" ", "") in t for p in prefixes)


def send_text(msg):
    if not (msg or '').strip():
        # 空文案会让 FILL_JS 填不进去、按钮保持 disabled，白等 3 秒再记一条 FAIL；
        # 更糟的是自校验 msg[:8] 为空串时恒真，会返回假的 SENT。
        return 'SKIP_EMPTY'
    r = S.ev(FILL_JS % json.dumps(msg, ensure_ascii=False))
    if not (r or '').startswith('FILLED'):
        return 'FAIL:' + (r or '')
    time.sleep(0.5)
    st = S.ev(BTN_JS)
    # 按钮从 disabled 变可点有一小段延迟（execCommand 触发的是真实 input 事件，Vue 异步更新），
    # 单次读取常常正好读到还没解锁的那一帧 → 轮询最多 3 秒
    for _ in range(6):
        if st == 'READY':
            break
        time.sleep(0.5)
        st = S.ev(BTN_JS)
    if st != 'READY':
        S.ev(CLEAR_JS)
        return 'FAIL:' + (st or '')
    S.ev(CLICK_JS)
    time.sleep(2.5)
    # 取最近 3 条判断：发送后 BOSS 可能补一条 item-system，只看最后一条会误判
    tail = S.ev(RECENT_JS) or ""
    ok = "item-myself" in tail and msg[:8] in tail
    if not ok:
        time.sleep(2)
        tail = S.ev(RECENT_JS) or ""
        ok = "item-myself" in tail and msg[:8] in tail
    if not ok:
        S.ev(CLEAR_JS)
        return 'UNVERIFIED:' + (S.ev(ALL_MSG_JS) or '')[:70]
    return 'SENT'


def wait_conv_list(timeout=15):
    """等左侧会话列表真的渲染出来，返回条数（0 = 超时）。

    新标签 goto 之后有一段时间 execution context 会被销毁重建，这期间
    `evaluate` 会抛 "Execution context was destroyed" 并被上层吞成空串。
    空串看起来就像"这家公司没有会话"——于是整批目标全被判 notfound。
    这不是找不到人，是页面还没就绪；先等列表，再按名字找。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            n = int(S.ev("document.querySelectorAll('.user-list [role=listitem]').length") or 0)
        except Exception:
            n = 0
        if n:
            return n
        time.sleep(0.8)
    return 0


def classify_batch_state(url, list_count=0, probe="", body=""):
    """把批次异常分层；纯函数便于无浏览器回归测试。

    登录墙优先级最高：即使读取列表同时报错，也必须报告 LOGIN_REQUIRED，
    绝不继续重试或把登录页当成“列表还没渲染”。
    """
    url = str(url or "")
    probe = str(probe or "")
    body = str(body or "")
    login_url = url.lower()
    if any(x in login_url for x in ("passport", "verify", "login")) or any(
            x in body for x in ("安全验证", "滑块", "请输入验证码", "扫码登录",
                                "账号登录", "密码登录", "请先登录", "登录后继续")):
        return "LOGIN_REQUIRED", "检测到登录页/验证码/安全验证，URL=" + url[:120]
    if not url or url.startswith("EXC:") or probe.startswith("EXC:"):
        detail = probe or url or "无法读取当前 URL"
        return "BROWSER_DEAD", "CDP/桥或页面连接不可用：" + detail[:120]
    try:
        n = int(list_count or 0)
    except (TypeError, ValueError):
        n = 0
    if n <= 0:
        return "LIST_NOT_READY", "会话列表持续为空，URL=" + url[:120]
    return "OK", "会话列表已就绪（%d 条）" % n


def batch_preflight(timeout=15, probe=""):
    """发送前确认页面、登录态和真实会话列表；任何非 OK 都必须停批。"""
    url = S.ev("location.href") or ""
    body = S.ev("document.body?document.body.innerText.slice(0,20000):''") or ""
    state, why = classify_batch_state(url, 1, probe=probe, body=body)
    if state != "OK":
        return state, why
    n = wait_conv_list(timeout)
    # 等待期间可能跳登录页或浏览器可能退出，必须重新读取，不能沿用旧 URL。
    url = S.ev("location.href") or ""
    body = S.ev("document.body?document.body.innerText.slice(0,20000):''") or ""
    return classify_batch_state(url, n, probe=probe, body=body)


def classify_header_state(company, header, preflight_code="", preflight_why="", title=""):
    """会话已点开之后，标题能不能作为「确实开对了」的证据。

    ok=True 但标题为空是**定位异常**，不是「标题不符」：页面可能正在重渲染、
    执行上下文刚被销毁，或者浏览器已经退出。把它当标题不符继续下一家，会让
    整批变成静默 SKIP（历史上就是这样误杀了整批会话）。

    有些会话的右侧标题栏只显示「HR / 职位」，不显示公司名（实测 ONES、伙旺），
    此时公司名验证必然失败。点击前已经按公司键命中过列表项，标题栏岗位片段
    一致即可放行；两者都无证据才判标题不符。
    """
    h = str(header or "").strip()
    if not h or h.startswith("EXC:"):
        if preflight_code and preflight_code != "OK":
            return preflight_code, preflight_why or ("定位后页面异常：" + h[:120])
        return "LIST_NOT_READY", "会话已打开但标题为空/异常（%r），不能按标题不符跳过" % h[:60]
    if any(k in h for k in company_keys(company)):
        return "OK", h
    for p in title_probes(title):
        if p in h:
            return "OK", h
    return "TITLE_MISMATCH", h


def open_result_fallback_code(ok, header):
    """主循环的停批判据；空串表示可继续 NOT_FOUND 或正常标题匹配。

    ok=True 只代表点击流程结束，不代表会话标题读取成功。空/空白 header
    按 LIST_NOT_READY 停批，EXC 按 BROWSER_DEAD 停批，不能落入公司级标题不符。
    """
    reason = str(header or "")
    if ok:
        if not reason.strip():
            return "LIST_NOT_READY"
        if reason.startswith("EXC:"):
            return "BROWSER_DEAD"
        return ""
    return "" if reason.lower() == "notfound" else "LIST_NOT_READY"


_BRACKET_RE = re.compile(r"[【\[（(][^】\]）)]*[】\]）)]")


def title_probes(title):
    """岗位名的可匹配形式：整串、去「【实习】/（可转正）」这类括号片段后的主体、主体前 6 字。

    固定取前 4 字会在「【实习】大数据开发」和「【实习】前端开发」上撞车——
    两条岗位的前缀一模一样，谁先出现就点谁，最后发错人或把对会话判成不符
    （2026-11-05 实测：Shopee / Anker 各有两个岗位）。括号里通常是招聘标签
    而不是岗位内容，去掉它才是真正能区分岗位的部分。
    """
    t = (title or "").strip()
    if not t:
        return []
    out = [t]
    body = re.sub(r"\s+", " ", _BRACKET_RE.sub(" ", t)).strip()
    if len(body) >= 4 and body not in out:
        out.append(body)
    if len(body) >= 6 and body[:6] not in out:
        out.append(body[:6])       # 列表里的岗位名可能被截断
    return [p for p in out if len(p) >= 4]


def company_keys(company):
    """公司名的多个可匹配形式：全名、去「有限公司」、前 6 字。

    聊天列表对长公司名会截断成「深圳墨生万物人工...」，只拿全名 indexOf
    永远匹配不上——会被误判成 NOT_FOUND。
    """
    c = (company or "").strip()
    out = []
    for k in (c, c.replace("有限公司", "").strip(), c[:6], c.replace("有限公司", "").strip()[:6]):
        k = k.strip()
        if len(k) >= 2 and k not in out:
            out.append(k)
    return out


def _locate_js(keys, probes, job_id=""):
    """数据源定位用的 JS（单独成型，便于自测里真跑这段代码而不是复刻一份）。

    job_id 存在时优先走 encryptJobId 精确匹配：BOSS 改版后数据源里已没有
    jobName/positionName（title 变成了 HR 角色「招聘者/招聘经理」、sourceTitle 为空），
    靠岗位名文本打分必然得 0，会被误判成「标题不符」而整批静默跳过。
    """
    return r"""
    (() => {
      const el = document.querySelector('.user-list-content');
      const vm = el && el.__vue__;
      const ds = (vm && vm.$props && vm.$props.dataSources) || [];
      const ks = %s, pr = %s, wantJob = %s;
      // ① 首选：encryptJobId 精确命中，彻底绕开文本匹配的歧义（同公司多岗位也不会串档）
      if (wantJob) {
        for (let i = 0; i < ds.length; i++) {
          if (String(ds[i].encryptJobId || '') === wantJob) {
            return JSON.stringify({idx: i, best: 9999, second: 0, total: ds.length,
                                   name: String(ds[i].brandName || ''),
                                   job: String(ds[i].jobName || ''), byJob: true});
          }
        }
      }
      const norm = s => String(s || '').replace(/\.\.\.$|…$/g, '');
      const cok = b => ks.some(k => b.includes(k)) || ks.some(k => k.includes(norm(b)) && norm(b).length >= 4);
      // 最长公共子串：能同时容忍「列表里岗位名被截断」和「台账里多写了【实习】」
      const lcs = (a, b) => {
        a = String(a || ''); b = String(b || '');
        if (!a || !b) return 0;
        let prev = new Array(b.length + 1).fill(0), cur = new Array(b.length + 1).fill(0), best = 0;
        for (let i = 1; i <= a.length; i++) {
          for (let j = 1; j <= b.length; j++) {
            if (a.charCodeAt(i - 1) === b.charCodeAt(j - 1)) {
              cur[j] = prev[j - 1] + 1;
              if (cur[j] > best) best = cur[j];
            } else cur[j] = 0;
          }
          const tmp = prev; prev = cur; cur = tmp;
          for (let k = 0; k < cur.length; k++) cur[k] = 0;
        }
        return best;
      };
      const score = s => {
        let m = 0;
        for (let q = 0; q < pr.length; q++) { const v = lcs(pr[q], s); if (v > m) m = v; }
        return m;
      };
      let best = -1, bestS = 0, second = 0, bestName = '', bestJob = '', cand = 0, first = -1;
      for (let i = 0; i < ds.length; i++) {
        const b = String(ds[i].brandName || '');
        if (!cok(b)) continue;
        cand++; if (first < 0) first = i;
        const j = String(ds[i].jobName || ''), p = String(ds[i].positionName || '');
        let s = Math.max(score(j), score(p));
        if (pr.length && (j === pr[0] || p === pr[0])) s = 999;   // 完全一致直接胜出
        if (s > bestS) { second = bestS; bestS = s; best = i; bestName = b; bestJob = j || p; }
        else if (s > second) { second = s; }
      }
      if (!pr.length) {
        // 没给岗位名（--only 按公司找）：只有一个会话才算唯一，多个交给 --job
        if (cand === 1) { best = first; bestS = 1; second = 0; bestName = String(ds[first].brandName || ''); bestJob = String(ds[first].jobName || ''); }
        else { best = -1; return JSON.stringify({idx: -1, best: 0, second: 0, total: ds.length, name: '', job: '', ambiguous: cand > 1}); }
      }
      return JSON.stringify({idx: best, best: bestS, second: second, total: ds.length,
                             name: bestName, job: bestJob});
    })()
    """ % (json.dumps(keys, ensure_ascii=False), json.dumps(probes, ensure_ascii=False),
           json.dumps(job_id or "", ensure_ascii=False))


def locate_conv_by_data(company, title="", job_id=""):
    """在虚拟列表的完整数据源里定位会话，滚动到它并让它进入 DOM。

    聊天页左侧是虚拟滚动：DOM 里通常只渲染前 40 条，但
    `.user-list-content.__vue__.$props.dataSources` 里有全部 90+ 条。
    只按 DOM 文本找，老会话会被误判成 NOT_FOUND（11-03 那批就是这样）。
    """
    keys = company_keys(company)
    probes = title_probes(title)
    js = _locate_js(keys, probes, job_id)
    try:
        raw = S.ev(js)
        info = json.loads(raw) if raw and raw.startswith("{") else {}
    except Exception:
        info = {}
    idx = int(info.get("idx", -1))
    if idx < 0:
        if info.get("ambiguous"):
            return False, "ambiguous(0,%r)" % (company,)
        return False, "data_not_found(%s)" % info.get("total", "?")
    best = int(info.get("best") or 0)
    second = int(info.get("second") or 0)
    by_job = bool(info.get("byJob"))
    if probes and not by_job and best < 4:
        # 公司对上了但岗位名毫无重叠：宁可不发，也不点第一条碰运气
        return False, "no_title_match(best=%d)" % best
    if probes and not by_job and best == second:
        # 两条会话一样像（典型：同公司两个只差前缀的岗位）→ 交给 --job 精确寻址
        return False, "ambiguous(best=%d,%r)" % (best, info.get("job", ""))
    scroll = r"""
    (() => {
      const el = document.querySelector('.user-list-content');
      const vm = el && el.__vue__;
      if (!vm || !vm.scrollToIndex) return 'NO_SCROLL';
      vm.scrollToIndex(%d);
      // 只改 scrollTop 不会更新虚拟窗口：必须把 scroll 事件喂给组件，
      // 否则 range 仍停在 0-39，目标项永远不进 DOM。
      try { vm.onScroll({target: el}); } catch (e) {}
      el.dispatchEvent(new Event('scroll', {bubbles: true}));
      return 'OK:%d/%d';
    })()
    """ % (idx, idx, int(info.get("total") or 0))
    res = S.ev(scroll) or ""
    time.sleep(0.9)
    return res.startswith("OK"), "%s idx=%d/%s" % (res or "NO_SCROLL", idx, info.get("total", "?"))


def open_conv_for(company, title="", attempts=3, job_id=""):
    """按「公司 + 岗位名片段」定位会话。

    坑 1：一家公司可能有两个岗位、两个 HR、两个会话（比如同一家的「数据开发」和「前端」）。
    只按公司名匹配会永远命中第一个，导致第二个岗位被误判成"已发全"而漏发。
    坑 2：新标签刚打开时，evaluate 会间歇性拿到空串（执行上下文重建中）。
    一次拿空就判 notfound 会把好会话漏掉，所以整段定位最多重试 3 次。
    坑 3：虚拟列表只渲染前 40 条，老会话在数据源里但不在 DOM 里 →
    先按数据索引滚到目标，再重试点击。
    坑 4：同公司两个岗位名字只差前缀时，「点第一个」等于随机发；宁可返回
    ambiguous 停批，也不猜。
    """
    if not wait_conv_list(15):
        return False, "list_not_ready"
    header = ""
    for i in range(attempts):
        ok, header = _open_conv_once(company, title)
        if ok:
            return ok, header
        if header in ("ambiguous", "no_title_match"):
            break                      # DOM 分不清/对不上，交给数据源再判一次
        if header not in ("notfound", ""):
            return ok, header          # 真的点开了但标题不符，不再重试
        time.sleep(1.5)
    found, detail = locate_conv_by_data(company, title, job_id)
    if found:
        print("LOCATE", company, detail, flush=True)
        # 数据源已按 encryptJobId 精确定位 → 直接按下标点，避免同公司多岗位再猜一次
        m = re.search(r"idx=(\d+)/", str(detail))
        d_idx = int(m.group(1)) if m else None
        for _ in range(2):
            ok, header = _open_conv_once(company, title, dom_index=d_idx)
            if ok:
                return ok, header
            time.sleep(1.0)
    elif detail.startswith(("ambiguous", "no_title_match")):
        # 数据源也没法唯一定位：不是"没有会话"，不能按 NOT_FOUND 静默跳过
        return False, detail
    return False, header or "notfound"


def _open_conv_once(company, title="", dom_index=None):
    title = (title or "").strip()
    probes = title_probes(title)
    keys = company_keys(company)
    # dom_index 由数据源按 encryptJobId 精确算出的下标直接驱动：会话列表 DOM 的顺序
    # 与 dataSources 一致（前 40 条全渲染），同公司多岗位时只有它能唯一确定目标。
    if dom_index is not None and dom_index >= 0:
        r = S.ev("""(function(){var i=%d;
            var ls=document.querySelectorAll('.user-list [role=listitem]');
            if(i<0||i>=ls.length)return 'out_of_range:'+ls.length;
            var c=ls[i].querySelector('.friend-content')||ls[i];
            c.setAttribute('data-rb3','1');return 'found:'+i;})()""" % dom_index)
    else:
        r = S.ev("""(function(){var ks=%s,pr=%s;
var lcs=function(a,b){a=String(a||'');b=String(b||'');if(!a||!b)return 0;
 var prev=new Array(b.length+1).fill(0),cur=new Array(b.length+1).fill(0),best=0;
 for(var i=1;i<=a.length;i++){for(var j=1;j<=b.length;j++){
   if(a.charCodeAt(i-1)===b.charCodeAt(j-1)){cur[j]=prev[j-1]+1;if(cur[j]>best)best=cur[j];}else cur[j]=0;}
  var tmp=prev;prev=cur;cur=tmp;for(var k=0;k<cur.length;k++)cur[k]=0;}
 return best;};
var score=function(s){var m=0;for(var q=0;q<pr.length;q++){var v=lcs(pr[q],s);if(v>m)m=v;}return m;};
var stale=document.querySelectorAll('[data-rb3]');
for(var z=0;z<stale.length;z++){stale[z].removeAttribute('data-rb3');}
var ls=document.querySelectorAll('.user-list [role=listitem]');
var bi=-1,bs=0,second=0,cand=0,first=-1;
for(var i=0;i<ls.length;i++){
 var node=ls[i];
 var jt=node.querySelector('.name-box,.title-box,.job-name,.source-job,.job-title');
 var text=jt?(jt.innerText||''):(node.innerText||'');
 var full=node.innerText||'';
 var cok=false;for(var k=0;k<ks.length;k++){if(full.indexOf(ks[k])>=0){cok=true;break;}}
 if(!cok)continue;
 cand++;if(first<0)first=i;
 var s=score(text);
 // 首个候选必须先占位：BOSS 新版会话列表不显示岗位名，score 可能全为 0，
 // 若只写 if(s>bs) 则 bi 恒为 -1，永远选不中（实测表现为 SKIP NOT_FOUND）。
 if(bi<0){bi=i;bs=s;}
 else if(s>bs){second=bs;bs=s;bi=i;}else if(s>second){second=s;}
}
if(cand===0)return 'notfound';
if(!pr.length){
 if(cand!==1)return 'ambiguous:0';
 var c0=ls[first].querySelector('.friend-content')||ls[first];
 c0.setAttribute('data-rb3','1');return 'found:'+first;
}
if(bi<0)return 'notfound';
if(bs<4){
 // BOSS 改版后会话列表不再显示岗位名：.title-box/.name-box 里只有「HR名+公司名+角色」，
 // 拿岗位名打分必然为 0。此时只要公司名唯一命中一条会话，就按唯一性放行；
 // 命中多条才判 no_title_match / ambiguous，交给数据源按 encryptJobId 精确寻址。
 if(cand===1){bs=4;} else {return 'no_title_match:'+bs;}
}
if(bs===second&&cand>1)return 'ambiguous:'+bs;
var c=ls[bi].querySelector('.friend-content')||ls[bi];
c.setAttribute('data-rb3','1');return 'found:'+bi;})()""" % (
        json.dumps(keys, ensure_ascii=False), json.dumps(probes, ensure_ascii=False)))
    if r.startswith("ambiguous"):
        # 两条会话一样像 → 绝不点第一条碰运气，交给 --job 精确寻址
        return False, "ambiguous"
    if r.startswith("no_title_match"):
        return False, "no_title_match"
    if not r.startswith("found"):
        return False, "notfound"
    # 后台标签页(hidden=true)下 Chromium 会丢弃 Input.dispatchMouseEvent，
    # 表现是 click 返回成功但会话根本没打开（header 停在空状态提示）。
    # JS click 走 DOM 事件派发不受可见性影响，先点它；再补一次鼠标点击作兜底。
    # 打开会话是幂等操作，重复点击不会发任何消息，安全。
    S.ev("""(function(){var e=document.querySelector('[data-rb3="1"]');
        if(e){e.scrollIntoView({block:'center'});e.click();return 1;}return 0;})()""")
    time.sleep(0.8)
    S.click('[data-rb3="1"]')
    S.ev("(function(){var e=document.querySelector('[data-rb3]');if(e)e.removeAttribute('data-rb3');return 1;})()")
    time.sleep(2.2)
    # 只读 60 字会把公司名挤出截断窗口（「冯斌 / 联合创始人…」），
    # 于是明明开对了却判「标题不符」。读 160 字并轮询至非空。
    header = ""
    for _ in range(5):
        header = S.ev("(function(){var c=document.querySelector('.chat-conversation');"
                      "return c?c.innerText.slice(0,160).replace(/\\n/g,' / '):''})()")
        if header:
            break
        time.sleep(0.8)
    return True, header


def log_greeting(ev):
    """逐条 append + flush：中途 Ctrl-C 也要保住已处理的那几家。

    以前批次日志在循环结束后整车覆盖写一次，于是 11-03 那批 40 家一条不剩、
    11-04 那批 20 条被后来一次单家补发冲掉。事件流不能被"本批次"语义污染。
    """
    ev.setdefault("at", time.strftime("%Y-%m-%d %H:%M:%S"))
    try:
        with open(GREETING_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
            f.flush()
    except Exception as e:
        print("GREETING_LOG_FAIL", str(e)[:80], flush=True)


def abort_batch(log, code, why):
    """批次级失败：保留此前证据，但不给当前公司伪造 SKIP/NOT_FOUND。"""
    print("BATCH_ABORT", code, why, flush=True)
    log_greeting({"event": "batch_abort", "status": code, "why": str(why)[:200]})
    json.dump(log, open(LOG, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    return 2


def done_keys():
    """已经「图+字都成功」的记录键（jobId，回退公司名）。"""
    done = set()
    if not os.path.exists(GREETING_LOG):
        return done
    try:
        with open(GREETING_LOG, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                if e.get("status") == "OK":
                    k = e.get("jobId") or e.get("company")
                    if k:
                        done.add(k)
    except Exception:
        pass
    return done


def split_legacy(rows):
    """把台账分成（有投递时间的, 无投递时间的）。

    早期版本的 delivered 只有 company/title/jobId，没有 delivered_at / direction。
    它们是**真投递过**的记录，但没有时间戳就无法界定"该不该补"——堆在补发队列最前面，
    会让 `5 --pending` 一直啃几周前的老岗位，用户当天的积压反而排不上。
    所以默认不当成积压，只有 --include-legacy 才纳入。
    """
    live, legacy = [], []
    for r in rows:
        (legacy if not (r.get("delivered_at") or "").strip() else live).append(r)
    return live, legacy


def resolve_targets(limit, only="", job_id="", pending=False, since="", include_legacy=False):
    """挑出本轮要补发的**记录**（不是公司名）。

    --job      同公司双投时唯一可靠的寻址方式
    --pending  只挑还没有"图+字都成功"事件的，可断点续跑
    --since    只看某天之后投的
    """
    rows = [r for r in load_records(limit=100000) if (r.get("company") or "").strip()]
    if job_id:
        rows = [r for r in rows if r.get("jobId") == job_id]
    elif only:
        rows = [r for r in rows
                if only in (r.get("company") or "") or (r.get("company") or "") in only]
    if since:
        rows = [r for r in rows if (r.get("delivered_at") or "")[:10] >= since]
    if pending:
        done = done_keys()
        rows = [r for r in rows if (r.get("jobId") or r.get("company")) not in done]
        # 补发积压：先过滤已完成、再从**最旧**的开始取 limit 条。
        # 旧实现是先 rows[-limit:] 再过滤，于是 5 --pending 永远盯着台账最新 5 条；
        # 那 5 条一旦补齐，后面每一批都返回"没有记录"，积压永远不动（2026-11-05 实测）。
        if not job_id and not only and not include_legacy:
            live, legacy = split_legacy(rows)
            if legacy:
                print("NOTE 跳过 %d 条无投递时间的历史记录（--include-legacy 可纳入）"
                      % len(legacy), flush=True)
            rows = live
        if limit and not job_id and not only:
            rows = rows[:limit]
    elif limit and not job_id and not only:
        rows = rows[-limit:]
    return rows


def main():
    args = list(sys.argv[1:])
    dry = '--dry' in args
    want_msg = '--msg' in args
    same_tab = '--same-tab' in args
    pending = '--pending' in args
    include_legacy = '--include-legacy' in args
    opt = {}
    for flag in ('--img', '--job', '--since'):
        if flag in args:
            k = args.index(flag)
            opt[flag] = args[k + 1] if len(args) > k + 1 else ''
            del args[k:k + 2]
    img_override = opt.get('--img', '')
    job_id = opt.get('--job', '')
    since = opt.get('--since', '')
    auto_img = '--auto-img' in args
    args = [a for a in args if a not in ('--dry', '--msg', '--same-tab', '--auto-img',
                                         '--pending', '--include-legacy')]
    limit = int(args[0]) if args else 20
    only = args[1] if len(args) > 1 else ''

    # 允许送入按 JD 定制的简历图（默认仍是那张通用图）
    global IMG, AUTO_IMG, IMG_OVERRIDE
    if img_override:
        if not os.path.exists(img_override):
            print('IMG_NOT_FOUND', img_override, flush=True)
            return
        IMG = img_override.replace('\\', '/')
        IMG_OVERRIDE = IMG
    AUTO_IMG = auto_img

    targets = resolve_targets(limit, only, job_id, pending, since, include_legacy)
    if not targets:
        print("没有投递记录可补发：先跑投递流程，或检查 BOSS_WORKDIR 是否指对了", flush=True)
        return

    if dry:
        for i, rec in enumerate(targets, 1):
            gid, gtext = pick_greeting(rec)
            print("%2d. %-20s %-18s -> [%s] %s" % (
                i, (rec.get('company') or '')[:20], (rec.get('title') or '')[:18],
                gid, gtext[:44]), flush=True)
        return

    global SESSION_NAME, TAB2_ID
    try:
        W.require_bridge()        # 真正要动浏览器了，CDP/桥不可达就终止本批
    except SystemExit:
        return abort_batch([], "BROWSER_DEAD", "CDP/桥不可用，未进入发送循环")
    except Exception as e:
        return abort_batch([], "BROWSER_DEAD", "CDP/桥预检异常：" + str(e)[:120])
    if not same_tab:
        # 实验性：WorkBuddy 真实补发必须走下面的 --same-tab 分支。
        SESSION_NAME = TAB2
        r0 = W.api('navigate', {'url': CHAT_URL}, session=TAB2)
        TAB2_ID = (r0.get('data') or {}).get('tabId') or TAB2_ID
        bind_tab(TAB2)
        if not (r0.get('data') or {}).get('ok'):
            print("WARN 第二标签导航未确认落点，先等会话列表再说", flush=True)
        W.api('bring_to_front', {}, session=TAB2)
    else:
        SESSION_NAME = W.SESSION
        cur = S.ev("location.href") or ""
        body = S.ev("document.body?document.body.innerText.slice(0,20000):''") or ""
        code, why = classify_batch_state(cur, 1, body=body)
        if code != "OK":
            return abort_batch([], code, why)
        if "/web/geek/chat" not in cur:
            S.navigate(CHAT_URL, wait_range=(5, 7))
    time.sleep(2.0)
    code, why = batch_preflight()
    if code != "OK":
        return abort_batch([], code, why)
    print("PRECHECK OK", why, flush=True)

    prefixes = greeting_prefixes()
    log = []
    for i, rec in enumerate(targets, 1):
        company = rec.get('company') or ''
        rec_title = rec.get('title') or ''
        jid = rec.get('jobId') or ''
        # 空公司名是致命输入：open_conv 用 indexOf 匹配，空串恒命中列表第一条，
        # 会把「图 + 简历已附上」发给一个完全无关的 HR，且撤不回。
        if not company or len(company.strip()) < 2:
            log.append({"n": i, "company": company, "status": "FAIL", "why": "公司名为空，拒绝发送"})
            log_greeting({"event": "skip", "company": company, "jobId": jid or None,
                          "title": rec_title, "bucket": "", "status": "FAIL",
                          "why": "公司名为空，拒绝发送"})
            print(i, repr(company), "FAIL 公司名为空，跳过", flush=True)
            continue

        gid, gtext = pick_greeting(rec)

        ok, header = open_conv_for(company, rec_title, job_id=jid)
        if not ok:
            reason = str(header or "")
            if reason.startswith("ambiguous") or reason.startswith("no_title_match"):
                # 同公司多岗位且名字只差前缀：既不能发（可能发错人），
                # 也不能记 SKIP（会让积压看起来"处理过了"）。停批等 --job。
                return abort_batch(log, "TARGET_AMBIGUOUS",
                                   "%s：%s / %s，改用 --job 精确寻址" % (reason, company, rec_title))
            if reason.startswith("data_not_found"):
                # 数据源里连公司都没有 = 会话已归档/被删，是真 NOT_FOUND
                log.append({"n": i, "company": company, "status": "SKIP",
                            "why": "NOT_FOUND:" + reason})
                log_greeting({"event": "skip", "company": company, "jobId": jid or None,
                              "title": rec_title, "bucket": gid, "status": "SKIP",
                              "why": "NOT_FOUND:" + reason})
                print(i, company, "SKIP NOT_FOUND", reason, flush=True)
                continue
            if reason.lower() != "notfound":
                # list_not_ready / 空结果 / EXC 都不是公司级 NOT_FOUND。
                # 再读一次页面是为了区分浏览器死、登录失效和持续列表未就绪；
                # 即使这次列表恢复，本次定位异常仍明确停批，绝不整批假 SKIP。
                code, why = batch_preflight(timeout=3, probe=reason)
                if code == "OK":
                    code = "LIST_NOT_READY"
                    why = "open_conv_for 返回 %r，不能按 NOT_FOUND 跳过" % reason
                return abort_batch(log, code, why)
            log.append({"n": i, "company": company, "status": "SKIP", "why": "NOT_FOUND"})
            log_greeting({"event": "skip", "company": company, "jobId": jid or None,
                          "title": rec_title, "bucket": gid, "status": "SKIP",
                          "why": "NOT_FOUND"})
            print(i, company, "SKIP NOT_FOUND", flush=True)
            continue
        hstate, hdetail = classify_header_state(company, header, title=rec_title)
        if hstate == "TITLE_MISMATCH":
            log.append({"n": i, "company": company, "status": "SKIP", "why": "标题不符:" + hdetail})
            log_greeting({"event": "skip", "company": company, "jobId": jid or None,
                          "title": rec_title, "bucket": gid, "status": "SKIP",
                          "why": "标题不符:" + str(hdetail)[:60]})
            print(i, company, "SKIP 标题不符:", hdetail, flush=True)
            continue
        if hstate != "OK":
            # ok=True 但标题为空/EXC：先分清楚是浏览器死、登录失效还是页面没渲染，
            # 然后停批。绝不把它降级成公司级 SKIP。
            code, why = batch_preflight(timeout=3, probe=str(header or ""))
            hstate, hdetail = classify_header_state(company, header, code, why, title=rec_title)
            return abort_batch(log, hstate, hdetail)
        header = hdetail

        last = S.ev(LAST_JS) or ""
        cls = last.split("|")[0] if "|" in last else ""
        my_imgs = int(S.ev(MY_IMG_JS) or 0)
        my_text = (S.ev(MY_TEXT_JS) or "").replace(" ", "")
        already_img = my_imgs > 0
        # 判据抽到函数里：空串恒真、与默认招呼语撞车这两类错都出在这个表达式上，
        # 现在它有了独立名字，验收脚本可以直接对着真实配置跑它。
        already_msg = text_already_sent(my_text, prefixes)

        if already_img and already_msg:
            log.append({"n": i, "company": company, "status": "SKIP", "why": "图+话术都已发过"})
            # 记成 send 而不是 skip：这不是"跳过"，是"从会话里确认过图与字都在"。
            # 记 skip 的话 greeting_index 会把它滤掉，对账就会把这条永远当成没发过。
            log_greeting({"event": "send", "company": company, "jobId": jid or None,
                          "title": rec_title, "direction": rec.get("direction") or "",
                          "bucket": gid, "text": gtext, "img_ok": True, "msg_ok": True,
                          "status": "OK", "why": "already_complete"})
            print(i, company, "SKIP 已发全", flush=True)
            continue

        img_res, msg_res = 'SKIP', 'OFF'
        img_ok = already_img
        if not already_img:
            img_path, img_mode = choose_image(rec)
            log_img_mode(rec, img_mode, img_path)
            if img_mode != 'generic:static':
                print(i, company, "IMG_MODE", img_mode, flush=True)
            if not stage_blob(img_path):
                log.append({"n": i, "company": company, "status": "FAIL", "why": "取图失败"})
                log_greeting({"event": "send", "company": company, "jobId": jid or None,
                              "title": rec_title, "direction": rec.get("direction") or "",
                              "bucket": gid, "text": gtext, "img_ok": False, "msg_ok": False,
                              "img_res": "STAGE_FAIL", "msg_res": "OFF", "status": "FAIL"})
                print(i, company, "FAIL stage", flush=True)
                continue
            ensure_foreground()          # 后台标签里上传会静默失败
            imgs0 = int(S.ev(MY_IMG_JS) or 0)
            cnt0 = int(S.ev(MSG_COUNT_JS) or 0)
            r = S.inject()
            time.sleep(4.0)
            imgs1 = int(S.ev(MY_IMG_JS) or 0)
            cnt1 = int(S.ev(MSG_COUNT_JS) or 0)
            if imgs1 <= imgs0:
                # 后台标签/被遮挡窗口下，注入成功后计数仍可能读到 0（2026-11-03 实测：
                # 实测某单图已经落地、列表预览都显示 [图片]，脚本却报 img 0->0 NOT_SENT）。
                # 重新打开会话再数一次，别直接把成功记成失败。
                time.sleep(2.5)
                try:
                    open_conv_for(company, rec_title, job_id=jid)
                    time.sleep(1.5)
                except Exception:
                    pass
                imgs1 = int(S.ev(MY_IMG_JS) or 0)
                cnt1 = int(S.ev(MSG_COUNT_JS) or 0)
            # 判据用「我方图片数变多」而不是「最后一条是 item-myself」：
            # 图片落地后 BOSS 可能紧接着推一条 item-system（如平台规范提示），
            # 那时最后一条不再是我方消息，按「最后一条」判会把成功记成失败。
            ok_inject = str(r).startswith("OK")
            grew = imgs1 > imgs0
            img_ok = bool(ok_inject and grew)
            img_res = "%s | img %d->%d, msg %d->%d %s" % (
                r, imgs0, imgs1, cnt0, cnt1, "OK" if img_ok else "NOT_SENT")
            print(i, company, "IMG", img_res, flush=True)
            if not img_ok:
                log.append({"n": i, "company": company, "status": "FAIL",
                            "why": "图未入库:%s img %d->%d" % (r, imgs0, imgs1)})
                log_greeting({"event": "send", "company": company, "jobId": jid or None,
                              "title": rec_title, "direction": rec.get("direction") or "",
                              "bucket": gid, "text": gtext, "img_ok": False, "msg_ok": False,
                              "img_res": img_res, "msg_res": "OFF", "status": "FAIL"})
                continue
        else:
            print(i, company, "IMG 会话里已有我发的图，跳过", flush=True)

        if want_msg and not already_msg:
            ensure_foreground()
            msg_res = send_text(gtext)
            print(i, company, "MSG[" + gid + "]", msg_res, flush=True)
            time.sleep(1.0)
        elif already_msg:
            msg_res = 'SKIP_ALREADY'

        # 三态：以前不管 msg 成败一律记 OK，于是"只有图没有字"在日志里看不出来，
        # 也就没人会去补那句话。
        msg_ok = msg_res in ('SENT', 'SKIP_ALREADY')
        status = "OK" if (img_ok and msg_ok) else ("PARTIAL" if (img_ok or msg_ok) else "FAIL")
        log.append({"n": i, "company": company, "status": status,
                    "img": img_res, "msg": msg_res, "bucket": gid})
        log_greeting({"event": "send", "company": company, "jobId": jid or None,
                      "title": rec_title, "direction": rec.get("direction") or "",
                      "bucket": gid, "text": gtext, "img_ok": bool(img_ok),
                      "msg_ok": bool(msg_ok), "img_res": img_res, "msg_res": msg_res,
                      "status": status})
        time.sleep(0.8)

    json.dump(log, open(LOG, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    ok_n = sum(1 for x in log if x["status"] == "OK")
    part_n = sum(1 for x in log if x["status"] == "PARTIAL")
    # PARTIAL 要单独报：以前"图成功就记 OK"，于是有图没字的那些在收尾时看起来全绿
    print("DONE %d / %d   PARTIAL %d（有图无字或有字无图，用 daily_close.py 看缺口）"
          % (ok_n, len(log), part_n), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
