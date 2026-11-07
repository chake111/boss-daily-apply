# BOSS直聘每日投递

**每天投 N 份对口实习，并且算得出这 N 份有没有用。**

不是点击器，是一套判断流程：探供给 → 按简历证据强度分配方向 → 一张一张读 JD → 语义终审
判该不该投 → 当场投 → 分批补发简历图和一句话 → 收尾出汇总页与回复台账。

[![License](https://img.shields.io/badge/license-MIT-2f7d5a?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776ab?style=flat-square)](https://www.python.org/)
![Deps](https://img.shields.io/badge/deps-stdlib_only-6b7280?style=flat-square)
![Chrome](https://img.shields.io/badge/chrome-not_required-0f766e?style=flat-square)

> **和具体工具无关**：`SKILL.md` 是技能定义，`scripts/` 是可执行的机械层，
> `references/` 是给人看的判定与踩坑手册。WorkBuddy、Claude Code、Cursor、Codex、
> 甚至纯终端都能用 —— 一个 Markdown 加一堆标准库脚本而已。

---

## 30 秒上手

```bash
git clone https://github.com/chake111/boss-daily-apply.git
cd boss-daily-apply

python scripts/onboard.py      # 向导：问信息 → 问装不装 → 装 → 扫码登录 → 写配置
```

向导只做五件事：问城市 / 届别 / 方向 / 简历位置 → **说清楚要装什么、多大、为什么，你点头才装**
→ 把 PDF 简历转成图（需要时问你）→ 起浏览器、等你扫码登录一次 → 写好配置，告诉你以后每天只做两件事。

想先看它打算干什么、不改任何东西：

```bash
python scripts/onboard.py --check
```

配置好之后，每天从这两条命令开始：

```bash
python scripts/supply_probe.py --rounds 40    # 今天投 40 份：够不够、各方向分几份
python scripts/_live_driver.py walk           # 开始逐张走卡
```

后面的判断由运行本技能的智能体完成。你在终端里自己跑、没有智能体，就照
[`references/judgment.md`](references/judgment.md) 的表格自己判 —— 流程一样。

<details>
<summary>不想用向导 / 让智能体自己跑</summary>

```bash
python scripts/install.py --list                  # 你的智能体该装哪
python scripts/install.py --target claude         # workbuddy / cursor / codex / plain
python scripts/bootstrap.py                       # 只建目录和配置，不装任何东西
python scripts/onboard.py --yes --city 深圳 --year 2027 \
    --direction "Java 后端开发实习" --resume "D:/简历.pdf"
python scripts/cdp_client.py --serve              # 起浏览器（后台常驻，别中途关）
python scripts/env_check.py                       # 浏览器 / 通道 / 登录态 / 页面结构
python scripts/selftest.py --no-browser           # 54 项自检，跳过真实点击
```

</details>

---

## 一天里到底发生了什么

| 步 | 做什么 | 命令 | 落盘 |
|---|---|---|---|
| 1 探供给 | 宽词 + `jobType=1902`，每词 page 1/2，比对新旧页 jobId 防「假翻页」 | `supply_probe.py --rounds N` | `supply.json` |
| 2 配比 | 按 `config/supply_mix.json` 把 N 份分到各方向，给出投放顺序 | 同上 | `supply.json` |
| 3 逐张判 | `walk` 只给一张卡 → `screen` 机械红线 → `open` 读完整 JD → 语义终审 | `_live_driver.py walk / open` | `walk_state.json` |
| 4 当场投 | 公司名必须取自右侧面板底部，短于 2 字或像岗位名一律不投 | `_live_driver.py deliver` | `stream_progress.json` |
| 5 补图补话 | 每满 5 份，补发简历长图 + 按方向的一句话 | `send_img2.py 5 --msg --same-tab` | `greeting_log.jsonl` |
| 6 收尾 | 对账缺口 → 决策看板 → 汇总页 → 当日台账 → 待我动作 | `daily_close.py` / `decide.py` / `phase_stream.py` / `ledger.py daily` | `决策看板.md` / `投递汇总.html` |

在 WorkBuddy 沙箱里，涉及浏览器的命令一律再加 `BOSS_BACKEND=cdp`（表格为可读性省略）。
每一步的分支、失败处置、汇报格式见 [`references/runbook.md`](references/runbook.md)。

---

## 为什么这样设计

**① 一次只判一张卡。**
批量抓 15 个 JD 再统一挑，看着快，实际会跳序、会漏判、会把「点开了 A 却记录了 B」。
所以 `walk` 每次只返回一张卡，判断和投递在同一个 live 页面态完成。

**② 代码里没有「该投 / 不该投」的规则。**
`screen.py` 只处理无歧义的机械红线（外包公司名、非技术岗标题、硬性届别）。
「这个岗到底对不对口」由智能体读完 JD 语义判断，依据是 `user_profile.json`。
好处是换个人、换个技术方向只改档案，代码一行不动。

但**换行业不是「只改档案」**：`blacklist.json` 的 `title_reject` 里有销售、运营、设计、
测试、教师、客服，`judgment.md` 的 APPROVE 也写着技术栈要求（Java / 前端 / Python / AI）。
一个教师岗进来会被 `screen.py` 直接判死——这是实测，不是推测。真要投别的行业，
得同时改 `blacklist.json` 和 `judgment.md`，那不是配置，是重新定判据。

**③ 投递结构按「证据强度」分配，不按「岗位多少」分配。**
这是整个仓库最重要的一条经验。AI 岗在 BOSS 上供给天然多，纯按「哪个词新卡多就投哪个」排序，
40 份里会有 20 份落在 AI 方向 —— 而简历里撑 AI 的可能只有一个项目。
**投得最猛的方向，恰好是证据最弱的方向。** 所以配额由 `config/supply_mix.json` 决定
（示例：前端 40% / Java 25% / AI 20% / 数据 5% / 其他 10%，按你自己的项目改）。

**④ 回复率必须带区间。**
「217 份 3 个回复，回复率 1%」和「5/40 = 12%」在统计上分不开 —— 前者 Wilson 95% 区间是 0–3%。
没有区间的回复率只能用来安慰自己，不能用来做决策。

---

## 装什么，能不能不装

**没有 Chrome 不是问题**：Edge（Windows 自带）、Brave、Vivaldi、Chromium 都支持 CDP，
而 CDP 是浏览器自带的调试协议，**一个扩展都不用装**。Firefox / Safari 没有 CDP，也装不了扩展，是硬限制。

| 你的情况 | 走哪条 | 怎么做 |
|---|---|---|
| 有任意 Chromium 浏览器，不想装扩展 | **CDP**（默认，推荐） | `python scripts/cdp_client.py --launch`，首次扫码登录一次 |
| 已经装了 Kimi WebBridge 扩展 | **WebBridge** | 起服务即可，脚本自动优先用它 |
| 只有终端、没有智能体 | 脚本模式 | 直接跑脚本，判断照 `judgment.md` 自己做 |
| 确实没有任何 Chromium 浏览器 | 手动记账 | `python scripts/ledger.py`，判断和统计照用 |

```bash
python scripts/browser.py --list          # 看看这台机器上有哪些 Chromium 系浏览器
python scripts/cdp_client.py --launch     # 带调试端口起一个，免扩展
```

三个后端在 `webbridge_client.py` 里统一路由，上层脚本调用方式完全一致。
**Playwright 只有显式 `BOSS_BACKEND=playwright` 才启用**；它在 WorkBuddy 沙箱里会连调试浏览器一起带走，
所以沙箱内一律 `BOSS_BACKEND=cdp` 并常驻 `--serve`：

```bash
python scripts/cdp_client.py --serve --url https://www.zhipin.com/web/geek/jobs
```

> Windows 上别用 `Start-Process` / `cmd start` 拉浏览器：1~2 分钟内会被会话回收，调试端口和扩展一起掉。
> 统一走 `browser.py` / `cdp_client.py`，它们用的是 `explorer.exe` 或 `DETACHED_PROCESS`。

Python 3.9+，**只用标准库，不需要 `pip install`**。完整环境矩阵见
[`references/portability.md`](references/portability.md)。

---

## 首次配置

向导已经把这些写好了；之后想细调（换城市、换话术）只改这两个文件：

| 文件 | 改什么 |
|---|---|
| `<工作目录>/user_profile.json` | 城市 + `city_code`、届别、技术栈、`role_summary`、`own_greeting_prefix` |
| `<工作目录>/config/greetings.json` | 四个方向各一句 40 字内的话术 + `generic` 兜底 |

改完先过两道检查，**全绿才开投**：

```bash
python scripts/env_check.py     # 环境四项：浏览器 / 通道 / 登录态 / 页面结构
python scripts/acceptance.py    # 配置验收 16 项：判据在你这份数据上会不会恒真
```

为什么要把「自检」和「验收」分开：`selftest.py` 管代码（54 项，含定位器 JS、点击兜底、词表健康、
一次 headless 点击），`acceptance.py` 管**你这份配置和台账**。曾经出现过兜底文案开头撞上账号默认招呼语，
导致 `already_msg` 恒真、每家都 `SKIP 已发全`，补发永久静默失效 —— 而 selftest 全绿、日志也正常。
代码没问题不代表配置没问题。

---

## 输出长什么样

开工先记基线，收尾再跑一次，两个数相减就是本轮成果：

```console
$ python scripts/ledger.py status
工作目录  ~/.boss-daily-apply
已投递    278 条（其中 61 条带时间戳）
已判否    422 条
今日已记  20 条
```

回复率报表刻意带区间，样本不足就直说：

```console
$ python scripts/stats.py
观测窗 72h
  已过窗   41 份 / 有回复 2  → 4.9%  (区间 1–16%)
  观察中   25 份（投出去不足 72h，不计入分母）
  无时间戳 217 份（旧记录，老口径，单独列）
  本批送达  66 份投递 → 有简历图 66 → 有话术 66
已写入 .../回复率报表.md
```

收尾还会生成 `投递汇总.html`（当天每家的公司/岗位/薪资/判定理由）和
`回复台账`（要简历 / 网申·测评 / 约面试，逐条可核对）。

---

## 目录

```
SKILL.md              技能定义（触发词 + 每日流程 + 硬停手条件）
config/
  user_profile.example.json   个人档案模板（AI 语义终审的唯一依据）
  supply_mix.json             方向配额 + 关键词表（决定投递结构）
  blacklist.json              机械否决库
  greetings.json              四个方向的一句话话术 + generic 兜底
scripts/
  _live_driver.py   walk / open / deliver / reject —— 唯一投递入口
  locators.py       页面定位器：每类元素多套策略 + 结构兜底 + 页面健康检查
  keyword_health.py 词表健康：连续两轮挖空的词自动跳过
  supply_probe.py   供给探测 + 按证据强度出配额（默认 jobType=1902）
  screen.py         机械否决
  send_img2.py      补发简历图 + 按方向一句话（CDP + --same-tab）
  daily_close.py    收尾对账：谁没送图 / 谁没发话术（只读，给逐条补发命令）
  acceptance.py     配置验收 16 项（selftest 管代码，它管配置）
  reply_check.py    扫会话 → 「待我动作」台账
  stage.py          进度台账：约面 / 一面 / 二面 / offer（会话里看不出来的那一段）
  decide.py         决策看板：转化链 + 断点 + 今日上限（看下一步用这个）
  stats.py          回复率报表（Wilson 95% 区间）
  phase_stream.py   收尾生成 投递汇总.html
  ledger.py         无浏览器模式：手动记账，报表口径不变
  onboard.py        首次使用向导（问信息 / 问是否装工具 / 装 / 登录 / 写配置）
  env_check.py      环境四项自检
  cdp_client.py     内置 CDP 后端 + 浏览器启动器（零安装兜底）
  playwright_backend.py  Playwright 后端（连调试端口，点击与上传交给库）
  browser.py        浏览器适配层（检测 / 启动，不限 Chrome）
  webbridge_client.py    后端路由 + 底层页面操作
  config_v3.py      档案加载、薪资解析、语义终审的 prompt 组装
  metrics.py        指标口径：公司名归一、事件匹配、Wilson 区间
  paths.py          路径解析（代码与状态分离）
  bootstrap.py      首次安装：建目录、拷配置、检查简历图
  install.py        装到 workbuddy / claude / cursor / codex，或纯文本用法
  cleanup.py        清临时产物（白名单，台账一律不碰）
  selftest.py       自检 54 项（含一次 headless 浏览器点击；--no-browser 跳过）
  send_img.py       内部库（旧补发入口已废弃，send_img2 复用其函数）
references/
  runbook.md        11 步完整执行细节 —— 遇到分支先查这里
  judgment.md       判定标准 + 22 条边界案例（唯一权威判定表）
  pitfalls.md       42 条踩坑（现象 → 根因 → 处置）
  metrics.md        回复率口径与 A/B 实验纪律
  portability.md    环境适配：没有 Chrome / 不用 WorkBuddy 怎么办
  dom_structure.md  BOSS 页面选择器实测对照表
```

---

## 关键机制

### `jobType=1902` 实习通道

BOSS 搜索页的 `&page=N` 有效，换页能拿到不同卡片，**完全绕开懒加载**。
但每个普通搜索词的结果集只有首屏 ~15 张，滚动到底也加载不出更多 —— 想要更多卡只能翻页；
想要实习卡，就加 `jobType=1902`（筛选栏会显示「求职类型(1)」）。
`1901` 曾被当成实习用过，**实测无效**（卡里混着 5-10 年社招）。

宽词（`前端` / `Java` / `后端` / `React` / `Vue` / `AI` / `全栈` / `Python`）+ `1902` + `page=1/2`
才是稳定的供给来源；「方向 + 实习」的长词在挖空之后基本只返回重复卡。
词表也会自动淘汰：连续两轮 fresh=0 的词直接跳过（`python scripts/keyword_health.py --reset 词` 可复位）。

### 分页绕开 `document.hidden`

Chromium 系浏览器有原生遮挡检测：窗口被完全盖住时 `document.hidden=true`，BOSS 的懒加载直接停住。
这时 `walk --more` 永远 `grew:false`，看起来「每页都到底了」。

**别去调窗口** —— `activate_tab` 只切标签不抬窗口，`ShowWindow` 被安全策略拦，点任务栏回来立刻又 hidden，
WebBridge 也没有 focus/raise 动作。`hidden=true` 不是停手理由，是走分页的信号。

### 代码与状态分离

脚本在技能目录（可被 git 覆盖），台账在工作目录（永不进版本库）：

| 环境变量 | 默认值 | 作用 |
|---|---|---|
| `BOSS_WORKDIR` | `~/.boss-daily-apply`（旧位置存在则自动沿用） | 所有状态文件 |
| `BOSS_CONFIG_DIR` | 依次找 `<工作目录>/config`、`<工作目录>`、`<技能目录>/config` | 配置覆盖 |
| `BOSS_PROFILE` | `<工作目录>/user_profile.json` | 个人档案 |
| `BOSS_RESUME_IMG` | `<工作目录>/resume/resume.png` | 简历图 |
| `BOSS_BROWSER` | 自动检测 | 指定浏览器可执行文件 |

多账号 / 多城市并行跑：给每个实例一个 `BOSS_WORKDIR` 即可。

> 早期默认是 `~/WorkBuddy/BOSS/boss-data`。该目录若存在会被继续使用，数据不会丢；
> 想迁到新默认位置见 [`references/portability.md`](references/portability.md)。

### 补发按记录寻址，不按公司名

同一家公司投了两个岗位时，按公司名反查会拿到后投的那条 —— AI 岗收到数据岗的话术。
所以定位一律用 `--job <jobId>`；定位不出来时脚本会 `BATCH_ABORT TARGET_AMBIGUOUS` 停批，而不是猜一个。
成功也只认「会话条数变多」（`IMG OK ... | 2->3 OK`），不认「点击返回 true」。

---

## 数据口径

| | 定义 |
|---|---|
| 分母 | 投递距今 ≥ 72h 的记录。不足 72h 的单列「观察中」，**不进分母** |
| 分子 | `reply_events.jsonl` 里能匹配到投递记录的公司；匹配不上记 `?哈希`，不算回复 |
| 算回复 | 要简历 / 网申·测评 / 约面试 / 对方说话 / 系统通知 |
| 不算回复 | 已读未回、我方最后发言、拒信 |
| 区间 | Wilson 95%；样本 < 30 时点估计不可用 |

**A/B 纪律**：简历图和招呼语是两个变量，同时改就分不清是谁的作用。
先跑图 A/B，两组 n 都过 30 再动招呼语，动之前先记基线。详见 [`references/metrics.md`](references/metrics.md)。

---

## 它不做什么

- **不代投别人的简历**，只跑你自己的账号。
- **不绕过风控**。日上限 150、连续失败熔断；一旦出现验证码、滑块、人脸核验，立刻停手交人工。
- **不批量抓 JD 再挑**。违反「一次一卡」，跳序和错记就是这么来的。
- **不猜公司名**。空的或截断的公司名会让补发命中会话列表第一条，把简历发给无关的人且撤不回。
- **不刷量**。宁可少投、投对口 —— 这也是用「证据强度配额」而不是「能投多少投多少」的原因。
- **不做社招**。默认 `jobType=1902` 只筛实习；社招要自己改通道并重写判据。

自动化投递会消耗 HR 的注意力。这个项目假设你愿意为此负责。

---

## 常见问题

| 问题 | 答案 |
|---|---|
| 一定要装 Chrome 吗 | 不用。Edge / Brave / Vivaldi / Chromium 都行；Firefox、Safari 不行 |
| 要 `pip install` 吗 | 不用，纯标准库。只有你主动选 Playwright 后端时才需要装它一个包 |
| 简历和台账会上传吗 | 不会。全部在本地 `<工作目录>`，且 `.gitignore` 掉 |
| 会不会把账号投废 | 内置日上限、熔断、验证码即停；但频率和合规风险最终由你判断 |
| 换城市 / 换届别 | 改 `user_profile.json`，或重跑 `onboard.py` |
| BOSS 改版了怎么办 | 先跑 `env_check.py` 看「页面结构」是否红灯，再去 `scripts/locators.py` 补一条策略，业务代码不动 |
| 能多账号并行吗 | 能，每个实例一个 `BOSS_WORKDIR` |
| 没有智能体能用吗 | 能，`ledger.py` 记账 + 手动判卡，报表口径完全一致 |

---

## 参考文档

| 文档 | 什么时候看 |
|---|---|
| [`runbook.md`](references/runbook.md) | 执行遇到分支，按 11 步逐步对照 |
| [`judgment.md`](references/judgment.md) | 判卡时唯一权威，含 22 条实测边界案例 |
| [`pitfalls.md`](references/pitfalls.md) | 出现怪现象先查这 42 条（现象 → 根因 → 处置） |
| [`metrics.md`](references/metrics.md) | 改简历图或话术前，先读 A/B 纪律 |
| [`portability.md`](references/portability.md) | 没有 Chrome、不想装东西、要迁移工作目录 |
| [`dom_structure.md`](references/dom_structure.md) | 平台改版后探测选择器 |

## License

MIT
