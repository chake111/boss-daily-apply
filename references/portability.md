# 环境适配：不是 WorkBuddy 也能用，没有 Chrome 也能用

这个 skill 的本质是**一份流程 + 一组标准库脚本**。它不依赖任何特定智能体，
也不强制你装 Chrome。下面按"你有什么"分四种形态，对号入座即可。

---

## 一、先判断你属于哪种形态

| 你有 | 形态 | 能用什么 | 不能用什么 |
|---|---|---|---|
| 智能体 + Chromium 浏览器 + WebBridge 扩展 | **全自动** | 全部 | — |
| 智能体 + 浏览器，但装不了扩展（公司电脑/权限受限） | **半自动** | 判定标准、机械否决、记账、报表 | 自动翻页、自动点投递、自动补发 |
| 只有终端，没有智能体 | **脚本模式** | 同上，判断由你自己做 | 语义终审那一步得你亲自读 JD |
| 什么都没有，只想先看看 | **纯文本** | `SKILL.md` + `references/` 就是一份可执行手册 | — |

**关键认知**：这个 skill 真正值钱的是 `judgment.md` 的判定表和 `metrics.md` 的口径，
不是点击动作。没有浏览器，前两样照样能用。

---

## 二、浏览器：Chromium 系就行，不必是 Chrome

WebBridge 是 **Chromium 内核扩展**，所以这些都能装：

| 浏览器 | 支持 | 说明 |
|---|---|---|
| Google Chrome | ✅ | 默认优先 |
| Microsoft Edge | ✅ | **Windows 10/11 自带，等于不用装** |
| Brave | ✅ | 内置 Chrome 商店，直接装 |
| Vivaldi / Chromium / Opera | ✅ | 一般可直接装 Chrome 商店扩展 |
| 360 / QQ / 搜狗（极速模式） | ⚠️ | 内核是 Chromium，多数能装，但内核版本可能过旧 |
| **Firefox** | ❌ | 扩展体系不同，装不了 |
| **Safari** | ❌ | 同上 |
| 内置浏览器（IDE / 智能体自带） | ❌ | 拿不到用户的登录态，投递必然失败 |

### Edge 装 Chrome 商店扩展

1. 打开 `edge://extensions/`
2. 左下角打开「**允许来自其他商店的扩展**」
3. 打开 Chrome 商店页面安装 WebBridge，弹窗点「允许」

### 自动检测与启动

```bash
python scripts/browser.py --list          # 装了哪些、在不在跑
python scripts/browser.py --launch        # 默认挑"正在运行"的那个
python scripts/browser.py --launch edge   # 指定 Edge
```

**为什么要专门用脚本启动**：Windows 上 `Start-Process` / `cmd start` 拉起的浏览器
会在 1~2 分钟内被会话回收，扩展跟着掉线；脚本走 `explorer.exe`（macOS 走 `open -a`，
Linux 走 `xdg-open`），把进程交给桌面 shell 托管才稳。

自定义路径：`export BOSS_BROWSER="/path/to/browser"`（Windows 用 `set`）。

### 完全装不了浏览器 / 扩展怎么办

用**半自动模式**：你自己在浏览器里投，脚本负责判断辅助和记账——

```bash
python scripts/ledger.py add --title "前端开发实习生" --company "某某科技" \
    --salary "200-300元/天" --industry 互联网 --direction 前端开发
python scripts/ledger.py list
python scripts/stats.py                    # 回复率报表，口径和自动模式一致
```

`ledger.py` 写的是和 driver **完全相同**的 schema，所以 `stats.py`、`phase_stream.py`
不用改就能出报表。判断"该投不该投"时，把 JD 粘给智能体，让它对照
`references/judgment.md` 判，比你自己纠结快。

---

## 三、智能体：谁都能接

| 智能体 | 安装方式 | 说明 |
|---|---|---|
| WorkBuddy | `python scripts/install.py --target workbuddy` | 装到 `~/.workbuddy/skills/` |
| Claude Code | `python scripts/install.py --target claude` | 装到 `~/.claude/skills/`；项目级加 `--project .` |
| Cursor | `python scripts/install.py --target cursor --project .` | 生成 `.cursor/rules/boss-daily-apply.mdc` |
| Codex CLI | `python scripts/install.py --target codex --project .` | 往 `AGENTS.md` 插一个受管区块 |
| 其他（Cline / Continue / 自研） | `--target plain` | 把仓库路径告给它，让它读 `SKILL.md` |
| 纯终端，无智能体 | 不用安装 | 直接跑脚本，判断自己做 |

