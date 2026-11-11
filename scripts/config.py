#!/usr/bin/env python3
"""Boss直聘投递 — 统一配置（零硬编码 · AI 语义终审）

核心约定：
  - 彻底删除所有硬编码筛选标准（不再有任何 BASE_* 排除词 / 行业黑名单 /
    手艺岗规则 / 门店店长 off-target / 管理岗豁免 / 强相关关键词表）。
  - 任何"投递标准"与"排除标准"都只能来自 user_profile.json 中用户自己填写的
    自由文本字段（role_summary / prefer / avoid / min_salary_k / target_city），
    由智能体在问答采集时根据用户本次提供的信息动态生成，绝不写死在代码里。
  - 最终审核不再依赖关键词匹配：脚本只做"机械采集 + 平台级护栏（登录态、
    日上限、已投去重、薪资/城市硬门槛）"，岗位是否投递由【智能体自身】基于
    用户画像与 JD 上下文做语义判断（不调用任何外部 LLM API）。

设计哲学：
  - 代码层：只负责浏览器机械操作 + 平台级安全护栏，不替用户做任何
    "这个岗该不该投"的价值判断。
  - AI 层：拿着"用户自述的意向 + 岗位全量信息"做语义理解，输出
    APPROVE / REJECT / NEED_MORE 决策与理由。

档案加载顺序：
  1. 环境变量 BOSS_PROFILE 指向的文件（若存在）
  2. 技能目录下的 user_profile.json
  3. 内置 EXAMPLE_PROFILE（通用空白模板，零硬编码、零特定人物/城市/行业）
"""

import os
import json
import sys

# ═══════════════════════════════════════════════════════════
# 路径解析
# ═══════════════════════════════════════════════════════════

_HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(_HERE)


def _default_profile_path():
    """返回档案路径。

    顺序：BOSS_PROFILE 环境变量 → <工作目录>/user_profile.json
          → <技能目录>/user_profile.json（老布局的兼容位置）。
    个人档案属于「用户数据」，理想位置是工作目录，这样升级技能不会覆盖它。
    """
    try:
        from scripts import paths
        return paths.profile()
    except Exception:
        p = os.environ.get("BOSS_PROFILE")
        if p and os.path.exists(p):
            return p
        return os.path.join(SKILL_DIR, "user_profile.json")


# ═══════════════════════════════════════════════════════════
# 内置默认档案（通用空白模板）
#   仅用于在找不到 user_profile.json 时保证技能不崩溃；
#   实际使用时智能体会在使用前根据你的回答自动生成 user_profile.json，
#   你也可以手动编辑它。本模板不含任何特定人物 / 城市 / 行业 / 关键词。
# ═══════════════════════════════════════════════════════════

EXAMPLE_PROFILE = {
    "_guide": "这是内置通用模板（无任何特定人物/城市/行业/关键词）。请复制本结构到 user_profile.json 并按自身情况填写，或由智能体问答后自动生成。",
    "name": "",
    "experience": "",
    "target_city": "",
    "city_code": "",
    "min_salary_k": 0,
    "role_summary": "",
    "prefer": [],
    "avoid": [],
    "prefer_no_big_company": False,
    "prefer_no_headhunter": False,
    "accept_note": "",
}


# ═══════════════════════════════════════════════════════════
# Profile 加载
# ═══════════════════════════════════════════════════════════

def _log(msg):
    """诊断信息只走 stderr，且默认静默。

    为什么不直接 print：`_live_driver.py` 的 stdout 是给智能体解析的 JSON，
    任何一行多余输出都会让「最后一行是 JSON」的约定失效。
    需要看档案来源时设 BOSS_DEBUG=1。
    """
    if os.environ.get("BOSS_DEBUG"):
        print(msg, file=sys.stderr)


def load_profile(path=None):
    """加载个人档案 user_profile.json。返回 dict。

    找不到时使用内置 EXAMPLE_PROFILE，保证技能可开箱运行。
    以 BOSS_PROFILE 环境变量优先，便于智能体在运行时注入不同档案。
    """
    path = path or _default_profile_path()
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                prof = json.load(f)
            # 过滤掉以 _ 开头的说明字段
            prof = {k: v for k, v in prof.items() if not k.startswith("_")}
            _log(f"[config] 已加载档案: {path}")
            return prof
        except Exception as e:
            _log(f"[config] 读取档案失败 {path}: {e}，改用内置示例档案")
    else:
        _log(f"[config] 未找到档案 {path}，使用内置示例档案；请编辑 user_profile.json")
    return dict(EXAMPLE_PROFILE)


# 模块级常量（供其它脚本便捷 import）
PROFILE = load_profile()


