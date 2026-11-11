#!/usr/bin/env python3
"""BOSS 直聘投递 · 投递原语库 + 收尾（实时单卡投递由 _live_driver.py 驱动）

架构：
  - _live_driver.py 负责「智能体交互层」：walk / open / deliver / reject 单卡游标，
    把每步动作交给浏览器，方向判断（该不该投）由 AI 语义完成，脚本只做两道
    机械硬门槛（城市 + 薪资下限），绝不硬编码岗位类型/行业关键词。
  - 本文件 phase_stream.py 提供「投递共享原语 + 收尾」：
      ① 浏览器操作原语：滚动懒加载、读 JD、弹窗识别/关闭、面板校验、
         推荐页内原地投递 deliver_click、每步 DOM 回读校验；
      ② 收尾：write_summary_page（--mode report，投递成果汇报 + 打赏码二合一 HTML）；
      ③ 独立诊断：run_verify（--mode verify，交叉核对真实沟通列表，读后自动回推荐页）；
      ④ 诊断模式：--diag（只读 dump 浮层 + 弹窗分类 + 日上限检测，不投递）。

设计铁律（与筛选无关，平台级）：
  - 每次投递都回读页面确认「送达」才继续；遇未知弹窗 / 误触 / 日上限 立即整批停手。
  - 弹窗只点白名单关闭键（留在此页/继续沟通/取消/关闭/稍后），绝不点发送/上传类按钮。
  - 连续投递失败熔断（FAIL_BREAKER）：连续 ≥3 次失败/超时即停手。
  - 投递全程停在推荐页/搜索页，绝不把会话停在 /chat。

用法（仅收尾/诊断，投递主流程在 _live_driver.py）：
    python scripts/phase_stream.py --workdir <目录> --mode report
    python scripts/phase_stream.py --workdir <目录> --mode verify
    python scripts/phase_stream.py --workdir <目录> --diag
"""
import sys, os, time, json

_HERE = os.path.dirname(os.path.abspath(__file__))
# 兼容 Git Bash 的 /c/... UNIX 风格路径：Windows Python 会把 /c 误算成 C:\c
if len(_HERE) >= 3 and _HERE[0] == "/" and _HERE[1].isalpha() and _HERE[2] == "/":
    _HERE = _HERE[1].upper() + ":" + _HERE[2:]
SKILL_DIR = os.path.dirname(_HERE)
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)

from scripts.webbridge_client import (
    SESSION, api, evaluate, extract_jobs, detect_page_anomaly,
    ProgressManager, parse_salary_max, wait_for_feedback, AbortScriptError,
    navigate, snapshot_page, click, click_verified, click_card, js_click,
)
# 页面定位统一走 locators：改版时只补一条策略，这里不用动。
from scripts import locators as _loc
_DETAIL_REF = _loc._DETAIL_REF
from scripts.config import load_profile
from scripts.env_check import check_env

RECOMMEND_URL = "https://www.zhipin.com/web/geek/jobs?ka=header-jobs"
# 仅用于 _ensure_recommend 判定当前是否已在 BOSS 工作页（推荐页/搜索页同路径，仅 query 不同）
WORKING_URL = RECOMMEND_URL


def search_url_for(query, city_code):
    from urllib.parse import quote
    if not query:
        # 无关键词 → 返回 BOSS 推荐页（用户个性化 feed，命中率最高，walk 默认起点）
        return RECOMMEND_URL
    return f"https://www.zhipin.com/web/geek/jobs?query={quote(query)}&city={city_code}"


def scroll_jobs_list(session=SESSION, times=1):
    """滚动左侧岗位列表到底部，触发 BOSS 懒加载更多卡片。

    适配推荐页与关键词搜索页：每次把 .job-list（或其最近可滚祖先 / 页面）滚到底，
    等待 BOSS 渲染下一批。懒加载的真正「到底」由 _live_driver 的 _exhaust_recommend_feed
    （滚动→等 3s→连续 4 次稳定才停）判定，本函数只负责单次触发。
    """
    for _ in range(max(1, times)):
        evaluate(r"""(function(){
            var list = document.querySelector('#main .job-list') || document.querySelector('.job-list');
            if (list && list.scrollHeight > list.clientHeight + 4) {
                list.scrollTop = list.scrollHeight;
            } else {
                var p = list;
                while (p && p !== document.body) {
                    if (p.scrollHeight > p.clientHeight + 4 && p.clientHeight > 0) {
                        p.scrollTop = p.scrollHeight; return;
                    }
                    p = p.parentElement;
                }
                window.scrollTo(0, document.body.scrollHeight);
            }
        })()""")
        time.sleep(1.2)


# ───────────────────────────────────────────────────────────
# 读取 JD（点击卡片 → 右侧面板切换 → 抽取 JD 文本）
# ───────────────────────────────────────────────────────────
JD_JS = r"""
(function(){
    function grab(sel){ var el=document.querySelector(sel); return el? el.innerText.trim(): null; }
    // 优先用已确认过的面板引用（locators 挂的），避免这里再写一套选择器：
    // 两处选择器一旦不同步，就会出现「校验用的是新容器、读 JD 用的是旧容器」
    var detail = null;
    if (window.__bossDetail && window.__bossDetail.isConnected) {
        detail = (window.__bossDetail.innerText || '').trim() || null;
    }
    if (!detail) {
        detail = grab('.job-detail-box') || grab('#main .job-detail') || grab('.job-detail')
                 || grab('.detail-content') || grab('div.detail-content');
    }
    if (detail) return '=== JD面板 ===\n' + detail;
    var main = document.querySelector('#main');
    if (main){ var list = main.querySelector('.job-list'); if (list) list.remove();
        return '=== #main(已去左列表) ===\n' + main.innerText.trim(); }
    return '=== body兜底 ===\n' + (document.body.innerText||'').trim();
})()
"""

def read_jd(job, session=SESSION):
    ptype = read_popup_type(session)
    if ptype in ("not_interested", "unknown"):
        raise AbortScriptError(f"读JD前检测到危险弹窗({ptype})，停止待人工介入")
    if ptype:
        safe_close_popup(session)
    jid = job.get("jobId")
    sel = f'a[href*="job_detail/{jid}"]'
    r = click(sel)
    time.sleep(3)
    return evaluate(JD_JS) or ""


# ═══════════════════════════════════════════════════════════
# 通用可见浮层扫描（取代固定选择器白名单）
# ═══════════════════════════════════════════════════════════
OVERLAY_SCAN_JS = r"""
function _ovVis(el){ if(!el) return false; var s; try{s=getComputedStyle(el);}catch(e){return true;}
    if(s.display==='none'||s.visibility==='hidden'||+s.opacity===0) return false;
    if(el.offsetParent===null && el.tagName!=='BODY' && el.tagName!=='HTML'){
        var p=s.position; if(p!=='fixed'&&p!=='absolute') return false; }
    return true; }
function _ovIs(el){ var s; try{s=getComputedStyle(el);}catch(e){s={};}
    if(el.getAttribute('role')==='dialog'||el.getAttribute('role')==='alertdialog') return true;
    var cls=(''+(el.className||'')).toLowerCase();
    if(/mask|modal|dialog|popup|overlay|drawer|toast|layer|chat-block|greet|confirm/.test(cls)) return true;
    if(s.position==='fixed'||s.position==='absolute'){
        var t=(el.innerText||'').replace(/\s+/g,' ').trim();
        if(/不感兴趣|上传附件|已向BOSS|上限|沟通次数|确定|取消|发送|继续沟通|留在此页/.test(t)) return true; }
    return false; }
function _ovScan(){ var out=[]; var all=document.querySelectorAll('*');
    for(var i=0;i<all.length;i++){ var el=all[i]; if(!_ovVis(el)) continue; if(!_ovIs(el)) continue;
        var t=(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim(); if(!t||t.length<2) continue;
        var s; try{s=getComputedStyle(el);}catch(e){s={position:'',zIndex:'0'};}
        out.push({tag:el.tagName, cls:(''+(el.className||'')).slice(0,60), pos:s.position, z:(parseInt(s.zIndex,10)||0), text:t.slice(0,200)}); }
    out.sort(function(a,b){ return (b.z-a.z)||(b.text.length-a.text.length); });
    return out.slice(0,10); }
"""

