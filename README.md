# BOSS直聘每日投递 · Skill

把"每天投 N 份实习岗"从体力活变成一条可复现、可度量的流水线。

不是点击器，是一套**判断流程**：先探供给 → 按简历证据强度分配方向 → 一张一张读 JD →
语义终审判该不该投 → 当场投 → 分批补发简历图和一句话 → 收尾出汇总页和回复台账。

> **和具体工具无关**：`SKILL.md` 是技能定义，`scripts/` 是可执行的机械层，
> `references/` 是给人看的判定与踩坑手册。WorkBuddy、Claude Code、Cursor、Codex、
> 甚至纯终端都能用 —— 一个 markdown + 一堆标准库脚本而已。

---

## 先看这里：你需要什么

**两条自动化通道，都能自动翻页、自动点投递、自动补发简历图：**

| 你的情况 | 走哪条 | 怎么做 |
|---|---|---|
| 有任意 Chromium 浏览器（Edge 就算），不想装扩展 | **CDP**（推荐） | `python scripts/cdp_client.py --launch`，首次扫码登录一次 |
| 已经装了 Kimi WebBridge 扩展 | **WebBridge** | 起服务即可，脚本自动优先用它 |
| 只有终端，没有智能体 | 脚本模式 | 直接跑脚本，判断照 `judgment.md` 自己做 |
| 一个 Chromium 浏览器都没有（只能用 Firefox） | 手动记账 | `python scripts/ledger.py`，判断和统计照用 |

**没有 Chrome 不是问题**：Edge（Windows 自带）、Brave、Vivaldi、Chromium 都支持。
CDP 是浏览器自带的调试协议，**一个扩展都不用装**。

```bash
python scripts/browser.py --list       # 看看你机器上有哪些 Chromium 系浏览器
python scripts/cdp_client.py --launch  # 带调试端口起一个，免扩展
```

完整的环境选项见 **[references/portability.md](references/portability.md)**。

---

## 为什么这样设计

**① 一次只判一张卡。**
批量抓 15 个 JD 再统一挑，看着快，实际会跳序、会漏判、会把"点开了 A 却记录了 B"。
所以 `walk` 每次只返回一张卡，判断和投递在同一个 live 页面态完成。

**② 代码里没有"该投/不该投"的规则。**
`screen.py` 只处理无歧义的机械红线（外包公司名、非技术岗标题、硬性届别）。
"这个岗到底对不对口"由智能体读完 JD 语义判断，依据是 `user_profile.json`。
好处是换个人、换个行业（司机、教师、运营）只改档案，代码一行不动。

**③ 投递结构按"证据强度"分配，不按"岗位多少"分配。**
这是整个仓库最重要的一条经验。AI 岗位在 BOSS 上供给天然多，纯按"哪个词新卡多就投哪个"
排序，40 份里会有 20 份落在 AI 方向 —— 而简历里撑 AI 的可能只有一个项目。
**投得最猛的方向，恰好是证据最弱的方向。** 所以配额由 `config/supply_mix.json` 决定
（前端 40% / Java 25% / AI 20% / 数据 5% / 其他 10%，按你自己的项目改）。

**④ 回复率必须带区间。**
"217 份 3 个回复，回复率 1%" 和 "5/40 = 12%" 在统计上分不开 ——
前者 Wilson 95% 区间是 0–3%。没有区间的回复率只能用来安慰自己，不能用来做决策。

---

## 快速开始

```bash
git clone https://github.com/chake111/boss-daily-apply.git
cd boss-daily-apply
python scripts/selftest.py                    # 27 项自检，含一次真浏览器点击（--no-browser 跳过）
python scripts/install.py --list              # 你的智能体该装哪
python scripts/install.py --target claude     # 或 workbuddy / cursor / codex / plain
python scripts/bootstrap.py                   # 建工作目录、拷配置、建 resume 目录
python scripts/cdp_client.py --serve          # 起浏览器（免扩展），首次扫码登录一次；
                                              # 智能体里请丢到后台任务，否则进程树会被回收
python scripts/env_check.py                   # 浏览器 / 通道 / 登录态 三条自检
```

装好后改两个文件（默认工作目录 `~/.boss-daily-apply`，从旧版本升级会自动沿用旧目录）：

| 文件 | 改什么 |
|---|---|
| `<工作目录>/user_profile.json` | 城市+city_code、届别、技术栈、`role_summary`、`own_greeting_prefix` |
| `<工作目录>/config/greetings.json` | 四个方向各一句 40 字内的话术 |

把简历长图放到 `<工作目录>/resume/resume.png`，然后：

```bash
python scripts/supply_probe.py --rounds 20        # 探供给，出配额
python scripts/_live_driver.py walk               # 开始逐张走卡
python scripts/send_img2.py 5 --msg               # 每投满 5 份补一次图
python scripts/phase_stream.py --mode report --workdir "$BOSS_WORKDIR"
```

