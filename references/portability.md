# 环境适配：不是 WorkBuddy 也能用，没有 Chrome 也能用

这个 skill 的本质是**一份流程 + 一组标准库脚本**，不依赖特定智能体，也不强制装 Chrome。

**两条自动化通道，任选一条，都能跑完整的投递流程（含自动翻页、自动点投递、自动补发）：**

| 通道 | 需要什么 | 适合谁 |
|---|---|---|
| **CDP**（推荐） | 任意 Chromium 系浏览器，**不用装任何扩展** | 公司电脑装不了扩展、只有 Edge、不想折腾 |
| **WebBridge** | Chromium 浏览器 + Kimi WebBridge 扩展 | 已经有这个扩展的人 |

只有**一个 Chromium 浏览器都没有**时，才会退到手动记账模式。

---

## 一、先判断你属于哪种形态

| 你有 | 形态 | 自动翻页 / 点投递 / 补发 |
|---|---|---|
| Chromium 浏览器（Edge 就算）+ 智能体 | **全自动（CDP）** | ✅ 全部自动 |
| 同上 + 已装 WebBridge 扩展 | **全自动（WebBridge）** | ✅ 全部自动 |
| 只有终端，没有智能体 | **脚本模式** | ✅ 全部自动，判断你自己做 |
| 一个 Chromium 浏览器都没有 | 手动记账 | ❌ 点投递要人做 |

---

## 二、免扩展自动化：CDP

Chromium 系浏览器自带 **DevTools 协议（CDP）**，启动时加一个调试端口，脚本就能直接
执行 JS、点击元素、导航、开新标签——这正是"自动投递"需要的全部能力，**不需要任何扩展**。

```bash
python scripts/cdp_client.py --launch     # 起一个带调试端口的浏览器
python scripts/cdp_client.py --check      # 确认端口就绪、列出标签页
python scripts/env_check.py               # 三条自检
```

首次要在这个新窗口里**扫码登录一次 BOSS直聘**。之后登录态存在独立 profile 里
（`<工作目录>/browser-profile`），下次直接可用。

### 为什么默认用独立 profile

- 完全不干扰你日常用的浏览器（不抢占、不改配置、不需要你关掉它）
- 登录态只属于这个 profile，不会因为日常浏览器的 cookie 清理而失效

想复用日常登录，把 `BOSS_CDP_PROFILE` 指向真实 profile 目录，并**先关掉所有浏览器窗口**
再由脚本拉起——否则新进程只会把命令行交给已有实例，调试端口起不来。

### 它和 WebBridge 的区别

| | CDP | WebBridge |
|---|---|---|
| 装扩展 | 不需要 | 需要 |
| 启动方式 | 带 `--remote-debugging-port` 启动 | 正常启动 + 扩展连本地服务 |
| 支持的浏览器 | 所有 Chromium 系 | 所有 Chromium 系 |
| 自动翻页 / 点击 / 补发 | ✅ | ✅ |
| 多标签（补发用第二个标签） | ✅ `Target.createTarget` | ✅ session |
| 依赖 | 无（标准库手写 WebSocket） | kimi-webbridge 服务 |

`webbridge_client` 里做了后端路由：上层脚本调用 `evaluate / click / navigate / api`
时自动选通道，**投递脚本一行都不用改**。
用 `BOSS_BACKEND=cdp` 或 `BOSS_BACKEND=webbridge` 可强制指定。

### 手动唤醒（排障用）

```bash
# 等价于 cdp_client --launch，但参数看得见
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" \
  --remote-debugging-port=9222 \
  --user-data-dir="%USERPROFILE%\.boss-daily-apply\browser-profile" \
  --no-first-run --no-default-browser-check
```

---

## 三、浏览器：Chromium 系就行，不必是 Chrome

| 浏览器 | CDP | WebBridge 扩展 |
|---|---|---|
| Google Chrome | ✅ | ✅ |
| Microsoft Edge | ✅ | ✅ Windows 10/11 自带，等于不用装 |
| Brave | ✅ | ✅ 内置 Chrome 商店 |
| Vivaldi / Chromium / Opera | ✅ | ✅ 一般可直接装 |
| 360 / QQ / 搜狗（极速模式） | ⚠️ 内核可能过旧 | ⚠️ 同 |
| **Firefox** | ❌ 无 CDP | ❌ 扩展体系不同 |
| **Safari** | ❌ | ❌ |
| 内置浏览器（IDE / 智能体自带） | ❌ 拿不到你的登录态 | ❌ |

### Edge 装 WebBridge 扩展（如果你选 B 通道）

1. 打开 `edge://extensions/`
2. 左下角打开「**允许来自其他商店的扩展**」
3. 打开 Chrome 商店页面安装，弹窗点「允许」

### 检测与启动

```bash
python scripts/browser.py --list          # 装了哪些、在不在跑
python scripts/browser.py --launch        # 默认挑"正在运行"的那个
python scripts/browser.py --launch edge   # 指定 Edge
python scripts/browser.py --cdp           # 带调试端口（免扩展通道）
```

