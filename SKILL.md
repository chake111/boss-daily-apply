---
name: boss-daily-apply
description: "BOSS直聘批量投递实习岗的完整流程：探供给、逐张读 JD 判方向、当场投递、补发简历图与按方向话术、出回复台账和回复率报表。用户在 BOSS直聘 上要批量投简历时使用——『投递』『今天投 N 份』『继续投』『BOSS 投简历』『看看回复』，或要按城市/方向/届别批量投实习岗。不用于改简历、写求职信、单个岗位咨询。Daily BOSS Zhipin batch application runbook."
agent_created: true
metadata:
  requires: "kimi-webbridge (127.0.0.1:10086), Python 3.9+"
  entrypoint: "scripts/_live_driver.py"
---

# BOSS直聘每日投递

一张一张地判、够了就停的投递流程。核心不是"投得多"，是**投得对口且能算出效果**。

> 约定：`$SKILL_DIR` = 本技能根目录（`SKILL.md` 所在目录）；
> `$BOSS_WORKDIR` = 工作目录，默认 `~/.boss-daily-apply`（旧位置 `~/WorkBuddy/BOSS/boss-data`
> 若存在则自动沿用），可用同名环境变量覆盖。
> 所有状态文件都在工作目录，**不要在技能目录里写任何运行时文件**。

## 首次使用（必须走向导，别让人手改 JSON）

判断标准只有一条：`<工作目录>/user_profile.json` 里有没有 `role_summary`。
没有就是首次使用，**先按下面四步走完，再谈投递**。

### 第 1 步：在对话里把信息问清楚（由你问，不要让用户去改文件）

一次问完，别一项一项挤牙膏：

1. **目标城市**（如 深圳；决定搜哪个城市）
2. **毕业年份**（如 2027；决定"只招 2026 届"这类要不要跳）
3. **想投什么岗位**（一句话，如「Java 后端开发实习 / 前端开发实习」——这是 AI 判岗的核心依据）
4. **简历文件在哪**（PNG/JPG 长图，或 PDF；没有就先跳过，但补发简历图会用）
5. 可选：**实习月薪下限**（不知道就 0）

拿到答案后跑向导，它会把信息写进档案、处理简历、按需装工具：

```bash
python "$SKILL_DIR/scripts/onboard.py" --yes \
  --city 深圳 --year 2027 --direction "Java 后端开发实习" \
  --resume "D:/我的简历.pdf"
```

### 第 2 步：装任何东西之前，先说清楚

向导会自己征求同意，但**你在对话里也要先说一遍**，格式照这个来：

> 要装 Playwright（Python 包，约 39MB，MIT 许可），用它驱动浏览器点投递。
> 只装包，不下载浏览器内核——直接用你系统里的 Edge/Chrome。
> 不想装也行，仓库自带内置方案，功能一样，只是点击稳定性略差。装吗？

**红线**：没说清楚"装什么 / 多大 / 为什么 / 装到哪 / 怎么卸载"之前，不许执行 `pip install`。

### 第 3 步：让他扫码登录一次

```bash
python "$SKILL_DIR/scripts/cdp_client.py" --serve        # 后台任务，保持运行
```

首次要在这个新窗口里扫码登录 BOSS直聘，登录态存在独立 profile 里，之后不用再登。

### 第 4 步：验证

```bash
python "$SKILL_DIR/scripts/env_check.py"
```

四项全绿即可开工（浏览器 / 自动化通道 / 登录态 / 页面结构）。有红的先按提示修，别硬上。

---

## 三条不可违背的原则

1. **一次只判一张卡**。`walk` 每次只给一张，禁止批量抓取整页再挑。判断与投递在同一个
   live 页面态完成——绝不先采集一批 JD 再统一决定。
2. **代码里没有"该投/不该投"的规则**。`screen.py` 只处理无歧义的机械红线（外包/猎头/
   非技术岗标题），方向是否对口由**运行本技能的智能体**读完 JD 后语义判断。
   判定依据全部来自 `user_profile.json`。
3. **除了 `deliver`，任何离开一张卡的动作前都要先 `reject`**。否则下一轮重扫会全部重判，
   而且合格率会虚高。

## 前置依赖

