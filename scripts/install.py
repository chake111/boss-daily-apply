# -*- coding: utf-8 -*-
"""把技能装到你用的那个智能体里 —— 不假设是哪一个。

支持的安装位：
    workbuddy   ~/.workbuddy/skills/boss-daily-apply
    claude      ~/.claude/skills/boss-daily-apply        （Claude Code，个人级）
                <项目>/.claude/skills/boss-daily-apply   （加 --project）
    cursor      <项目>/.cursor/rules/boss-daily-apply.mdc （规则文件，指向 SKILL.md）
    codex       <项目>/AGENTS.md 里插入一个受管区块
    antigravity ~/.gemini/config/skills/boss-daily-apply （Google Antigravity 全局；
                App / CLI / IDE 三个面都从这里读技能）
                <项目>/.agents/skills/boss-daily-apply    （antigravity-project，工作区级）
    plain       不装，只打印怎么用（任何能跑 shell 的地方都行）

用法：
    python scripts/install.py --list
    python scripts/install.py --target workbuddy
    python scripts/install.py --target claude --project .
    python scripts/install.py --target cursor --project .
    python scripts/install.py --target antigravity            # 默认只放一个入口指针
    python scripts/install.py --target antigravity --copy     # 改成整包复制
    python scripts/install.py --target all
    python scripts/install.py --target claude --dry-run

装的是**目录副本**（不含 .git）。想跟仓库同步就用 git pull 后重跑一次；
不想要副本也可以直接把 agent 指向仓库里的 SKILL.md（--target plain 会告诉你路径）。

antigravity 是例外：它原生按 SKILL.md 自动发现技能，所以默认不复制整包，只在技能目录
放一个**入口指针**（几十行的 SKILL.md，正文指回本仓库）。好处是仓库改了立刻生效、
副本不会过期；缺点是机器人要多读一次文件。要自包含就加 --copy。
"""
import argparse
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = os.path.basename(ROOT)
HOME = os.path.expanduser("~")

IGNORE = shutil.ignore_patterns(
    ".git", "__pycache__", "*.pyc", ".tmp-*", "*.tmp", ".tab_lock",
    "stream_progress.json", "walk_state.json", "supply.json",
)

# 给 rule 类目标用的紧凑版规则：即使 agent 不读 SKILL.md，也不会踩红线
RULES = """# BOSS 直聘每日投递（boss-daily-apply）

完整流程见 `{skill}/SKILL.md`，判定标准见 `{skill}/references/judgment.md`，
执行细节见 `{skill}/references/runbook.md`。

## 三条红线（任何情况下都不能违反）
1. 一次只判一张卡：`walk` 每次只返回一张，禁止批量抓整页再挑。
2. 代码里没有"该投/不该投"的规则，方向由你读完 JD 后语义判断，依据 `user_profile.json`。
3. 除 `deliver` 外，离开一张卡之前必须先 `reject`。

## 立即停止的条件
验证码 / 滑块 / 人脸核验、平台风控提示、连续 3 次投递失败、扩展连续掉线且重启浏览器两轮不通。
`document.hidden=true` **不是**停手理由（走 `&page=N` 分页兜底）。

## 命令入口
```bash
python "{skill}/scripts/_live_driver.py" walk
python "{skill}/scripts/_live_driver.py" open <jobId>
python "{skill}/scripts/_live_driver.py" deliver <jobId> "<公司>" "<薪资>" "<行业>" "<方向>"
python "{skill}/scripts/_live_driver.py" reject <jobId>
```

## 没有浏览器 / 没有扩展时
用 `python "{skill}/scripts/ledger.py"` 手动记账，`stats.py` 照样出回复率报表。
"""


def _copy_tree(src, dst, dry_run, force):
    if os.path.exists(dst) and not force:
        return "skip", dst + "（已存在，要覆盖加 --force）"
    # 目标目录本身是 git 工作区时，--force 的 rmtree 会把 .git 一起删掉，
    # 连带删掉本地所有未推送的提交和历史。这种情况一律拒绝，交给人处理。
    # 触发场景：仓库直接放在安装位置（改代码就在那儿改），又一次从这里装到别处，
    # 或者装了两次。宁可让命令失败，也不能静默删掉版本库。
    if os.path.isdir(os.path.join(dst, ".git")):
        return "blocked", dst + "（是 git 工作区，拒绝覆盖：请先提交或用别处的副本部署）"
    if dry_run:
        return "dry", dst
    if os.path.exists(dst) and force:
        shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copytree(src, dst, ignore=IGNORE)
    return "ok", dst


