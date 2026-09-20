# 并行会话协议（Parallel Session Protocol）

> **TL;DR**: 一个会话 = 一个租约+ 一个 git worktree + 一个绑定 change。私有物互不可见；共享物必须持锁写入；合并串行经 `integrate` 锁。本文件是并行隔离与合并的权威源，优先级高于 `changes/structure.md` 中"最多一个 active"的旧约定。

本文件定义多会话并行的隔离边界、锁矩阵、租约规则与合并协议。
单一会话内的 Flow/Gate/Memory 规则不变，见 `flow.md` / `gates.md` / `rollback.md`。

## 1. 会话生命周期

```
register(new) → worktree 隔离执行（heartbeat 续租） → Gate 全过 → integrate（串行合并） → release
```

| 阶段 | 命令 | 说明 |
|------|------|------|
| 注册 | `python3 .harness/tools/session.py new --change {id}` | 生成 `sess-xxxxxxxx`、分支 `harness/{id}`、worktree `../.harness-worktrees/{id}`，并在 INDEX 增行（含 Session 列） |
| 续租 | `python3 .harness/tools/session.py heartbeat --session {sid}` | 每个 Phase 出口、每次长操作前执行；默认 TTL 900s |
| 合并 | 见 §4 | 串行 |
| 释放 | `python3 .harness/tools/session.py release --session {sid} [--status done\|abandoned]` | worktree 删除、分支保留、租约终止 |

租约过期（TTL 内无心跳）的会话由 `sweep` 隔离为 `orphaned`：其 INDEX 行视为脏数据，合并前必须人工接管（`bind`）或废弃。

## 2. 隔离边界（Iron Law 8：会话不得越界）

### 2.1 私有（会话独占，无需锁）
- 自己 worktree 内的一切文件修改（代码、`changes/{自己的-id}/` 全部产物）。
- 自己会话的 sub-agent 调度（Planner/Implementer/Reviewer 仍按 orchestrator 隔离协议 fresh 启动）。

### 2.2 共享-写（必须持锁，锁名见 `tools/lock.py` CANONICAL_LOCKS）
| 资源 | 锁 | 允许写入时机 |
|------|-----|--------------|
| `changes/INDEX.md` | `index` | session 注册/状态同步/释放，经 `session.py` 自动加锁 |
| `.harness/wiki/`（正式页） | `wiki` | 仅 Human Approval 后的 Ingest；`log.md` 只 append |
| `.harness/memory/*` | `memory` | append-only，条目带 `{sid}` 前缀 |
| `.harness/evolution/*` | `evolution` | analyze_failures 产出 candidates 时 |
| 集成分支合并序列 | `integrate` | 见 §4 |

用法：`python3 .harness/tools/lock.py with --repo . --name wiki --owner {sid} -- <命令>`

### 2.3 共享-只读（禁止会话内修改）
`rules/`、`agents/`、`skills/`、`tools/`、`mcp/` —— 治理文件变更走主分支上的治理 Flow（强制 Standard-flow + `risk_flags=governance`），再由各会话 `git rebase` 获取。

### 2.4 冲突即 Stop-the-Line
- 锁获取失败（LOCK-FAIL）→ 等待重试或挂起任务，不得绕锁写文件。
- INDEX 中出现无 live session 绑定的 `active` 行 → validator FAIL，接管或废弃。
- 两会话命中同一 change-id → `session.py new` 直接拒绝。

## 3. INDEX 与多 active 语义（修订 structure.md）

- 允许 N 个 `active`，**每行必须绑定唯一 live session**（Session 列）。
- 会话只恢复自己 Session 列对应的 change；Session Startup 读 INDEX 后按本会话 id 过滤。
- 状态同步（`active→done`）仍走两段式 + validator，且写入时持 `index` 锁。

## 4. 合并协议（integrate）

一个 change 的 final Gate = `pass` 且 Human Approval = `approved` 后：

```
1. 持 integrate 锁（同一时刻全局仅一个合并序列在执行）
2. git rebase harness/{id} onto integration 分支（默认 main）
3. 在 worktree 内重跑 Gate 必查命令（编译/测试/validate_change.py --change {id}）→ fresh evidence
4. 快进或 PR 合并到 integration 分支
5. 持 wiki 锁执行正式 Wiki Ingest（如有 approved candidates）
6. 持 index 锁同步 INDEX 行 done → release 会话
7. 释放 integrate 锁
```

rebase 冲突 → Stop-the-Line：记录 failure evidence + 根因，回退到自己分支修复，**禁止直接改对方分支产物**。合并后其余会话在下一个 Phase 入口前 `git rebase integration` 同步治理文件与已完成变更。

## 5. Memory / Wiki 并发写规范

- memory 条目格式增加首字段 `- {sid}`；append 时持 `memory` 锁，读不需要锁。
- wiki candidates 本来就是 change-local（不冲突）；正式 wiki 更新只发生在合并序列第 5 步，天然串行。
- `generate_wiki_index.py` / `validate_wiki.py` 仅在持 `wiki` 锁的临界区内运行。

## 6. 生产工程要求

- 所有共享写入命令必须可重入、幂等：崩溃后锁由 TTL 回收（3×TTL 或 pid 死亡判定），`locks/quarantine/` 留痕审计。
- pre-commit（见 `tools/install_hooks.sh`）：禁止提交时直接改他人 `changes/{id}/`；禁止绕过 `index` 锁改 INDEX。
- CI（`.github/workflows/harness-ci.yml`）：每次 PR 跑 `validate_change.py --all` + `sweep` + 锁残留检查 + 会话-INDEX 一致性。
- 会话数上限：`HARNESS_MAX_SESSIONS`（默认 8）；`session.py new` 超限时拒绝，防止 worktree/上下文爆炸。