- **任意 Chromium 系浏览器**：Chrome / Edge（Windows 自带）/ Brave / Vivaldi / Chromium / Opera。
  **不要求 Chrome**；Firefox / Safari 没有 CDP，也装不了扩展，是硬限制。
- **自动化通道**：
  - **内置 CDP**（默认优先）：不装任何东西也能跑，点击逻辑自己实现，页面改版时可能需要更新。
  - **Playwright**（仅显式 `BOSS_BACKEND=playwright`）：普通终端可选用；WorkBuddy 沙箱禁用。
  - **WebBridge**：已有 Kimi WebBridge 扩展时，作为 CDP 不可用后的回退。
  - 三者都在 `webbridge_client` 里做了路由，上层脚本调用方式完全一致。
- Python 3.9+，只用标准库，无需 `pip install`。

### 环境不满足时（别卡在这里）

| 情况 | 处置 |
|---|---|
| 没装扩展 | **不是问题**：走 CDP，`cdp_client.py --launch`，照样自动点 |
| 只有 Edge | 同上，Edge 一样支持 CDP |
| 装不了任何 Chromium 浏览器 | 转 `python scripts/ledger.py` 手动记账；判断与报表照用 |
| 只有终端、没有智能体 | 直接跑脚本；JD 判定照 `references/judgment.md` 自己做 |

`ledger.py` 写的是和 driver **完全相同**的 schema，所以指标、报表、去重规则全部沿用。
完整的环境矩阵见 `references/portability.md`。

首次安装：

```bash
python "$SKILL_DIR/scripts/install.py" --list     # 你的智能体该装哪（workbuddy/claude/cursor/codex）
python "$SKILL_DIR/scripts/bootstrap.py"          # 建工作目录 + 拷配置 + 建 resume 目录
python "$SKILL_DIR/scripts/cdp_client.py" --launch  # 起带调试端口的浏览器（首次扫码登录）
python "$SKILL_DIR/scripts/env_check.py"          # 浏览器 / 通道 / 登录态自检
python "$SKILL_DIR/scripts/browser.py" --list     # 装了哪些浏览器、在不在跑
```

`bootstrap.py` 之后必须改两个文件：`<工作目录>/user_profile.json`（城市、届别、方向、
`own_greeting_prefix`）和 `<工作目录>/config/greetings.json`（四个方向的一句话）。

## 文件地图

```
scripts/
  _live_driver.py   walk / open / deliver / reject —— 唯一的投递入口
  locators.py       页面定位器组：详情面板/立即沟通/卡片/会话各给多套查找策略，
                    改版时只补一条策略，业务代码不动。含结构兜底与页面健康检查
  keyword_health.py 词表健康：连续两轮挖空的词自动跳过，不再重复扫同一批卡
  supply_probe.py   探供给，按证据强度出配额，写 supply.json（翻页未换内容会标 SAME）
  screen.py         机械否决（黑名单在 config/blacklist.json）
  send_followup.py  补发简历图 + 按方向一句话（WorkBuddy 用 CDP + --same-tab；第二标签实验性）
  send_img.py       兼容壳 → browser_ops.py（旧命令仍可用，2026-12-10 删除）
  send_img2.py      兼容壳 → send_followup.py（旧命令仍可用，2026-12-10 删除）
  render_resume.py  逐岗位定制：配置 -> 单页 PNG，文件名按 BOSS 的 80 字节上限裁剪
  apply_one.py      投一份并当场补发**这一份**的简历图（定制流程专用，见 references/per-job-tailoring.md）
  daily_close.py    收尾对账：谁还没送简历图 / 谁没发话术（只读，给逐条补发命令）
  acceptance.py     配置验收：判据在你真实配置下会不会恒真（开投前跑，16 项）
  reply_check.py    扫会话，出「待我动作」台账
  stage.py          进度台账：约面/一面/二面/offer——会话里看不出来的那一段
  decide.py         决策看板：转化链 + 断点 + 今日上限（看下一步用这个）
  stats.py          回复率报表（Wilson 95% 区间）
  phase_stream.py   收尾生成 投递汇总.html
  ledger.py         无浏览器模式：手动记账（schema 与 driver 一致）
  onboard.py        首次使用向导：问信息 / 问是否装工具 / 装 / 登录 / 写配置
  playwright_backend.py  Playwright 后端（连调试端口，点击与上传交给库）
  browser.py        浏览器适配层（检测 / 启动，不限 Chrome）
  cdp_client.py     内置 CDP 后端 + 浏览器启动器（零安装兜底）
  install.py        装到各智能体，或输出纯文本用法
  paths.py          路径解析（工作目录 / 配置 / 简历图）
  bootstrap.py      首次安装：建目录、拷配置、检查简历图
  selftest.py       自检 52 项（含定位器 JS、点击兜底、词表健康、headless 点击）
references/
  runbook.md        11 步完整执行细节 —— 遇到分支先查这里
  per-job-tailoring.md  逐岗位定制简历（全国投放）：城市码、命名、当场补发的完整循环
  pitfalls.md       26 条踩坑，照做即可
  metrics.md        回复率口径与 A/B 纪律
  judgment.md       判定标准 + 边界案例表
  portability.md    环境适配：没有 Chrome / 不用 WorkBuddy 怎么办
```