**为什么要专门用脚本启动**：Windows 上 `Start-Process` / `cmd start` 拉起的浏览器
会在 1~2 分钟内被会话回收，扩展跟着掉线。`browser.py` 走 `explorer.exe`
（macOS `open -a`、Linux `xdg-open`）把进程交给桌面 shell 托管；
`cdp_client` 则用 `DETACHED_PROCESS` 脱离控制台。

自定义路径：`BOSS_BROWSER="/path/to/browser"`。

---

## 四、一个 Chromium 浏览器都没有

这才是真正需要手动的时候（比如只能用系统自带的 Firefox）。判断标准、去重规则、
回复率口径照样能用，只是"点投递"由你做：

```bash
python scripts/ledger.py add --title "前端开发实习生" --company "某某科技" \
    --salary "200-300元/天" --industry 互联网 --direction 前端开发
python scripts/ledger.py status      # 开工/收尾基线
python scripts/stats.py              # 回复率报表，口径与自动模式一致
```

`ledger.py` 写的 schema 和 driver **完全相同**，所以报表、去重、分组都不用改。

---

## 五、智能体：谁都能接

| 智能体 | 安装方式 | 说明 |
|---|---|---|
| Claude Code | `python scripts/install.py --target claude` | 装到 `~/.claude/skills/`；项目级加 `--project .` |
| Cursor | `python scripts/install.py --target cursor --project .` | 生成 `.cursor/rules/*.mdc` |
| Codex CLI | `python scripts/install.py --target codex --project .` | 往 `AGENTS.md` 插受管区块 |
| WorkBuddy | `python scripts/install.py --target workbuddy` | 装到 `~/.workbuddy/skills/` |
| 其他 / 自研 | `python scripts/install.py --target plain` | 不复制，直接给它仓库路径 |
| 纯终端 | 不用安装 | 直接跑脚本 |

```bash
python scripts/install.py --list          # 看每个目标装没装、装在哪
```

**什么都不装也能跑**：脚本全是标准库，`python scripts/selftest.py` 可直接验证。
`SKILL.md` 本身是给人读的执行手册，贴给任何智能体都能照做。

---

## 六、目录与迁移

```
技能目录（git 管理，可随时覆盖）      <repo>/
工作目录（你的数据，永不进版本库）    ~/.boss-daily-apply/          ← 新默认
                                      ~/WorkBuddy/BOSS/boss-data/   ← 旧默认，存在则自动沿用
```

从旧版本升级上来，第一次跑 `bootstrap.py` 会：检测到旧目录就**继续用它**、把旧
`user_profile.json` 复制过来、旧位置散落的 `greetings.json` / `blacklist.json` 直接命中。

| 环境变量 | 默认 | 作用 |
|---|---|---|
| `BOSS_WORKDIR` | `~/.boss-daily-apply`（旧位置存在则沿用） | 所有状态文件 |
| `BOSS_CONFIG_DIR` | 依次找 `<工作目录>/config`、`<工作目录>`、`<技能目录>/config` | 配置覆盖 |
| `BOSS_PROFILE` | `<工作目录>/user_profile.json` | 个人档案 |
| `BOSS_RESUME_IMG` | `<工作目录>/resume/resume.png` | 简历图 |
| `BOSS_BROWSER` | 自动检测 | 指定浏览器可执行文件 |
| `BOSS_BACKEND` | 自动（WebBridge 优先，否则 CDP） | 强制 `webbridge` / `cdp` |
| `BOSS_CDP_PORT` | `9222` | 调试端口 |
| `BOSS_CDP_PROFILE` | `<工作目录>/browser-profile` | CDP 用的 profile 目录 |
| `BOSS_DEBUG` | 空 | 设 1 打印诊断信息 |

多账号 / 多城市并行：给每个实例一套 `BOSS_WORKDIR` + `BOSS_CDP_PORT`。

---

## 七、跨平台

| 能力 | Windows | macOS | Linux |
|---|---|---|---|
| 浏览器检测 / 启动 | ✅ | ✅ | ✅ |
| CDP 自动化 | ✅ | ✅ | ✅ |
| WebBridge | ✅ | 视官方发布 | 视官方发布 |
| 投递全流程 | ✅ | ✅（CDP） | ✅（CDP） |

CDP 是协议级能力，不依赖任何平台的专有组件——所以在三个平台上都能跑全自动。

---

## 八、最短路径

```bash
git clone https://github.com/chake111/boss-daily-apply.git
cd boss-daily-apply
python scripts/selftest.py            # 27 项自检（含一次真浏览器点击）
python scripts/install.py --list      # 你的智能体该装哪
python scripts/bootstrap.py           # 建工作目录
python scripts/cdp_client.py --launch # 起浏览器（首次扫码登录一次）
python scripts/env_check.py           # 三条全过就能开工
```

前两条不通再看 WebBridge；两条都不通才用 `ledger.py`。
**绝大多数人卡在"以为要装 Chrome"，其实 Edge 加一条命令就够了。**
