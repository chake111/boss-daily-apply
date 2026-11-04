# -*- coding: utf-8 -*-
"""发简历图 + 按方向附一句（greetings.json）。支持第二个标签专门做补发，不打断搜索页。

用法：
    python send_img2.py 5 --msg                 # 给最近 5 家：发图 + 一句话
    python send_img2.py 5 --msg --dry           # 只打印「谁配哪句」，不动浏览器
    python send_img2.py 1 "深投数科" --msg       # 只补某一家（短名匹配）
    python send_img2.py 5 --msg --same-tab      # 不用第二个标签（会抢占当前标签）
    python send_img2.py 1 "某某实业" --msg --img resume/out/简历-fe-vue-某某实业-20261103.png
                                                # 送按 JD 定制的那张图（默认仍是通用图）

为什么用第二个标签：
    投递主流程的红线是「不打开聊天页」。但又要求每 5 份补一次图，两者冲突。
    WebBridge 支持多 session 各绑一个 tab，所以让 boss-img 独占一个聊天标签，
    boss-main 的搜索页全程不动、游标不丢。

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
CHAT_URL = "https://www.zhipin.com/web/geek/chat"
TAB2 = "boss-img"
TAB2_ID = None


def ensure_foreground():
    """把正在用的标签切到前台。

    踩过的坑：第二个标签在后台时，图片上传的 change 事件会被忽略——注入返回 'OK'、
    会话条数却不变，而按「图片张数」判定的旧 verify 会把历史图片数成成功（假阳性）。
    """
    global TAB2_ID
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


def choose_image(company, records):
    """返回 (图片路径, 模式标签)。模式标签会落盘，供 A/B 统计分组。

    分桶按 jobId 的 md5 奇偶，和岗位属性无关——等价于随机分组，
    但不用维护「谁在哪组」的状态文件。
    """
    if IMG_OVERRIDE:
        return IMG_OVERRIDE, "manual"
    if not AUTO_IMG:
        return IMG, "generic:static"

    rec = find_record(company, records) or {}
    if not rec.get("jobId"):
        # 没匹配到投递记录就别分桶——A/B 只对有台账的投递成立
        return IMG, "unknown"
    # 按公司名分桶（不是 jobId）：img_mode_log 以公司为键，同一个会话只会发一次图，
    # 按公司分桶才能保证「同一家永远在同一组」，重发时不会跨组。
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


def log_img_mode(company, mode, path):
    log = {}
    if os.path.exists(IMG_MODE_LOG):
        try:
            log = json.load(open(IMG_MODE_LOG, encoding="utf-8"))
        except Exception:
            log = {}
    log[company] = {"mode": mode, "img": path, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    json.dump(log, open(IMG_MODE_LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def load_records(limit=150):
    try:
        rows = json.load(open(PROGRESS, encoding='utf-8')).get('delivered', [])[-limit:]
    except Exception:
        return {}
    return {r.get('company', ''): r for r in rows}


def find_record(company, records):
    """短名也要能对上（写 "深投" 时不该退回默认文案）。"""
    if company in records:
        return records[company]
    for k, v in records.items():
        if k and (company in k or k in company):
            return v
    return {}


def pick_greeting(company, records):
    """加权打分选桶。

    以前是「先命中先用」，导致「AI应用开发（后端/数据方向）」被 java 桶抢先命中
    （因为 java 的 match 里有泛化的"后端"）。现在改成按词权重累加：
    具体技术词（Java/Python/AI/Agent/大模型/前端）权重高，泛化词（后端/数据/应用开发）权重低，
    分数最高且 >0 的桶胜出，全 0 才走 default。
    """
    cfg = json.load(open(GREET, encoding='utf-8'))
    rec = find_record(company, records)

    # ① direction 是投递时人工标的，直接映射最准
    dmap = cfg.get('direction_map') or {}
    want = dmap.get(rec.get('direction') or '')
    if want:
        b = next((x for x in cfg['buckets'] if x['id'] == want), None)
        if b:
            return b['id'], b['text']

    # ② 没标方向的才退回加权打分。keyword 刻意不参与——
    #    那是搜索词不是岗位属性，会把「AI Agent实习」这类词带进不相干的岗位
    blob = " ".join([rec.get('title') or '', company or '']).lower()

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
        best = next((b for b in cfg['buckets'] if b['id'] == cfg.get('default')), cfg['buckets'][0])
    return best['id'], best['text']


def greeting_prefixes():
    cfg = json.load(open(GREET, encoding='utf-8'))
    return [b['text'][:6] for b in cfg['buckets']]


def send_text(msg):
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


def open_conv_for(company, title=""):
    """按「公司 + 岗位名片段」定位会话。

    坑：一家公司可能有两个岗位、两个 HR、两个会话（比如同一家的「数据开发」和「前端」）。
    只按公司名匹配会永远命中第一个，导致第二个岗位被误判成"已发全"而漏发。
    """
    title = (title or "").strip()
    if len(title) < 4:
        return S.open_conv(company)
    frag = title[:4]
    r = S.ev("""(function(){var ls=document.querySelectorAll('.user-list [role=listitem]');
for(var i=0;i<ls.length;i++){var t=ls[i].innerText||'';
 if(t.indexOf(%s)>=0 && t.indexOf(%s)>=0){var c=ls[i].querySelector('.friend-content')||ls[i];
 c.setAttribute('data-rb3','1');return 'found:'+i;}}
return 'notfound'})()""" % (json.dumps(company, ensure_ascii=False), json.dumps(frag, ensure_ascii=False)))
    if not r.startswith("found"):
        return S.open_conv(company)          # 退化为按公司名
    S.click('[data-rb3="1"]')
    time.sleep(2.2)
    header = S.ev("(function(){var c=document.querySelector('.chat-conversation');"
                  "return c?c.innerText.slice(0,60).replace(/\\n/g,' / '):''})()")
    return True, header


def main():
    args = list(sys.argv[1:])
    dry = '--dry' in args
    want_msg = '--msg' in args
    same_tab = '--same-tab' in args
    img_override = ''
    if '--img' in args:
        k = args.index('--img')
        img_override = args[k + 1] if len(args) > k + 1 else ''
        del args[k:k + 2]
    auto_img = '--auto-img' in args
    args = [a for a in args if a not in ('--dry', '--msg', '--same-tab', '--auto-img')]
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

    records = load_records()
    targets = [only] if only else S.load_targets(limit)
    if not targets:
        print("没有投递记录可补发：先跑投递流程，或检查 BOSS_WORKDIR 是否指对了", flush=True)
        return

    if dry:
        for i, company in enumerate(targets, 1):
            gid, gtext = pick_greeting(company, records)
            print("%2d. %-22s -> [%s] %s" % (i, company[:22], gid, gtext[:44]), flush=True)
        return

    global SESSION_NAME, TAB2_ID
    W.require_bridge()            # 真正要动浏览器了，桥不可达就别往下走
    if not same_tab:
        SESSION_NAME = TAB2
        r0 = W.api('navigate', {'url': CHAT_URL}, session=TAB2)  # 确保第二个标签存在
        TAB2_ID = (r0.get('data') or {}).get('tabId') or TAB2_ID
        bind_tab(TAB2)
    else:
        SESSION_NAME = W.SESSION
        cur = S.ev("location.href") or ""
        if "/web/geek/chat" not in cur:
            S.navigate(CHAT_URL, wait_range=(5, 7))
    time.sleep(2.0)

    prefixes = greeting_prefixes()
    log = []
    for i, company in enumerate(targets, 1):
        # 空公司名是致命输入：open_conv 用 indexOf 匹配，空串恒命中列表第一条，
        # 会把「图 + 简历已附上」发给一个完全无关的 HR，且撤不回。
        if not company or len(company.strip()) < 2:
            log.append({"n": i, "company": company, "status": "FAIL", "why": "公司名为空，拒绝发送"})
            print(i, repr(company), "FAIL 公司名为空，跳过", flush=True)
            continue

        gid, gtext = pick_greeting(company, records)

        rec_title = (find_record(company, records) or {}).get('title', '')
        ok, header = open_conv_for(company, rec_title)
        if not ok:
            log.append({"n": i, "company": company, "status": "SKIP", "why": header})
            print(i, company, "SKIP", header, flush=True)
            continue
        if company.replace("有限公司", "") not in header:
            log.append({"n": i, "company": company, "status": "SKIP", "why": "标题不符:" + header})
            print(i, company, "SKIP 标题不符:", header, flush=True)
            continue

        last = S.ev(LAST_JS) or ""
        cls = last.split("|")[0] if "|" in last else ""
        my_imgs = int(S.ev(MY_IMG_JS) or 0)
        my_text = (S.ev(MY_TEXT_JS) or "").replace(" ", "")
        already_img = my_imgs > 0
        already_msg = any(p.replace(" ", "") in my_text for p in prefixes)

        if already_img and already_msg:
            log.append({"n": i, "company": company, "status": "SKIP", "why": "图+话术都已发过"})
            print(i, company, "SKIP 已发全", flush=True)
            continue

        img_res, msg_res = 'SKIP', 'OFF'
        if not already_img:
            img_path, img_mode = choose_image(company, records)
            log_img_mode(company, img_mode, img_path)
            if img_mode != 'generic:static':
                print(i, company, "IMG_MODE", img_mode, flush=True)
            if not stage_blob(img_path):
                log.append({"n": i, "company": company, "status": "FAIL", "why": "取图失败"})
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
                    open_conv_for(company, rec_title)
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
            img_res = "%s | img %d->%d, msg %d->%d %s" % (
                r, imgs0, imgs1, cnt0, cnt1, "OK" if (ok_inject and grew) else "NOT_SENT")
            print(i, company, "IMG", img_res, flush=True)
            if not (ok_inject and grew):
                log.append({"n": i, "company": company, "status": "FAIL",
                            "why": "图未入库:%s img %d->%d" % (r, imgs0, imgs1)})
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

        log.append({"n": i, "company": company, "status": "OK",
                    "img": img_res, "msg": msg_res, "bucket": gid})
        time.sleep(0.8)

    json.dump(log, open(LOG, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print("DONE", sum(1 for x in log if x["status"] == "OK"), "/", len(log), flush=True)


if __name__ == '__main__':
    main()
