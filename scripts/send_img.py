# -*- coding: utf-8 -*-
"""聊天会话操作库（供 send_img2.py 复用）+ 旧版补发入口（已废弃）。

⚠️ 作为 CLI 直接运行 `send_img.py` 走的是「页面 fetch 本地图床」的老路子，
   新版 Chrome 的「本地网络访问」权限会直接拦掉（`TypeError: Failed to fetch`），
   补 `Access-Control-Allow-Private-Network` 预检头也无效。**请用 `send_img2.py`**，
   它改成 base64 分片注入页面内组 Blob，实测稳定。

保留本文件是因为 send_img2.py 复用了这里的 ev / open_conv / inject 等函数。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import paths  # noqa: E402
from scripts.webbridge_client import click, evaluate, navigate  # noqa: E402

IMG_URL = "http://127.0.0.1:8765/resume.png"
FILE_NAME = os.environ.get("BOSS_RESUME_FILENAME") or "resume.png"


def ev(code):
    try:
        return evaluate(code) or ""
    except Exception as e:
        return "EXC:" + str(e)[:120]


def load_targets(limit):
    p = paths.state("stream_progress.json")
    try:
        d = json.load(open(p, encoding="utf-8"))
    except FileNotFoundError:
        return []
    except Exception:
        return []
    names = [r.get("company") or "" for r in d.get("delivered", [])]
    return [n for n in names if n][-limit:]


def open_conv(company):
    """按公司名定位左侧会话并原生点击，返回 (ok, header)。"""
    sel = (
        "(function(){var ls=document.querySelectorAll('.user-list [role=listitem]');"
        "for(var i=0;i<ls.length;i++){var t=ls[i].textContent||'';"
        "if(t.indexOf(%s)>=0){var c=ls[i].querySelector('.friend-content')||ls[i];"
        "c.setAttribute('data-rb','1');return 'found:'+i;}}return 'notfound';})()"
        % json.dumps(company, ensure_ascii=False)
    )
    r = ev(sel)
    if not r.startswith("found"):
        return False, r
    click('[data-rb="1"]')
    ev("document.querySelector('[data-rb=\"1\"]')&&document.querySelector('[data-rb=\"1\"]').removeAttribute('data-rb')")
    time.sleep(2.2)
    header = ev(
        "(function(){var b=document.querySelector('.chat-conversation');"
        "if(!b)return '';var h=b.innerText||'';return h.slice(0,120).replace(/\\n/g,' / ');})()"
    )
    return True, header


def stage_blob():
    ev(
        "(function(){window.__rb=null;window.__rbe=null;fetch(%s+'?t='+Date.now())"
        ".then(function(r){return r.blob();}).then(function(b){window.__rb=b;})"
        ".catch(function(e){window.__rbe=String(e);});return 'go';})()" % json.dumps(IMG_URL)
    )
    for _ in range(12):
        time.sleep(0.4)
        if ev("window.__rb?String(window.__rb.size):''"):
            return True
    return False


def inject():
    return ev(
        "(function(){if(!window.__rb)return 'ERR:'+(window.__rbe||'no-blob');"
        "var inp=document.querySelector('.btn-sendimg input[type=file]');"
        "if(!inp){var all=document.querySelectorAll('input[type=file]');if(all.length)inp=all[0];}"
        "if(!inp)return 'NO_INPUT';"
        "var f=new File([window.__rb],%s,{type:'image/png'});"
        "var dt=new DataTransfer();dt.items.add(f);inp.files=dt.files;"
        "inp.dispatchEvent(new Event('change',{bubbles:true}));"
        "return 'OK '+f.size;})()" % json.dumps(FILE_NAME)
    )


def confirm():
    """回读：会话最后一条自己发出的消息里出现图片。"""
    return ev(
        "(function(){var c=document.querySelector('.chat-conversation');if(!c)return 'no-chat';"
        "var imgs=c.querySelectorAll('.message-item.myself img, .chat-message.myself img, "
        ".item-myself img, .message-item .image img');"
        "return imgs.length?('IMG '+imgs.length):'none';})()"
    )


def main():
    print("⚠️ send_img.py 的 CLI 已废弃：页面 fetch 本地图床会被 Chrome 拦掉。")
    print("   请改用: python scripts/send_img2.py <份数> --msg")
    print("   （本文件仍作为 send_img2.py 的函数库保留，直接 import 是安全的）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
