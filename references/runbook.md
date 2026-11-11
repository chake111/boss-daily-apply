# 每日投递手册（完整版）

> 这份是 11 步主流程的完整执行细节。`SKILL.md` 是索引，遇到具体分支回这里查。
> 文中 `$SKILL_DIR` = 技能根目录，`$BOSS_WORKDIR` = 工作目录（默认 `~/.boss-daily-apply`；
> 若旧位置 `~/WorkBuddy/BOSS/boss-data` 存在则自动沿用）。
> 开工会话第一件事就是确定这两个值，切错目录会出现「我设了游标但脚本读不到」。

**手册覆盖的关键流程**：`jobType=1902` 实习筛选通道（第 3 步）、
供给见底的判定信号与处置（第 3.5 步）、deliver 后必须重新导航（第 3/4 步）、
判定标准补边界案例（第 5 步）、补发 SKIP/NOT_SENT 的处置（第 8 步）、
收尾命令带 `PYTHONPATH`（第 10/11 步）。

---

## 第 0 步 · 开工三件事

**① 切工作目录**（所有状态文件都在这里）：

```bash
cd "$BOSS_WORKDIR"     # 默认 ~/.boss-daily-apply（旧位置存在则沿用）
```

**② 记基线**：`stream_progress.json` 里只有**新记录**才有 `delivered_at`，旧记录没有。
所以"今日累计"不能靠数总数：

```bash
python "$SKILL_DIR/scripts/ledger.py" status
```

```
工作目录  ~/.boss-daily-apply
已投递    278 条（其中 61 条带时间戳）
已判否    422 条
今日已记  20 条
          （217 条旧记录无时间戳，不计入今日）
```

- 本轮新增投递 = 收尾时「已投递」− 开工时「已投递」
- 本轮新增判否 = 收尾时「已判否」− 开工时「已判否」
- 合格率 = 新增投递 ÷（新增投递 + 新增判否）
- 今日累计：**以第 10 步写入的 `daily_log.json` 求和为准**；「今日已记」只覆盖带
  `delivered_at` 的记录，旧数据算不进去（那行括注就是这部分，别硬凑）

**③ 命令入口**——全文的 `walk / open / deliver / reject` 都是同一个脚本的子命令：

```bash
DRV="python $SKILL_DIR/scripts/_live_driver.py"
$DRV walk                  # 默认起点：推荐页，呈现下一张卡
$DRV walk --next           # 推进一张
$DRV walk --more           # 滚动加载后再呈现下一张
$DRV walk "<关键词>"        # 切关键词（要求 walk_state.recommend_exhausted=true）
$DRV open <jobId>          # 一次只开一张，读 JD
$DRV deliver <jobId> "<公司>" "<薪资>" "<行业>" "<方向>"   # 参数顺序固定，全部加引号
$DRV reject <jobId>        # 判否留痕
```

---

## 第 1 步 · 环境自检

能自己修的一律自己修，别回来汇报修了什么。只有第 4 小节列的几种情况才允许停下来问人。

### 1) 探自动化通道

两条都能全自动，任选其一。**没有扩展就用 CDP**，别以为必须装扩展：

```bash
python "$SKILL_DIR/scripts/cdp_client.py" --check     # CDP 就绪？
```

没就绪 → **用 `--serve` 放后台任务**（不是前台 `--launch`）：

```bash
python "$SKILL_DIR/scripts/cdp_client.py" --serve --url https://www.zhipin.com/web/geek/jobs
```

**为什么必须 `--serve`**：很多宿主会在命令结束时回收整棵进程树，单独 spawn 的浏览器
会被一起杀掉、端口消失，表现成"刚启动就查不到"。`--serve` 留一个常驻父进程挡住回收。
这一轮投递期间它要一直跑着。人在终端里手动用时 `--launch` 即可。

```bash
curl -s --noproxy '*' http://127.0.0.1:10086/status  # 有 WebBridge 扩展就顺手看一眼
"$HOME/.kimi-webbridge/bin/kimi-webbridge.exe" start --foreground
```

`webbridge_client` 会自动选通道（WebBridge 优先，否则 CDP），上层命令完全一致。
用 `BOSS_BACKEND=cdp|webbridge` 可强制指定。

### 2) 看浏览器

