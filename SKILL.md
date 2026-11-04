---
name: boss-daily-apply
description: "BOSS直聘每日批量投递 runbook：探供给→按证据强度配比→逐张走卡读 JD→AI 语义终审→当场投递→分批补发简历图与按方向话术→收尾出汇总页与回复台账。含 jobType=1902 实习通道、分页绕懒加载、机械否决库、Wilson 区间回复率报表。当用户说『投递』『今天投 N 份』『继续投』『BOSS 投简历』『看看回复』，或要在 BOSS直聘 上按城市/方向/届别批量投实习岗时使用。依赖 Kimi WebBridge（127.0.0.1:10086）驱动已登录的 Chromium 系浏览器（Chrome/Edge/Brave 均可，不要求 Chrome），不可用 CDP 或内置浏览器替代；没有浏览器扩展时可用 ledger.py 半自动记账。Daily BOSS Zhipin job-application runbook — supply probing, evidence-weighted allocation, one-card-at-a-time JD review, semantic gating, on-the-spot apply, staged resume-image follow-ups, and a Wilson-interval reply report."
version: 3.0.0
agent_created: true
metadata:
  requires: "kimi-webbridge (127.0.0.1:10086), Python 3.9+"
  entrypoint: "scripts/_live_driver.py"
---

# BOSS直聘每日投递 v3

一张一张地判、够了就停的投递流程。核心不是"投得多"，是**投得对口且能算出效果**。

> 约定：`$SKILL_DIR` = 本技能根目录（`SKILL.md` 所在目录）；
> `$BOSS_WORKDIR` = 工作目录，默认 `~/WorkBuddy/BOSS/boss-data`，可用同名环境变量覆盖。
> 所有状态文件都在工作目录，**不要在技能目录里写任何运行时文件**。

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
  **不要求 Chrome**；Firefox / Safari 装不了 WebBridge 扩展，是硬限制。
- **Kimi WebBridge**，本地端口 `10086`，控制一台**已登录 BOSS直聘**的浏览器。
  **不可**用 CDP 直连 / 内置浏览器接管——会丢登录态。桥连不上就修桥，别换工具。
- Python 3.9+，只用标准库，无需 `pip install`。

### 环境不满足时（别卡在这里）

这个 skill 的价值一半在判断表，一半在自动化。**没有桥也能用后半段**：

| 情况 | 降级方案 |
|---|---|
| 装不了扩展（公司电脑 / 权限受限） | `python scripts/ledger.py add ...` 手动记账；`stats.py` 照常出报表 |
| 只有终端、没有智能体 | 直接跑脚本；JD 判定照 `references/judgment.md` 自己做 |
| 浏览器 / 平台不支持 WebBridge | 同上，全流程转半自动 |

`ledger.py` 写的是和 driver **完全相同**的 schema，所以指标、报表、去重规则全部沿用。
完整的环境矩阵见 `references/portability.md`。

首次安装：

```bash
python "$SKILL_DIR/scripts/install.py" --list     # 你的智能体该装哪（workbuddy/claude/cursor/codex）
python "$SKILL_DIR/scripts/bootstrap.py"          # 建工作目录 + 拷配置 + 建 resume 目录
python "$SKILL_DIR/scripts/env_check.py"          # 浏览器 / WebBridge / 登录态自检
python "$SKILL_DIR/scripts/browser.py" --list     # 装了哪些浏览器、在不在跑
```

`bootstrap.py` 之后必须改两个文件：`<工作目录>/user_profile.json`（城市、届别、方向、
`own_greeting_prefix`）和 `<工作目录>/config/greetings.json`（四个方向的一句话）。

## 文件地图