---

## 每日流程

### Step 0 · 开工三件事

```bash
cd "$BOSS_WORKDIR"      # 默认 ~/.boss-daily-apply，所有状态文件都在这
DRV="python $SKILL_DIR/scripts/_live_driver.py"
```

先记基线（收尾时再跑一次，两个数相减就是本轮成果）：

```bash
python "$SKILL_DIR/scripts/ledger.py" status
```

```
工作目录  ~/.boss-daily-apply
已投递    278 条（其中 61 条带时间戳）
已判否    422 条
今日已记  20 条
```

> 旧记录没有 `delivered_at`，所以"今日累计"不能数总数——以收尾时写入的
> `daily_log.json` 为准；`status` 里的"带时间戳"那一行就是能算进当日的部分。

### Step 1 · 环境自检（能自己修的一律自己修）

先确认自动化通道。**没有扩展不是问题**，CDP 这条路一样能自动点：

```bash
python "$SKILL_DIR/scripts/cdp_client.py" --check    # 端口已就绪就直接开工
```

没就绪就起一个。**注意用 `--serve` 并放进后台任务**，不要用前台 `--launch`：

```bash
python "$SKILL_DIR/scripts/cdp_client.py" --serve --url https://www.zhipin.com/web/geek/jobs
```

> 为什么必须 `--serve`：不少宿主（IDE / 智能体 / 沙箱）会在命令结束时回收整棵进程树，
> 单独 `Popen` 的浏览器会被一起杀掉，端口随即消失——表现是"刚启动就查不到"。
> `--serve` 留一个常驻父进程挡住回收。**这一轮投递期间它会一直跑着，别中途关掉。**
> 人自己在终端里跑，用 `--launch` 就够。

首次要在这个窗口里扫码登录一次 BOSS直聘，之后登录态存在独立 profile
（`<工作目录>/browser-profile`）里，长期有效。

有 WebBridge 扩展的，起一下服务即可，脚本会自动优先用它：

```bash
curl -s --noproxy '*' http://127.0.0.1:10086/status
"$HOME/.kimi-webbridge/bin/kimi-webbridge.exe" start --foreground
```

浏览器本身也可以先看一眼（**不要求 Chrome**，Edge / Brave / Vivaldi 都行）：

```bash
python "$SKILL_DIR/scripts/browser.py" --list
```

`env_check.py` 里「自动化通道」「登录态」「页面结构」三项都绿了才开工。
「页面结构」是 2026-11-06 加的：它按当前 DOM 检查还能不能找到详情面板、岗位卡片、
「立即沟通」按钮。BOSS 改一次版，这三样会一起静默失效——日志里只有满屏 SKIP、
没有任何错误，等逐张判卡才发现已经浪费十几分钟。这项红灯时去 `scripts/locators.py`
补一条选择器即可，不用改业务代码。只有这些才找人：两条通道都起不来、
没有任何 Chromium 浏览器、登录态要扫码、出现验证码/滑块/人脸、各试两轮仍不通。

再跑一次**配置验收**（不是环境，是判据本身）：

```bash
python "$SKILL_DIR/scripts/acceptance.py"
```

