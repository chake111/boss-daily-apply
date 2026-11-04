# BOSS 页面结构（选择器实测对照）

> 平台改版后按这里探测再改代码，别猜。所有选择器都集中在
> `scripts/webbridge_client.py`（列表/弹窗/薪资）和 `scripts/phase_stream.py`（详情面板/投递/会话）。

## ⚠️ 核心教训

BOSS 的 class 命名有误导性：`company-name` 不是列表页的公司名，`job-area` 不是地区。
**动手改之前先在控制台 dump 一次 `innerHTML`，别照名字猜。**

```javascript
document.querySelector('.job-card-box').innerHTML.substring(0, 3000)
```

---

## 列表页

```html
<li class="job-card-box">
  <div class="job-info">
    <div class="job-title clearfix">
      <a href="/job_detail/xxx.html" class="job-name">产品内容策划</a>
      <span class="job-salary"><!-- 薪资字体加密 --></span>
    </div>
    <ul class="tag-list"><li>1-3年</li><li>本科</li></ul>
  </div>
  <div class="job-card-footer">
    <a href="/gongsi/xxx.html" class="boss-info">
      <div class="boss-logo"><img src="..."></div>
      <span class="boss-name">某某食品</span>   <!-- ← 公司名在这 -->
    </a>
    <span class="company-location">深圳·南山区·科技园</span>  <!-- ← 地区在这 -->
  </div>
</li>
```

### 选择器对照（已验证）

| 数据 | ❌ 容易猜错 | ✅ 实际选择器 | 说明 |
|---|---|---|---|
| 岗位卡片 | `li[class*="job-card"]` | `.job-card-wrap li.job-card-box` | 列表项 |
| 岗位标题 | `h3`, `.job-title` | `.job-name`（a 标签） | 同时带 href |
| 薪资 | `[class*="salary"]` | `.job-salary` | 字体加密，需解密 |
| 公司名 | `.company-name` | **`.boss-name`** | 最容易猜错 |
| 工作地区 | `.job-area` | **`.company-location`** | 不是 `.job-area` |
| 经验/学历 | `.tag-list li` | `.tag-list li` | 对 |
| 详情链接 | `a[href*="job_detail"]` | 同左，href = `/job_detail/{jobId}.html` | |

### 提取在代码里怎么做的

`webbridge_client.extract_jobs()` 走两级：

1. **Vue 私有 API**：读 `__vue__.$props.data` —— 快，但改版容易断
2. **DOM 兜底**：按上表选择器扫 `.job-name` / `.boss-name` / `.company-location`

**注意**：`_live_driver.py walk` 只输出 `jobId / title / salary / city / industry`，
**不含公司名**。公司名要在 `open` 之后从右侧面板读（见下），这是刻意的——
卡片上的公司名可能被截断，用截断名投递会导致补发简历时匹配错会话。

---

## 详情面板（右侧）

| 数据 | 选择器 | 备注 |
|---|---|---|
| 面板容器 | `.job-detail-box`（兜底 `#main .job-detail`） | `panel_ok` 判据就是它的文本长度 |
| 岗位标题 | `.job-detail-box .job-name` | **必须 scope 到面板内**：裸 `.job-name` 会命中左侧列表第一张卡，导致「点开 A 却记录 B」 |
| 公司名 + HR | 面板底部一行，形如 `公司名 · 人事经理` | `deliver` 第二个参数的来源 |
| JD 正文 | `.job-detail-box` 的 `innerText` | 含末尾 HR 活跃度，一次读完 |

**踩坑**：`document.hidden=true`（窗口被遮挡）时 SPA 不渲染详情，`.job-detail-box`
文本长度为 0、`open` 报 `panel_ok:false`。这不是卡片坏了——**重新 navigate 一次搜索页**
强制整页加载再 `open` 即可。

---

## 投递按钮与弹窗

| 目标 | 选择器 | 注意 |
|---|---|---|
| 立即沟通 | `.btn-startchat`，或遍历 `a.op-btn` / `button.op-btn` 文本含"立即沟通" | 面板确认在本岗位后再点 |
| 投递弹窗 | 含「留在此页」/「继续沟通」两个按钮 | **只点「留在此页」** |

点「继续沟通」会导航到 `/web/geek/chat`，返回时搜索页重建、游标失效。
投递主流程全程不打开聊天页。

第 120 份左右会出现一次额外提示弹窗（含「好 / 确定」），点掉后继续投，非致命。

---

## 会话页（补发简历图用）

```html
<div class="user-list">
  <div role="listitem">          <!-- 一个会话 -->
    <div class="friend-content">…公司名 / HR名 / 最后一条预览…</div>
  </div>
</div>
<div class="chat-conversation">
  <div class="message-item item-myself">…</div>   <!-- 我方消息 -->
  <div class="message-item">…</div>               <!-- 对方消息 -->
</div>
```

| 数据 | 选择器 | 备注 |
|---|---|---|
| 会话项 | `.user-list [role=listitem]` | 只渲染最近 ~40 条，更早的 `SKIP notfound` |
| 会话可点区 | `.friend-content` | 点它才切会话 |
| 消息容器 | `.chat-conversation` | |
| 我方消息 | `.message-item.item-myself` | 判「图发出去没」只看这里 |
| 我方图片 | `.item-myself img` 且 `naturalHeight > 100` | 不过滤会把头像算进来 |
| 输入框 | `textarea.input`（兜底 `#chat-input`） | 用 `HTMLTextAreaElement.prototype.value` 的 setter 赋值才触发 Vue |
| 发送按钮 | `.btn-sure-v2.btn-send` | 页面上有两个 `.btn-sure-v2`，**不带 `btn-send` 的是隐藏控件**（点了会触发"请求交换电话"） |
| 发图入口 | `.btn-sendimg input[type=file]` | 兜底：第一个 `input[type=file]` |

**发送按钮的可点判据**：同时满足「可见」+「class 不含 disabled」。
填内容后 Vue 异步解锁，单次读取常常正好读到未解锁那一帧——要轮询最多 3 秒。

**判定成功的唯一标准**：`.message-item` 条数变多。
按「图片张数」判会被历史旧图骗成成功（假阳性）。

---

## 筛选栏

| 参数 | 效果 | 备注 |
|---|---|---|
| `jobType=1902` | 求职类型=实习 | 筛选栏显示"求职类型(1)" |
| `jobType=1901` | **无效** | 筛选栏虽显示已选，但卡里混着 5-10 年社招 |
| `page=N` | 翻页 | 有效，完全绕开懒加载 |
| `city=101280600` | 城市 | 深圳 |

每个搜索词的结果集只有首屏 ~15 张，滚动到底也加载不出更多——**只有翻页能拿到更多卡**。

---

## 底部到底标记

推荐页/搜索结果滚到底会出现这些文案之一：

`没有更多了` / `已经到底` / `到底啦` / `没有更多职位` / `没有职位了`

`_recommend_end_marker()` 靠它判断穷尽。**懒加载判定要留足时间**：先滚 2 次 →
等 3 秒 → 再计数；连续 4 次计数不变才判触底。只等 1.4 秒会把"还在加载"误判成"到底"。
