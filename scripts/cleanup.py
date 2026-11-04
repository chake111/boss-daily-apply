#!/usr/bin/env python3
"""清理临时产物 —— 只删可以重建的东西，台账一律不碰。

⚠️ 早期版本把 `stream_progress*.json` / `stream_seen*.json` 也列进清理范围，
   跑一次就把投递台账（以及它的历史）删了。投递记录**不可重建**：删了就再也
   算不出合格率、回复率、A/B 分组。所以现在改成白名单：只删下面这几类。

删除：
  diag_*.json           诊断模式产出的临时报告
  candidates/ 下的文件   旧版流水线的遗留候选（本版不产生）
  .onboarded            旧版首次安装标记
  __pycache__/          字节码缓存

绝不删除（投递流程的唯一事实来源）：
  stream_progress.json  walk_state.json  reply_log.json  reply_events.jsonl
  pending_actions.json  daily_log.json   img_mode_log.json  supply.json
  回复率报表.md         投递汇总.html    resume/  config/  user_profile.json

用法:
  python scripts/cleanup.py                 # 清默认工作目录
  python scripts/cleanup.py --workdir <目录>
  python scripts/cleanup.py --dry-run       # 只列出不删除
  python scripts/cleanup.py --quiet         # 仅输出计数
"""
import argparse
import glob
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import paths  # noqa: E402

DISPOSABLE_PATTERNS = ["diag_*.json"]
DISPOSABLE_DIRS = ["candidates", "__pycache__"]
DISPOSABLE_FILES = [".onboarded"]

# 即使有人手滑把上面写宽了，这些名字也永远跳过
NEVER_DELETE = {
    "stream_progress.json", "walk_state.json", "reply_log.json",
    "reply_events.jsonl", "pending_actions.json", "daily_log.json",
    "img_mode_log.json", "supply.json", "user_profile.json",
    "回复率报表.md", "投递汇总.html",
}


def run_cleanup(work_dir=None, dry_run=False, quiet=False):
    work_dir = work_dir or paths.WORKDIR
    deleted = []

    for pat in DISPOSABLE_PATTERNS:
        for fp in glob.glob(os.path.join(work_dir, pat)):
            base = os.path.basename(fp)
            if base in NEVER_DELETE:
                continue
            if not dry_run:
                os.remove(fp)
            deleted.append(base)

    for d in DISPOSABLE_DIRS:
        cdir = os.path.join(work_dir, d)
        if not os.path.isdir(cdir):
            continue
        for name in os.listdir(cdir):
            fp = os.path.join(cdir, name)
            if name in NEVER_DELETE:
                continue
            if not dry_run:
                shutil.rmtree(fp) if os.path.isdir(fp) else os.remove(fp)
            deleted.append(os.path.join(d, name))

    for name in DISPOSABLE_FILES:
        fp = os.path.join(work_dir, name)
        if os.path.isfile(fp) and name not in NEVER_DELETE:
            if not dry_run:
                os.remove(fp)
            deleted.append(name)

    if dry_run:
        print(f"\n🔍 Dry Run（{work_dir}）- 将删除 {len(deleted)} 项")
        for d in deleted:
            print(f"  - {d}")
    elif not quiet:
        if deleted:
            print(f"\n🧹 已清理 {len(deleted)} 项临时产物（{work_dir}）")
            for d in deleted:
                print(f"  - {d}")
        else:
            print(f"\n✨ 没有需要清理的临时产物（{work_dir}）")
    return len(deleted)


def main():
    parser = argparse.ArgumentParser(description="清理临时产物（台账永不删除）")
    parser.add_argument("--workdir", default="", help="工作目录（默认 BOSS_WORKDIR）")
    parser.add_argument("--dry-run", action="store_true", help="只列出不删除")
    parser.add_argument("--quiet", action="store_true", help="仅输出计数")
    args = parser.parse_args()
    n = run_cleanup(args.workdir or None, dry_run=args.dry_run, quiet=args.quiet)
    if not args.dry_run and args.quiet:
        print(f"cleanup: {n} items removed")


if __name__ == "__main__":
    main()