它拿你真实的 `greetings.json` 和真实台账，验证「补发判据不会恒真」——包括
每桶文案的指纹互不相同、不与账号默认招呼语重叠、同名公司多投不串档、对账只读幂等。
**16/16 才开投**。为什么单独有这一步：曾出现兜底文案开头撞上默认招呼语，导致
`already_msg` 恒真、每家都 `SKIP 已发全`，补发永久静默失效，而 `selftest` 全绿、日志也正常。
`selftest.py` 管代码，`acceptance.py` 管你这份配置和数据。

> **别再自己 spawn 浏览器**：Windows 上 `Start-Process` / `cmd start` 拉起的会在 1~2 分钟内
> 被会话回收，调试端口和扩展一起掉。统一用 `browser.py` / `cdp_client.py`。

> 连 Chromium 浏览器都没有（只能用 Firefox/Safari）→ 转 `python scripts/ledger.py`：
> 你在浏览器里自己投，脚本负责记账、去重和报表。判断标准与指标口径照用。

### Step 2 · 判 `document.hidden`（决定 A 路还是 B 路）

Chromium 系浏览器有原生遮挡检测：窗口被完全盖住时 `document.hidden=true`，BOSS 懒加载直接停住。
`hidden=true` **不是停手理由**，是走分页的信号。

- **A 路**（hidden=false）：`walk --more` 能滚到底，穷尽判据 = 连续两次 `grew:false`。
- **B 路**（hidden=true）：禁止用 `grew:false` 判词走完，改走 Step 3 分页。
  别浪费轮次去调窗口——`activate_tab` 只切标签不抬窗口，`ShowWindow` 被安全策略拦，
  点任务栏回来立刻又 hidden（实测均无效）。

### Step 3 · 探供给，按证据强度分配

```bash
python "$SKILL_DIR/scripts/supply_probe.py" --pages 2 --rounds <本次份数>
```

默认带 `jobType=1902`（求职类型=实习）。输出每个词的 fresh + 各方向「目标/可用/实投」+
**建议投放顺序**（每项带 `take` = 该词本轮最多投几份），写 `supply.json`。

为什么不是"按 fresh 降序投"：AI 岗供给天然多，纯按 fresh 排会让投递结构被最不缺人的方向
拉走，而简历里撑 AI 的证据往往是各方向里最弱的。配额在 `config/supply_mix.json`，
**先改这里再看数据**——它决定的是结构，比改文案影响大得多。

**供给见底的信号**：`walk --next` 连续 10+ 张都是"已判否-跳过" → 立刻切宽词 1902 通道
（`前端`→`Java`→`后端`→`React`→`Vue`→`AI`→`全栈`→`Python`，每词先 page=1 再 page=2），
不要在旧长词表上继续耗。

**词表会自动淘汰**：每轮探测的结果都记进 `keyword_health.json`，连续两轮 fresh=0 的词
下次开跑直接跳过（日志里会写「跳过 N 个已挖空的词」）。想强制重测某词加
`--include-exhausted`；误判用 `python scripts/keyword_health.py --reset 词` 清掉。
为什么需要：判否台账只用来跳过单张卡，从不反哺搜索策略，于是同一个词每天把同样的
15 张卡重判一遍，新增候选接近个位数——2026-11-06 实测三个词各 15 张，真正的新卡约 8 张。

**翻页会校验是否真的换了内容**：标签页在后台时，URL 里的 page 改了但列表可能不重新拉取，
第二页拿到的还是第一页那 15 张。旧逻辑会把它读成「翻页后 fresh=0」→ 提前收工，
凭空砍掉后面的候选。现在比对新旧两页的 jobId 集合，完全相同就标 `p2:SAME`，
并在输出里写明「翻页未换内容(只算第1页)」——这是前端的锅，不代表这个词没货。

#### 分页导航（B 路与 1902 通道都用这段）

```python
import sys, json, time, urllib.parse
sys.path.insert(0, r'<SKILL_DIR>')
from scripts.webbridge_client import navigate
from scripts import _live_driver as L

kw, page, jt, city = '前端', 1, '1902', '<你的 city_code>'
navigate(f"https://www.zhipin.com/web/geek/jobs?query={urllib.parse.quote(kw)}"
         f"&city={city}&page={page}&jobType={jt}", wait_range=(5, 7))
time.sleep(2)
st = json.load(open('walk_state.json', encoding='utf-8'))
st.update(keyword=kw, idx=0, last_jid='', kw_exhausted=False)
json.dump(st, open('walk_state.json', 'w', encoding='utf-8'), ensure_ascii=False)
L._present_next()
```

