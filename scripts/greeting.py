#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按岗位 JD 自动生成打招呼语（管理与校验工具）。

子命令：
  prompt  组装指定岗位的生成提示词（白名单事实 + 本条 JD + 原文方法论）
  check   对给定的打招呼语执行 12 条机器硬指标校验
  save    校验通过后落盘至 <工作目录>/greetings/<jobId>.json
  show    查看指定岗位已保存的话术
  list    列出当前工作目录下所有已定制的话术及状态
"""

import os
import sys
import json
import argparse
import re
from datetime import datetime

# 保证可直接导入 scripts 内部模块
_HERE = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_HERE)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

from scripts import paths
from scripts import config


def get_greetings_dir():
    """返回 greetings 保存目录，确保目录存在。"""
    d = os.path.join(paths.workdir(), "greetings")
    os.makedirs(d, exist_ok=True)
    return d


def get_greeting_path(jid):
    """返回单岗位话术文件路径。"""
    jid_clean = re.sub(r'[^a-zA-Z0-9_\-]', '', str(jid))
    return os.path.join(get_greetings_dir(), f"{jid_clean}.json")


def load_last_open():
    """读取最近一次 cmd_open 记录的岗位快照。"""
    p = paths.state("last_open.json")
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def resolve_job_context(jid="", jd_arg="", title_arg="", company_arg="", salary_arg="", direction_arg=""):
    """解析岗位上下文：优先命令行传入，其次 last_open.json，其次 stream_progress / candidates。"""
    last = load_last_open() or {}
    job = {
        "jobId": jid or last.get("jobId") or "",
        "title": title_arg or last.get("title") or "",
        "company": company_arg or last.get("company") or "",
        "salary": salary_arg or last.get("salary") or "",
        "industry": last.get("industry") or "",
        "direction": direction_arg or last.get("direction") or "",
        "detail": jd_arg or last.get("detail") or "",
    }
    # 如果指定了 jid 且与 last_open 的 jobId 匹配，沿用 last_open 的详情
    if jid and last.get("jobId") == jid:
        for k in ("title", "company", "salary", "industry", "direction", "detail"):
            if not job.get(k) and last.get(k):
                job[k] = last[k]
    return job


def load_all_existing_greetings():
    """读取工作目录已保存的所有话术。"""
    d = get_greetings_dir()
    res = {}
    if not os.path.exists(d):
        return res
    for fname in os.listdir(d):
        if fname.endswith(".json"):
            jid = fname[:-5]
            fp = os.path.join(d, fname)
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    res[jid] = json.load(f)
            except Exception:
                pass
    return res


# ═══════════════════════════════════════════════════════════
# 12 条校验规则
# ═══════════════════════════════════════════════════════════

def validate_greeting(text, hook="", profile=None, job=None, jd_text="", existing=None):
    """执行 12 条机器硬指标校验。

    返回: (passed: bool, results: list of dict)
    每项 result 为: {"rule": int, "name": str, "ok": bool, "msg": str, "hint": str}
    """
    p = profile or config.load_profile()
    facts, _ = config.extract_greeting_facts(p)
    job = job or {}
    existing = existing if existing is not None else load_all_existing_greetings()
    jid = job.get("jobId") or ""

    results = []

    # 1. 总长 ≤140 字符（含标点与换行）
    total_len = len(text)
    r1_ok = total_len <= 140
    results.append({
        "rule": 1,
        "name": "总长 ≤140 字符",
        "ok": r1_ok,
        "msg": f"总长 {total_len} 字符" + ("" if r1_ok else "（超限）"),
        "hint": "删减修饰词、副词，或合并重复表达" if not r1_ok else ""
    })

    # 2. 首行 ≤18 字符；首行不以 您好|你好|请问|我对|想应聘 开头
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    first_line = lines[0] if lines else ""
    first_len = len(first_line)
    bad_prefix = bool(re.search(r'^(?:您好|你好|请问|我对|想应聘)', first_line))
    r2_ok = (first_len <= 18) and (not bad_prefix) and (first_len > 0)
    msg2 = f"首行 {first_len} 字符"
    if bad_prefix:
        msg2 += " 且包含套话开头"
    elif first_len > 18:
        msg2 += " 超出 18 字上限"
    results.append({
        "rule": 2,
        "name": "首行 ≤18 字符且禁套话开头",
        "ok": r2_ok,
        "msg": msg2,
        "hint": "首行直接上最高含金量标签（如：中南大学在读/两段大厂实习/完整掌握后端体系），不要写「您好」" if not r2_ok else ""
    })

    # 3. text[:18] == hook 或首行自洽
    if hook:
        hook_match = (text.startswith(hook) or text[:len(hook)] == hook or first_line == hook)
        r3_ok = hook_match and len(hook) <= 18
        msg3 = "hook 与首部一致" if r3_ok else f"hook（{hook}）与正文开头不匹配"
    else:
        # 未显式传 hook 时，以第一行或前 18 字符为 hook 检验
        r3_ok = (first_len <= 18)
        msg3 = f"首行 ({first_line[:18]}) 作为 hook 自洽"
    results.append({
        "rule": 3,
        "name": "结构自洽 (hook == text[:18])",
        "ok": r3_ok,
        "msg": msg3,
        "hint": "确保输出 JSON 中 hook 等于正文第一行（且 ≤18 字符）" if not r3_ok else ""
    })

    # 4. 全文 ≥90 字符（太短说明关键事实与高价值话术未放进去）
    r4_ok = total_len >= 90
    results.append({
        "rule": 4,
        "name": "全文 ≥90 字符",
        "ok": r4_ok,
        "msg": f"总长 {total_len} 字符" + ("" if r4_ok else "（过短，信息不充实）"),
        "hint": "补齐匹配的技术栈经历或到岗承诺话术" if not r4_ok else ""
    })

    # 5. 至少命中一条高价值话术：随时到岗|实习\s*[六6]\s*个月|半年以上|每周\s*[5五]\s*天|抗压
    high_value_pattern = r'(?:随时到岗|可随时|连续实习\s*[六6]\s*个月|连续实习半年以上|实习半年以上|每周\s*[5五]\s*天|抗压能力强|适应快节奏)'
    r5_ok = bool(re.search(high_value_pattern, text))
    results.append({
        "rule": 5,
        "name": "至少命中一条高价值话术",
        "ok": r5_ok,
        "msg": "命中高价值话术" if r5_ok else "未包含高价值话术",
        "hint": "加入「可随时到岗、连续实习半年以上，每周出勤5天」或「抗压能力强」" if not r5_ok else ""
    })

    # 6. 技术名词 ≤4 个（按 stack 词表命中计数，去重）
    known_stacks = facts.get("stack") or [
        "Java", "Spring Boot", "Spring Cloud", "Vue", "React", "Python", "Redis",
        "MySQL", "MyBatis", "WebSocket", "JWT", "Docker", "Git", "Linux", "AI"
    ]
    matched_tech = []
    for s in known_stacks:
        if re.search(r'(?i)\b' + re.escape(s) + r'\b', text) or (len(s) >= 3 and s.lower() in text.lower()):
            matched_tech.append(s)
    matched_tech = list(dict.fromkeys(matched_tech))
    r6_ok = len(matched_tech) <= 4
    results.append({
        "rule": 6,
        "name": "技术名词 ≤4 个（防名词堆砌）",
        "ok": r6_ok,
        "msg": f"命中 {len(matched_tech)} 个技术词 ({'、'.join(matched_tech)})" + ("" if r6_ok else "（超限）"),
        "hint": "删减次要技术词，HR看不懂堆砌的名词，保留 2~3 个与本岗最对口的即可" if not r6_ok else ""
    })

    # 7. 不出现招聘类空话：现在还招人吗|非常感兴趣，希望|贵公司发展
    empty_pattern = r'(?:现在还招人吗|非常感兴趣，希望|贵公司发展|想应聘贵司|贵公司目前)'
    has_empty = bool(re.search(empty_pattern, text))
    r7_ok = not has_empty
    results.append({
        "rule": 7,
        "name": "禁招聘空话",
        "ok": r7_ok,
        "msg": "无空话套话" if r7_ok else "包含套话（“现在还招人吗/非常感兴趣，希望”等）",
        "hint": "直接删掉这类无信息量的套话，留空间给硬实力" if not r7_ok else ""
    })

    # 8. 前 6 字不与 own_default_greeting 重叠（防 already_msg 恒真）
    g_cfg_path = paths.config("greetings.json")
    own_greet = ""
    try:
        if os.path.exists(g_cfg_path):
            with open(g_cfg_path, "r", encoding="utf-8") as f:
                own_greet = json.load(f).get("own_default_greeting") or ""
    except Exception:
        pass
    if not own_greet:
        own_greet = p.get("own_greeting_prefix") or ""
    own_clean = own_greet.replace(" ", "").replace("\n", "")
    prefix6 = text[:6].replace(" ", "").replace("\n", "")
    overlap = bool(own_clean and prefix6 and (prefix6 in own_clean or own_clean.startswith(prefix6)))
    r8_ok = not overlap
    results.append({
        "rule": 8,
        "name": "前 6 字不撞默认招呼语",
        "ok": r8_ok,
        "msg": "未与默认招呼语前缀重叠" if r8_ok else f"前 6 字「{prefix6}」撞上默认招呼语（会导致 already_msg 恒真）",
        "hint": "调整开头前几个字，避免与系统默认招呼语开头重复" if not r8_ok else ""
    })

    # 9. 与其他已完成岗位话术的前 20 字不同（防批量复制）
    text20 = text[:20].replace(" ", "").replace("\n", "")
    dup_jid = None
    for other_id, other_data in existing.items():
        if other_id == jid:
            continue
        other_t = (other_data.get("text") or "")[:20].replace(" ", "").replace("\n", "")
        if other_t and other_t == text20:
            dup_jid = other_id
            break
    r9_ok = (dup_jid is None)
    results.append({
        "rule": 9,
        "name": "与其他已完成话术前 20 字不重",
        "ok": r9_ok,
        "msg": "唯一开头" if r9_ok else f"前 20 字与岗位 {dup_jid} 完全重复",
        "hint": "针对本岗位的 JD 特征或公司业务修改首句，不要整套复制" if not r9_ok else ""
    })

    # 10. 文中「6 个月 / 5 天」等数字与 commitment 一致
    cmt = facts.get("commitment") or {}
    expected_months = cmt.get("months", 6)
    expected_days = cmt.get("days_per_week", 5)
    r10_ok = True
    r10_msg = "数字承诺与档案一致"

    m_mo = re.search(r'(\d+)\s*个?月', text)
    if m_mo:
        mo_val = int(m_mo.group(1))
        if mo_val != expected_months:
            r10_ok = False
            r10_msg = f"到岗月数（{mo_val} 个月）与档案承诺（{expected_months} 个月）矛盾"

    m_d = re.search(r'每周\s*([0-9五5])\s*天', text)
    if m_d and r10_ok:
        d_val = 5 if m_d.group(1) == "五" else int(m_d.group(1))
        if d_val != expected_days:
            r10_ok = False
            r10_msg = f"出勤天数（{d_val} 天）与档案承诺（{expected_days} 天）矛盾"

    results.append({
        "rule": 10,
        "name": "承诺数字一致性",
        "ok": r10_ok,
        "msg": r10_msg,
        "hint": f"核准文本中的数字：连续实习 {expected_months} 个月以上，每周出勤 {expected_days} 天" if not r10_ok else ""
    })

    # 11. 不出现 greeting_facts 之外的公司名 / 奖项
    # 建立敏感白名单
    allowed_companies = ["中南大学", "广西农业职业技术大学", "北京大学", "清华大学"]
    for item in (facts.get("internships") or []):
        allowed_companies.extend(re.findall(r'[\u4e00-\u9fa5a-zA-Z0-9]+', item))
    for item in (facts.get("awards") or []):
        allowed_companies.extend(re.findall(r'[\u4e00-\u9fa5a-zA-Z0-9]+', item))
    # 常见大厂名字池（不在白名单内则视为编造）
    suspicious_companies = ["字节跳动", "阿里", "腾讯", "美团", "快手", "百度", "京东", "华为", "网易", "拼多多", "滴滴"]
    hallucinated = []
    for comp in suspicious_companies:
        if comp in text:
            # 检查是否在允许白名单里
            if not any(comp in a for a in allowed_companies):
                hallucinated.append(comp)

    r11_ok = len(hallucinated) == 0
    results.append({
        "rule": 11,
        "name": "事实白名单（防编造大厂/奖项）",
        "ok": r11_ok,
        "msg": "事实均在白名单内" if r11_ok else f"出现了未在档案中登记的经历：{'、'.join(hallucinated)}",
        "hint": "只能使用个人档案中真实具备的经历与背景，严禁编造未发生的大厂实习或竞赛奖项" if not r11_ok else ""
    })

    # 12. direction 与 JD 命中的技术栈不矛盾
    direction = (job.get("direction") or "").strip()
    jd_full = (jd_text or job.get("detail") or "").lower()
    r12_ok = True
    r12_msg = "方向与技术栈协调"
    if direction in ("Java后端", "后端开发", "Java") and jd_full:
        # 如果 JD 全是前端或 UI 且明确没有后端技术
        if any(k in jd_full for k in ("vue", "react", "css", "html", "前端开发")) and not any(k in jd_full for k in ("java", "spring", "backend", "后端", "mysql", "redis", "服务端", "接口")):
            if "后端" in text and "前端" not in text:
                r12_ok = False
                r12_msg = "JD 呈现前端特征，话术却单写后端，存在方向冲突"
    results.append({
        "rule": 12,
        "name": "方向与 JD 技术栈不矛盾",
        "ok": r12_ok,
        "msg": r12_msg,
        "hint": "根据 JD 实际侧重的技术栈匹配自己的对应能力" if not r12_ok else ""
    })

    all_passed = all(r["ok"] for r in results)
    return all_passed, results


def format_check_report(passed, results):
    """格式化校验报告。"""
    passed_cnt = sum(1 for r in results if r["ok"])
    total_cnt = len(results)
    lines = []
    if passed:
        lines.append(f"✓ {passed_cnt}/{total_cnt} 全部校验通过")
    else:
        lines.append(f"✗ 校验未通过 ({passed_cnt}/{total_cnt})")
        for r in results:
            if not r["ok"]:
                lines.append(f"  ✗ 第 {r['rule']} 条 【{r['name']}】：{r['msg']}")
                if r.get("hint"):
                    lines.append(f"    💡 改法提示：{r['hint']}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# 子命令实现
# ═══════════════════════════════════════════════════════════

def cmd_prompt(args):
    """生成提示词。"""
    job = resolve_job_context(
        jid=args.job,
        jd_arg=args.jd,
        title_arg=args.title,
        company_arg=args.company,
        salary_arg=args.salary,
        direction_arg=args.direction
    )
    prof = config.load_profile()
    prompt = config.build_greeting_prompt(profile=prof, job=job, jd_text=job.get("detail", ""))
    print(prompt)
    return 0


def cmd_check(args):
    """仅校验话术。"""
    text = args.text
    hook = args.hook or ""
    if not text and args.json_input:
        try:
            data = json.loads(args.json_input)
            text = data.get("text") or ""
            hook = data.get("hook") or ""
        except Exception as e:
            print(f"✗ JSON 解析失败: {e}", file=sys.stderr)
            return 1
    if not text:
        print("✗ 请通过 --text 或 --json 输入话术文本", file=sys.stderr)
        return 1

    job = resolve_job_context(jid=args.job)
    passed, results = validate_greeting(text, hook=hook, job=job)
    print(format_check_report(passed, results))
    return 0 if passed else 1


def cmd_save(args):
    """校验并通过后落盘。"""
    text = args.text
    hook = args.hook or ""
    matched = []
    why = ""

    if not text and args.json_input:
        try:
            data = json.loads(args.json_input)
            text = data.get("text") or ""
            hook = data.get("hook") or ""
            matched = data.get("matched") or []
            why = data.get("why") or ""
        except Exception as e:
            print(f"✗ JSON 解析失败: {e}", file=sys.stderr)
            return 1

    if not text:
        print("✗ 请通过 --text 或 --json 输入话术文本", file=sys.stderr)
        return 1

    job = resolve_job_context(jid=args.job)
    jid = job.get("jobId") or args.job
    if not jid:
        print("✗ 缺少 jobId（通过 --job 指定或先执行 open <jobId>）", file=sys.stderr)
        return 1

    passed, results = validate_greeting(text, hook=hook, job=job)
    report = format_check_report(passed, results)
    print(report)

    if not passed and not args.force:
        print(f"✗ 校验未通过，拒绝保存至 greetings/{jid}.json（可用 --force 强行覆盖）", file=sys.stderr)
        return 1

    # 结构化保存
    if not hook:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        hook = lines[0][:18] if lines else text[:18]
    body = text[len(hook):].lstrip("\n") if text.startswith(hook) else text

    out_data = {
        "jobId": jid,
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "direction": job.get("direction", ""),
        "hook": hook,
        "body": body,
        "text": text,
        "matched": matched,
        "why": why,
        "created_at": datetime.now().isoformat(),
        "check": {
            "passed": passed,
            "score": f"{sum(1 for r in results if r['ok'])}/{len(results)}"
        }
    }
    save_path = get_greeting_path(jid)
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)

    print(f"✓ 已保存定制打招呼语: {save_path}")
    return 0


def cmd_show(args):
    """查看单岗位定制话术。"""
    jid = args.job
    if not jid:
        last = load_last_open() or {}
        jid = last.get("jobId")
    if not jid:
        print("✗ 请指定 --job <jobId>", file=sys.stderr)
        return 1
    p = get_greeting_path(jid)
    if not os.path.exists(p):
        print(f"· 未找到岗位 {jid} 的定制话术 ({p})")
        return 2
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_list(args):
    """列出所有已定制的话术。"""
    all_g = load_all_existing_greetings()
    if not all_g:
        print("· 暂无已保存的定制话术")
        return 0
    print(f"共找到 {len(all_g)} 条定制打招呼语：")
    print(f"{'jobId':<14} {'公司':<16} {'评分':<8} {'字数':<6} {'首行 (Hook)'}")
    print("-" * 75)
    for jid, d in sorted(all_g.items()):
        comp = (d.get("company") or "")[:14]
        score = (d.get("check") or {}).get("score", "未知")
        text = d.get("text") or ""
        hook = (d.get("hook") or text[:18]).replace("\n", " ")
        print(f"{jid:<14} {comp:<16} {score:<8} {len(text):<6} {hook}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="按岗位 JD 自动生成打招呼语管理工具")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # prompt
    p_prompt = subparsers.add_parser("prompt", help="组装打招呼语提示词")
    p_prompt.add_argument("--job", default="", help="岗位 ID（缺省读 last_open.json）")
    p_prompt.add_argument("--jd", default="", help="JD 正文或路径")
    p_prompt.add_argument("--title", default="", help="岗位名")
    p_prompt.add_argument("--company", default="", help="公司名")
    p_prompt.add_argument("--salary", default="", help="薪资")
    p_prompt.add_argument("--direction", default="", help="方向标签")

    # check
    p_check = subparsers.add_parser("check", help="校验话术规则")
    p_check.add_argument("--job", default="", help="岗位 ID")
    p_check.add_argument("--text", default="", help="话术全文")
    p_check.add_argument("--hook", default="", help="首行 hook")
    p_check.add_argument("--json", dest="json_input", default="", help="结构化 JSON 输入")

    # save
    p_save = subparsers.add_parser("save", help="校验并保存话术")
    p_save.add_argument("--job", required=True, help="岗位 ID")
    p_save.add_argument("--text", default="", help="话术全文")
    p_save.add_argument("--hook", default="", help="首行 hook")
    p_save.add_argument("--json", dest="json_input", default="", help="结构化 JSON 输入")
    p_save.add_argument("--force", action="store_true", help="未通过校验也强制保存")

    # show
    p_show = subparsers.add_parser("show", help="查看已保存的话术")
    p_show.add_argument("--job", default="", help="岗位 ID")

    # list
    subparsers.add_parser("list", help="列出全部定制话术")

    args = parser.parse_args()
    if args.subcommand == "prompt":
        return cmd_prompt(args)
    elif args.subcommand == "check":
        return cmd_check(args)
    elif args.subcommand == "save":
        return cmd_save(args)
    elif args.subcommand == "show":
        return cmd_show(args)
    elif args.subcommand == "list":
        return cmd_list(args)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
