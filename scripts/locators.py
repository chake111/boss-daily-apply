"""页面定位器组：同一个目标给多套查找策略，按顺序尝试。

为什么单独有这么一层（2026-11-06 实测）：
BOSS 改版把右侧详情容器从 `#main .job-detail` 换成 `.job-detail-box`，
而代码里写的是 `querySelector('#main .job-detail') || document`——找不到就
退化成整个 document，于是「找第一个立即沟通按钮」命中的是页面上别处那个，
`panel_ok` 恒假、点击落到无关元素，整条链路静默失效：日志全是 SKIP，
没有任何一处报错。

这里把「目标」和「怎么找到它」分开：
  · 业务代码只说「我要详情面板」，不写选择器；
  · 查找策略按可靠性从高到低排，CSS 全失效时还有一条**结构兜底**
    （从「立即沟通」按钮往上找到足够大的容器）；
  · 每个策略都记名字，命中哪条可以打日志，下次改版能一眼看出是哪条顶住了。

设计边界：这里只做确定性定位，不引入 LLM/视觉模型。理由是这个流程每天跑、
结果必须可复现；语义定位的收益（吸收改版）用「多策略 + 结构兜底」就拿到了，
代价只是多写几行 JS，而不是每次点击都产生一次模型调用的不确定性。
"""

# ── 详情面板 ────────────────────────────────────────────────
# 查找逻辑集中在 _DETAIL_REF（见下），它同时负责"命中后挂到 window 上复用"。
# 这里只暴露一个探针，供自检和健康检查读取"到底找到了没有、找到的是谁"。

# 把详情面板挂到 window 上供后续复用，避免每次点击都重新找一遍。
#
# 两条防线（都是 2026-11-06 交叉验证里被指出来的）：
# ① 引用必须 `isConnected`：保留"上一次找到的面板"可以省查找，但如果它已经被
#    移出 DOM，读它的 innerText 会拿到旧 JD、点它的按钮会打在脱离文档的节点上——
#    表现是 panel_ok:true + detail 是上一张岗位，正好是这次要消灭的那类静默失败。
#    所以只保留仍然挂在文档里的旧引用，死节点一律丢掉。
# ② 结构兜底不能认错容器：从「立即沟通」往上爬时，左侧列表也可能被选中
#    （它同样够大、同样含「立即沟通」）。判据里排掉"含 ≥2 个岗位链接"的容器，
#    否则会把整列岗位当成详情面板读，AI 拿着整页文本去判断要不要投。
_DETAIL_REF = """
(function(){
  var SEL = ['.job-detail-box', '#main .job-detail', '.job-detail', '.detail-content'];
  function isList(n){
    // 列表容器里会挂多个岗位卡链接；详情面板最多带一两个「相关职位」
    var links = n.querySelectorAll('a[href*="job_detail/"]');
    return links.length >= 2;
  }
  function panelish(n){
    if (!n || !n.isConnected || isList(n)) return false;
    var r = n.getBoundingClientRect();
    return r.width > 320 && r.height > 180;
  }
  var found = null;
  for (var i = 0; i < SEL.length; i++) {
    var el = document.querySelector(SEL[i]);
    if (el && el.isConnected && !isList(el) && (el.innerText || '').trim().length > 30) {
      found = el; break;
    }
  }
  if (!found) {
    var btns = document.querySelectorAll('button, a');
    for (var k = 0; k < btns.length; k++) {
      if ((btns[k].textContent || '').trim() !== '立即沟通') continue;
      var n = btns[k];
      for (var d = 0; d < 8 && n; d++) {
        n = n.parentElement;
        if (!n) break;
        if (panelish(n)) { found = n; break; }
      }
      if (found) break;
    }
  }
  // 注意：这里绝不能再写成 `window.__bossDetail = (function(){...})()`——
  // IIFE 里设的引用会被外层赋成 undefined，等于永远清空（踩过）。
  if (found) { window.__bossDetail = found; return; }
  var prev = window.__bossDetail;
  window.__bossDetail = (prev && prev.isConnected) ? prev : null;
})();
"""


def detail_ref_probe_js():
    """执行一次查找，返回 {ok, id}：找到了没有、找到的是哪个容器。

    包在 IIFE 里很重要——`_DETAIL_REF` 是一段语句，直接拼在顶层再接 `return`
    是语法错误（踩过一次）。id 用来在自检里钉住「命中的到底是面板还是左列表」，
    只断言"找到了"是不够的：错的容器同样能让它返回 true。
    """
    return ("(function(){\n" + _DETAIL_REF +
            "\nvar b = window.__bossDetail;\n"
            "return JSON.stringify({ok: !!(b && b.isConnected), "
            "id: b ? (b.id || '') : ''});\n})()")


# ── 「立即沟通」按钮 ────────────────────────────────────────
# 必须限定在详情面板内找。面板找不到就明确返回 NO_PANEL，**不退化为全局查找**：
# 全局找会命中左侧列表里别的岗位的按钮（2026-11-06 交叉验证实测），
# 那正是 pitfalls #37 已经删掉一次的那个兜底，不能再请回来。
CHAT_BUTTON = r"""
(function(){
  __BOSS_DETAIL_REF__
  var box = window.__bossDetail;
  if (!box || !box.isConnected) return JSON.stringify({el:false, by:'no_panel'});
  var els = box.querySelectorAll('button, a');
  for (var i = 0; i < els.length; i++) {
    if ((els[i].textContent || '').trim() === '立即沟通') {
      return JSON.stringify({el:true, by:'panel', inPanel:true});
    }
  }
  return JSON.stringify({el:false, by:'panel_no_button'});
})()
"""

