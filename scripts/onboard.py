# -*- coding: utf-8 -*-
"""首次使用向导：问清楚、装该装的、跑通一次。

一个刚 clone 下来的人不需要知道 city_code、profile 字段、调试端口。
他只应该做三件事：回答问题、点一次"允许安装"、扫码登录。

    python scripts/onboard.py            # 交互式（推荐）
    python scripts/onboard.py --check    # 只体检，不改任何东西

给智能体用（非交互）：
    python scripts/onboard.py --yes --city 深圳 --year 2027 \
        --direction "Java 后端开发实习" --resume "D:/简历.pdf"

设计原则：
  1. **装任何东西之前先说明**：装什么、多大、为什么、装到哪、有没有替代方案，
     得到明确同意才动手。不想装也能继续（退回内置 CDP 后端）。
  2. **不让人手改 JSON**：问到的值直接写进 user_profile.json。
  3. **每步都有反馈**：6 步、带序号，卡住时知道卡在哪。
  4. **可以重复跑**：已配置的项默认沿用，不会把已有数据冲掉。
"""
import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import paths  # noqa: E402

# BOSS 常用城市编码。写错会静默搜错城市，所以允许 --city-code 直接覆盖。
CITY_CODES = {
    "北京": "101010100", "上海": "101020100", "广州": "101280100", "深圳": "101280600",
    "杭州": "101210100", "成都": "101270100", "南京": "101190100", "武汉": "101200100",
    "西安": "101110100", "苏州": "101190400", "天津": "101030100", "重庆": "101040100",
    "长沙": "101250100", "郑州": "101180100", "东莞": "101281600", "佛山": "101280800",
    "合肥": "101220100", "厦门": "101230200", "青岛": "101120200", "济南": "101120100",
    "福州": "101230100", "无锡": "101190200", "宁波": "101210400", "珠海": "101280700",
    "中山": "101281700", "惠州": "101280300", "南宁": "101300100", "昆明": "101290100",
    "贵阳": "101260100", "南昌": "101240100", "太原": "101100100", "沈阳": "101070100",
    "大连": "101070200", "哈尔滨": "101050100", "长春": "101060100", "石家庄": "101090100",
}


def c(txt, color=""):
    """极简着色，不支持就不上色（Windows 老控制台会乱码）。"""
    if not sys.stdout.isatty():
        return txt
    codes = {"g": "32", "y": "33", "r": "31", "b": "36", "d": "90"}
    return "\033[%sm%s\033[0m" % (codes.get(color, "0"), txt) if color else txt


def step(n, total, title):
    print("\n" + c("[%d/%d] " % (n, total), "b") + c(title, "b"))