# ═══════════════════════════════════════════════════════════
# 薪资解析辅助
# ═══════════════════════════════════════════════════════════

def parse_salary_min(sal):
    """取薪资区间下限（K）。如 '3-8K'→3, '7-9K'→7, '12-18K·13薪'→12。"""
    import re
    vals = []
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*[Kk]', sal or ''):
        vals.append(float(m.group(1)))
    if not vals:
        m = re.search(r'(\d+(?:\.\d+)?)', sal or '')
        return float(m.group(1)) if m else 0
    return min(vals)


def parse_salary_max(sal):
    """取薪资区间上限（K）。如 '3-8K'→8, '7-9K'→9。"""
    import re
    vals = []
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*[Kk]', sal or ''):
        vals.append(float(m.group(1)))
    if not vals:
        m = re.search(r'(\d+(?:\.\d+)?)', sal or '')
        return float(m.group(1)) if m else 0
    return max(vals)


# ═══════════════════════════════════════════════════════════
# AI 语义审核提示词（完全由 profile 驱动，零硬编码类别）
# ═══════════════════════════════════════════════════════════

def build_review_prompt(profile=None, job=None, jd_text=""):
    """根据个人档案动态生成 AI 语义审核提示词（不写死任何行业/类别）。

    返回的字符串内含岗位全量信息 + 用户自述意向，交由【智能体自身】基于语义理解
    输出结构化决策（不调用任何外部 LLM API）。所有"该投 / 不该投"的标准都来自
    用户的 role_summary / prefer / avoid 自由文本，而非代码里的关键词表。

    参数：
      profile : user_profile.json 解析后的 dict
      job     : 岗位 dict（title/company/salary/city/degree/experience 等）
      jd_text : 已读取的 JD 正文
    """
    p = profile or PROFILE
    name = p.get("name") or "候选人"
    exp = p.get("experience") or "（未填写，请完善档案）"
    city = p.get("target_city") or "（未限定）"
    min_sal = p.get("min_salary_k") or 0
    role_summary = p.get("role_summary") or "（未填写，请完善档案）"
    prefer = p.get("prefer") or []
    avoid = p.get("avoid") or []
    accept = p.get("accept_note") or "（无）"
    no_big = p.get("prefer_no_big_company")
    no_headhunter = p.get("prefer_no_headhunter")

    big_rule = "尽量不投大厂/上市公司（已上市、2000人以上）" if no_big else "大厂/上市公司均可接受"
    headhunter_rule = "尽量避开猎头/人力外包/代招公司" if no_headhunter else "猎头/人力外包公司均可接受"

    prefer_lines = "\n".join(f"  - {x}" for x in prefer) or "  （未填写）"
    avoid_lines = "\n".join(f"  - {x}" for x in avoid) or "  （未填写）"

    # 岗位信息（全量，供 AI 语义理解；不做任何代码侧裁剪）
    job = job or {}
    job_info = (
        f"职位名称：{job.get('title', '')}\n"
        f"公司名称：{job.get('company', '')}\n"
        f"薪资：{job.get('salary', '')}\n"
        f"城市：{job.get('city', '')}\n"
        f"学历要求：{job.get('degree', '')}\n"
        f"经验要求：{job.get('experience', '')}\n"
        f"岗位链接/ID：{job.get('jobId', '')}\n"
        f"JD 正文：\n{jd_text or '（未读取到）'}"
    )

    return f"""你是一位严格的岗位匹配审核专家。请基于【候选人画像】与【岗位信息】做语义理解，判断该岗位是否适合投递。

【候选人画像】
- 姓名：{name}
- 经验背景：{exp}
- 目标城市：{city}
- 最低薪资期望：{min_sal}K（0 表示未设下限）
- 求职方向概述（一句话自述，是最重要的匹配依据）：{role_summary}
- 公司偏好：{big_rule}；{headhunter_rule}
- 偏好补充说明：{accept}

【候选人明确"希望投"的方向（自由文本，来自本人填写）】
{prefer_lines}

【候选人明确"不希望投"的方向（自由文本，来自本人填写）】
{avoid_lines}

【岗位信息】
{job_info}

【审核原则 —— 语义理解，而非关键词匹配】
1. 以"求职方向概述 + 希望投/不希望投"为核心依据，结合 JD 全文做语义判断。
   例如候选人自述「某行业 X 的运营管理」，则同行业 X 的运营/相关岗应判 APPROVE；
   与自述明显无关的岗位（如完全不同的其它行业岗）应判 REJECT。
2. 城市：若岗位城市与候选人目标城市不一致，通常 REJECT（除非候选人未限定城市）。
3. 薪资：若岗位薪资上限明显低于候选人最低期望（{min_sal}K），REJECT；薪资"面议"或高于期望则不影响。
4. "不希望投"清单：岗位若命中候选人自述的排除方向（如"不要销售""不要夜班"），应 REJECT。
5. 当仅凭标题/公司无法判断、需看 JD 才能定夺时，输出 NEED_MORE（脚本会视为待定，
   由人工/智能体进一步确认，绝不默认 APPROVE 或 REJECT）。
6. 如信息不足或不确定，宁可输出 NEED_MORE / REJECT，也不要勉强 APPROVE。

【输出格式】
必须严格输出以下 JSON（不要任何额外解释文字）：
{{
  "decision": "APPROVE" | "REJECT" | "NEED_MORE",
  "reason": "一句话语义理由（引用岗位与画像的具体对应点）",
  "confidence": "high" | "medium" | "low"
}}

规则：
- APPROVE：岗位明显匹配候选人的求职方向，可直接投递
- REJECT：岗位明显不匹配，或命中候选人明确排除的方向
- NEED_MORE：标题/公司无法判断，需结合 JD 或进一步确认
- 不确定时优先 NEED_MORE / REJECT，避免误投
"""