**不要求 Chrome**：Edge（Windows 自带）/ Brave / Vivaldi / Chromium / Opera 都能装 WebBridge。
Firefox / Safari 装不了扩展，是硬限制。

```bash
python "$SKILL_DIR/scripts/browser.py" --list      # 装了哪些、在不在跑
python "$SKILL_DIR/scripts/browser.py" --launch    # 默认挑"正在运行"的那个拉起
python "$SKILL_DIR/scripts/browser.py" --launch edge
```

没开 → **用 `browser.py --launch`，别自己 spawn**。它按平台走
`explorer.exe` / `open -a` / `xdg-open`，把进程交给桌面 shell 托管。

启动方式的血泪史（别再试别的）：

- ❌ bash 里直接 `explorer.exe "..."`：静默无反应，进程不会出现（实测两次）
- ❌ `cmd //c start "" "chrome.exe"` / `Start-Process`：能起来，但 1~2 分钟内被会话回收、扩展跟着掉
- ✅ 走桌面 shell（explorer / open -a / xdg-open）：能活，扩展稳定

开了但扩展不连 → 正常关掉浏览器（**不要强杀**）后按上面重启一次。
Windows 上卸干净可用 `taskkill //IM chrome.exe`（不带 `/F`），Edge 换成 `msedge.exe`。

### 3) 等 12 秒再判

- **CDP 通道**：`cdp_client.py --check` 能列出标签页就算就绪（启动后端口需要几秒才监听）。
- **WebBridge 通道**：首次探测常为 false，`/status` 里 `extension_connected`
  **连续 3 次为 true** 才开工；中途掉线（`extension_not_connected`）等 10 秒重探，
  不行重启浏览器，属"能自己修"。

### 4) 只有这些才找人（都涉及下载/安装/人肉操作）

- **两条通道都起不来**（`cdp_client --launch` 失败 且 WebBridge 服务不可用）
- **没有任何 Chromium 系浏览器**（此时转 `ledger.py`，别硬装）
- 浏览器不支持 `--remote-debugging-port`（版本太旧），且扩展也装不上
- 登录态失效要扫码（这个必须人来）
- 出现验证码、滑块、人脸核验
- 上面 1~3 步各试两轮仍然起不来

---

## 第 2 步 · 前台状态 `document.hidden`

决定后面走 A 路还是 B 路。

```python
import sys; sys.path.insert(0, r'<SKILL_DIR>')
from scripts.webbridge_client import api, evaluate
tabs = api('list_tabs', {})['data']['tabs']
z = [t for t in tabs if 'zhipin.com' in (t.get('url') or '')]
if not z:                       # 刚重启过 Chrome 时可能一个 BOSS 标签都没有，先建一个
    api('navigate', {'url': 'https://www.zhipin.com/web/geek/jobs?ka=header-jobs'}, session='boss-main')
    tabs = api('list_tabs', {})['data']['tabs']
    z = [t for t in tabs if 'zhipin.com' in (t.get('url') or '')]
assert z, '没有可用的 BOSS 标签页，且自动新建失败 —— 按「扩展异常」上报'
api('activate_tab', {'tabId': z[0]['tabId']})
print(evaluate('document.hidden'), evaluate('document.visibilityState'))
```

**为什么会 hidden**：Chrome 有原生遮挡检测——窗口只要被别的窗口完全盖住
（哪怕标签是 active、哪怕手动点过任务栏），`document.hidden` 就是 true。
BOSS 搜索页在 hidden 状态下懒加载会停住、`walk --more` 永远 `grew:false`，
于是"没加载"被误判成"这个词走空了"。

- **A 路（hidden=false）**：正常走，`walk --more` 能滚到底，穷尽判据 = 连续两次 `grew:false`。
- **B 路（hidden=true 且修不回来）**：**不要死磕窗口**，改走分页（第 3 步）。
  以下尝试都不必再重复：
  - `activate_tab` 只能切标签，**不能把最小化/被遮挡的窗口调到前台**（实测连续激活 6 次，hidden 全程 true）
  - 别用 PowerShell `Add-Type` / `ShowWindow`：安全策略直接拦编译调用；
    最小化窗口 `GetWindowRect` 只有 158x26，按尺寸过滤找不到主窗口
  - 别让用户去点任务栏的 Chrome：前台一失去，Chrome 立刻又 hidden（实测两次无效）
  - WebBridge 没有 focus_window / activate_window / raise_window 这类动作，试了也是 `Unknown tool`

