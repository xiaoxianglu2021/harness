# harness-parallel

基于 [Jinwangithub/harness](https://github.com/Jinwangithub/harness)（Harness Engineering）改进的**生产级、多会话并行** AI Coding Agent 工程框架。

## 相对原版的改进

原版三大并行瓶颈及本版对策：

| # | 原版瓶颈 | 本版方案 | 借鉴来源 |
|---|----------|----------|----------|
| 1 | `INDEX.md` 强制"任意时刻最多一个 active"（validator 硬编码 FAIL） | 5 列 INDEX（新增 Session 列），允许多 active；每个 active 必须绑定唯一 live session，孤儿行/session 复用 → validator FAIL | spec-kit / OpenSpec 的 change-proposal 模型 |
| 2 | 多会话共享同一工作区，文件互踩 | 每会话一个 git worktree + 独立分支（物理隔离）；治理文件（rules/agents/skills/tools）只读，变更走主分支治理 Flow | vibe-kanban / agent-of-empires 的多会话管理 |
| 3 | INDEX/memory/wiki 并发写无保护 | 跨平台文件锁（`tools/lock.py`，O_EXCL + TTL 租约 + 崩溃回收 + 隔离区审计）；写共享资源必须持锁 | 生产工程惯例 + moai-adk 门禁思想 |
| 4 | 无 CI 防线 | pre-commit 钩子（跨会话污染拦截）+ GitHub Actions（全量校验/残留锁检查/并发冒烟测试） | gsd / agent-os 的 CI 集成 |
| 5 | 仅 Claude Code 入口 | `CLAUDE.md` + `AGENTS.md` 双入口，适配 pi/Codex/Cursor 等宿主 | gsd-pi / superpowers 多宿主经验 |

## 快速开始

```bash
# 一次性：安装治理钩子
bash .harness/tools/install_hooks.sh

# ── 会话 A（终端 1）────────────────────────────
python3 .harness/tools/session.py --repo . new --change feat-login-20260920
# → 输出 {"session":"sess-xxxx", "worktree":"../.harness-worktrees/feat-login-20260920", ...}
cd ../.harness-worktrees/feat-login-20260920     # 一切工作在 worktree 内
export HARNESS_SESSION=sess-xxxx HARNESS_CHANGE=feat-login-20260920
# … 按 CLAUDE.md/AGENTS.md 启动 agent，正常走 Flow/Gate …
python3 .harness/tools/session.py --repo <主仓库路径> heartbeat --session sess-xxxx

# ── 会话 B（终端 2）：同样流程，互不影响 ────────
python3 .harness/tools/session.py --repo . new --change fix-nav-20260920

# ── 共享资源写入（锁保护示例）──────────────────
python3 .harness/tools/lock.py with --repo . --name memory --owner sess-xxxx -- \
  sh -c 'echo "- sess-xxxx lesson ..." >> .harness/memory/lessons-learned.md'

# ── 交付合并（串行，见 rules/parallel.md §4）───
# final Gate=pass + approved 后：持 integrate 锁 → rebase → 重跑 Gate → 合并 → wiki ingest → release
python3 .harness/tools/session.py --repo . release --session sess-xxxx --status done
```

## 新增/修改文件

```
新增  .harness/rules/parallel.md          并行协议（隔离边界/锁矩阵/租约/合并）— 权威源
新增  .harness/tools/lock.py              跨平台文件锁（TTL/心跳/崩溃回收/CLI）
新增  .harness/tools/session.py           会话管理（new/heartbeat/release/list/sweep/exec/bind）
新增  .harness/tools/install_hooks.sh     pre-commit 跨会话污染拦截
新增  .github/workflows/harness-ci.yml    CI：全量校验 + 锁残留 + 并发冒烟
新增  .harness/sessions/  .harness/locks/ 会话注册表 / 锁目录（运行时产物，不入库）
新增  AGENTS.md                            多宿主入口（与 CLAUDE.md 同步）
修改  .harness/tools/validate_change.py   多 active + Session 列 + 孤儿/复用检测
修改  .harness/changes/INDEX.md           5 列格式（Session 列）
修改  .harness/changes/structure.md       多 active 语义 + 锁规则
修改  .harness/agents/orchestrator.md     Session Startup 并行化 + Iron Law 8（会话不越界）
修改  CLAUDE.md                            导航表增加 parallel/session/lock
```

## 隔离模型（Iron Law 8）

```
私有（无需锁）   会话 worktree 内一切文件、自己的 changes/{id}/、sub-agent 调度
共享-写（持锁）  INDEX(index) · wiki(wiki) · memory(memory) · evolution(evolution) · 合并(integrate)
共享-只读        rules/ · agents/ · skills/ · tools/ · mcp/
```

会话 = 租约（TTL 900s，可 `HARNESS_LEASE_TTL` 调整）+ worktree + 绑定 change。
租约过期由 `sweep` 隔离为 `orphaned`，合并前必须人工接管或废弃。
并发上限 `HARNESS_MAX_SESSIONS`（默认 8），`session.py new` 超限拒绝。

## 已验证

- `lock.py`：40 任务 / 16 线程全互斥通过、崩溃锁 TTL 回收通过、CLI 通过
  （含 Windows `unlink` 与并发读句柄冲突的修复：删除重试）
- `session.py`：双会话并行注册、重复绑定拒绝、心跳、释放、worktree 清理、sweep 通过
- `validate_change.py`：双 active + 双 live session → PASS；
  孤儿 active → FAIL（`index.active_unbound`）；同 session 绑两 change → FAIL（`index.session_reused`）

## 兼容性

原单会话流程完全兼容：不运行 session.py 时，4 列 INDEX 旧格式仍被接受
（active 无 Session 绑定会得到明确 FAIL 指引，按提示用 session.py 注册即可）。

## Attribution

- 本项目派生自 [Jinwangithub/harness](https://github.com/Jinwangithub/harness)（Harness Engineering 框架），保留其 Flow/Gate/Memory 治理语义。
- 并行化扩展（会话租约、文件锁、并发隔离、CI 防线、编码与命令规范）由本仓库贡献。
- 引入的 Skills：`verification-before-completion`、`subagent-driven-development`、`using-git-worktrees` 来自 [obra/superpowers](https://github.com/obra/superpowers)（MIT, © 2025 Jesse Vincent）。