```
scripts/
  _live_driver.py   walk / open / deliver / reject —— 唯一的投递入口
  supply_probe.py   探供给，按证据强度出配额，写 supply.json
  screen.py         机械否决（黑名单在 config/blacklist.json）
  send_img2.py      补发简历图 + 按方向一句话（第二个标签，不打断搜索页）
  reply_check.py    扫会话，出「待我动作」台账
  stats.py          回复率报表（Wilson 95% 区间）
  phase_stream.py   收尾生成 投递汇总.html
  ledger.py         无浏览器模式：手动记账（schema 与 driver 一致）
  browser.py        浏览器适配层（检测 / 启动，不限 Chrome）
  install.py        装到各智能体，或输出纯文本用法
  paths.py          路径解析（工作目录 / 配置 / 简历图）
  bootstrap.py      首次安装：建目录、拷配置、检查简历图
  selftest.py       离线自检（不碰浏览器、不碰真实台账）—— 改完代码先跑它
references/
  runbook.md        11 步完整执行细节 —— 遇到分支先查这里
  pitfalls.md       22 条踩坑，照做即可
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

先看浏览器在不在（**不要求 Chrome**，Edge / Brave / Vivaldi 都行）：

```bash
python "$SKILL_DIR/scripts/browser.py" --list     # 装了哪些、在不在跑
python "$SKILL_DIR/scripts/browser.py" --launch   # 默认挑"正在运行"的那个
```

再探桥：

```bash
curl -s --noproxy '*' http://127.0.0.1:10086/status
```

连不上就起服务（后台任务）：`"$HOME/.kimi-webbridge/bin/kimi-webbridge.exe" start --foreground`，
等 5 秒重探。启动浏览器**必须走 `browser.py`**（它用 `explorer.exe` / `open -a` / `xdg-open`）——
自己 `Start-Process` / `cmd start` 拉起的会在 1~2 分钟内被会话回收，扩展跟着掉线。

`extension_connected` 连续 3 次为 true 才开工。只有这些才找人：WebBridge 缺文件/版本不匹配、
扩展被禁用、没有可用的 Chromium 浏览器、登录态要扫码、出现验证码/滑块/人脸、
上述步骤各试两轮仍不通。

> 桥或扩展怎么都装不上（公司电脑、Firefox、无权限）→ **不要卡在环境上**。
> 转 `python scripts/ledger.py` 半自动模式：你在浏览器里自己投，脚本负责记账、去重和报表。
> 判断标准、指标口径、A/B 纪律全都照用，功能只少"自动点击"这一块。

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
2. 读完 JD（连末尾 HR 活跃度一起读完，别 head 截断）→ 三选一：`deliver` / `reject` / 表面不沾边也要 `reject`
3. **公司名只出现在 `open` 之后的右侧面板底部**（`公司名 · HR头衔`）。
   不足 2 字、像岗位名、或被截断的，**一律不许 deliver**——空串会让补发脚本命中会话列表第一条，
   把简历发给无关的人且撤不回。
4. 投满即停，不多投。每投满 5 份停下来补一次图（Step 6）。

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
python "$SKILL_DIR/scripts/send_img2.py" 5 --msg          # 每满 5 份跑一次
python "$SKILL_DIR/scripts/send_img2.py" 2 --msg          # 收尾补剩余
python "$SKILL_DIR/scripts/send_img2.py" 1 "公司短名" --msg  # 只补某一家
```

- 自动用第二个标签（session `boss-img`），搜索页和游标不受影响。
- 话术按 `direction` 映射到 `greetings.json` 的桶；**`keyword` 不参与匹配**（那是搜索词，不是岗位属性）。
- **成功只认「会话条数变多」**（`IMG OK ... | 2->3 OK`）。`NOT_SENT` 就是没发出去；
  但先看会话列表预览有没有 `[图片]`——后台标签重渲染会让计数读到 0，详情见 `pitfalls.md` #15。
- `SKIP 标题不符` → 等 20 秒重试一次（列表渲染延迟），再不行用短名补。

### Step 7 · 收尾

```bash
python "$SKILL_DIR/scripts/phase_stream.py" --mode report --workdir "$BOSS_WORKDIR"
```

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
**`reply_check.py` 只读不发**——`kind=要简历` 的还得另跑 `send_img2.py 1 "<短名>" --msg`。

每周跑一次 `stats.py` 出 `回复率报表.md`（含 Wilson 95% 区间）。
每组 n < 30 就写"样本不足"，别拿小样本比高低。

---

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
待我动作：要简历 / 网申 / 约面，逐条列
```

细节表格（公司/岗位/薪资/理由）+ 三块单列：值得破例的、有回复的 HR、供给情况。

## 节奏

日上限 150；单轮份数只看用户给的数，别自己加量。当日累计过 130 提醒一次。
一轮合格率低于 40% 说明供给见底，收工并告诉用户该换哪个关键词。