**结论：hidden 不作为"停下来找人"的理由，也不作为"判定走空"的前提**——有分页兜底，自己解决。

---

## 第 3 步 · 分页行走 + 实习筛选（核心供给通道，A/B 路通用）

BOSS 搜索页的 `&page=N` 参数有效，换页会拿到不同的卡片，**完全绕开懒加载**。每页约 15~17 张。

**每个普通搜索词的结果集其实只有首屏 ~15 张，滚动到底也加载不出更多**（实测连滚 4 次、
卡片数恒为 15）——想要更多卡，唯一的办法就是翻页；想要实习卡，就加 `jobType=1902`。

```python
import sys, json, time, urllib.parse
sys.path.insert(0, r'<SKILL_DIR>')
from scripts.webbridge_client import api, evaluate, navigate
from scripts import _live_driver as L

kw, page, jt = '前端', 1, '1902'   # jt 固定 1902 = 求职类型"实习"
navigate(f"https://www.zhipin.com/web/geek/jobs?query={urllib.parse.quote(kw)}&city={CITY_CODE}&page={page}&jobType={jt}",
         wait_range=(5, 7))
time.sleep(2)
st = json.load(open('walk_state.json', encoding='utf-8'))
st.update(keyword=kw, idx=0, last_jid='', kw_exhausted=False)
json.dump(st, open('walk_state.json', 'w', encoding='utf-8'), ensure_ascii=False)
L._present_next()                        # 只呈现"下一张卡"，然后照常走
```

**`jobType=1902` 是实测出来的关键**：

- `1902` = 求职类型「实习」，筛选生效时页面筛选栏会显示"求职类型(1)"，出来的全是实习岗；
- `1901` 曾被当成实习用过，**实测无效**（筛选栏虽显示已选，但卡里混着 5-10 年社招）——别再用；
- 挖空后的通用词照样能用：`前端`、`Java`、`后端`、`React`、`Vue`、`AI`、`全栈`、`Python`
  这类宽词 + `1902` + `page=1/2`，单组合 15 张、翻页再 15 张，够撑起一轮；
- `jobType=1902` 下仍会混入"AI 漫剧/编剧/数据标注/翻译/产品经理"等内容岗，
  靠第 5 步判定和机械黑名单筛掉。

之后照常 `walk --next` / `open <jid>` / `deliver` / `reject`，动作和 A 路一样，但**穷尽判据不同**：

- **B 路禁止用 `grew:false` 判"这个词走完了"**。hidden 状态下懒加载本来就不触发，
  `grew` 永远是 false，用它会得出"每页都到底了"的错误结论。
- B 路的正确判据只有一条：**逐页把 fresh 投/判到 0，且连续两页 fresh 都是 0**，才换词。
- **每 `deliver` 成功一次，必须重跑上面的代码块、把 `page` 设回当前页**。
  因为投递弹窗会把页面带回推荐页/搜索首页，而 `_present_next` 在 URL 漂走时
  会导航回**不带 page 也不带 jobType 参数**的搜索首页——不重设不仅会静默退回第 1 页，
  还会**丢掉实习筛选**，出来的全是社招卡。
- BOSS 每次请求结果集都会重排/补位，同一个 `page` 两次加载的卡可能不同，
  所以"这页没新卡"要**同一个 page 连测两次**再判空。

---

## 第 3.5 步 · 先探供给，再决定怎么走

开工先跑一次：

```bash
python $SKILL_DIR/scripts/supply_probe.py --pages 2 --rounds <本次份数>
```

它按词表逐个翻页（默认带 `jobType=1902`），统计"没投过、没判否过"的新卡（fresh），
然后**按目标结构分配份数**，写 `supply.json`。

**为什么不是「按 fresh 降序投」**：AI 岗位在 BOSS 上供给天然多，纯按 fresh 排会让投递结构
被 AI 拉走。实测 40 份里 AI 占 20 份（50%），但简历里撑 AI 的只有 1 个项目、
撑数据的只有 1 次竞赛——投得最猛的方向恰好是证据最弱的方向。所以按「证据强度」定权重
（`config/supply_mix.json`）：

