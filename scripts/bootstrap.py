# -*- coding: utf-8 -*-
"""首次安装：把工作目录搭起来，把可改的配置拷出来。

用法：
    python scripts/bootstrap.py                 # 建目录 + 拷配置模板
    python scripts/bootstrap.py --force         # 覆盖已存在的配置（谨慎）
    python scripts/bootstrap.py --print-config  # 只打印路径，不写文件

它只做三件事，全部可重复执行（幂等）：
    1. 建工作目录（默认 ~/WorkBuddy/BOSS/boss-data）
    2. 把 config/*.json 拷成 <工作目录>/config/*.json，供你自由修改
    3. 若没有 user_profile.json，从示例拷一份空档案，并提示你填

不会联网、不碰浏览器，装完即可跑 `python scripts/screen.py ...` 验证。
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
        action, dst = _copy(src, os.path.join(cfg_dir, name), a.force)
        print("  [%s] %s" % ("写入" if action == "write" else "保留", dst))

    prof = os.path.join(paths.WORKDIR, "user_profile.json")
    if not os.path.exists(prof):
        legacy = next((p for p in paths.legacy_profile_candidates() if os.path.exists(p)), "")
        if legacy:
            # 从旧版本升级上来：档案里有城市/方向的真实配置，直接搬过来
            shutil.copyfile(legacy, prof)
            print("  [迁移] %s  ← 从 %s" % (prof, legacy))
        else:
            example = os.path.join(paths.BUILTIN_CONFIG_DIR, "user_profile.example.json")
            if os.path.exists(example):
                shutil.copyfile(example, prof)
                print("  [写入] %s  ← 请填写你的城市 / 方向 / 期望薪资" % prof)
    else:
        print("  [保留] %s" % prof)

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
    print("  1) Chrome 打开并登录 BOSS直聘，确认 Kimi WebBridge 扩展已连接")
    print("  2) python scripts/env_check.py          # 环境自检")
    print("  3) python scripts/supply_probe.py --rounds 10   # 探供给、出配额")
    print("  4) python scripts/_live_driver.py walk  # 开始逐张走卡")


if __name__ == "__main__":
    main()