def build_candidate_dossier(profile, job, jd_text=""):
    """构造一个候选岗位档案 dict（供 AI 审核 + 落盘到 candidates/ 目录）。"""
    return {
        "job": job,
        "jd_text": jd_text,
        "profile_snapshot": {k: profile.get(k) for k in (
            "name", "experience", "target_city", "min_salary_k",
            "role_summary", "prefer", "avoid", "accept_note",
            "prefer_no_big_company", "prefer_no_headhunter",
        )},
        "review_prompt": build_review_prompt(profile, job, jd_text),
    }


# ═══════════════════════════════════════════════════════════
# 打招呼语方法论与提示词组装
# ═══════════════════════════════════════════════════════════

def load_greeting_playbook():
    """读取 references/greeting-playbook.md 全文（逐字，不得改写）。"""
    p = os.path.join(SKILL_DIR, "references", "greeting-playbook.md")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""


def extract_greeting_facts(profile=None):
    """提取或兜底抽取打招呼语所需的事实清单。

    若 profile 中显式提供了 greeting_facts，则直接使用，标记 unverified=False；
    否则从 experience、role_summary、accept_note 中启发式抽取，标记 unverified=True。
    返回: (facts_dict, unverified_bool)
    """
    import re
    p = profile or PROFILE or {}
    if "greeting_facts" in p and isinstance(p["greeting_facts"], dict):
        facts = dict(p["greeting_facts"])
        c = facts.get("commitment") or {}
        facts["commitment"] = {
            "available_now": c.get("available_now", True),
            "months": c.get("months", 6),
            "days_per_week": c.get("days_per_week", 5),
        }
        return facts, False

    exp = p.get("experience") or ""
    role = p.get("role_summary") or ""
    accept = p.get("accept_note") or ""
    all_text = f"{exp} {role} {accept}"

    m_school = re.search(r'([\u4e00-\u9fa5]+(?:大学|学院|职业技术大学))', all_text)
    school = m_school.group(1) if m_school else ""

    m_grade = re.search(r'(\d{4}\s*届)', all_text)
    grade = m_grade.group(1) if m_grade else ""

    internships = []
    for m in re.finditer(r'([\u4e00-\u9fa5a-zA-Z0-9]+(?:实习|经历))', all_text):
        internships.append(m.group(1))

    awards = []
    for m in re.finditer(r'([\u4e00-\u9fa5a-zA-Z0-9]+(?:省[级一二三]等奖|国[一二三]|银奖|金奖|铜奖|证书|六级|四级|设计师))', all_text):
        awards.append(m.group(1))

    known_stacks = [
        "Java", "Spring Boot", "Spring Cloud", "Vue", "React", "Python", "Redis",
        "MySQL", "MyBatis", "MyBatis-Plus", "WebSocket", "JWT", "Docker", "Git",
        "Linux", "Claude Code", "Cursor", "AI 编程工具", "Next.js", "TypeScript"
    ]
    matched_stack = []
    for s in known_stacks:
        if re.search(r'\b' + re.escape(s) + r'\b', all_text, re.IGNORECASE):
            matched_stack.append(s)

    months = 6
    m_mo = re.search(r'(\d+)\s*个?月', all_text)
    if m_mo:
        months = int(m_mo.group(1))
    elif "半年" in all_text:
        months = 6

    days = 5
    m_day = re.search(r'每周\s*([0-9五5])\s*天', all_text)
    if m_day:
        d_val = m_day.group(1)
        days = 5 if d_val == "五" else int(d_val)

    avail = ("随时到岗" in all_text) or ("可随时" in all_text)

    facts = {
        "school": school or "在读高校",
        "grade": grade or "在读",
        "internships": internships,
        "awards": list(dict.fromkeys(awards)),
        "stack": matched_stack or ["Java", "Spring Boot", "MySQL"],
        "commitment": {
            "available_now": avail,
            "months": months,
            "days_per_week": days,
        }
    }
    return facts, True