| 方向 | 目标 | 依据（示例，按你自己的项目改） |
|---|---|---|
| 前端开发 | 40% | 3 个项目里 2 个是 Vue 3 全栈 |
| Java 后端 | 25% | 2 个 Spring Boot 项目 |
| AI 应用开发 | 20% | 1 个 Next.js 项目 |
| 数据开发 | 5% | 只有竞赛集群部署，无生产数据工程 |
| 其他（全栈 / 软件 / Node / Go） | 10% | |

输出长这样：

```
本轮目标 40 份，按证据强度分配（不是按 fresh 多少）：
  方向            目标   可用   实投
  前端开发          16     29     17
  Java后端         10     10     10
  ...
建议投放顺序：
  1) 前端开发实习      前端开发   投 5 份（可用 8）
  2) Java实习        Java后端   投 4 份（可用 4）
```

- **按「建议投放顺序」投**，括号前的份数是这个词本轮最多投几份，投满换下一个词
- 某方向可用 fresh 不够时，缺口自动回补给还有货的方向，不用手动调
- 列表里的"已挖空"就是下轮别再花时间的词
- 全部 fresh 总和 < 本次目标份数 → 直接告诉用户"供给不足"，不要降标准凑数
- 结果集每次请求会重排，fresh=0 只作参考，实际仍以 `walk` 的呈现为准
- **供给见底的实操信号**：`walk --next` 连续 10+ 张全是 `auto_skipped` 的"已判否-跳过"——
  此时**立刻切第 3 步的 1902 通道**（`前端`→`Java`→`后端`→`React`→`Vue`→`AI`→`全栈`→`Python`，
  每个先 page=1 再 page=2），不要在旧长词表上继续耗。1902 通道也挖空了，才算真的供给不足。

---

## 第 4 步 · 投递流程

1. 看 `walk_state.json`：`recommend_exhausted=true` 就直接进关键词；`false` 才走推荐页
   （`walk` 无参 → `walk --more` 滚到底，逐条判读后再进关键词）。
2. 关键词顺序**以 `supply.json` 的 `plan` 为准**（`plan` 已按配额排好，每项带 `take` = 该词最多投几份）。
   下面这个固定列表只是 `supply_probe.py` 跑不起来时的兜底顺序（已按同一套权重排好，不再是 AI 打头）：
   `前端开发实习` → `Java实习` → `AI应用开发实习` → `前端开发实习生` → `后端开发实习`
   → `React前端实习` → `Java开发实习` → `Vue实习` → `AI应用开发` → `Agent开发实习` → `软件开发实习`
   > 注意别用 `React实习` 这种短词：BOSS 是全文匹配，实测搜出来的是 go实习生 / 移动端实习生 /
   > python实习生，fresh 看着多但对口率低。词要带「前端/开发实习」这类限定。
3. 每个词内部：`walk` → **先跑机械否决**
   `python $SKILL_DIR/scripts/screen.py --title "<标题>" --company "<公司>" --industry "<行业>"`：
   - `REJECT`（命中硬红线，会列出原因）→ 直接 `reject <jid>`，**别 open**
   - `REVIEW`（仿真/多模态/管培生这类模糊词）→ 值得 `open` 看一眼
   - `PASS` → `open <jid>` 读 JD
   一张一张走，不许批量抓。
   可以写临时脚本把「标题含黑名单词」的卡批量 reject+next，**但有时序约束**：
   - 先把**当前呈现的这张卡判完**（投或拒），再跑批量脚本——脚本是从下一张开始扫的，
     当前卡不判就直接跑会把它无声跳过（实测两次，都得回头补判）；
   - 脚本只做"标题黑名单 → reject"这一件事，等于 `screen.py` 的自动化，不代替读 JD 判定。用完删掉。
