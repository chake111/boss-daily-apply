# -*- coding: utf-8 -*-
"""首次安装：把工作目录搭起来，把可改的配置拷出来。

用法：
    python scripts/bootstrap.py                 # 建目录 + 拷配置模板
    python scripts/bootstrap.py --force         # 覆盖已存在的配置（谨慎）
    python scripts/bootstrap.py --print-config  # 只打印路径，不写文件

它只做三件事，全部可重复执行（幂等）：
    1. 建工作目录（默认 ~/.boss-daily-apply；旧位置存在则沿用）
    2. 把 config/*.json 拷成 <工作目录>/config/*.json，供你自由修改
    3. 若没有 user_profile.json，放一份空模板

关于旧档案
----------
不会自动迁移。个人档案里有姓名、学校、项目经历，共用电脑时自动搬过来
就等于把别人的身份带进你的投递。所以只在检测到旧档案时**提示路径**，
由你确认「那是我的」之后显式执行：

    python scripts/bootstrap.py --migrate      # 复制过来（已有则跳过，--force 才覆盖）

不会联网、不碰浏览器，装完即可跑 `python scripts/screen.py ...` 验证。
没装浏览器 / 扩展也能继续用：后面的投递用 `python scripts/ledger.py` 手动记账。
"""
import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import paths  # noqa: E402

COPY_FILES = ["blacklist.json", "greetings.json"]


def _copy(src, dst, force):
    if os.path.exists(dst) and not force:
        return "keep", dst
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)
    return "write", dst


def main():
    ap = argparse.ArgumentParser(description="初始化 BOSS 每日投递工作目录")
    ap.add_argument("--force", action="store_true", help="覆盖已有配置（会丢你的改动）")
    ap.add_argument("--migrate", action="store_true",
                    help="把旧版本位置里的个人档案复制到工作目录（确认是自己的再跑）")
    ap.add_argument("--print-config", action="store_true", help="只打印路径摘要")
    a = ap.parse_args()

    if a.print_config:
        print(paths.describe())
        return

    print("技能目录:", paths.SKILL_DIR)
    os.makedirs(paths.WORKDIR, exist_ok=True)
    print("工作目录:", paths.WORKDIR, "(已就绪)")

    cfg_dir = os.path.join(paths.WORKDIR, "config")
    os.makedirs(cfg_dir, exist_ok=True)
    for name in COPY_FILES:
        src = os.path.join(paths.BUILTIN_CONFIG_DIR, name)
        if not os.path.exists(src):
            print("  [跳过]", name, "模板不存在")
            continue
        # 旧布局把配置直接放在工作目录根下。那里的是用户改过的真货，
        # 再往 config/ 写一份模板副本会把真货遮住（config/ 优先级更高）。
        legacy = os.path.join(paths.WORKDIR, name)
        if os.path.exists(legacy) and not a.force:
            print("  [沿用] %s  ← 工作目录根下的旧配置，未覆盖" % legacy)
            continue
        action, dst = _copy(src, os.path.join(cfg_dir, name), a.force)
        print("  [%s] %s" % ("写入" if action == "write" else "保留", dst))

    prof = os.path.join(paths.WORKDIR, "user_profile.json")
    legacy_all = [p for p in paths.legacy_profile_candidates()
                  if os.path.exists(p) and os.path.abspath(p) != os.path.abspath(prof)]

    if a.migrate:
        # 显式迁移：只在用户明确说"那是我的档案"时才搬。
        # 静默搬的代价是共用电脑上把别人的姓名/学校/项目带进来，投出去的简历就是错的。
        if os.path.exists(prof) and not a.force:
            print("  [跳过] %s 已存在；要覆盖旧档案加 --force" % prof)
        elif not legacy_all:
            print("  [跳过] 没找到可迁移的旧档案")
        else:
            src = legacy_all[0]
            if os.path.exists(prof):
                shutil.copyfile(prof, prof + ".bak")
                print("  [备份] %s.bak" % prof)
            shutil.copyfile(src, prof)
            print("  [迁移] %s  ← 从 %s" % (prof, src))
    elif os.path.exists(prof):
        print("  [保留] %s" % prof)
    else:
        example = os.path.join(paths.BUILTIN_CONFIG_DIR, "user_profile.example.json")
        if os.path.exists(example):
            shutil.copyfile(example, prof)
            print("  [写入] %s  ← 空模板，跑 onboard.py 会自动填好" % prof)
        if legacy_all:
            print("  " + "!" * 8)
            print("  发现旧档案：%s" % legacy_all[0])
            print("  如果那是你自己的，运行：python scripts/bootstrap.py --migrate")
            print("  不是你的就别动——本向导不会自动搬动别人的个人资料。")
            print("  " + "!" * 8)

    resume_dir = os.path.join(paths.WORKDIR, "resume")
    os.makedirs(resume_dir, exist_ok=True)
    img = paths.resume_img()
    if not os.path.exists(img):
        print("  [待办] 把简历图放到 %s（PNG，长图更好；也可用 BOSS_RESUME_IMG 指定）" % img)
    else:
        print("  [就绪] 简历图 %s" % img)

    # 校验档案必填项，早报错好过跑到一半才发现方向是空的
    try:
        data = json.load(open(prof, encoding="utf-8"))
        missing = [k for k in ("target_city", "city_code", "role_summary") if not data.get(k)]
        if missing:
            print("\n⚠️ user_profile.json 还缺字段: %s" % ", ".join(missing))
            print("   填完再开工——这两个字段决定投哪个城市、AI 拿什么标准做语义终审。")
    except Exception as e:
        print("\n⚠️ user_profile.json 读取失败:", e)

    print("\n下一步：")
    print("  1) 打开浏览器（Chrome/Edge/Brave 都行）并登录 BOSS直聘，确认 WebBridge 扩展已连接")
    print("     python scripts/browser.py --list        # 装了哪些、在不在跑")
    print("  2) python scripts/env_check.py             # 浏览器 / 通道 / 登录态 / 页面结构 四项自检")
    print("  3) python scripts/supply_probe.py --rounds 10   # 探供给、出配额")
    print("  4) python scripts/_live_driver.py walk     # 开始逐张走卡")
    print("\n装不了扩展 / 没有 Chromium 浏览器也能用：")
    print("  python scripts/ledger.py add --title ... --company ...   # 手动投，脚本记账")
    print("  详细降级方案见 references/portability.md")


if __name__ == "__main__":
    main()
