# -*- coding: utf-8 -*-
"""投一份岗位，并立刻把**这一份**定制简历图 + 一句话发过去。

为什么要有这个脚本
------------------
常规流程是「先攒一批投递，再分批补发通用变体图」。但逐岗位定制简历时，
每家公司的图都不一样，**批次就被打散成一份一份**：投完这家必须当场把这张图
发出去，否则后面再补发就得回头查"这家的图是哪张"。手动串两条命令容易漏，
这里把 deliver + send_followup 串成一步，失败时能看出是哪一段断的。

用法
----
    python scripts/apply_one.py --jid <jobId> --company 某某科技 \
        --salary "200-250元/天" --industry 计算机软件 --direction 全栈开发 \
        --jobtitle 全栈开发实习生 --img path/to/简历.png

    python scripts/apply_one.py ... --dry-run     # 只校验参数，不动浏览器

    --img 省略时只投递、不发图（用于沿用已发过简历图的场景）。

输出一行 JSON：{ok, png, img, msg, delivered_ok, reason}
任一环节失败以非零退出，便于批量脚本判断。
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import paths  # noqa: E402
from scripts import _live_driver as L  # noqa: E402

SEND_IMG = os.path.join(paths.SCRIPTS_DIR, "send_followup.py")


def out(obj, code=0):
    print(json.dumps(obj, ensure_ascii=False))
    sys.exit(code)


def archive(img, company):
    """留一份带公司前缀的副本。

    定制图按「姓名-岗位-学校-手机号」命名，同一个人投两个同名岗位时后一张会
    覆盖前一张——发出去的时候已经发出去了，但事后追查"这家当时发的是哪版"
    就查不到了。副本放 resume/archive/，不参与补发，只做追溯。
    """
    try:
        d = os.path.join(paths.WORKDIR, "resume", "archive")
        os.makedirs(d, exist_ok=True)
        safe_co = re.sub(r"[^\w\u4e00-\u9fa5]+", "", company or "")[:16] or "unknown"
        dst = os.path.join(d, "%s-%s-%s" % (safe_co, datetime.date.today().strftime("%Y%m%d"),
                                            os.path.basename(img)))
        shutil.copy2(img, dst)
        return dst
    except Exception as e:  # 归档失败不该阻断投递
        print("WARN 归档失败：%r" % (e,), file=sys.stderr)
        return ""


def send_resume(jid, img, same_tab=True):
    """补发简历图 + 话术。返回 (img_ok, msg_ok, raw_tail)。"""
    cmd = [sys.executable, SEND_IMG, "--job", jid, "--msg", "--img", img]
    if same_tab:
        cmd.append("--same-tab")
    r = subprocess.run(cmd, cwd=paths.WORKDIR, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=240)
    text = (r.stdout or "") + (r.stderr or "")
    img_ok = "IMG OK" in text
    msg_ok = "MSG[" in text and "SENT" in text
    return img_ok, msg_ok, text.strip().splitlines()[-1:] or [""]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jid", required=True, help="岗位 jobId（encryptJobId）")
    ap.add_argument("--company", required=True)
    ap.add_argument("--salary", default="")
    ap.add_argument("--industry", default="")
    ap.add_argument("--direction", default="全栈开发", help="方向标签，决定话术桶")
    ap.add_argument("--jobtitle", default="", help="仅用于日志与文件名，不参与投递")
    ap.add_argument("--img", default="", help="这一份的定制简历图；省略则只投递")
    ap.add_argument("--no-same-tab", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.jobtitle and a.img:
        got = os.path.basename(a.img)
        if a.jobtitle.replace(" ", "") not in got.replace(" ", ""):
            print("WARN 图名里没有岗位关键字「%s」，确认不是拿错图：%s" % (a.jobtitle, got),
                  file=sys.stderr)

    if a.img and not os.path.exists(a.img):
        out({"ok": False, "stage": "img", "reason": "图片不存在: %s" % a.img}, 2)

    if a.dry_run:
        out({"ok": True, "dry_run": True, "jid": a.jid, "company": a.company,
             "img": a.img or None, "direction": a.direction,
             "workdir": paths.WORKDIR})

    res = L.cmd_deliver(a.jid, a.company, a.salary, a.industry, a.direction)
    if not res.get("delivered_ok"):
        out({"ok": False, "stage": "deliver", "delivered_ok": False,
             "reason": res.get("reason", ""), "detail": {k: v for k, v in res.items()
                                                         if k in ("reason", "click_method")}}, 1)

    if not a.img:
        out({"ok": True, "delivered_ok": True, "img": None, "msg": None})

    archived = archive(a.img, a.company)
    img_ok, msg_ok, tail = send_resume(a.jid, a.img, not a.no_same_tab)
    ok = img_ok and msg_ok
    out({"ok": ok, "delivered_ok": True, "img": img_ok, "msg": msg_ok, "png": a.img,
         "archived": archived, "tail": tail}, 0 if ok else 1)


if __name__ == "__main__":
    main()