4. **公司名从哪来**：`walk` 呈现的卡片只有 `jobId/title/salary/city/industry`，**没有公司名**。
   公司名在 `open` 之后右侧面板底部那行（`公司名 · HR头衔`），例如「某某软件 · 人事经理」。
   `deliver` 的第二个参数就填它。
   **硬校验**：公司名不足 2 个字、或明显是岗位名/HR 名，一律不许 `deliver`——留空的后果是
   补发图时 `open_conv` 用空串匹配，会命中会话列表第一条，把简历发给完全无关的 HR，且撤不回。
   投完立刻回读 `stream_progress.json` 最后一条，`company` 为空就停手并记为异常，禁止进入第 8 步。
   卡片上公司名**被截断**（如「某市某区某某…」）的同样不许投——截断名过不了硬校验，
   而且这类"一句话 JD + 中专可投"的小作坊岗质量可疑，直接 reject。
5. **判定只有三个出口，离开一张卡之前必须落到其中一个**：
   - APPROVE → `deliver <jid> "<公司>" "<薪资>" "<行业>" "<方向>"`
   - REJECT（`screen` 判否，或读完 JD 判否）→ `reject <jid>`
   - 表面就不沾边、连 screen 都不用跑 → **也要 `reject <jid>`** 再 `walk --next`
   总则：**除了 deliver，任何"离开这张卡"的动作前都要先 `reject`**。否则下一轮从顶部重扫时
   会全部再判一遍，而且第 0 步的"新增判否"会少算、合格率虚高。
6. `deliver` 后游标回顶、靠去重往后找，属正常，别以为卡住了；**也别重复裸 `walk`**（会把游标推回顶部）。
7. 读 JD **一次看全**——连末尾那行 HR 活跃度一起读完再判，别 head 截断后重开。
8. `deliver` 参数**全部加引号**（公司名常带括号和中文符号，如「某某(中国)」）。
9. **失败怎么处置**（别自己发明，按下表）：

   | 返回 | 含义 | 动作 |
   |---|---|---|
   | `panel_ok: false` | 右侧面板没切到目标岗位 | 不重试同一张，`walk --next` 取下一张，记异常 1 次 |
   | `delivered_ok: false` 且 reason 含 panel | 同上，没点中 | 同上 |
   | `delivered_ok: false` 且 reason 含弹窗/验证码 | 未知弹窗或风控 | **立刻整批停手**（第 9 步） |
   | 同一 jid 连续 2 次失败 | 卡片状态异常 | `reject` 掉它，记异常，继续下一张 |
   | 连续 3 次投递失败 | 环境异常 | 停手交人工 |

10. 一个词走完（A 路：`view_exhausted` 且连续两次 `grew:false`；B 路：分页 fresh 连测两页为 0）再换下一个。
11. 投满立刻收手，不多投。
12. **每投满 5 份，停手 30 秒补一次图 + 一句话**（见第 8 步）。补发走第二个标签，
    `boss-main` 的搜索页和游标都不动，回来直接 `walk --next` 继续。
    别攒到整批结束——HR 是收到招呼的当下才有印象。

---

## 第 5 步 · 判定标准

完整判定表（APPROVE 条件 / REJECT 清单 / 23 条边界案例 / 同公司规则 / 公司名硬校验）
统一维护在 **`references/judgment.md`**，改规则只改那一个文件，这里不复述以免两处不一致。

开工前必读的三个要点：

1. **三个出口，一个都不能漏**：APPROVE → `deliver`；REJECT → `reject`；
   表面就不沾边（连 `screen.py` 都不用跑）→ **也要 `reject`** 再 `walk --next`。
2. **`screen.py` 只管机械红线**，方向是否对口由你读完 JD 语义判断。
   `REVIEW` 不等于拒，是"值得 open 看一眼"。
3. **HR 活跃度是刷掉最多的一类**：在线 / 今日 / 3 日内 / 本周 / 本月 / 2 周内 / 3 月内 可投；
   4 月内 / 5 月内 / 半年前 直接拒；"2月内"落在可投档。价值极高的岗位也不自作主张投，
   写进"值得破例"等人拍板。

---

## 第 6 步 · 同公司规则

- 同一岗位换 HR 重复发帖 → 只投一次（按"公司+岗位名"去重）
- 同一公司不同岗位 → 本轮最多 2 个，超了跳过
- 往轮已投过的公司 → 不再投；除非方向完全不同且特别对口，在汇报里单列等人拍板

---

## 第 7 步 · 留痕

