# -*- coding: utf-8 -*-
"""把"定制好的简历配置"渲染成一张可直接发给 HR 的 PNG。

为什么要单独有这个脚本
----------------------
逐岗位定制简历时，图片是**一次性**的：这家公司一张、下家另一张。
`resume/{variant}.png` 那种固定变体图解决不了，所以这里做的是
"配置 -> 单页 PNG"，文件名按 BOSS 附件名的 80 字节限制自动裁剪。

依赖
----
本脚本是 **resume-generator 技能**的桥接层，不自带模板与事实库：
    ~/.workbuddy/skills/resume-generator/assets/template-cn-single.html
    ~/.workbuddy/skills/resume-generator/references/work-history.md
    ~/.workbuddy/skills/resume-generator/scripts/generate.py
没装那个技能时不做任何猜测，直接给出安装提示并退出 2。

用法
----
    python scripts/render_resume.py --config job.json --jobtitle 全栈开发实习生
    python scripts/render_resume.py --config job.json --jobtitle 全栈开发实习生 \
        --out <工作目录>/resume/out

config 字段与 resume-generator 一致（company / title_lines / skills / experience）。
渲染后会顺手检查内容是否溢出 A4：溢出时打印 OVERFLOW 并以 3 退出，
避免把被裁掉的简历发给 HR。
"""
import argparse
import base64
import importlib.util
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import paths  # noqa: E402

RESUME_SKILL = os.environ.get(
    "RESUME_SKILL_DIR",
    os.path.join(os.path.expanduser("~"), ".workbuddy", "skills", "resume-generator"),
)
TEMPLATE = "template-cn-single.html"
PHOTO_CANDIDATES = ("photo.jpg", "photo.png")


def die(msg, code=2):
    print(msg)
    sys.exit(code)


def load_generator():
    gen_py = os.path.join(RESUME_SKILL, "scripts", "generate.py")
    if not os.path.exists(gen_py):
        die("找不到 resume-generator 技能：%s\n"
            "先安装它（或设 RESUME_SKILL_DIR 指向它的目录），再跑这条命令。" % gen_py)
    spec = importlib.util.spec_from_file_location("resume_gen", gen_py)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def find_photo():
    for name in PHOTO_CANDIDATES:
        for base in (os.path.join(paths.WORKDIR, "resume"), paths.WORKDIR,
                     os.path.join(RESUME_SKILL, "assets")):
            p = os.path.join(base, name)
            if os.path.exists(p):
                return p
    return ""


def safe(name, limit=16):
    return re.sub(r"[^\w\u4e00-\u9fa5]+", "", name or "")[:limit] or "unknown"


def boss_safe_name(full_name, job, school, phone, ext=".png", limit=80):
    """按 BOSS 附件名的 80 字节限制裁字段，优先丢学校、最后才丢岗位。

    字节数按 UTF-8 算（一个汉字 3 字节），不是字符数——100 字节的名字
    看起来只有 46 个字，超限很不直观。
    """
    parts = [full_name, job, school, phone]
    while parts:
        name = "-".join(p for p in parts if p) + ext
        if len(name.encode("utf-8")) <= limit:
            return name
        # 从"信息量最低"的一端开始丢：学校 -> 岗位 -> 手机号
        if school and school in parts:
            parts.remove(school)
        elif job and job in parts:
            parts.remove(job)
        else:
            parts = parts[:-1]
    return (full_name or "resume") + ext


def render(config_path, out_dir, jobtitle, photo=""):
    gen = load_generator()
    cfg = json.loads(open(config_path, encoding="utf-8").read())
    wh = gen.load_work_history()

    html = gen.load_template(os.path.join(RESUME_SKILL, "assets", TEMPLATE))
    html = gen.inject_personal_info(html, wh)
    html = gen.replace_page_title(html, cfg.get("company", wh.get("name", "")), wh)
    html = gen.replace_title(html, cfg.get("title_lines") or [jobtitle or "全栈开发工程师"])
    if cfg.get("about_text"):
        html = gen.replace_about(html, cfg["about_text"])
    if cfg.get("skills"):
        html = gen.replace_skills(html, cfg["skills"])
    if cfg.get("core_competencies"):
        html = gen.replace_core_competencies(html, cfg["core_competencies"])
    if cfg.get("experience"):
        html = gen.replace_experience(html, cfg["experience"])

    photo = photo or find_photo()
    if not photo:
        die("找不到证件照：把 photo.jpg 放到 <工作目录>/resume/ 下再重试。")
    mime = "image/png" if photo.lower().endswith(".png") else "image/jpeg"
    b64 = base64.b64encode(open(photo, "rb").read()).decode()
    html = html.replace("{{PHOTO_BASE64}}", "data:%s;base64,%s" % (mime, b64))

    school = ""
    edu = wh.get("education") or [{}]
    if edu:
        school = re.sub(r"^\*\*.+?\*\*[：:]\s*", "", edu[0].get("school", "") or "")
    name = boss_safe_name(wh.get("name", ""), jobtitle, school, wh.get("phone", ""))

    os.makedirs(out_dir, exist_ok=True)
    html_path = os.path.join(out_dir, os.path.splitext(name)[0] + ".html")
    png_path = os.path.join(out_dir, name)
    open(html_path, "w", encoding="utf-8").write(html)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        die("需要 Playwright 才能出图：pip install playwright（只用本机 Edge/Chrome，不下载内核）", 2)

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(channel="msedge")
        except Exception:
            browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 794, "height": 1123}, device_scale_factor=2)
        page.goto("file:///" + html_path.replace("\\", "/"), wait_until="networkidle")
        page.wait_for_timeout(250)
        info = page.evaluate("""() => {
            const secs = [...document.querySelectorAll('.sec')];
            const last = secs.length ? secs[secs.length - 1].getBoundingClientRect().bottom : 0;
            return {bottom: Math.round(last), limit: Math.round(1123 - 13 / 25.4 * 96),
                    scroll: document.querySelector('.resume-page').scrollHeight};
        }""")
        page.locator(".resume-page").screenshot(path=png_path)
        browser.close()
    return png_path, info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="岗位定制配置 JSON")
    ap.add_argument("--jobtitle", default="", help="写进文件名的岗位名")
    ap.add_argument("--out", default=os.path.join(paths.WORKDIR, "resume", "out"))
    ap.add_argument("--photo", default="", help="证件照路径，默认自动找")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.dry_run:
        print(json.dumps({"config": a.config, "exists": os.path.exists(a.config),
                          "out": a.out, "jobtitle": a.jobtitle}, ensure_ascii=False))
        return

    png, info = render(a.config, a.out, a.jobtitle, a.photo)
    print(png)
    if info["bottom"] > info["limit"] + 2 or info["scroll"] > 1125:
        print("OVERFLOW bottom=%s limit=%s scroll=%s" % (info["bottom"], info["limit"], info["scroll"]))
        sys.exit(3)


if __name__ == "__main__":
    main()