def ask(prompt, default="", required=False):
    """问一个问题。回车用默认值；非交互环境下直接返回默认值。"""
    tip = "（%s）" % default if default else ""
    if not sys.stdin.isatty():
        print("  %s%s → %s" % (prompt, tip, default or "（空）"))
        return default
    while True:
        try:
            v = input("  %s%s: " % (prompt, tip)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return default
        if not v:
            v = default
        if v or not required:
            return v
        print("  " + c("这项不能空", "y"))


def yes(prompt, default=True):
    if not sys.stdin.isatty():
        print("  %s → %s" % (prompt, "是" if default else "否"))
        return default
    d = "Y/n" if default else "y/N"
    try:
        v = input("  %s [%s]: " % (prompt, d)).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    if not v:
        return default
    return v in ("y", "yes", "是", "1")


def pip_install(pkgs, note=""):
    """装 Python 包，实时显示进度。返回 (ok, message)。"""
    if note:
        print("  " + c(note, "d"))
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"] + pkgs
    print("  $ " + " ".join(cmd))
    try:
        p = subprocess.run(cmd, timeout=900)
        return p.returncode == 0, "exit %d" % p.returncode
    except subprocess.TimeoutExpired:
        return False, "超时（网络太慢？可换国内镜像：-i https://pypi.tuna.tsinghua.edu.cn/simple）"
    except Exception as e:
        return False, str(e)[:200]


def has_module(name):
    try:
        __import__(name)
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════
# 各步骤
# ═══════════════════════════════════════════════════════════

def step_env():
    print("  Python  %s" % sys.version.split()[0])
    print("  系统    %s" % sys.platform)
    print("  工作目录 %s" % paths.WORKDIR)
    if sys.version_info < (3, 9):
        print("  " + c("✗ 需要 Python 3.9 及以上", "r"))
        return False
    print("  " + c("✓ 环境可用", "g"))
    return True


def step_profile(a, existing):
    """问 4 件事，够 AI 判岗用即可，不追求完整简历。"""
    city = a.city or existing.get("target_city") or ask("目标城市（写城市名，如 深圳）", "深圳", required=True)
    code = a.city_code or existing.get("city_code") or CITY_CODES.get(city, "")
    if not code:
        print("  " + c("⚠ 没内置「%s」的城市编码，请填一个（深圳=101280600）" % city, "y"))
        code = ask("city_code", "101280600", required=True)

    year = a.year or existing.get("_grad_year") or ask("你的毕业年份（如 2027）", "", required=False)
    direction = a.direction or existing.get("role_summary") or ask(
        "想投什么岗位（一句话，如：Java 后端开发实习 / 前端开发实习）", "", required=True)
    salary = a.salary or str(existing.get("min_salary_k") or "") or ask(
        "实习月薪下限（K，不知道就填 0）", "0")

    profile = dict(existing)
    profile.update({
        "target_city": city,
        "city_code": code,
        "role_summary": direction,
        "min_salary_k": int(float(salary or 0)),
        "own_greeting_prefix": existing.get("own_greeting_prefix") or "",
    })
    if year:
        profile["_grad_year"] = year
        profile["experience"] = existing.get("experience") or ("%s 届在校生，%s。" % (year, direction))
    profile.setdefault("prefer", [])
    profile.setdefault("avoid", ["销售", "非技术岗位", "外包派遣", "要求 3 年以上工作经验"])
    return profile


def step_resume(a, profile):
    """简历图：能直接用就用，PDF 现场转，其它格式给出明确指引。"""
    target = paths.resume_img()
    os.makedirs(os.path.dirname(target), exist_ok=True)

    src = a.resume or ""
    if not src and sys.stdin.isatty():
        src = ask("简历文件路径（PNG/JPG 长图，或 PDF；直接回车跳过）", "")
    if not src and os.path.exists(target):
        print("  ✓ 已有简历图：%s" % target)
        return True
    if not src:
        print("  " + c("· 跳过。补发简历图会用到，稍后放到：%s" % target, "y"))
        return False

    src = os.path.abspath(os.path.expanduser(src.strip('"').strip("'")))
    if not os.path.exists(src):
        print("  " + c("✗ 找不到文件：%s" % src, "r"))
        return False

    ext = os.path.splitext(src)[1].lower()
    if ext in (".png", ".jpg", ".jpeg", ".webp"):
        shutil.copyfile(src, target)
        print("  ✓ 已复制到 %s" % target)
        return True

    if ext == ".pdf":
        if not has_module("pypdfium2"):
            print("  要把 PDF 转成图片，需要一个转换库：")
            print("    · pypdfium2（约 3MB，Apache-2.0，无需额外系统组件）")
            print("    · 不会安装 Ghostscript / poppler 这类系统级依赖")
            if not yes("安装 pypdfium2 并转换？"):
                print("  " + c("· 已跳过。你也可以自己截图存成 %s" % target, "y"))
                return False
            ok, msg = pip_install(["pypdfium2"], "安装 PDF 渲染库…")
            if not ok:
                print("  " + c("✗ 安装失败：%s" % msg, "r"))
                return False
        try:
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(src)
            page = pdf[0]
            img = page.render(scale=2).to_pil()
            img.save(target)
            print("  ✓ 已把 PDF 第 1 页转成 %s（%dx%d）" % (target, img.width, img.height))
            return True
        except Exception as e:
            print("  " + c("✗ 转换失败：%s" % e, "r"))
            return False

    if ext in (".docx", ".doc"):
        print("  " + c("· Word 文档没法直接当图片发给 HR。", "y"))
        print("    两种做法：① 用 Word 导出 PDF，再跑一次本向导；")
        print("              ② 直接截图拼接成长图，存成 %s" % target)
        return False

    print("  " + c("· 不认识的格式 %s，请提供 PNG/JPG/PDF" % ext, "y"))
    return False


def step_tools(a):
    """说明 + 征得同意 + 安装。装完返回 (ok, backend_hint)。"""
    print("  驱动浏览器有两种方式，功能一样，差别只在「要不要装东西」：\n")
    print("  " + c("A. 装 Playwright（推荐，约 39MB）", "g"))
    print("     · 它把「等元素可点、自动滚动、失败重试、文件上传」都做好了")
    print("     · 只装 Python 包，**不下载浏览器内核**——直接驱动你系统里的 Edge/Chrome")
    print("     · 卸载：pip uninstall playwright")
    print("  " + c("B. 什么都不装", "y"))
    print("     · 用内置的协议直连（本仓库自带，无需联网安装）")
    print("     · 点击稳定性略差，官方页面改版时可能需要更新脚本")
    print()

    use_pw = a.yes_all
    if not a.skip_install and not has_module("playwright"):
        use_pw = yes("安装 Playwright？（选 n 则用内置方案，仍可自动投递）")
        if use_pw:
            ok, msg = pip_install(["playwright"], "正在安装 playwright…")
            if not ok:
                print("  " + c("✗ 安装失败：%s" % msg, "r"))
                print("    改用内置方案继续，不影响使用。")
                return True, "cdp"
            print("  " + c("✓ Playwright 装好了", "g"))
    elif has_module("playwright"):
        print("  ✓ 已检测到 Playwright，直接用")
        use_pw = True

    return True, ("playwright" if use_pw and has_module("playwright") else "cdp")


def step_login(a, deadline_s=240):
    """起浏览器 → 让用户扫码 → 轮询登录态。"""
    from scripts import cdp_client

    port = cdp_client.DEFAULT_PORT
    if cdp_client.available(port):
        print("  ✓ 调试端口已在监听，复用现有浏览器")
    else:
        print("  正在启动浏览器（首次会打开一个新窗口，用独立 profile，不干扰你日常浏览）…")
        ok, msg = cdp_client.launch(port=port,
                                    url="https://www.zhipin.com/web/geek/jobs?ka=header-jobs")
        if not ok:
            print("  " + c("✗ 启动失败：%s" % msg, "r"))
            return False
        print("  " + msg)

    print("\n  请在打开的窗口里扫码登录 BOSS直聘。登录一次即可，之后会一直记住。")
    try:
        from scripts.env_check import _check_boss_login
    except Exception:
        return True

    t0 = time.time()
    while time.time() - t0 < deadline_s:
        try:
            ok, detail = _check_boss_login()
        except Exception:
            ok, detail = False, "检测异常"
        if ok:
            print("  " + c("✓ 登录状态已确认", "g"))
            return True
        if "无法确认" in detail and sys.stdin.isatty():
            # 自动判断拿不准时，别猜——直接问人，比给个假结论强
            if yes("  页面看起来不像未登录，你确认已经登录好了吗？", True):
                print("  " + c("✓ 已按你的确认继续", "g"))
                return True
        left = int(deadline_s - (time.time() - t0))
        print("  … 还没检测到登录（剩 %ds），登录完成后会自动继续" % left, flush=True)
        time.sleep(12)
    print("  " + c("· 超时未确认登录。不影响后续：登录后直接开工即可。", "y"))
    return False


def step_save(profile):
    p = os.path.join(paths.WORKDIR, "user_profile.json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    print("  ✓ 已写入 %s" % p)
    return p


# ═══════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="BOSS 投递 · 首次使用向导")
    ap.add_argument("--city", default="")
    ap.add_argument("--city-code", default="")
    ap.add_argument("--year", default="")
    ap.add_argument("--direction", default="")
    ap.add_argument("--salary", default="")
    ap.add_argument("--resume", default="")
    ap.add_argument("--yes", dest="yes_all", action="store_true",
                    help="非交互：全用默认/参数值，并同意安装 Playwright")
    ap.add_argument("--skip-install", action="store_true", help="不装任何东西，用内置方案")
    ap.add_argument("--check", action="store_true", help="只体检，不改配置")
    ap.add_argument("--login-timeout", type=int, default=240,
                    help="等待扫码登录的秒数（默认 240）")
    a = ap.parse_args()

    print()
    print(c("  BOSS 直聘 · 每日投递  首次使用向导", "b"))
    print(c("  ─────────────────────────────────────", "d"))

    paths.ensure_workdir()
    prof_path = os.path.join(paths.WORKDIR, "user_profile.json")
    existing = {}
    if os.path.exists(prof_path):
        try:
            existing = json.load(open(prof_path, encoding="utf-8"))
        except Exception:
            existing = {}

    if a.check:
        step(1, 1, "环境检查")
        if not step_env():
            return 2
        from scripts.webbridge_client import backend
        print("  驱动方式  %s" % (backend(force=True) or "未就绪"))
        print("  求职信息  %s" % ("✓" if existing.get("role_summary") else "✗ 还没填，跑一次 onboard.py"))
        print("  简历图    %s" % ("✓" if os.path.exists(paths.resume_img()) else "· 未提供"))
        return 0

    total = 5
    step(1, total, "环境检查")
    if not step_env():
        return 2

    step(2, total, "你的求职信息（AI 判岗就靠这几项）")
    profile = step_profile(a, existing)

    step(3, total, "简历")
    step_resume(a, profile)

    step(4, total, "驱动浏览器的工具")
    ok, hint = step_tools(a)
    if not ok:
        return 2

    step(5, total, "登录 BOSS直聘")
    logged = step_login(a, deadline_s=a.login_timeout)

    save_this = not a.check
    if save_this:
        step_save(profile)

    # ── 收尾：把"下一步做什么"说清楚，别让人猜
    print("\n" + c("  ─────────────────────────────────────", "d"))
    print(c("  就绪情况", "b"))
    print("    求职信息   %s" % ("✓" if profile.get("role_summary") else "✗ 缺方向"))
    print("    城市        %s（%s）" % (profile.get("target_city"), profile.get("city_code")))
    print("    简历图      %s" % ("✓" if os.path.exists(paths.resume_img()) else "· 未提供"))
    print("    驱动方式    %s" % hint)
    print("    登录状态    %s" % ("✓" if logged else "· 未确认"))

    print("\n" + c("  以后每天只做两件事：", "b"))
    print("    1) 开工：python scripts/cdp_client.py --serve          # 保持这个窗口开着")
    print("    2) 投递：python scripts/_live_driver.py walk           # 或直接跟智能体说「投 20 份」")
    print("\n  先试一把：")
    print("    python scripts/env_check.py")
    print("    python scripts/supply_probe.py --rounds 10")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