每投一份记：公司 / 岗位 / 薪资 / 一句话理由。判否的也留痕（`reject` 写进 `walk_state`），
汇报时按大类归纳即可，不用逐条列。

---

## 第 8 步 · 简历图 + 一句话（分批补发，走第二个标签）

本次投递过程中**分批补发**，不要攒到整批结束：

- 图片：`<工作目录>/resume/resume.png`（或用 `BOSS_RESUME_IMG` 指定）
- **换成按 JD 定制的图**：加 `--auto-img`（`python scripts/send_followup.py 5 --msg --auto-img`）。
  脚本按公司名哈希分 A/B：A 组按 `direction` 查 `resume/variants.json` 现场渲染定制图，
  B 组照旧发通用图；实际发了哪种写进 `img_mode_log.json`，`stats.py` 的「按简历图（A/B）」表直接读它。
  分组是固定哈希，同一家公司永远同组，重发不会跨组。只想临时指一张图用 `--img <路径>`。
- **节奏**：每投满 5 份跑一次 `python scripts/send_followup.py 5 --msg`；
  收尾再把剩余不足 5 份的补齐（例：投了 17 份 → 5 + 5 + 5 + 2）
- **它自己会用第二个标签**（session `boss-img`）做补发，搜索页和游标不受影响；
  万一第二标签起不来，加 `--same-tab` 退回旧行为（会抢占当前标签，之后要重新定位关键词页）
- **打招呼语生成与选桶顺序**：
  ① 优先查找 `<工作目录>/greetings/<jobId>.json`：读完 JD 后由智能体通过 `greeting.py prompt` 组装并经 `greeting.py save` 校验落盘的定制专属话术（`src=jd`）；
  ② 取不到定制时退回 `greetings.json` 方向桶映射（`src=direction`）：先看 `direction_map` 映射；
  ③ 没标的才退回 title + 公司名加权打分；
  ④ 全 0 走 `default`（退至 generic）。
  **定制生成失败处置**：
  - 超长或首行超限：按校验报错削减副词和形容词，直接给核心标签与到岗承诺；
  - 撞默认招呼语：调整首句前 6 字，避免判重恒真；
  - 确实无法生成或网络异常：放行投递，自动退回方向桶，并在对账中显式记录未定制缺口。
- 同一家公司投了两个岗位时共用一个会话，只能发一句话，按**最后一次投递**的 direction 取桶。
- 只想看匹配结果不动手：`python scripts/send_followup.py 5 --msg --dry`
- 图已是最后一条会跳过发图只补话术；图 + 话术都发过会整体跳过，**不会重复发**
- **判定成功只认「会话条数变多」**（输出形如 `IMG OK 841773 | 2->3 OK`）。
  出现 `NOT_SENT` / `图未入库` 就是没发出去，别当成功，记进异常——按「图片张数」判会被历史旧图骗成成功。
- 脚本会自己把补发标签切到前台（后台标签上传会静默失败），不需要手动点。
- **不要再用 `serve_img.py` + 页面 fetch**：新版 Chrome 的「本地网络访问」权限会直接拦掉，
  页面里报 `TypeError: Failed to fetch`；补 `Access-Control-Allow-Private-Network` 预检头也无效
  （实测 17 条全 FAIL）。
- **份数就是「本次要补几家」**：分批时写 5，收尾写剩下的（别照抄第一行）
- 会话列表只渲染最近 ~40 条，最早的会 `SKIP notfound`：改用公司短名逐个补，
  `python scripts/send_followup.py 1 "某短名" --msg`
- **`SKIP 标题不符`**（会话标题显示的是 HR 名而不是公司名）：**先等 20 秒重试一次**——
  刚投的会话在列表里渲染有延迟，实测第一次 SKIP、20 秒后重试即成功；再不行才用短名补。
- **`img 0->0 NOT_SENT` 但怀疑已发出**：直接用短名重跑 `send_followup.py 1 "短名"`，
  脚本会检测"会话里已有我发的图"自动跳过发图、只补话术，不会重复发（实测有效）。