```bash
python scripts/install.py --list          # 看每个目标装没装、装在哪
```

**什么都不装也能跑**：脚本全是标准库，`python scripts/selftest.py` 可以直接验证。
`SKILL.md` 本身是给人读的执行手册，把内容贴给任何智能体都能照做。

### 为什么 skill 里没有"必须用某个工具"的步骤

早期版本里有 `present_files`（某宿主专有的展示工具）、写死的 `~/.workbuddy/` 路径。
现在这些全部换成：

- 出摘要页 → 打印 HTML 的绝对路径，用系统默认程序打开
- 状态目录 → `BOSS_WORKDIR`，默认 `~/.boss-daily-apply`，与工具无关
- 配置查找 → 工作目录 → 工作目录根 → 技能目录，三级回退

---

## 四、目录与迁移

```
技能目录（git 管理，可随时覆盖）      <repo>/
工作目录（你的数据，永不进版本库）    ~/.boss-daily-apply/     ← 新默认
                                      ~/WorkBuddy/BOSS/boss-data/  ← 旧默认，存在则自动沿用
```

从旧版本升级上来的，第一次跑 `bootstrap.py` 会：

- 检测到 `~/WorkBuddy/BOSS/boss-data` 存在 → **继续用它**，不搬动任何数据
- 检测到旧位置的 `user_profile.json` → 复制到工作目录
- 旧位置散落的 `greetings.json` / `blacklist.json` → 直接命中，不用搬家

想主动迁到新位置：

```bash
BOSS_WORKDIR=~/.boss-daily-apply python scripts/bootstrap.py
# 然后把旧目录的 stream_progress.json / walk_state.json 拷过去
```

| 环境变量 | 默认 | 作用 |
|---|---|---|
| `BOSS_WORKDIR` | `~/.boss-daily-apply` | 所有状态文件 |
| `BOSS_CONFIG_DIR` | 依次找 `<工作目录>/config`、`<工作目录>`、`<技能目录>/config` | 配置覆盖 |
| `BOSS_PROFILE` | `<工作目录>/user_profile.json` | 个人档案 |
| `BOSS_RESUME_IMG` | `<工作目录>/resume/resume.png` | 简历图 |
| `BOSS_BROWSER` | 自动检测 | 指定浏览器可执行文件 |
| `BOSS_DEBUG` | 空 | 设 1 打印档案加载来源（诊断用） |

多账号 / 多城市并行：给每个实例一个 `BOSS_WORKDIR` 即可，互不干扰。

---

## 五、跨平台说明

| 能力 | Windows | macOS | Linux |
|---|---|---|---|
| 浏览器启动 | ✅ `explorer.exe` | ✅ `open -a` | ✅ `xdg-open` |
| 浏览器检测 | ✅ 注册路径 + 常见安装位 | ✅ `/Applications` | ✅ `PATH` |
| WebBridge 服务 | ✅ `.exe` | 视官方发布情况 | 视官方发布情况 |
| 脚本主体 | ✅ | ✅ | ✅ |
| 投递全流程 | ✅ | ⚠️ 需自备 WebBridge | ⚠️ 需自备 WebBridge |

自动化那一段依赖 WebBridge 的官方发布形态。如果你的平台没有 WebBridge，
直接走半自动模式——功能不受影响，只是"点投递"这一步由人做。

---

## 六、最短路径

```bash
git clone https://github.com/chake111/boss-daily-apply.git
cd boss-daily-apply
python scripts/selftest.py          # 26 项离线自检，先确认脚本本身没问题
python scripts/install.py --list    # 看你的智能体该装哪
python scripts/bootstrap.py         # 建工作目录
python scripts/env_check.py         # 浏览器 / 桥 / 登录态
```

`env_check` 里浏览器那项过了、桥那项没过 → 要么装扩展，要么走 `ledger.py`。
**两条路都能走完整个求职季**，只是手动程度不同。