POPUP_STATE_JS = OVERLAY_SCAN_JS + r"""
(function(){
    __BOSS_DETAIL_REF__
    var out={};
    var gb = document.querySelector('.greet-boss-container')||document.querySelector('.greet-boss-dialog');
    out.greet_open = !!(gb && _ovVis(gb));
    out.greet_text = (gb && _ovVis(gb)) ? (gb.innerText||'').replace(/\s+/g,' ').trim().slice(0,200) : '';
    var overlays = _ovScan();
    if(overlays.length){ var top=overlays[0]; out.popup=true; out.popup_text=top.text; out.popup_cls=top.cls;
        var btns=[]; var b=document.querySelectorAll('button,a,span,[role=button]');
        for(var j=0;j<b.length;j++){var bt=(b[j].textContent||'').trim(); if(bt) btns.push(bt);}
        out.popup_buttons=btns;
    } else { out.popup=false; out.popup_text=''; }
    var bodyTxt=(document.body.innerText||'').replace(/\s+/g,' ');
    var limitKw=['您已达到沟通上限','您今天已与','沟通上限','已与150位','休息一下，明天再来',
                 '达到上限','已达上限','今日沟通次数','沟通次数已','今日已向'];
    out.body_has_limit=false; out.limit_phrase='';
    for(var k=0;k<limitKw.length;k++){ if(bodyTxt.indexOf(limitKw[k])>=0){ out.body_has_limit=true; out.limit_phrase=limitKw[k]; break; } }
    var box=window.__bossDetail||null;
    var els=box?box.querySelectorAll('button,a'):[];
    for(var i=0;i<els.length;i++){var t=(els[i].textContent||'').trim();
        if(t.indexOf('沟通')>=0||t.indexOf('送达')>=0){out.btn=t;break;}}
    out.overlays=overlays;
    return JSON.stringify(out);
})()
""".replace("__BOSS_DETAIL_REF__", _DETAIL_REF)

VISIBLE_OVERLAYS_JS = OVERLAY_SCAN_JS + r"""
(function(){
    var ov=_ovScan();
    var bodyTxt=(document.body.innerText||'').replace(/\s+/g,' ');
    var limitKw=['您已达到沟通上限','您今天已与','沟通上限','已与150位','休息一下，明天再来',
                 '达到上限','已达上限','今日沟通次数','沟通次数已','今日已向'];
    var hit=null; for(var k=0;k<limitKw.length;k++){ if(bodyTxt.indexOf(limitKw[k])>=0){ hit=limitKw[k]; break; } }
    return JSON.stringify({overlay_count:ov.length, overlays:ov, body_has_limit:!!hit, limit_phrase:hit||''}, null, 1);
})()
"""

POPUP_ALLOW_CLOSE = ["留在此页", "继续沟通", "取消", "关闭", "我知道了", "稍后", "暂不", "X"]


def read_popup_type(session=SESSION):
    """只读识别当前弹窗类型，不点任何按钮。"""
    try:
        info = json.loads(evaluate(POPUP_STATE_JS) or "{}")
    except Exception:
        return ""
    # ① 日上限弹窗【必须最先判】：其按钮含"确定"，若晚于下方 tip 分支会被误判为普通提示，
    #    导致循环不停（实测：150 上限弹窗被误判 tip → 反复点"确定"未停手）。
    #    即使浮层扫描未把它列为 popup/greet，只要正文含上限文案也要拦下。
    if info.get("body_has_limit"):
        return "daily_limit"
    if not info.get("popup") and not info.get("greet_open"):
        return ""
    txt = (info.get("popup_text") or "") + " || " + (info.get("greet_text") or "")
    _LIMIT_KW = ["已达上限", "达到上限", "今日上限", "投递上限", "已达150", "已达 150",
                 "今日已投递", "次数已达", "今日投递", "沟通上限", "已与150位",
                 "您已达到沟通上限", "休息一下，明天再来", "您今天已与"]
    for kw in _LIMIT_KW:
        if kw in txt:
            return "daily_limit"
    if "选择原因" in txt or "减少不合适职位推荐" in txt or "不感兴趣" in txt:
        return "not_interested"
    if "上传附件简历" in txt or "在线填写" in txt or "拖拽文件" in txt:
        return "resume_guide"
    if "已向BOSS发送消息" in txt or "已发送" in txt or "[送达]" in txt or "已送达" in txt \
            or "留在此页" in txt or "继续沟通" in txt:
        return "greet_sent"
    if "好" in txt or "确定" in txt or "我知道了" in txt or "继续加油" in txt:
        # 非致命提示弹窗（如第120份鼓励/提示弹窗），交由 safe_close_popup 点掉继续
        return "tip"
    return "unknown"


def click_popup_button(button_text, session=SESSION, expect_gone=True):
    """点击弹窗内文字匹配的按钮，并确认弹窗真的关掉了。

    匹配严格化（修复点错/点空隐患）：
      - 仅限 button / a 元素——弹窗按钮都是真按钮或链接；外层 div/span 的 textContent
        也包含按钮文字，若命中容器会点到"空壳"导致按钮没真正触发。
      - 优先【精确匹配】可见文字；无精确匹配才退回【包含匹配】，且只对叶子节点
        (children.length===0) 匹配，坚决避免命中包裹容器。

    为什么会校验「关掉了」（2026-11-06 交叉验证）：
      这里原来只有真实鼠标点击 + `sleep 1.5`。标签页在后台时鼠标事件会被丢弃，
      点不动却返回 success，弹窗留在原地；下一张卡的卡片点击被遮罩挡住 →
      panel_ok:false → 连锁失败，而第一张在日志里记的是「投递成功」。
      把确认标准从「点了」改成「弹窗消失了」，这类连锁才有机会被发现。
    """
    tag = evaluate(r"""(function(){
        var target=%s;
        var all=document.querySelectorAll('button,a');
        for(var i=0;i<all.length;i++){ var t=(all[i].textContent||'').trim();
            if(t===target){ all[i].id='__popbtn__'; return 'tagged'; } }
        for(var i=0;i<all.length;i++){ var el=all[i];
            if(el.children.length>0) continue;
            var t=(el.textContent||'').trim();
            if(t.indexOf(target)>=0){ el.id='__popbtn__'; return 'tagged'; } }
        return 'NO_BTN';
    })()""" % json.dumps(button_text))
    if tag != 'tagged':
        return 'NO_BTN:' + button_text

    # 鼠标点不动就换 JS 点：弹窗按钮和卡片一样，后台标签页下只有 DOM 点击可靠
    ok, _method = click_verified(
        '#__popbtn__',
        expect_js="" if not expect_gone else
        "(function(){return !document.getElementById('__popbtn__')"
        "||document.getElementById('__popbtn__').offsetParent===null;})()",
        timeout=4.0, session=session)
    evaluate(r"(function(){var e=document.getElementById('__popbtn__'); if(e) e.removeAttribute('id');})()")
    time.sleep(1.0)
    if not ok:
        return 'CLICK_FAIL'
    return 'CLICKED:' + button_text