- 同一公司两个岗位共用一个会话，报"已发过"是正常的，不用重发
- 进会话前核对右侧标题栏的公司+岗位，对不上就跳过并报告
- 发图失败先报告，别卡在发图上
- 若 `send_followup.py` 不在，按这个逻辑重建：读文件 → base64 → 每 12 万字符一段
  `evaluate("window.__b64+='...'")` → 页面内 `atob` 转 `Uint8Array` →
  `new File([blob],'resume.png',{type:'image/png'})` → 塞进 `.btn-sendimg input[type=file]` →
  派发 `change` 事件。

---

## 第 9 步 · 硬停手条件 · 遇到任一立刻停，绝不自行绕过

- 未知弹窗、验证码、滑块验证、人脸核验
- 平台风控/异常登录提示
- **A 路（hidden=false）下**：列表空、`walk --more` 连续两次 `grew:false` 且页面没有"到底了"文案
  → 说明结构变了，停手
- 连续 3 次投递失败
- 扩展连续掉线，且重启浏览器两轮仍连不上

（`document.hidden` 不在停手条件里——走第 3 步分页兜底；B 路列表只有 15~17 张、
`grew` 恒为 false 都属正常，不要据此停手。）

---

## 第 10 步 · 收尾

1. 生成汇总页：

   ```bash
   python $SKILL_DIR/scripts/phase_stream.py --mode report --workdir "$BOSS_WORKDIR"
   ```

   然后打开 `$BOSS_WORKDIR/投递汇总.html`（能预览 HTML 就预览，
   否则用系统默认程序打开，或把绝对路径给用户）。

2. 按第 0 步基线算：本轮份数、新增判否、合格率。再记一笔当日台账，这样"今日累计"不用猜：

   ```bash
   python "$SKILL_DIR/scripts/ledger.py" daily --n <本轮份数>
   ```

   输出会给出今日明细和累计。汇报里的"今日累计"以这个数为准
   （`delivered_at` 只覆盖加了字段之后的记录，旧数据不能算）。

3. **本流程不启动任何后台服务**（`serve_img.py` 已废弃，不在链路里）；
   也要**清掉本轮自己新建的临时脚本**——只清你自己这次写的（如 `tmp_*.py`）。
   `stream_progress.json`、`walk_state.json`、`reply_log.json` **不许动、不许清空**。

4. **别把 `phase_stream.py --mode verify` 的"未找到"当投递失败依据**——它按标题匹配当前会话列表，
   一次能列上百条噪音。只认 `deliver` 返回的 `delivered_ok` / `verify`。

5. 想看"有回复的 HR"，去会话列表读最近 20~25 条的最后一条：是我方「送达+图片」就算没回复；
   出现对方文字或「对方已同意，您的附件简历已发送」算有进展。读完回推荐页，别停在聊天页。

6. 每周（或每 3 轮）跑一次 `stats.py` 生成 `回复率报表.md`：按来源关键词 / 薪资形态 /
   投递方向 / 简历图（A/B）/ 行业分组算回复率，**每组都带 Wilson 95% 区间**。
   **这是唯一能把"哪种岗位值得投"从猜测变成数据的动作**，报表里的结论直接写进下一轮的关键词顺序。
   - 默认 72h 观察窗；`--window 24` 改窗，`--strict` 只算已过窗的
   - 看完先确认样本：每组的 n 不到 30 就别改关键词顺序，只在汇报里写"样本不足"
   - 「按简历图（A/B）」这张表就是定制简历的对照组，别只看总回复率

---

## 第 11 步 · 回复应答（投递不是终点）

投完必跑（**必须带 `PYTHONPATH`**，裸跑会报 `ModuleNotFoundError: No module named 'scripts'`）：

```bash
PYTHONPATH="$SKILL_DIR" python $SKILL_DIR/scripts/reply_check.py
```

- 输出「待我动作」清单（要简历 / 网申·测评 / 约面试），**逐条写进汇报**，由用户处理
- 待办是**台账**，不是每次现扫：`python scripts/reply_check.py --list` 看全部未处理项
  （包括已经滑出会话列表的老的），用户处理完的用 `--resolve <id>` 关掉。
  **别用重扫来"清"待办**——会话列表只渲染最近 ~40 条，早的会直接消失，
  重扫只会把它从视野里抹掉，不会变成"已处理"
- 抓会话要连 WebBridge；桥没起来时会直接报错，此时用 `--list` 看台账、
  `--from <dump>` 回放上次结果都还能用