SHIM = """---
name: {name}
description: "BOSS直聘批量投递实习岗（投递 / 今天投 N 份 / 继续投 / BOSS 投简历 / 看看回复）。本文件是入口指针，正文在本地技能仓库。"
---

# {name}（入口指针）

技能正文**不在这个目录**，在：

    {skill}

## 第一步（必须先做）

用读文件工具把 `{skill}/SKILL.md` 完整读一遍，然后按它的流程执行。
本文件只有入口，不含流程——**不要凭这几行猜步骤**，也不要把状态文件写在这里。

- 完整流程：`{skill}/SKILL.md`
- 判定标准：`{skill}/references/judgment.md`
- 执行细节与踩坑：`{skill}/references/runbook.md`、`pitfalls.md`

## 三条红线（读正文之前也不能违反）

1. 一次只判一张卡：`walk` 每次只给一张，禁止批量抓整页再挑。
2. 代码里没有「该投 / 不该投」的规则，方向由你读完 JD 后语义判断，依据 `user_profile.json`。
3. 除 `deliver` 外，离开一张卡之前必须先 `reject`。

## 命令入口

```bash
python "{skill}/scripts/_live_driver.py" walk
python "{skill}/scripts/_live_driver.py" open <jobId>
python "{skill}/scripts/_live_driver.py" deliver <jobId> "<公司>" "<薪资>" "<行业>" "<方向>"
python "{skill}/scripts/_live_driver.py" reject <jobId>
```

## 立即停手

验证码 / 滑块 / 人脸核验、平台风控提示、连续 3 次投递失败、浏览器两轮都连不上。
`document.hidden=true` **不是**停手理由（走 `&page=N` 分页兜底）。

## 没有浏览器时

`python "{skill}/scripts/ledger.py"` 手动记账，`stats.py` 照样出回复率报表。
"""


def _write_shim(dst, dry_run, force):
    """在 dst 放一个只指向本仓库的 SKILL.md。

    为什么不复制整包：仓库在持续改（判据、选择器、话术），副本装一次就过期一次，
    而「改了没生效」在投递里表现为「判据没更新却没人发现」，只有复盘时才会发现。
    指针只有几十行，永远指向最新版；代价是智能体多读一次文件。
    """
    path = os.path.join(dst, "SKILL.md")
    if os.path.exists(path) and not force:
        return "skip", path + "（已存在，要覆盖加 --force）"
    if os.path.isdir(os.path.join(dst, ".git")):
        return "blocked", dst + "（是 git 工作区，拒绝覆盖）"
    if dry_run:
        return "dry", path
    # --force 时先清空：上一版可能是一份整包副本，留着 scripts/ references/ 会变成
    # 「指针指向新仓库、旁边还躺着旧脚本」——出问题时最难判断到底跑的哪一份。
    if force and os.path.isdir(dst):
        shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(dst, exist_ok=True)
    # 统一用正斜杠：Windows 的 Python 和 PowerShell 都认，Git Bash 里也不会被当转义符
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(SHIM.format(name=NAME, skill=ROOT.replace("\\", "/")))
    return "ok", path + "  ->  " + ROOT


def _write_file(path, text, dry_run):
    if dry_run:
        return "dry", path
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return "ok", path


def _upsert_block(path, text, dry_run):
    begin, end = "<!-- boss-daily-apply:begin -->", "<!-- boss-daily-apply:end -->"
    block = begin + "\n" + text.strip() + "\n" + end
    old = ""
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old = f.read()
    if begin in old and end in old:
        head, rest = old.split(begin, 1)
        tail = rest.split(end, 1)[1] if end in rest else ""
        new = head + block + tail
        action = "updated"
    else:
        new = (old.rstrip() + "\n\n" + block + "\n") if old.strip() else block + "\n"
        action = "appended"
    if dry_run:
        return "dry", path
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)
    return action, path