def safe_close_popup(session=SESSION):
    ptype = read_popup_type(session)
    if ptype == "resume_guide":
        r = _click_text("没有附件简历", session)
        if not r.startswith("CLICKED"):
            click_popup_button("X", session)
        return ptype
    if ptype == "greet_sent":
        click_popup_button("留在此页", session)
        return ptype
    if ptype == "not_interested":
        r = click_popup_button("X", session)
        if not r.startswith("CLICKED"):
            click_popup_button("取消", session)
        return ptype
    if ptype == "tip":
        # 第120份等非致命提示弹窗：点掉继续，不计入成功/失败
        for bt in ("我知道了", "知道了", "好", "确定"):
            r = click_popup_button(bt, session)
            if r and r.startswith("CLICKED"):
                break
        return ptype
    if ptype == "daily_limit":
        return ptype
    return ptype


def _click_text(text_sub, session=SESSION):
    """原生点击文字精确匹配的元素（WebBridge 真实鼠标点击）。"""
    tag = evaluate(r"""(function(){
        var t=%s;
        var all=document.querySelectorAll('a,span,div,button,em,i,label,p,[role=button]');
        for(var i=0;i<all.length;i++){ var el=all[i];
            if(el.children.length===0 && (el.textContent||'').trim()===t){ el.id='__txtbtn__'; return 'tagged'; } }
        return 'NO';
    })()""" % json.dumps(text_sub))
    if tag != 'tagged':
        return 'NO:'+text_sub
    ok = click('#__txtbtn__')
    evaluate(r"(function(){var e=document.getElementById('__txtbtn__'); if(e) e.removeAttribute('id');})()")
    time.sleep(1.2)
    return ('CLICKED:'+text_sub) if ok else 'CLICK_FAIL'


def auto_handle_popups(session, max_rounds=6):
    last_type = ""
    for _ in range(max_rounds):
        ptype = read_popup_type(session)
        last_type = ptype
        if ptype == "":
            return json.loads(evaluate(POPUP_STATE_JS) or "{}"), "clean", ""
        if ptype == "daily_limit":
            return json.loads(evaluate(POPUP_STATE_JS) or "{}"), "limit", "daily_limit"
        if ptype in ("not_interested", "unknown"):
            return json.loads(evaluate(POPUP_STATE_JS) or "{}"), "danger", ptype
        safe_close_popup(session)
        time.sleep(0.8)
    return json.loads(evaluate(POPUP_STATE_JS) or "{}"), "forced", last_type


def CLICK_CHAT_JS():
    """点详情面板内的「立即沟通」。定位与禁用态判断都交给 locators。

    返回 'CLICKED:panel' / 'CLICKED:global' / 'DISABLED' / 'NO_BTN'。
    DISABLED 是真实状态（岗位已停止接收沟通），调用方据此跳过而不是空等超时。
    """
    from scripts import locators
    return locators.click_chat_js()


def VERIFY_DELIVERED_JS():
    """投递后回读面板按钮与送达标记。"""
    from scripts import locators
    return locators.delivered_state_js()


def _feedback(label, session=SESSION):
    """每步操作后回读 DOM，打印当前落点/按钮/弹窗类型（反馈机制，杜绝'以为'与'实际'脱节）。"""
    url, body, blen = snapshot_page(session=session)
    btn = ""
    ptype = ""
    try:
        d = json.loads(evaluate(POPUP_STATE_JS) or "{}")
        btn = d.get("btn", "")
        ptype = read_popup_type(session)
    except Exception:
        pass
    on_chat = "/chat" in url
    print(f"[feedback] {label} | URL={url[:72]} | btn={btn!r} | popup={ptype} | chat={on_chat}")
    return url, btn, ptype, on_chat


def _ensure_recommend(session=SESSION):
    """确保在工作页（推荐页 或 行业搜索页）；若不在则导航过去一次（投递循环内仅首次会真正导航，之后全程停留）。
    工作页 URL 路径均为 /web/geek/jobs（推荐页与搜索页同路径，仅 query 不同），
    故以该路径判定是否已在工作页；严禁 navigate 到 job_detail 详情 URL。
    """
    url, _, _ = snapshot_page(session=session)
    if "/web/geek/jobs" not in (url or ""):
        is_search = WORKING_URL != RECOMMEND_URL
        navigate(WORKING_URL, wait_range=(3, 5), session=session,
                 expect_url_contains=("query=" if is_search else "header-jobs"),
                 label="工作页")
        time.sleep(1)
    return True


def _js_click_card(jid, session=SESSION):
    """用 JS 原生 click 点卡片容器（li.job-card-box），返回是否点到。

    BOSS 的选中逻辑绑在卡片容器上，点里面的 a.job-name 不会切换右侧详情；
    且标签页在后台时真实鼠标事件会被 Chromium 丢弃，只有 JS 点击稳定生效。
    """
    from scripts import locators
    try:
        r = str(evaluate(locators.click_card_js(jid), session) or "")
        return r.startswith("CLICKED")
    except Exception:
        return False


def _select_card_on_recommend(jid, session=SESSION, max_scroll=10):
    """在推荐页【左侧列表内原地】选中 jid 对应卡片：滚动让卡片可见 → WebBridge 原生点击其岗位链接。
    返回 True/False。全程不离开推荐页（绝不 navigate 到 job_detail URL）。
    """
    sel = f'a[href*="job_detail/{jid}"]'
    for attempt in range(max_scroll):
        # 先滚动让该卡片进入视口（原生点击前需可见）
        evaluate(r"""(function(){
            var el=document.querySelector('a[href*="job_detail/%s"]');
            if(el){ el.scrollIntoView({block:'center'}); }
            return !!el;
        })()""" % jid)
        time.sleep(0.8)
        ok = click(sel)
        if ok:
            time.sleep(2.0)
            return True
        # 没点到 → 滚动左侧岗位列表加载更多卡片后重试
        evaluate(r"""(function(){
            var el=document.querySelector('a[href*="job_detail/%s"]');
            if(el){
                var p=el.parentElement;
                while(p && p!==document.body){
                    if(p.scrollHeight > p.clientHeight+4 && p.clientHeight>0){ p.scrollTop+=800; return; }
                    p=p.parentElement;
                }
            }
            window.scrollBy(0,800);
        })()""" % jid)
        time.sleep(1.2)
    return False


def _panel_shows_job(jid, title, session=SESSION):
    """校验右侧面板当前显示的是目标岗位。

    权威依据：右侧面板『立即沟通』按钮的 ka 属性必须含目标 jid。
    ⚠️ 严禁用 `title in document.body.innerText` 兜底——左侧列表本就罗列所有岗位标题，
    该判断永远为真，会掩盖'面板没切到目标岗'的脱钩，导致向错误岗位投递却记成成功。
    """
    from scripts import locators
    ka = evaluate(locators.panel_ka_js())
    if ka and jid and jid in ka:
        return True
    return False