- **`reply_check.py` 只读不发**：清单里 `kind=要简历` 的，要另跑
  `python scripts/send_followup.py 1 "<公司短名>" --msg` 才会真发
  （脚本对已发过的会输出 `SKIP 已发全`，属正常）。别以为跑完 reply_check 图就补了。
- 「已拒」归档即可，不用回
- 「已读未回」不催，催了容易被投诉/限流

口径（**以 `stats.py` 为准，别在汇报里另算一套**）：

- 分母 = 投递距今 ≥ 72h 的记录；不足 72h 的单列「观察中」，**不进分母**
  （刚投出去的还没到能回复的时间，混进去会把回复率稀释成假数）
- 分子 = `reply_events.jsonl` 里能匹配到投递记录的公司；匹配不上的会话记 `?哈希`，不算回复
- 算回复：要简历 / 网申·测评 / 约面试 / 对方说话 / 系统通知；不算：已读未回、我方最后发言、拒信
- 一律带 Wilson 95% 区间。样本 < 30 就说「还不能当结论」，不要拿两个 40% 和 20% 的小样本比高低
- **A/B 期间不要动默认招呼语**。招呼语和简历图是两个变量，同时改就分不清是谁的作用。
  顺序：先跑简历图 A/B，两组 n 都过 30 再定；然后才改招呼语，改之前先记基线

---

## 汇报格式

```
本次投递：X 份（合格率 X%）
关键跳过原因：…
异常：hidden 是否修好 / 哪个词走了分页兜底、扫到第几页 / 有没有只扫到首屏的词
今日累计：X 份（含往轮，说明口径）
供给：哪些词已空、fresh 还剩几张、各方向的「目标 / 实投」差多少（配额没投满要说明原因）
待我动作：reply_check 挑出来的（要简历/网申/约面），逐条列
```

再用表格列明细（公司 / 岗位 / 薪资 / 理由），并单列三块：

- 值得破例的岗位（用户划掉但其实很好的，说明为什么，等人拍板）
- 有回复的 HR
- 供给情况（哪个词空了、要不要换关键词）

---

## 节奏

- 日上限 150；单轮份数只看用户给的那个数，不改就别自己加量。
- 当天累计超过 130 提醒用户一次，别闷头投到被平台拦（累计数字看第 10 步的 `daily_log.json`）。
- 一轮合格率低于 40%（口径同第 0 步）说明供给见底，直接收工并告诉用户该换哪个关键词。

---

## 附 · 日常维护速查

- **每轮只改一个数**：开头发给智能体的"本次投 N 份"，其余不动。发图份数跟着实际投递数走。
- **想改城市**：改 `user_profile.json` 的 `target_city` 和 `city_code`（深圳 `101280600`）。
  第 3 步示例 URL 里的 `city` 参数也来自它（`supply_probe.py` 会自动带上）。
- **想加/减关键词**：改 `config/supply_mix.json` 的 `keywords`（唯一权威表）。
  改完确认 `KW_RULES` 或 `keyword_direction` 能覆盖到新词，否则它会落到「其他」。
- **想调方向配比**：改 `config/supply_mix.json` 的 `mix`（或用 `user_profile.json` 的
  `direction_mix` 覆盖）。**先改这里再看数据**——它决定的是投递结构，比改文案的影响大得多。
- **`jobType=1902` 的词序建议**：`前端` → `Java` → `后端` → `React` → `Vue` → `AI` →
  `全栈` → `Python`，每个 page=1 走完再 page=2。供给从这些组合里出，不从旧长词表出。
- **改完配置立刻看效果**：`python scripts/supply_probe.py --reuse` 不重新探页面，
  直接用现有 `supply.json` 重算配额。
- **默认招呼语只能手动设一次**：文案在 BOSS 设置里，**它不会按岗位变**——
  点「立即沟通」自动发的那条是账号唯一一套。而按岗位 JD 定制的专属打招呼语是在 Step 4 读完 JD 生成并在 Step 6 自动补发（`src=jd`，若未定制则退回 `greetings.json` 四个桶）。不要试图在点击沟通时动态改系统默认招呼语。
- **开工前手动确认一次**：Chrome 窗口**不要被完全遮住**（哪怕不点它）——
  这是能走 A 路、省一半时间的唯一前提。
