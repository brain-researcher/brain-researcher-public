# antigravity AG-1..AG-6 Runbook

> 适用范围：Web UI 预发/发版前可靠性验证
> 目标：补齐 Playwright 难覆盖的并发/网络/恢复场景

本 runbook 对应 `tests/antigravity/ag-scenarios.yaml`，按场景逐条执行并记录结果。

---

## 前置条件

- Web UI 可访问（默认 `http://localhost:3000`）
- Agent/Orchestrator/BR-KG 处于可用状态（至少能跑一个快速 pipeline）
- 准备：
  - 1 个 **running** analysis（用于 AG-1/2/6）
  - 1 个 **succeeded** analysis（用于 AG-3）
  - 2 个不同 analysis（用于 AG-5）

建议准备一个快速 workflow（例如 nilearn connectivity）来缩短验证时间。

---

## 记录模板（复制到 issue/PR）

| 场景 | 结果 | 备注 |
|---|---|---|
| AG-1 SSE reconnect | ☐ Pass / ☐ Fail |  |
| AG-2 Cancel→Retry | ☐ Pass / ☐ Fail |  |
| AG-3 Share security | ☐ Pass / ☐ Fail |  |
| AG-4 Tools loop | ☐ Pass / ☐ Fail |  |
| AG-5 Multi-tab | ☐ Pass / ☐ Fail |  |
| AG-6 Refresh recovery | ☐ Pass / ☐ Fail |  |

---

## AG-1：SSE reconnect after network drop（P0）

1. 打开 Studio（Results 可见）并确认：
   - 进度条在更新
   - Console/Logs 在追加
2. DevTools → Network → 勾选 Offline（保持 ~10 秒）
3. 观察 UI：
   - 不白屏、不 crash
   - 有连接提示（如 reconnecting）最好；没有也可接受，但不能卡死
4. 取消 Offline：
   - 5 秒内恢复更新
   - progress/console 继续从断点推进（不是重新开始）

---

## AG-2：Cancel → Retry → Attempt isolation（P0）

1. 对 running analysis 点击 Cancel 并确认
2. 验证状态进入 `cancelled`
3. 点击 Retry/Approve&Run（创建新 attempt）
4. 打开 AttemptSwitcher：
   - attempt id 发生变化
   - 切回旧 attempt 时，console/artifacts 不应显示新 attempt 的内容

---

## AG-3：Share security boundaries（P1）

1. 对 succeeded analysis 打开 Share modal，选择 Summary-only 并生成链接
2. 用无痕窗口打开链接：
   - 不显示 raw logs
   - 页面/DOM 不包含本地路径（`/data/`, `/home/` 等）
   - 不暴露 `.nii/.nii.gz`（summary scope）
3. 尝试 URL 篡改（如追加 `/logs` 或直接猜下载链接）：
   - 返回 403/404
4. 回到主窗口 revoke share link
5. 无痕窗口刷新：
   - 显示 expired/invalid/not found（立即生效）

---

## AG-4：Tools → Ask Agent loop（P1）

1. 打开 Tools catalog
2. 搜索一个工具（如 nilearn）
3. 点击 “Ask Agent to use this”
4. 跳转回 Studio：
   - Chat 输入框含 tool 上下文
5. 发送后等待 Agent action card：
   - 点击 Add/Replace 能更新 Plan

---

## AG-5：Multi-tab concurrency isolation（P1）

1. Tab1 打开 analysis A；Tab2 打开 analysis B
2. 两个 tab 同时运行
3. 验证：
   - Tab1 的 analysis id/console 只属于 A
   - Tab2 的 analysis id/console 只属于 B

---

## AG-6：Refresh recovery（P0）

1. 打开 running analysis 的 Studio
2. 记录当前进度（大概数值即可）
3. 刷新页面（Cmd/Ctrl+R）
4. 验证：
   - 自动恢复到同一个 analysis
   - 进度继续推进
   - console/logs 继续追加
