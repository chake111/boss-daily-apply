# -*- coding: utf-8 -*-
"""把技能装到你用的那个智能体里 —— 不假设是哪一个。

支持的安装位：
    workbuddy   ~/.workbuddy/skills/boss-daily-apply
    claude      ~/.claude/skills/boss-daily-apply        （Claude Code，个人级）
                <项目>/.claude/skills/boss-daily-apply   （加 --project）
    cursor      <项目>/.cursor/rules/boss-daily-apply.mdc （规则文件，指向 SKILL.md）
    codex       <项目>/AGENTS.md 里插入一个受管区块
    plain       不装，只打印怎么用（任何能跑 shell 的地方都行）

用法：
    python scripts/install.py --list
    python scripts/install.py --target workbuddy
    python scripts/install.py --target claude --project .
    python scripts/install.py --target cursor --project .
    python scripts/install.py --target all
    python scripts/install.py --target claude --dry-run

装的是**目录副本**（不含 .git）。想跟仓库同步就用 git pull 后重跑一次；
不想要副本也可以直接把 agent 指向仓库里的 SKILL.md（--target plain 会告诉你路径）。
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
    if dry_run:
        return "dry", dst
    if os.path.exists(dst) and force:
        shutil.rmtree(dst, ignore_errors=True)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copytree(src, dst, ignore=IGNORE)
    return "ok", dst


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
        "plain": ("plain", ROOT),
    }


def main():
    ap = argparse.ArgumentParser(description="安装 boss-daily-apply 到你的智能体")
    ap.add_argument("--target", default="", help="workbuddy|claude|claude-project|cursor|codex|plain|all")
    ap.add_argument("--project", default="", help="项目目录（cursor / codex / claude-project 用）")
    ap.add_argument("--force", action="store_true", help="覆盖已存在的安装")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    ts = targets(a.project)

    if a.list or not a.target:
        print("技能目录:", ROOT)
        print("\n可安装目标：")
        for k, (kind, path) in ts.items():
            state = "已存在" if os.path.exists(path) else "未安装"
            print("  %-16s %-8s %-8s %s" % (k, kind, state, path))
        print("\n例：python scripts/install.py --target claude --project .")
        return 0

    chosen = list(ts) if a.target == "all" else [a.target]
    for name in chosen:
        if name not in ts:
            print("✗ 未知目标:", name)
            return 2
        kind, path = ts[name]
        if kind == "dir":
            act, where = _copy_tree(ROOT, path, a.dry_run, a.force)
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
        icon = {"ok": "✓", "skip": "·", "dry": "○", "updated": "✓", "appended": "✓"}.get(act, "?")
        print("%s %-14s %s" % (icon, name, where))

    if not a.dry_run and any(ts[k][0] == "dir" for k in chosen):
        hint_dir = ts["claude"][1] if "claude" in chosen else (
            ts["claude-project"][1] if "claude-project" in chosen else ROOT)
        print("\n下一步：")
        print("  python \"%s\"" % os.path.join(hint_dir, "scripts", "bootstrap.py"))
        print("  python \"%s\"" % os.path.join(hint_dir, "scripts", "env_check.py"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