def _verify_delivered_on_page(session=SESSION):
    """页面停留在岗位详情页时，确认投递已生效：按钮变'继续沟通'或正文含送达。"""
    try:
        d = json.loads(evaluate(POPUP_STATE_JS) or "{}")
        btn = (d.get("btn") or "")
        body = evaluate("document.body.innerText") or ""
        if "继续沟通" in btn or "继续沟通" in body[:400] or "[送达]" in body or "已送达" in body:
            return True
    except Exception:
        pass
    return False


def card_exists(jid, session=SESSION):
    """当前 DOM 中是否存在目标岗位的卡片链接（用于判断该岗在当前页是否可定位）。"""
    sel = f'a[href*="job_detail/{jid}"]'
    r = evaluate(f'(function(){{return !!document.querySelector({json.dumps(sel)});}})()')
    return str(r).strip().lower() in ("true", "1", "yes")


def _try_locate_card(jid, title, session=SESSION, max_rounds=3):
    """在【当前已导航到的工作页】上定位并选中目标卡片（含滚动加载更多）。

    返回:
      - 'ok'     : 已点击且右侧面板确已切到目标岗（可继续点'立即沟通'）
      - 'absent' : 滚动加载后卡片仍不在 DOM（该页确实没有此岗 → 应跳过，不中止整批）
      - 'timing' : 卡片在 DOM 但面板始终未切换（SPA 时序异常 → 为安全计也按跳过处理）

    点击与校验合成一步（click_card 收 expect）：原先是「鼠标点 → 单独校验 →
    失败再 JS 兜底」三段式，任何一段脱钩都只能靠调用方自己发现，而调用方通常
    只看返回值。现在只有「面板真的切到目标岗」才算 ok。

    已知限制：面板若停在「已沟通过」的岗位，按钮文案是「继续沟通」而不是
    「立即沟通」，ka 取不到 → 判 false。这种情况会走完 max_rounds 后按 timing
    跳过——不投错人，但要白等几轮。max_rounds 从 6 降到 3 就是为了少等这一会。

    滚动改为最多 3 次：原来只滚一次就判 absent，懒加载慢的时候会把
    「还没加载完」误判成「该页没有此卡」。
    """
    from scripts import locators
    expect = locators.panel_shows_job_js(jid)
    for _r in range(max_rounds):
        if not card_exists(jid, session):
            still_absent = True
            for _s in range(3):
                scroll_jobs_list(session=session)
                time.sleep(1.3)
                if card_exists(jid, session):
                    still_absent = False
                    break
            if still_absent:
                return "absent"
            continue
        ok, _method = click_card(jid, expect_js=expect, timeout=4.0, session=session)
        if ok:
            return "ok"
        time.sleep(1.0)  # 面板未切换 → 等 SPA 渲染后重试
    return "timing" if card_exists(jid, session) else "absent"


def deliver_click(job, session=SESSION, auto=True):
    """在【推荐页内原地】完成一次投递：
      定位该 jid 的卡片 → 点击选中(右侧切JD) → 点'立即沟通' → 成功弹窗点'留在此页' → 校验仍在推荐页。

    用户手把手纠正后的铁律：
      - 全程不离开推荐页：绝不 navigate 到 job_detail URL（缺 securityId 会重定向、且会刷新列表导致错位）。
      - 选中卡片用 WebBridge 原生 click（dispatchEvent 合成事件无法触发 SPA 切换面板）。
      - 每步回读 DOM 反馈(_feedback)确认'我做的=实际发生的'，杜绝脱钩。
      - 成功弹窗【只点'留在此页'】，绝不点'继续沟通'（后者进聊天界面、返回会刷新乱序）。
    """
    jid = job.get("jobId")
    title = (job.get("title") or "").strip()
    # 0) 先清理上一封可能遗留的弹窗
    safe_close_popup(session)
    time.sleep(0.6)
    # 1) 在当前来源页（search/recommend，由 WORKING_URL 决定）定位目标卡片
    _ensure_recommend(session)
    res = _try_locate_card(jid, title, session=session)
    if res != "ok":
        if res == "timing":
            # 卡片在、但面板没切过去。原因文案要如实区分，否则排障会往错的方向走
            # （以前这里一律说「未找到」，实际是卡在时序或已沟通过的岗）。
            return {"delivered_ok": False, "timing": True, "jid": jid,
                    "reason": "卡片在 DOM 里，但右侧面板始终没切到目标岗"
                              "（SPA 时序异常，或该岗已沟通过、按钮变成「继续沟通」）"}
        # 当前来源页确实没有这张卡（BOSS 搜索结果动态变化）。
        return {"delivered_ok": False, "not_found": True, "jid": jid,
                "reason": f"卡片[{jid}]({title})在当前来源页未找到（BOSS搜索结果动态变化），交由上层决定是否回退推荐页"}
    _feedback(f"已选中卡片[{jid}]", session)
    # 2) 点'立即沟通'
    # 返回值是状态判断依据，不是装饰：岗已停招(DISABLED)时干等 15 秒超时，
    # 会被记成一次「投递失败」，连着三张就触发整批停手——把一个正常跳过
    # 升级成了误判停批。
    print(f"[stream] 点击'立即沟通'：{job.get('title')}")
    r = str(evaluate(CLICK_CHAT_JS()) or "")
    if r == "DISABLED":
        return {"delivered_ok": False, "skipped": True, "reason": "chat_disabled",
                "note": "岗位已停止接收沟通（按钮 is-disabled）"}
    if r == "NO_PANEL":
        return {"delivered_ok": False, "not_found": True, "reason": "no_detail_panel",
                "note": "找不到右侧详情面板，停手不瞎点"}
    if r == "NO_BTN":
        return {"delivered_ok": False, "not_found": True, "reason": "no_chat_button",
                "note": "面板里没有『立即沟通』按钮（可能已沟通过，显示为继续沟通）"}
    time.sleep(1.5)
    _feedback("已点立即沟通", session)
    is_anom, detail = detect_page_anomaly(allow_login_wall=False, check_blank=False)
    if is_anom:
        return {"anomaly": detail}
    if not auto:
        return json.loads(evaluate(POPUP_STATE_JS) or "{}")
    # 3) 等待弹窗 / 反馈（含错误路径检测）
    deadline = time.time() + 15
    while time.time() < deadline:
        ptype = read_popup_type(session)
        if ptype == "not_interested":
            raise AbortScriptError("误触『不感兴趣』弹窗，整批停止待人工介入")
        if ptype == "daily_limit":
            st = json.loads(evaluate(POPUP_STATE_JS) or "{}")
            st["daily_limit"] = "daily_limit"
            return st
        if ptype == "resume_guide":
            safe_close_popup(session)
            continue
        if ptype == "tip":
            # 第120份等非致命提示弹窗：点掉继续，不计入成功/失败
            safe_close_popup(session)
            time.sleep(0.8)
            continue
        if ptype == "greet_sent":
            # 成功弹窗（含'留在此页/继续沟通'）→【只点'留在此页'】留在推荐页（正确路径）
            click_popup_button("留在此页", session)
            time.sleep(1.2)
            url, btn, ptype2, on_chat = _feedback("点'留在此页'后", session)
            if on_chat:
                # 极端兜底：被带进聊天页（理论不该发生）→ 记成功并纠正回推荐页
                _ensure_recommend(session)
                return {"delivered_ok": True, "wrong_path": True}
            # 成功弹窗即等于投递成功；面板/按钮校验仅作附加确认
            ok = _verify_delivered_on_page(session) or _panel_shows_job(jid, title, session=session)
            return {"delivered_ok": True, "verify": ok}
        # 检测错误路径：页面直接进了聊天（没弹窗但 URL 变 /chat）
        url, _, _ = snapshot_page(session=session)
        if "/chat" in url:
            # 投递成功但走了'继续沟通'错误路径 → 记成功，返回推荐页纠正
            _ensure_recommend(session)
            return {"delivered_ok": True, "wrong_path": True}
        if ptype == "unknown":
            raise AbortScriptError("出现未知弹窗，整批停止待人工介入")
        time.sleep(1.0)
    # 超时：再确认一次按钮是否变'继续沟通'/送达
    ok = _verify_delivered_on_page(session)
    url, _, _ = snapshot_page(session=session)
    if "/chat" in url:
        _ensure_recommend(session)
        return {"delivered_ok": True, "wrong_path": True, "timeout": True}
    return {"delivered_ok": ok, "timeout": True}


