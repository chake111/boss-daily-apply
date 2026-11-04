# -*- coding: utf-8 -*-
"""统一路径解析：代码留在技能目录，状态写进工作目录。

为什么要把两者分开
------------------
早期版本把脚本和台账混放在同一个 `boss-data/` 里，结果是「升级技能会覆盖投递台账」、
「换个工作目录得把所有脚本再复制一遍」。现在：

    技能目录（只读，可被 git 覆盖）   scripts/  config/  references/
    工作目录（可写，永不进版本库）     walk_state.json  stream_progress.json  resume/

所有路径都可以用环境变量覆盖，便于多账号 / 多城市并行跑：

    BOSS_WORKDIR     工作目录，默认 ~/.boss-daily-apply
                     （若该目录不存在、而历史位置 ~/WorkBuddy/BOSS/boss-data 存在，则沿用历史位置）
    BOSS_CONFIG_DIR  配置目录，默认依次找 <工作目录>/config、<工作目录>、<技能目录>/config
    BOSS_PROFILE     个人档案 JSON，默认依次找 <工作目录>/user_profile.json、<技能目录>/user_profile.json
    BOSS_RESUME_IMG  简历图，默认 <工作目录>/resume/resume.png
"""
import os

# ── 技能目录 ──────────────────────────────────────────────
# scripts/paths.py → 上一层就是技能根目录
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")
BUILTIN_CONFIG_DIR = os.path.join(SKILL_DIR, "config")


def _norm(p):
    """把 Git Bash 风格的 /c/Users/... 还原成 Windows 能认的 C:/Users/...。

    Windows 上的 Python 会把 `/c` 当成当前盘符下的 `\\c`，路径直接失效。
    """
    p = os.path.expanduser((p or "").strip().strip('"').strip("'"))
    if len(p) >= 3 and p[0] == "/" and p[1].isalpha() and p[2] == "/":
        p = p[1].upper() + ":" + p[2:]
    return os.path.abspath(p) if p else ""


def legacy_workdirs():
    """历史默认位置。用于新默认目录不存在时自动沿用，避免升级后"数据不见了"。"""
    home = os.path.expanduser("~")
    return [
        os.path.join(home, "WorkBuddy", "BOSS", "boss-data"),   # 早期版本（WorkBuddy 布局）
    ]


def workdir():
    """工作目录。

    优先级：BOSS_WORKDIR → <新默认> → 历史默认（存在则沿用）。
    新默认是 `~/.boss-daily-apply`：和具体工具无关，换 agent、换机器都不用改配置。
    """
    p = os.environ.get("BOSS_WORKDIR")
    if p:
        return _norm(p)
    neutral = _norm(os.path.join(os.path.expanduser("~"), ".boss-daily-apply"))
    if not os.path.exists(neutral):
        for old in legacy_workdirs():
            if os.path.exists(old):
                return _norm(old)
    return neutral


WORKDIR = workdir()


def ensure_workdir():
    """确保工作目录存在，返回路径。脚本启动时调一次即可。"""
    os.makedirs(WORKDIR, exist_ok=True)
    return WORKDIR


def state(name):
    """工作目录下的状态文件，例如 state("walk_state.json")。"""
    return os.path.join(WORKDIR, name)


def config(name):
    """找配置文件：工作目录/config 优先，其次工作目录根（旧布局），最后技能目录/config。

    这样用户可以只覆盖其中一份（比如只改 blacklist.json），其余继续跟技能一起升级；
    从旧版本升级上来的用户，配置还散在 boss-data/ 根目录，也能直接命中，不用搬家。
    """
    override = os.environ.get("BOSS_CONFIG_DIR")
    bases = ([_norm(override)] if override else []) + [
        os.path.join(WORKDIR, "config"),
        WORKDIR,
        BUILTIN_CONFIG_DIR,
    ]
    for base in bases:
        p = os.path.join(base, name)
        if os.path.exists(p):
            return p
    return os.path.join(BUILTIN_CONFIG_DIR, name)


def legacy_profile_candidates():
    """历史上档案可能被放在哪。**只给 --migrate 用，不参与日常查找。**

    为什么单独列出来：个人档案里有姓名、学校、项目经历。共用电脑时，
    别人的档案要是被"自动发现并采用"，投出去的简历就带着错误的身份。
    所以这些位置只作为"要不要搬过来"的提示，绝不隐式读取。
    """
    home = os.path.expanduser("~")
    return [
        # 老布局：档案和脚本一起放在技能目录（同一次安装，相对安全）
        os.path.join(SKILL_DIR, "user_profile.json"),
        # 上一代技能包的固定位置——可能是别人的
        os.path.join(home, ".workbuddy", "skills", "boss-zhipin-deliver", "user_profile.json"),
    ]


def profile():
    """个人档案 user_profile.json 的路径（不保证存在）。

    查找顺序：BOSS_PROFILE → <工作目录>/user_profile.json → <技能目录>/user_profile.json。
    **不碰 legacy_profile_candidates() 里的其它位置**——那些要用 bootstrap --migrate
    显式搬过来才会生效。宁可退化成空档案（onboard 会重新问），也不要静默用别人的。
    """
    p = os.environ.get("BOSS_PROFILE")
    if p:
        return _norm(p)
    for cand in (os.path.join(WORKDIR, "user_profile.json"),
                 os.path.join(SKILL_DIR, "user_profile.json")):
        if os.path.exists(cand):
            return cand
    return os.path.join(WORKDIR, "user_profile.json")


def resume_img():
    """简历图路径：环境变量优先，否则 <工作目录>/resume/resume.png。"""
    p = os.environ.get("BOSS_RESUME_IMG")
    if p:
        return _norm(p)
    return os.path.join(WORKDIR, "resume", "resume.png")


def resume_variants():
    """按方向定制的简历图变体目录（可选）。"""
    return os.path.join(WORKDIR, "resume")


def describe():
    """给 bootstrap / 排查用的可读路径摘要。"""
    cfg_dir = os.path.dirname(config("blacklist.json"))
    lines = [
        "技能目录  " + SKILL_DIR,
        "工作目录  " + WORKDIR,
        "个人档案  " + profile() + ("" if os.path.exists(profile()) else "  (未创建)"),
        "简历图    " + resume_img() + ("" if os.path.exists(resume_img()) else "  (未放置)"),
        "配置来源  " + cfg_dir,
    ]
    if WORKDIR in [os.path.normpath(p) for p in legacy_workdirs()]:
        lines.append("          ↑ 沿用了历史目录；想把数据搬到新默认位置，设 BOSS_WORKDIR 后重跑 bootstrap")
    return "\n".join(lines)


if __name__ == "__main__":
    print(describe())