# 点「立即沟通」。返回值是调用方要判断的状态，不是装饰：
#   DISABLED      岗位已停止接收沟通 → 存档跳过，不要空等超时
#   NO_PANEL      找不到详情面板 → 停手，别再瞎点
#   NO_BTN        面板在但没有按钮（已沟通过的会显示「继续沟通」）→ 存档
#   CLICKED:panel 正常
CLICK_CHAT = r"""
(function(){
  __BOSS_DETAIL_REF__
  var box = window.__bossDetail;
  if (!box || !box.isConnected) return 'NO_PANEL';
  var els = box.querySelectorAll('button, a');
  for (var i = 0; i < els.length; i++) {
    if ((els[i].textContent || '').trim() !== '立即沟通') continue;
    var cls = els[i].getAttribute('class') || '';
    if (cls.indexOf('is-disabled') >= 0) return 'DISABLED';
    els[i].click();
    return 'CLICKED:panel';
  }
  return 'NO_BTN';
})()
"""


def chat_button_js():
    return CHAT_BUTTON.replace("__BOSS_DETAIL_REF__", _DETAIL_REF)


def click_chat_js():
    return CLICK_CHAT.replace("__BOSS_DETAIL_REF__", _DETAIL_REF)


def panel_ka_js():
    """返回详情面板内「立即沟通」按钮的 ka 属性。

    这是判断「面板显示的到底是不是目标岗位」的唯一权威依据：ka 里带 jid。
    绝不能用「标题出现在页面文本里」代替——左侧列表本来就罗列所有岗位标题，
    那个判断永远为真，会把「面板没切过去」掩盖成投递成功。
    """
    return r"""(function(){
      __REF__
      var box = window.__bossDetail;
      if (!box || !box.isConnected) return '';
      var els = box.querySelectorAll('button, a');
      for (var i = 0; i < els.length; i++) {
        if ((els[i].textContent || '').trim() === '立即沟通') {
          return els[i].getAttribute('ka') || '';
        }
      }
      return '';
    })()""".replace("__REF__", _DETAIL_REF)


def panel_shows_job_js(jid):
    """布尔版：面板是否已切到目标岗位。给 click_card 当 expect 用。"""
    import json
    return r"""(function(){
      __REF__
      var box = window.__bossDetail;
      if (!box || !box.isConnected) return false;
      var want = __WANT__;
      var els = box.querySelectorAll('button, a');
      for (var i = 0; i < els.length; i++) {
        if ((els[i].textContent || '').trim() === '立即沟通') {
          return (els[i].getAttribute('ka') || '').indexOf(want) >= 0;
        }
      }
      return false;
    })()""".replace("__REF__", _DETAIL_REF).replace("__WANT__", json.dumps(str(jid)))


def delivered_state_js():
    """投递后回读：面板里按钮文案变了没、页面上有没有送达标记。"""
    return r"""(function(){
      __REF__
      var box = window.__bossDetail;
      var els = box ? box.querySelectorAll('button, a') : [];
      var btnText = '';
      for (var i = 0; i < els.length; i++) {
        var t = (els[i].textContent || '').trim();
        if (t.indexOf('沟通') >= 0 || t.indexOf('送达') >= 0) { btnText = t; break; }
      }
      var body = (document.body.innerText || '');
      var hasDelivery = body.indexOf('[送达]') >= 0 || body.indexOf('已送达') >= 0;
      var delivered = (btnText && btnText !== '立即沟通' && btnText.indexOf('立即') < 0) || hasDelivery;
      return JSON.stringify({delivered: delivered, btn: btnText, hasDelivery: hasDelivery});
    })()""".replace("__REF__", _DETAIL_REF)


# ── 岗位卡片（点选中会切换右侧详情）────────────────────────
def click_card_js(jid):
    """点卡片容器 li（不是里面的 a.job-name）。

    2026-11-06 实测：点 a 不触发 SPA 的选中逻辑，点它最近的 li 才行。
    jid 走 json.dumps 转义并拼进选择器，不用 % 格式化——避免 jid 里出现
    百分号时把整个模板打崩。
    """
    import json
    sel = 'a[href*="job_detail/%s"]' % str(jid).replace('"', '')
    return r"""(function(){
      var a = document.querySelector(__SEL__);
      if (!a || !a.isConnected) return 'ABSENT';
      var box = a.closest('li') || a.parentElement || a;
      box.scrollIntoView({block: 'center'});
      box.click();
      return 'CLICKED:' + (box.tagName || '');
    })()""".replace("__SEL__", json.dumps(sel))


# ── 页面健康检查 ───────────────────────────────────────────
# 给 acceptance / env_check 用：开投前先确认「按现在的页面结构，我们还能找到东西」。
# 三项都找不到，说明 BOSS 又改版了，此时开投只会得到一屏 SKIP。
PAGE_HEALTH = r"""
(function(){
  var out = {detail: false, cards: 0, chatBtn: false, url: location.href.slice(0, 120)};
  __BOSS_DETAIL_REF__
  out.detail = !!window.__bossDetail;
  var seen = {};
  var as = document.querySelectorAll('a[href*="job_detail/"]');
  for (var i = 0; i < as.length; i++) {
    var m = (as[i].getAttribute('href') || '').match(/job_detail\/([^.]+)\.html/);
    if (m && !seen[m[1]]) { seen[m[1]] = 1; out.cards++; }
  }
  var btns = document.querySelectorAll('button, a');
  for (var j = 0; j < btns.length; j++) {
    if ((btns[j].textContent || '').trim() === '立即沟通') { out.chatBtn = true; break; }
  }
  return JSON.stringify(out);
})()
"""


def page_health_js():
    return PAGE_HEALTH.replace("__BOSS_DETAIL_REF__", _DETAIL_REF)