def verify_delivered(session=SESSION):
    try:
        d = json.loads(evaluate(VERIFY_DELIVERED_JS()) or "{}")
        ok = d.get("delivered", False)
        detail = f"btn={d.get('btn','')} delivery={d.get('hasDelivery',False)}"
    except Exception:
        ok, detail = False, "verify_error"
    return ok, detail


def verify_against_account(session=SESSION, expected=None):
    """【独立诊断，非投递主流程】导航到 BOSS 真实沟通列表，读取已投递会话，作为【落地真相】
    与本地 progress 交叉核对，暴露'本地记了但真实账号没有'的脱钩问题。

    ⚠️ 铁律：本函数【绝不】出现在投递主流程里（投递全程停在推荐页、绝不打开聊天页）。
    它只应被显式触发（--mode verify）。读完后【立即导航回推荐页】，
    确保会话最终停留在推荐页，绝不把页面停在 /chat。
    """
    try:
        navigate("https://www.zhipin.com/web/geek/chat", wait_range=(3, 5),
                 session=session, expect_url_contains="chat", label="沟通列表")
    except Exception as e:
        return f"(无法打开沟通列表: {e})", (expected or [])
    time.sleep(1.5)
    body = evaluate("document.body.innerText") or ""
    missing = []
    if expected:
        for item in expected:
            # item 为 (title, company) 或纯 title 字符串
            if isinstance(item, (list, tuple)):
                title = item[0] if len(item) > 0 else ""
                company = item[1] if len(item) > 1 else ""
            else:
                title = item or ""
                company = ""
            # 聊天列表显示 HR/公司名（非岗位标题），优先按公司名匹配，其次岗位标题
            key = (company[:6] if company else "") or (title[:6] if title else "")
            if key and key not in body:
                missing.append(title or company)
    # 读完后立即回到推荐页，绝不把会话停在聊天页
    try:
        navigate(RECOMMEND_URL, wait_range=(3, 5), session=session,
                 expect_url_contains="header-jobs", label="回推荐页")
    except Exception:
        pass
    return body, missing


def run_verify(workdir, session=SESSION):
    """独立诊断模式：仅核对本地已投递记录与真实沟通列表，读后自动回到推荐页。"""
    progress_file = os.path.join(workdir, "stream_progress.json")
    pm = ProgressManager(progress_file)
    pm.load()
    delivered = pm.data.get("delivered", [])
    if not delivered:
        print("[verify] 本地无已投递记录，无需核对")
        return
    items = [(d.get("title", ""), d.get("company", "")) for d in delivered]
    _ensure_recommend(session)  # 起点确保在推荐页
    chat_body, missing = verify_against_account(session=session, expected=items)
    print(f"[verify] 本地已投递 {len(items)} 份，真实沟通列表核对：")
    if missing:
        print(f"[verify] ⚠️ 未找到（本地记了但真实列表没有）：{missing}")
    else:
        print("[verify] ✅ 全部在真实沟通列表中找到")