def targets(project):
    project = os.path.abspath(project or os.getcwd())
    return {
        "workbuddy": ("dir", os.path.join(HOME, ".workbuddy", "skills", NAME)),
        "claude": ("dir", os.path.join(HOME, ".claude", "skills", NAME)),
        "claude-project": ("dir", os.path.join(project, ".claude", "skills", NAME)),
        "cursor": ("rule", os.path.join(project, ".cursor", "rules", NAME + ".mdc")),
        "codex": ("agents", os.path.join(project, "AGENTS.md")),
        # Antigravity 原生读 SKILL.md，不需要规则文件；App / CLI / IDE 共用这一个全局目录。
        # 用 shim 而不是整包复制：只放入口指针，正文始终指向本仓库。
        "antigravity": ("shim", os.path.join(HOME, ".gemini", "config", "skills", NAME)),
        "antigravity-project": ("shim", os.path.join(project, ".agents", "skills", NAME)),
        "plain": ("plain", ROOT),
    }


def main():
    ap = argparse.ArgumentParser(description="安装 boss-daily-apply 到你的智能体")
    ap.add_argument("--target", default="",
                    help="workbuddy|claude|claude-project|cursor|codex|antigravity|antigravity-project|plain|all")
    ap.add_argument("--project", default="", help="项目目录（cursor / codex / claude-project / antigravity-project 用）")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的安装")
    ap.add_argument("--copy", action="store_true",
                    help="antigravity 目标改为整包复制（默认只放入口指针，正文指回仓库）")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    ts = targets(a.project)

    if a.list or not a.target:
        print("技能目录:", ROOT)
        print("\n可安装目标：")
        for k, (kind, path) in ts.items():
            state = "已存在" if (os.path.exists(path) or os.path.islink(path)) else "未安装"
            print("  %-20s %-6s %-8s %s" % (k, kind, state, path))
        print("\n例：python scripts/install.py --target claude --project .")
        print("    python scripts/install.py --target antigravity        # 入口指针，正文跟仓库走")
        print("    python scripts/install.py --target antigravity --copy # 整包复制，自包含")
        return 0

    chosen = list(ts) if a.target == "all" else [a.target]
    ok_any = False
    for name in chosen:
        if name not in ts:
            print("✗ 未知目标:", name)
            return 2
        kind, path = ts[name]
        if kind == "dir":
            act, where = _copy_tree(ROOT, path, a.dry_run, a.force)
        elif kind == "shim":
            if a.copy:
                act, where = _copy_tree(ROOT, path, a.dry_run, a.force)
            else:
                act, where = _write_shim(path, a.dry_run, a.force)
        elif kind == "rule":
            body = "---\ndescription: BOSS 直聘每日投递 runbook（探供给 / 逐张判 JD / 记账统计）\nglobs: \nalwaysApply: false\n---\n\n" + \
                   RULES.format(skill=ROOT)
            act, where = _write_file(path, body, a.dry_run)
        elif kind == "agents":
            act, where = _upsert_block(path, RULES.format(skill=ROOT), a.dry_run)
        else:
            print("plain: 不复制任何文件。仓库就在 %s" % ROOT)
            print("  把 SKILL.md 的内容交给你的智能体，或让它直接读这个目录即可。")
            continue
        icon = {"ok": "✓", "copied": "~", "skip": "·", "dry": "○",
                "updated": "✓", "appended": "✓", "blocked": "✗", "failed": "✗"}.get(act, "?")
        print("%s %-20s %s" % (icon, name, where))
        if act in ("ok", "copied", "updated", "appended"):
            ok_any = True
        if act == "blocked":
            print("    版本库不能覆盖。若确实要用这份覆盖，先 cd 过去 git status 确认，"
                  "手动删掉 .git 再装；或换个目标目录。")

    if not a.dry_run and ok_any and any(ts[k][0] in ("dir", "shim") for k in chosen):
        # 指针模式下真正能跑脚本的还是仓库本身，所以提示里给的路径得跟着模式走
        hint_dir = ROOT
        for k in ("workbuddy", "claude", "claude-project", "antigravity", "antigravity-project"):
            if k in chosen and (ts[k][0] == "dir" or a.copy):
                hint_dir = ts[k][1]
                break
        print("\n下一步：")
        print("  python \"%s\"" % os.path.join(hint_dir, "scripts", "bootstrap.py"))
        print("  python \"%s\"" % os.path.join(hint_dir, "scripts", "env_check.py"))
        if "antigravity" in chosen or "antigravity-project" in chosen:
            print("\nAntigravity 侧：新开一个会话（或 IDE 里重新加载窗口），Customizations 里就能看到"
                  " boss-daily-apply；\n  也可以直接输入 /boss-daily-apply 手动调起。"
                  "\n  首次跑脚本会让它执行终端命令 + 开浏览器，按提示授权即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