没装扩展？把上面第三条换成 `python scripts/ledger.py`，其余照旧。

---

## 前置依赖

- **任意 Chromium 系浏览器**（Chrome / Edge / Brave / Vivaldi / Chromium / Opera）。
  **不要求 Chrome**。
- **自动化通道，二选一**：
  - **CDP**（默认推荐）：浏览器自带的调试协议，`cdp_client.py --launch` 即可，**零扩展**。
  - **WebBridge**：Kimi WebBridge 扩展 + 本地服务（端口 10086），已有就自动优先用。
  - 都不能用 CDP 直连内置浏览器——拿不到你的登录态。
- Python 3.9+，**只用标准库**，不需要 `pip install`。
- Windows 上浏览器要用 `explorer.exe '<路径>'` 或 `DETACHED_PROCESS` 拉起
  （`browser.py` / `cdp_client.py` 已经这么做）：`Start-Process` / `cmd start`
  会在 1~2 分钟内被会话回收。

---

## 目录

```
SKILL.md              技能定义（触发词 + 每日流程 + 硬停手条件）
config/
  user_profile.example.json   个人档案模板（AI 语义终审的唯一依据）
  supply_mix.json             方向配额 + 关键词表（决定投递结构）
  blacklist.json              机械否决库
  greetings.json              四个方向的一句话话术
scripts/
  _live_driver.py   walk / open / deliver / reject —— 唯一投递入口
  supply_probe.py   供给探测 + 配额分配（默认 jobType=1902 实习筛选）
  screen.py         机械否决
  send_img2.py      补发简历图 + 话术（第二个标签，不打断搜索页）
  reply_check.py    扫会话 → 「待我动作」台账
  stats.py          回复率报表（Wilson 95% 区间）
  phase_stream.py   收尾生成 投递汇总.html
  ledger.py         无浏览器模式：手动记账，报表口径不受影响
  browser.py        浏览器适配层（检测 / 启动，不限 Chrome）
  cdp_client.py     CDP 后端：免扩展的自动化通道（手写 WebSocket，零依赖）
  install.py        装到 workbuddy / claude / cursor / codex，或纯文本用法
  paths.py          路径解析（代码与状态分离）
  bootstrap.py      首次安装：建目录、拷配置、检查简历图
  selftest.py       自检 27 项（含一次 headless 浏览器点击；--no-browser 跳过）
references/
  runbook.md        11 步完整执行细节
  judgment.md       判定标准 + 23 条边界案例
  pitfalls.md       25 条踩坑（现象 → 根因 → 处置）
  metrics.md        回复率口径与 A/B 实验纪律
  portability.md    环境适配：没有 Chrome / 不用 WorkBuddy 怎么办
  dom_structure.md  BOSS 页面选择器实测对照表
```

---

## 关键机制

### `jobType=1902` 实习通道

BOSS 搜索页的 `&page=N` 有效，换页能拿到不同卡片，**完全绕开懒加载**。
但每个普通搜索词的结果集只有首屏 ~15 张，滚动到底也加载不出更多 —— 想要更多卡只能翻页；
想要实习卡，就加 `jobType=1902`（筛选栏会显示"求职类型(1)"）。
`1901` 曾被当成实习用过，**实测无效**（卡里混着 5-10 年社招）。

宽词（`前端`/`Java`/`后端`/`React`/`Vue`/`AI`/`全栈`/`Python`）+ `1902` + `page=1/2`
才是稳定的供给来源；"方向+实习"的长词在挖空之后基本只返回重复卡。

### 分页绕开 `document.hidden`

Chromium 系浏览器有原生遮挡检测：窗口被完全盖住时 `document.hidden=true`，BOSS 的懒加载直接停住。
这时 `walk --more` 永远 `grew:false`，看起来"每页都到底了"。
**别去调窗口**（`activate_tab` 只切标签不抬窗口，`ShowWindow` 被安全策略拦，点任务栏回来立刻又 hidden，
WebBridge 也没有 focus/raise 动作）—— 直接走分页。

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
> 想迁到新默认位置见 [references/portability.md](references/portability.md)。

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
先跑图 A/B，两组 n 都过 30 再动招呼语，动之前先记基线。详见 `references/metrics.md`。

---

## 使用边界

- 只用于**你自己账号**的求职投递。不要拿它跑别人的账号、不要做简历代投。
- 遵守平台规则与频率限制：脚本内置日上限 150、连续失败熔断、验证码/风控立即停手。
  一旦出现验证码、滑块、人脸核验，**停下来人工处理**，不要尝试绕过。
- 自动化投递会消耗 HR 的注意力。宁可少投、投对口，也不要为了数字刷量 ——
  这也是本项目用"证据强度配额"而不是"能投多少投多少"的原因。
- 平台 DOM 会变。选择器都集中在 `webbridge_client.py` / `phase_stream.py`，
  改版后先按 `references/dom_structure.md` 探测再改，别猜。

## License

MIT