- 每个搜索词的结果集只有首屏 ~15 张，滚动到底也加载不出更多——**只有翻页能拿到更多卡**。
- `1902` 才是实习筛选，`1901` 实测无效（卡里混着 5-10 年社招）。
- **每 `deliver` 成功一次，必须重跑这段把 page/jobType 设回去**：投递弹窗会把页面带回搜索首页，
  而 `_present_next` 在 URL 漂走时会导航回不带参数的搜索首页——不重设就静默退回第 1 页且丢掉实习筛选。

### Step 4 · 逐张走卡

```bash
$DRV walk            # 推荐页起点，呈现下一张
$DRV open <jobId>    # 一次只开一张，读 JD
$DRV deliver <jobId> "<公司>" "<薪资>" "<行业>" "<方向>"
$DRV reject <jobId>
$DRV walk --next
```

每张卡的固定动作：

1. `screen.py --title "<标题>" --company "<公司>" --industry "<行业>"`
   - `REJECT` → 直接 `reject`，**别 open**
   - `REVIEW` → `open` 看一眼
   - `PASS` → `open` 读 JD
2. 读完 JD（连末尾 HR 活跃度一起读完，别 head 截断）→ 判定是否 APPROVE：
   - 若 REJECT / 表面不沾边 → `$DRV reject <jobId>`。
   - 若 APPROVE → **当场生成该岗位定制打招呼语（核心）**：
     - 执行 `python "$SKILL_DIR/scripts/greeting.py" prompt --job <jobId>` 获取组装好的完整提示词；
     - 智能体按方法论原文与事实白名单编写这一条专属话术（≤140字符，首行≤18且无套话）；
     - 执行 `python "$SKILL_DIR/scripts/greeting.py" save --job <jobId> --text "..."` 执行 12 条机器硬指标校验并落盘；
     - 校验打回时按改法提示削减字数或微调词句；若因特殊原因未通过，允许 `--force` 保存或直接投递退回通用桶（会在日志与汇报中标记）。
3. 投递：`$DRV deliver <jobId> "<公司>" "<薪资>" "<行业>" "<方向>"`
   （驱动会自动检查是否存在定制话术并记入台账 `greeting_src`；未定制会打出 `NOTE 未定制，补发将用方向桶`）。
4. **公司名只出现在 `open` 之后的右侧面板底部**（`公司名 · HR头衔`）。
   不足 2 字、像岗位名、或被截断的，**一律不许 deliver**——空串会让补发脚本命中会话列表第一条，
   把简历发给无关的人且撤不回。
5. 投满即停，不多投。每投满 5 份停下来补一次图与话术（Step 6）。

判定标准见 `references/judgment.md`，边界案例表照抄即可，别临场纠结。

### Step 5 · 失败处置（别自己发明）

| 返回 | 动作 |
|---|---|
| `panel_ok: false` | 不重试同一张，`walk --next`，记异常 1 次 |
| `delivered_ok: false` + reason 含 panel | 同上 |
| `delivered_ok: false` + reason 含弹窗/验证码 | **立刻整批停手** |
| 同一 jid 连续 2 次失败 | `reject` 掉它，继续下一张 |
| 连续 3 次失败 | 停手交人工 |

### Step 6 · 分批补发简历图 + 一句话

```bash
BOSS_BACKEND=cdp python "$SKILL_DIR/scripts/send_followup.py" 5 --msg --same-tab  # 每满 5 份跑一次
BOSS_BACKEND=cdp python "$SKILL_DIR/scripts/send_followup.py" 2 --msg --same-tab  # 收尾补剩余
BOSS_BACKEND=cdp python "$SKILL_DIR/scripts/send_followup.py" 1 "公司短名" --msg --same-tab
BOSS_BACKEND=cdp python "$SKILL_DIR/scripts/send_followup.py" --job <jobId> --msg --auto-img --same-tab
BOSS_BACKEND=cdp python "$SKILL_DIR/scripts/send_followup.py" --pending --msg --auto-img --same-tab
BOSS_BACKEND=cdp python "$SKILL_DIR/scripts/send_followup.py" --pending --include-legacy --msg --auto-img --same-tab
```