# ───────────────────────────────────────────────────────────
# 收尾闭环：投递成果汇报 + 打赏（二合一自包含 HTML）
# ───────────────────────────────────────────────────────────
def write_summary_page(workdir, profile=None):
    """【收尾闭环】生成「投递台账」自包含 HTML。

    读三份状态文件，各给一栏真实信息，不混成一个大数字：
      stream_progress.json  delivered 明细（含 delivered_at / direction / keyword）
      daily_log.json        每日份数，「今日」的权威口径
      greeting_log.jsonl    每条的补发结果（img_ok / msg_ok），补发状态只认这里
      pending_actions.json  HR 有回复待我动作的台账，只取未 resolved 的

    设计取向：这是一份可核对的台账，不是庆祝海报。首屏先回答「今天投了什么、
    还欠什么、谁在等我」，历史累计退到后面。老记录没有 delivered_at，一律归入
    历史，绝不并进「今日」——否则 283 条累计会被读成「今天投了 283 份」。

    若技能目录 assets/ 下放了赞赏码图片，额外渲染一块打赏区；公开仓库不带收款码。
    """
    import base64, re, datetime, html as _h

    prog = os.path.join(workdir, "stream_progress.json")
    if not os.path.exists(prog):
        return None
    try:
        with open(prog, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    delivered = data.get("delivered", []) or []

    def _read_json(path, default):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    # ── 今日口径：以 daily_log.json 的最后日期为准；明细按 delivered_at 归日 ──
    daily = _read_json(os.path.join(workdir, "daily_log.json"), {})
    today = max(daily.keys()) if isinstance(daily, dict) and daily else ""
    if not today:
        stamps = [str(j.get("delivered_at") or "")[:10] for j in delivered]
        stamps = [s for s in stamps if s]
        today = max(stamps) if stamps else ""
    today_rows = [j for j in delivered if today and str(j.get("delivered_at") or "")[:10] == today]
    today_rows.sort(key=lambda j: str(j.get("delivered_at") or ""), reverse=True)
    daily_n = 0
    if isinstance(daily, dict) and today:
        entries = daily.get(today) or []
        if isinstance(entries, list):
            for e in entries:
                try:
                    daily_n += int(e.get("n") or 0)
                except Exception:
                    pass
    today_n = len(today_rows) if today_rows else daily_n
    today_ids = {str(j.get("jobId") or "") for j in today_rows}
    hist = [j for j in delivered if str(j.get("jobId") or "") not in today_ids]
    total = len(delivered)

    # ── 补发状态：只认 greeting_log.jsonl 的 send 事件 ──
    gstat = {}
    gl = os.path.join(workdir, "greeting_log.jsonl")
    if os.path.exists(gl):
        try:
            with open(gl, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    if rec.get("event") != "send":
                        continue
                    jid = str(rec.get("jobId") or "")
                    if not jid:
                        continue
                    st = gstat.setdefault(jid, {"img": False, "msg": False})
                    st["img"] = st["img"] or bool(rec.get("img_ok"))
                    st["msg"] = st["msg"] or bool(rec.get("msg_ok"))
        except Exception:
            pass

    def send_state(j):
        """返回 (状态类, 文案)。老记录既无投递时间也无补发留痕时文案为空，
        模板据此不渲染状态——一排「—」只是噪音，对核对没有帮助。"""
        st = gstat.get(str(j.get("jobId") or ""))
        if not st:
            return ("todo", "待补") if j.get("delivered_at") else ("none", "")
        if st["img"] and st["msg"]:
            return ("ok", "图+话术已发")
        if st["img"]:
            return ("half", "仅图")
        if st["msg"]:
            return ("half", "仅话术")
        return ("todo", "待补")

    def st_html(kind, label):
        return f'<span class="st st--{kind}">{label}</span>' if label else ""

    # ── 待我动作：pending_actions 里未 resolved 的 ──
    pend = []
    pa = _read_json(os.path.join(workdir, "pending_actions.json"), [])
    if isinstance(pa, list):
        pend = [x for x in pa if isinstance(x, dict) and str(x.get("status") or "") != "resolved"]
    pend.sort(key=lambda x: str(x.get("last_seen") or ""), reverse=True)

    def dir_of(j):
        return (j.get("direction") or j.get("industry") or "其他").strip() or "其他"

    def sal_num(s):
        """把「200-250元/天」「6-8K」折成月薪 K，仅用于和 min_salary_k 比。"""
        s = s or ""
        m = re.search(r"(\d+)\s*-\s*(\d+)\s*[Kk]", s)
        if m:
            return float(m.group(1))
        m = re.search(r"(\d+)\s*-\s*(\d+)\s*元\s*/\s*天", s)
        if m:
            return float(m.group(1)) * 21 / 1000.0
        return 0.0

    prof = profile or {}
    floor = prof.get("min_salary_k")
    city = prof.get("target_city") or "—"
    low = [j for j in delivered if floor and 0 < sal_num(j.get("salary", "")) < float(floor)]
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    floor_txt = f"{floor}K" if floor else "不限"

    sent_ok_n = sum(1 for j in today_rows if send_state(j)[0] == "ok")

    # 今日方向分布并进区块副标题：明细行里再单独列一次方向，会与岗位名重复
    # （「AI全栈开发」+「AI应用开发」连读像两个岗位名），信息密度也浪费。
    today_dirs = {}
    for j in today_rows:
        d = dir_of(j)
        today_dirs[d] = today_dirs.get(d, 0) + 1
    dir_mix = " · ".join(f"{k} {v}" for k, v in
                         sorted(today_dirs.items(), key=lambda kv: (-kv[1], kv[0])))
    today_sub_bits = []
    if today_rows:
        today_sub_bits.append(f"图+话术 {sent_ok_n}/{today_n} 已发")
    if dir_mix:
        today_sub_bits.append(dir_mix)
    today_sub = " · ".join(today_sub_bits)

    # ── 今日列表 ──
    if today_rows:
        rows = []
        for j in today_rows:
            kind, label = send_state(j)
            rows.append(
                '<li class="row">'
                '<div class="row__main">'
                f'<span class="row__co">{_h.escape(str(j.get("company") or "—"))}</span>'
                f'<span class="row__job">{_h.escape(str(j.get("title") or ""))}</span>'
                '</div>'
                '<div class="row__side">'
                f'<span class="row__sal">{_h.escape(str(j.get("salary") or "面议"))}</span>'
                f'{st_html(kind, label)}'
                '</div>'
                '</li>'
            )
        today_html = '<ul class="rows">' + "".join(rows) + "</ul>"
    else:
        today_html = '<p class="empty">今天还没有投递记录。</p>'

    # ── 待办 ──
    if pend:
        items = []
        for x in pend:
            raw_kind = str(x.get("kind") or "待处理")
            # 「对方说话」只是 HR 来了消息，不是明确的动作要求，用中性色；蓝只留给要你动手的类型
            kind_cls = " is-passive" if raw_kind == "对方说话" else ""
            txt = str(x.get("text") or "").replace("\n", " ").strip()
            if len(txt) > 90:
                txt = txt[:90] + "…"
            seen = str(x.get("last_seen") or "")[5:16]
            items.append(
                '<li class="todo">'
                f'<div class="todo__hd"><span class="todo__co">{_h.escape(str(x.get("company") or "—"))}</span>'
                f'<span class="todo__kind{kind_cls}">{_h.escape(raw_kind)}</span>'
                f'<span class="todo__when">{_h.escape(seen)}</span></div>'
                f'<p class="todo__text">“{_h.escape(txt)}”</p>'
                '</li>'
            )
        pend_html = '<ul class="todos">' + "".join(items) + "</ul>"
    else:
        pend_html = '<p class="empty">没有等你回复的消息。</p>'

    # ── 历史累计：按方向分组，组内新的在前 ──
    groups = {}
    for j in hist:
        groups.setdefault(dir_of(j), []).append(j)
    order = sorted(groups.keys(), key=lambda c: (-len(groups[c]), c))
    # 老台账既没有投递时间也没有补发留痕——按「组」决定列：某一组里一行都没有该字段，
    # 就不给这一组渲染这一列。全局决定列会让「表头在、整组全空」，右半屏变成一个空洞；
    # 组内个别空值仍用「—」占位，不让单元格看起来像没加载。
    hist_rows = []
    for cat in order:
        items = sorted(groups[cat], key=lambda j: str(j.get("delivered_at") or ""), reverse=True)
        g_has_time = any(str(j.get("delivered_at") or "") for j in items)
        g_has_state = any(str(j.get("jobId") or "") in gstat for j in items)
        head = '<th>公司 / 岗位</th><th class="ta-r">薪资</th>'
        if g_has_time:
            head += '<th class="col-t">投递时间</th>'
        if g_has_state:
            head += '<th class="ta-r col-s">补发</th>'
        hist_rows.append(
            '<div class="grp">'
            f'<h3 class="grp__t">{_h.escape(cat)}<span class="grp__n">{len(items)}</span></h3>'
            f'<table><thead><tr>{head}</tr></thead><tbody>'
        )
        for j in items:
            kind, label = send_state(j)
            when = str(j.get("delivered_at") or "")[5:16]
            cells = ('<td><span class="c__co">%s</span><span class="c__job">%s</span></td>'
                     '<td class="ta-r num">%s</td>' % (
                         _h.escape(str(j.get("company") or "—")),
                         _h.escape(str(j.get("title") or "")),
                         _h.escape(str(j.get("salary") or "—")),
                     ))
            if g_has_time:
                cells += f'<td class="col-t num">{_h.escape(when or "—")}</td>'
            if g_has_state:
                cells += f'<td class="ta-r col-s">{st_html(kind, label) or "—"}</td>'
            hist_rows.append(f"<tr>{cells}</tr>")
        hist_rows.append("</tbody></table></div>")
    hist_html = "".join(hist_rows) if hist_rows else '<p class="empty">还没有历史记录。</p>'

    # ── 打赏（仅当 assets 里有码） ──
    def b64img(name):
        p = os.path.join(SKILL_DIR, "assets", name)
        if not os.path.exists(p):
            return ""
        try:
            with open(p, "rb") as fh:
                return "data:image/jpeg;base64," + base64.b64encode(fh.read()).decode("ascii")
        except Exception:
            return ""
    wx, ali = b64img("tip_wechat.jpg"), b64img("tip_alipay.jpg")

    reward_html = ""
    if wx or ali:
        qrs = ""
        if wx:
            qrs += f'<figure class="qr"><img src="{wx}" alt="微信赞赏码"><figcaption>微信</figcaption></figure>'
        if ali:
            qrs += f'<figure class="qr"><img src="{ali}" alt="支付宝赞赏码"><figcaption>支付宝</figcaption></figure>'
        reward_html = (
            '<section class="block tip">'
            '<h2 class="block__t">这个工具帮到了你</h2>'
            '<p class="tip__lead">它替你把机械的浏览和投递做完了。愿意的话请作者喝杯咖啡。</p>'
            f'<div class="qrs">{qrs}</div>'
            '<p class="tip__foot">完全自愿，不打赏也照常能用。</p>'
            "</section>"
        )

    low_note = (f"；另有 {len(low)} 份低于你设的 {floor_txt} 门槛，已标出待核对"
                if low else "")
    # 两个累计数字的关系直接写在页面上，不留给读者做减法
    scope = (f"今日 {today_n} 条 + 今天之前 {len(hist)} 条 = 累计 {total} 条。"
             f"补发状态来自发送记录的成功回执；待办只列还没标记处理的消息{low_note}。")

    CSS = """
:root{
  --ink:#111827; --ink-2:#4b5563; --ink-3:#5b6371; --line:#e5e7eb;
  --line-2:#eef0f3; --bg:#f5f6f8; --card:#fff; --brand:#1d4ed8;
  --ok:#047857; --half:#b45309; --todo:#b91c1c;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
  font:400 14px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
  font-variant-numeric:tabular-nums;padding:36px 20px 64px}
.page{max-width:920px;margin:0 auto}
.num{font-variant-numeric:tabular-nums;font-feature-settings:"tnum"}

.head h1{font-size:22px;line-height:1.35;font-weight:650;margin:0 0 6px;letter-spacing:.2px}
.head p{margin:0;color:var(--ink-3);font-size:13px;line-height:1.6}
.nw{white-space:nowrap}

.stats{display:flex;flex-wrap:wrap;align-items:flex-end;gap:0 44px;margin:24px 0 4px;
  padding:0 0 22px;border-bottom:1px solid var(--line)}
.stat{display:flex;flex-direction:column;gap:2px;min-width:64px}
.stat__n{font-size:26px;font-weight:650;line-height:1;letter-spacing:-.2px;color:var(--ink-2);
  display:flex;align-items:baseline;gap:1px}
.stat__l{font-size:12.5px;color:var(--ink-3);letter-spacing:.3px}
.stat__of{font-size:14px;font-weight:400;color:var(--ink-3)}
.stat--lead .stat__n{font-size:40px;color:var(--brand);letter-spacing:-1px}
.stat--lead .stat__l{color:var(--ink-3)}
/* 待回复是这页唯一需要用户动手的地方，颜色跟着状态语义走（与「待补」同色系），
   但字号与主数字同量级——它不该比「已补完」这种无事可做的数字更弱。 */
.stat--act .stat__n{color:var(--half)}

.block{margin:34px 0 0}
.block__t{font-size:15px;font-weight:650;margin:0 0 2px;letter-spacing:.2px}
.block__n{color:var(--ink-3);font-weight:400;margin-left:6px;font-size:13px}
.block__sub{margin:0 0 14px;color:var(--ink-3);font-size:12.5px}

.rows{list-style:none;margin:12px 0 0;padding:0}
.row{display:grid;grid-template-columns:1fr auto;gap:2px 20px;
  padding:12px 0 11px;border-bottom:1px solid var(--line-2)}
.row:first-child{border-top:1px solid var(--line-2)}
.row__main{display:flex;flex-direction:column;gap:3px;min-width:0}
.row__co{font-size:15px;font-weight:600;line-height:1.4}
.row__job{font-size:13.5px;color:var(--ink-2);line-height:1.5}
.row__side{display:flex;flex-direction:column;align-items:flex-end;gap:6px;text-align:right}
.row__sal{font-size:13.5px;color:var(--ink);font-variant-numeric:tabular-nums}

.st{font-size:12px;line-height:1.5;white-space:nowrap}
.st::before{content:"";display:inline-block;width:6px;height:6px;border-radius:50%;
  margin-right:6px;vertical-align:1px;background:currentColor}
.st--ok{color:var(--ok)}
.st--half{color:var(--half)}
.st--todo{color:var(--todo)}
.st--none{color:var(--ink-3)}
.st--none::before{background:#c7cbd3}

.todos{list-style:none;margin:12px 0 0;padding:0;border-top:1px solid var(--line)}
.todo{padding:14px 0;border-bottom:1px solid var(--line-2)}
.todo__hd{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.todo__co{font-size:15px;font-weight:600}
.todo__kind{font-size:12px;color:var(--ink-3);letter-spacing:.2px}
.todo__kind.is-passive{color:var(--ink-3)}
.todo__when{font-size:12px;color:var(--ink-3);font-variant-numeric:tabular-nums}
.todo__text{margin:6px 0 0;font-size:13.5px;line-height:1.65;color:var(--ink-2);
  max-width:64ch;overflow-wrap:anywhere}

.grp{margin:26px 0 0}
.grp__t{display:flex;align-items:baseline;gap:8px;font-size:14px;font-weight:600;
  color:var(--ink-2);margin:0 0 10px;padding-bottom:8px;border-bottom:1px solid var(--line)}
.grp__n{font-size:12px;color:var(--ink-3);font-weight:400}
table{width:100%;border-collapse:collapse}
th{font-size:11.5px;font-weight:500;color:var(--ink-3);text-align:left;
  letter-spacing:.5px;padding:0 16px 5px 0}
td{padding:8px 16px 8px 0;border-bottom:1px solid var(--line-2);vertical-align:top;font-size:13px}
th:last-child,td:last-child{padding-right:0}
tr:last-child td{border-bottom:none}
tbody tr:hover td{background:#fafbfc}
.c__co{display:block;font-size:13.5px;font-weight:550;color:var(--ink);line-height:1.45}
.c__job{display:block;font-size:12.5px;color:var(--ink-3);line-height:1.45;
  overflow-wrap:anywhere}
.ta-r{text-align:right}
.col-t{width:92px;white-space:nowrap}
.col-s{width:100px;white-space:nowrap}
td.num{font-variant-numeric:tabular-nums;color:var(--ink-2);font-size:12.5px}

.empty{margin:14px 0 0;color:var(--ink-3);font-size:13px}

.tip{margin-top:44px;background:var(--card);border:1px solid var(--line);
  border-radius:8px;padding:22px 24px}
.tip__lead{margin:6px 0 18px;color:var(--ink-2);font-size:13.5px;max-width:52ch}
.qrs{display:flex;gap:24px;flex-wrap:wrap}
.qr{margin:0;text-align:center}
.qr img{width:180px;height:180px;display:block;border-radius:4px;border:1px solid var(--line-2)}
.qr figcaption{margin-top:8px;font-size:12.5px;color:var(--ink-3)}
.tip__foot{margin:18px 0 0;font-size:12px;color:var(--ink-3)}

.foot{margin:40px 0 0;padding-top:16px;border-top:1px solid var(--line);
  color:var(--ink-3);font-size:13px;line-height:1.7;max-width:76ch}

@media (max-width:640px){
  body{padding:24px 14px 48px}
  .stats{gap:0 26px;padding-bottom:18px}
  .stat--lead .stat__n{font-size:34px}
  .stat__n{font-size:22px}
  /* 单列堆叠：让中文岗位名占满行宽，不再被右侧两段挤成两行 */
  .row{grid-template-columns:1fr;gap:3px;padding:13px 0 12px}
  .row__main{order:1}
  .row__side{order:2;flex-direction:row;align-items:baseline;gap:14px;
    justify-content:flex-start;text-align:left;margin-top:1px}
  .col-t{display:none}
  th.col-t,td.col-t{display:none}
  .col-s{width:88px}
}
"""

    html_out = f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>投递台账 · {_h.escape(today or now[:10])} · 今日 {today_n} 份</title>
<style>{CSS}</style>
</head><body>
<main class="page">

  <header class="head">
    <h1>BOSS 直聘 · 投递台账</h1>
    <p><span class="nw">{_h.escape(now)}</span> · <span class="nw">目标城市 {_h.escape(str(city))}</span> · <span class="nw">薪资门槛 {floor_txt}</span></p>
  </header>

  <section class="stats" aria-label="总览">
    <div class="stat stat--lead"><span class="stat__n">{today_n}</span><span class="stat__l">今日投递</span></div>
    <div class="stat"><span class="stat__n">{total}</span><span class="stat__l">累计</span></div>
    <div class="stat stat--act"><span class="stat__n">{len(pend)}</span><span class="stat__l">待你回复</span></div>
  </section>

  <section class="block">
    <h2 class="block__t">今天投的<span class="block__n">{today_n} 家</span></h2>
    {f'<p class="block__sub">{_h.escape(today_sub)}</p>' if today_sub else ''}
    {today_html}
  </section>

  <section class="block">
    <h2 class="block__t">等你回复<span class="block__n">{len(pend)} 条</span></h2>
    {pend_html}
  </section>

  <section class="block">
    <h2 class="block__t">今天之前<span class="block__n">{len(hist)} 条</span></h2>
    <p class="block__sub">按方向分组；早期记录没有存投递时间，只计入条数</p>
    {hist_html}
  </section>

  {reward_html}

  <p class="foot">{_h.escape(scope)}</p>
</main>
</body></html>"""

    html_path = os.path.join(workdir, "投递汇总.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_out)
    return html_path


# ───────────────────────────────────────────────────────────
# 使用须知 / 首次运行引导
# ───────────────────────────────────────────────────────────
def print_usage_notice():
    notice = (
        "\n╔══════════════════════════════════════════════════════════════╗\n"
        "║          📋 BOSS 直聘投递技能 · 使用须知（必读）              ║\n"
        "╠══════════════════════════════════════════════════════════════╣\n"
        "║  ✅ 本技能定位：替你完成「机械重复的浏览+投递」，             ║\n"
        "║     最终「该不该投」由 AI 语义判断（基于你填写的求职意向）。      ║\n"
        "║                                                            ║\n"
        "║  ❌ 绝非鼓励无脑海投：                                       ║\n"
        "║     · 请勿高频滥用（建议每日 ≤50 次沟通）                     ║\n"
        "║     · 请勿对明显不匹配的岗位投递，避免污染你的求职画像        ║\n"
        "║     · 请勿刻意绕过平台反滥用机制                             ║\n"
        "║                                                            ║\n"
        "║  ⚙️  使用前必做：在 user_profile.json 填写你的求职方向         ║\n"
        "║     （role_summary / prefer / avoid），让 AI 审核有依据。     ║\n"
        "║                                                            ║\n"
        "║  🛡️  安全机制：每次投递都回读页面确认「送达」才继续；        ║\n"
        "║     遇未知弹窗/误触/日上限 立即整批停手，绝不无脑继续。       ║\n"
        "╚══════════════════════════════════════════════════════════════╝\n"
        "   三步上手：① 填 user_profile.json → ② 准备环境(Chrome/WebBridge/登录) → ③ 运行本技能\n"
    )
    print(notice)


# ───────────────────────────────────────────────────────────
# 平台级常量（与筛选无关，仅为安全护栏）
# ───────────────────────────────────────────────────────────
DAILY_CAP = 150
FAIL_BREAKER = 3

DAILY_LIMIT_JS = r"""
(function(){
    var txt = (document.body.innerText||'');
    var dlg = document.querySelector('.dialog-content,.dialog-wrap,.dialog-box,.dialog-container,[class*=dialog]');
    if (dlg) txt = txt + ' || ' + (dlg.innerText||'');
    var patterns = ['已达上限','达到上限','今日上限','投递上限','已达150','已达 150','今日已投递','次数已达','今日投递','沟通上限','已与150位','您已达到沟通上限','休息一下，明天再来','您今天已与'];
    var hit = null;
    for (var i=0;i<patterns.length;i++){ if (txt.indexOf(patterns[i])>=0){ hit = patterns[i]; break; } }
    return JSON.stringify({hit: hit});
})()
"""


def detect_daily_limit(session=SESSION):
    try:
        d = json.loads(evaluate(DAILY_LIMIT_JS) or "{}")
        hit = d.get("hit")
        return bool(hit), hit or ""
    except Exception:
        return False, "detect_error"


# ───────────────────────────────────────────────────────────
# 入口（仅收尾/诊断；投递主流程在 _live_driver.py）
# ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="BOSS 直聘投递 · 收尾/诊断（实时投递见 _live_driver.py）")
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--mode", default="report", choices=["verify", "report"])
    ap.add_argument("--diag", action="store_true",
                    help="诊断模式：只读 dump 所有可见浮层 + 弹窗分类 + 日上限检测，不投递")
    a = ap.parse_args()

    profile = load_profile()

    if a.diag:
        print_usage_notice()
        print("[diag] 进入诊断模式（只读，不投递）")
        _env = check_env(verbose=True)
        if not _env.ok:
            print("[diag] ⚠️ 环境异常，诊断结果可能不准确")
        navigate(RECOMMEND_URL, wait_range=(3, 5), session=SESSION,
                 expect_url_contains="header-jobs", label="推荐页")
        time.sleep(3)
        ov = json.loads(evaluate(VISIBLE_OVERLAYS_JS) or "{}")
        ptype = read_popup_type(SESSION)
        is_limit, lp = detect_daily_limit(SESSION)
        full = json.loads(evaluate(POPUP_STATE_JS) or "{}")
        report = {
            "read_popup_type": ptype,
            "detect_daily_limit": {"hit": is_limit, "phrase": lp},
            "visible_overlays": ov,
            "popup_state_full": full,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        diag_file = os.path.join(a.workdir, f"diag_{int(time.time())}.json")
        try:
            json.dump(report, open(diag_file, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            print(f"[diag] 报告已写入 {diag_file}")
        except Exception as e:
            print(f"[diag] 写文件失败: {e}")
        sys.exit(0)

    if a.mode == "verify":
        run_verify(a.workdir, session=SESSION)
    elif a.mode == "report":
        # 收尾闭环：合并「投递成果汇报 + 打赏」二合一自包含页
        out = write_summary_page(a.workdir, profile=profile)
        if not out:
            print("[report] ⚠️ 未找到 stream_progress.json，无法生成汇报页")
            sys.exit(1)
        print(f"[report] 已生成合并汇报页：{out}")
