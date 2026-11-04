# -*- coding: utf-8 -*-
"""统一路径解析：代码留在技能目录，状态写进工作目录。

为什么要把两者分开
------------------
早期版本把脚本和台账混放在同一个 `boss-data/` 里，结果是「升级技能会覆盖投递台账」、
「换个工作目录得把所有脚本再复制一遍」。现在：

    技能目录（只读，可被 git 覆盖）   scripts/  config/  references/
    工作目录（可写，永不进版本库）     walk_state.json  stream_progress.json  resume/

所有路径都可以用环境变量覆盖，便于多账号 / 多城市并行跑：

    BOSS_WORKDIR     工作目录，默认 ~/WorkBuddy/BOSS/boss-data
    BOSS_CONFIG_DIR  配置目录，默认依次找 <工作目录>/config、<技能目录>/config
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


def workdir():
    """工作目录：环境变量优先，否则 ~/WorkBuddy/BOSS/boss-data。"""
    p = os.environ.get("BOSS_WORKDIR")
    if p:
        return _norm(p)
    return _norm(os.path.join(os.path.expanduser("~"), "WorkBuddy", "BOSS", "boss-data"))


WORKDIR = workdir()


def ensure_workdir():
    """确保工作目录存在，返回路径。脚本启动时调一次即可。"""
    os.makedirs(WORKDIR, exist_ok=True)
    return WORKDIR


def state(name):
    """工作目录下的状态文件，例如 state("walk_state.json")。"""
    return os.path.join(WORKDIR, name)


def config(name):
    """找配置文件：工作目录/config 优先，其次技能目录/config。

    这样用户可以只覆盖其中一份（比如只改 blacklist.json），
    其余继续跟技能一起升级。
    """
    override = os.environ.get("BOSS_CONFIG_DIR")
    bases = ([_norm(override)] if override else []) + [
        os.path.join(WORKDIR, "config"),
        BUILTIN_CONFIG_DIR,
    ]
    for base in bases:
        p = os.path.join(base, name)
        if os.path.exists(p):
            return p
    return os.path.join(BUILTIN_CONFIG_DIR, name)


def profile():
    """个人档案 user_profile.json 的路径（不保证存在）。"""
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
    """给 --doctor / bootstrap 用的可读路径摘要。"""
    return "\n".join([
        "技能目录  " + SKILL_DIR,
        "工作目录  " + WORKDIR,
        "个人档案  " + profile() + ("" if os.path.exists(profile()) else "  (未创建)"),
        "简历图    " + resume_img() + ("" if os.path.exists(resume_img()) else "  (未放置)"),
        "配置目录  " + config("."),
    ])


if __name__ == "__main__":
    print(describe())