- **`--pending` 从最旧的积压开始补**（不是台账最新几条），可断点续跑；`--pending` + 数字可以
  一批批推进。没有 `delivered_at` 的历史记录默认不算积压（会打印 `NOTE 跳过 N 条`），
  确实要回溯老岗位才加 `--include-legacy`（pitfalls #35）。
- **同公司多岗位定位不出来时会停批**：输出 `BATCH_ABORT TARGET_AMBIGUOUS`，说明两条会话
  一样像（例如都叫「【实习】…」）。此时改用 `--job <jobId>` 精确寻址，**不要**靠改公司名重试
  （pitfalls #36）。

- **在 WorkBuddy 沙箱里跑一律加 `BOSS_BACKEND=cdp` 和 `--same-tab`**：
  playwright 后端在本沙箱会让调试浏览器整体退出（pitfalls #32）。
- 第二标签（不传 `--same-tab`，session `boss-img`）**暂停使用 / 实验性**：
  它可能拿不到登录态并落到 passport 校验页；真实补发不得新建第二标签。
- 主循环前预检失败会输出 `BATCH_ABORT BROWSER_DEAD / LOGIN_REQUIRED / LIST_NOT_READY`
  并非零退出；只有真正 `NOT_FOUND` 才是公司级 SKIP。登录/验证出现时不得重试或绕过。
- **按记录寻址，不按公司名**：同一家投了两个岗位时，用 `--job <jobId>` 才不会串档
  （按公司反查会拿到后投的那条，AI 岗收到数据岗的话术）。
- **话术优先取该岗位的定制文件**：`send_followup.py` 优先查找 `<工作目录>/greetings/<jobId>.json`，
  取到即发送专用定制话术（`src=jd`）；取不到才按 `direction` 映射到 `greetings.json` 的方向桶（`src=direction`）。
  方向没标或标了 `其他` 的走 `generic` 兜底。
  去重采用首 18 字与末 12 字双锚点指纹比对，杜绝定制文案重复补发或漏发。
- **成功只认「会话条数变多」**（`IMG OK ... | 2->3 OK`）。`NOT_SENT` 就是没发出去；
  但先看会话列表预览有没有 `[图片]`——后台标签重渲染会让计数读到 0，详情见 `pitfalls.md` #15。
- 每家处理完立即写一行 `greeting_log.jsonl`（`img_ok` / `msg_ok` / `status` 三态），
  中途中断也只丢当前这一家。**这张表是唯一的话术证据**，`img_mode_log` 只是选图决策。
- `SKIP 标题不符` → 等 20 秒重试一次（列表渲染延迟），再不行用短名补。

### Step 7 · 收尾

先对账，再出决策，最后出汇总页：

```bash
python "$SKILL_DIR/scripts/daily_close.py"                # 只读，默认退出码 0
python "$SKILL_DIR/scripts/decide.py" --target <本轮份数>  # 转化链 + 断点 + 今日上限
python "$SKILL_DIR/scripts/phase_stream.py" --mode report --workdir "$BOSS_WORKDIR"
```

`decide.py` 把「投递 → 回复 → 推进 → 约面 → offer」连成一条链，指出**最窄的那一段**，
再给出今天实际投得出去几份（新卡上界 × 历史合格率）。`stats.py` 回答"回复率多少"，
它回答"下一步干什么"——收尾时**两个都要看，先看 decide**。

**它的结论优先于用户的份数**：算出的上限低于用户要的份数时（池子只给得出 20 份、用户说投 40），
按 20 报并说明原因（`--target 40` 就是用来做这个对比的）。反过来，上限够、断点却在回复之后时，
加量没有意义，要直说。

`daily_close.py` 会列出「投了但没送简历图 / 没发话术」的记录，并给出逐条可复制的
`send_followup.py --job <jobId>` 命令。**把缺口清单原样贴给用户**，让他决定当场补还是明天补——
它不是门禁（`--strict` 才会在有缺口时退出 1）。只读、不碰浏览器,重跑结果一致。

然后打开 `$BOSS_WORKDIR/投递汇总.html`：能预览 HTML 的工具就预览，
否则用系统默认程序打开（`start` / `open` / `xdg-open`），或者直接把绝对路径给用户。
再记一笔当日台账，"今日累计"以它为唯一口径：