def build_greeting_prompt(profile=None, job=None, jd_text=""):
    """按方法论原文与候选人事实生成打招呼语提示词（七层结构，严格顺序）。

    参数：
      profile : user_profile dict
      job     : 岗位 dict（title/company/salary/direction 等）
      jd_text : JD 正文
    """
    p = profile or PROFILE or {}
    job = job or {}
    facts, unverified = extract_greeting_facts(p)
    playbook = load_greeting_playbook()

    school = facts.get("school") or ""
    grade = facts.get("grade") or ""
    internships = "、".join(facts.get("internships") or []) or "（无）"
    awards = "、".join(facts.get("awards") or []) or "（无）"
    stack = "、".join(facts.get("stack") or []) or "（未列出）"
    cmt = facts.get("commitment") or {}
    avail_str = "可随时到岗" if cmt.get("available_now", True) else "协调后到岗"
    cmt_str = f"{avail_str}、连续实习 {cmt.get('months', 6)} 个月以上、每周出勤 {cmt.get('days_per_week', 5)} 天"

    unverified_note = "（注意：以上事实从 profile 启发式抽取，标注「未核实」，投递前请在 user_profile.json 中补充 greeting_facts 核准）\n" if unverified else ""

    title = job.get("title") or "（岗位未指定）"
    company = job.get("company") or "（公司未指定）"
    salary = job.get("salary") or "（薪资未指定）"
    direction = job.get("direction") or "通用"
    jd = (jd_text or job.get("detail") or "（未读取到 JD）").strip()

    prompt = f"""你在替一位候选人写 BOSS直聘 的打招呼语。只写这一条，不要寒暄、不要解释。

【唯一权威写法】以下原文逐条遵守，不得改换风格、不得漏掉其中任何一条规则：
{playbook}

【候选人可用事实（只能用这些，不许编）】
- 学校 / 届别：{school} / {grade}
- 实习：{internships}
- 奖项 / 证书：{awards}
- 技术栈：{stack}
- 到岗承诺：{cmt_str}
{unverified_note}
【本次岗位】
- {title}｜{company}｜{salary}｜{direction}
- JD 全文：
{jd}

【硬约束（脚本会逐条校验，违反即打回）】
1. 总长 ≤140 字符（含标点、换行）。
2. 首行 ≤18 字符，直接给最强证据；不要以「您好」「你好」「请问」「我对」「想应聘」开头。
3. 首行之后最多 4 行：匹配度 / 技术能力 → 高价值话术 → 收尾一句。
4. 技术名词最多 4 个，只留与 JD 直接对应的（按候选人技术栈白名单）。
5. 必含至少一条高价值话术：可随时到岗 / 连续实习 6 个月以上（或半年以上） / 每周出勤 5 天 / 抗压能力强，能适应快节奏开发环境。
6. 不复述 JD 原句；不写「贵公司现在还招人吗」「非常感兴趣，希望」「贵公司发展」这类招聘空话。
7. 不提简历里没有的公司、奖项、数字。文中「6 个月 / 5 天」等数字与候选人到岗承诺一致。
8. 前 6 字不与候选人已有默认招呼语重叠。
9. 方向（{direction}）与 JD 命中的技术栈不矛盾。

【示例（正例，来自本人模板）】
完整掌握后端技术体系，有 xxx 经验，可随时到岗、连续实习半年以上，每周出勤5天；抗压能力强，能适应快节奏开发环境
xx大学(211)在读，具备 xxx 实战经验，可随时到岗、连续实习半年以上，每周出勤5天；

【反例】熟悉Java并发编程，熟悉 SSM、SprintBoot、SpringCloud等框架，熟悉Redis、Rabbit MQ、Kafka 的使用（技术名词堆砌，HR 看不懂）

【输出】只输出严格的 JSON（不要 markdown 代码块以外的多余文字）：
{{"hook":"首行，≤18 字符","body":"剩余部分","text":"hook+\\n+body",
 "matched":["JD 技术词 → 我的对应证据"],"why":"为什么这个开头对这家公司最强"}}
text 的前 18 个字符必须正好等于 hook。"""

    return prompt

