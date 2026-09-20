# Changes Index

恢复索引。会话开始时先读本文件，按本会话 id（Session 列）过滤出自己负责的 `active` 变更后读其 `summary.md`。

## Registry

| Change | Status | Resume point | Session | Notes |
|--------|--------|--------------|---------|-------|

## 说明

- 状态定义（`active`/`done`/`abandoned`）与维护规则见 `.harness/changes/structure.md`。
- 并行语义（多 active、Session 绑定、锁、合并）见 `.harness/rules/parallel.md`；本文件写入必须持 `index` 锁（经 `tools/session.py` 自动完成）。
- 每个 `active` 行必须绑定唯一 live session；同一 session 不得绑定多个 change。
| docs-usage-parallel-20260920 | done | none | sess-df1e66cf | 20260920 delivered; usage parallel section |