```bash
python "$SKILL_DIR/scripts/ledger.py" daily --n <本轮份数>
```

清掉本轮自己建的临时脚本；`stream_progress.json` / `walk_state.json` / `reply_log.json` 不许动。

### Step 8 · 回复应答

```bash
PYTHONPATH="$SKILL_DIR" python "$SKILL_DIR/scripts/reply_check.py"
```

输出「待我动作」清单（要简历 / 网申·测评 / 约面试），**逐条写进汇报**。
待办是台账不是快照：`--list` 看全部、`--resolve <id>` 关掉。
**`reply_check.py` 只读不发**——`kind=要简历` 的还得另跑 `send_followup.py 1 "<短名>" --msg`。

约到面试就立刻记一站，否则漏斗永远停在「待我动作」，`decide.py` 也就永远算不出断点：

```bash
python "$SKILL_DIR/scripts/stage.py" log "公司" 约面 --note "周四 15:00 腾讯会议"
python "$SKILL_DIR/scripts/stage.py" list
```

阶段只有 `约面 / 一面 / 二面 / 终面 / offer / 拒 / 失联` 七种，写别的会被拒并列出可选值。
同岗位同阶段重复记不会重复计数（幂等）。

每周跑一次 `stats.py` 出 `回复率报表.md`（含 Wilson 95% 区间）。
每组 n < 30 就写"样本不足"，别拿小样本比高低。

---

## 变体 · 逐岗位定制简历（用户要求「按 JD 改简历再投」时）

默认流程用 `resume/{variant}.png` 的固定变体图批量投、批量补发。用户要求逐岗位
定制时，改走下面这条，两处关键差异是**当场补发**和**图与岗一一对应**。

```bash
python scripts/_live_driver.py walk --next                  # 呈现下一张
python scripts/_live_driver.py open <jobId>                 # 读 JD
python scripts/render_resume.py --config job.json --jobtitle 全栈开发实习生
python scripts/apply_one.py --jid <jobId> --company <公司> --salary <薪资> \
    --industry <行业> --direction 全栈开发 --jobtitle 全栈开发实习生 --img <上一步的 png>
```

- 全国投放的城市码是 `100010000`（少一个 0 会静默零结果），`target_city` 写「全国」。
- 附件名限 **80 字节**（中文 3 字节/字），`render_resume.py` 按 姓名-岗位-学校-手机号 自动裁。
- 投完必须重新导航回带 `city` 与 `jobType=1902` 的关键词页再 `walk --next`。
- 溢出（退出码 3）先删内容，别把裁过的简历发出去。

完整循环、失败处置与和默认流程的对照表见 `references/per-job-tailoring.md`。

## 硬停手条件（遇到任一立刻停，绝不绕过）

- 未知弹窗、验证码、滑块、人脸核验
- 平台风控 / 异常登录提示
- A 路下列表空、`walk --more` 连续两次 `grew:false` 且页面没有"到底了"文案
- 连续 3 次投递失败
- 扩展连续掉线，重启浏览器两轮仍连不上

`document.hidden` **不在**停手条件里——走分页兜底。

## 汇报格式

```
本次投递：X 份（合格率 X%）
关键跳过原因：…
异常：hidden 状态 / 哪些词走了分页、扫到第几页 / 有没有只扫到首屏的词
今日累计：X 份（口径：daily_log.json 求和）
供给：哪些词已空、fresh 还剩几张、各方向「目标/实投」差多少
断点：哪一段最窄、下一步做什么（照 decide.py 的结论写，别自己总结）
待我动作：要简历 / 网申 / 约面，逐条列
```

细节表格（公司/岗位/薪资/理由）+ 三块单列：值得破例的、有回复的 HR、供给情况。

## 节奏

日上限 150；单轮份数听用户给的数，但要用 `decide.py` 算的供给上界封顶。当日累计过 130 提醒一次。

一轮合格率低于 40% 说明**这批词不对口**，先换词——不等于没货：实测合格率 39.3% 时，
27 个宽词仍有 177 张新卡。供给真的空了的信号是 `keyword_health` 里连续两轮 `fresh=0`，
以及 `walk --next` 连续 10+ 张「已判否-跳过」。
