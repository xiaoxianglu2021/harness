# 代码与命令规范（Coding & Command Standards）

> **TL;DR**: 生成的代码必须先过项目标准（有 lint 就跑 lint），跟随现有代码库风格、最小 diff；生成的命令必须可复现、幂等、可退出码检查，且不得命中 §3 危险命令黑名单（validator 机械强制）。

本文件是 Phase 4/5 生成代码与 Gate Evidence 命令的规范权威源。
Gate 判定见 `gates.md`；隔离协议见 `flow-standard.md`；本文件不重述。

## 1. 生成代码规范

### 1.1 优先级（高 → 低）

1. **项目自有标准**：项目根存在 `CODE_STANDARDS.md` / `CONTRIBUTING.md` / lint 配置（`.editorconfig`、`eslint`、`ruff`、`gofmt`…）时，以项目标准为准，本文件仅补缺。
2. **现有代码库风格**：命名、目录结构、错误处理模式、注释语言跟随目标文件所在模块的现状（"入乡随俗"，不趁机重排版他人代码）。
3. **本文件的语言无关核心**（下述 §1.2）。

### 1.2 语言无关核心

- **最小 diff**：只改与 approved spec/tasks 相关的行；禁止顺手格式化无关代码、无关重命名、尾随空格清理。
- **无死代码**：不留注释掉的旧实现、`TODO` 必须带 issue/原因、不引入未使用的依赖。
- **错误处理**：新代码不得静默吞错（空 `except` / 空 `catch` / 忽略退出码）；失败路径必须有可观测输出。
- **命名**：跟随模块现有约定；新公共 API 命名需在 spec/评审中显式出现过。
- **注释与文档语言**：跟随目标文件现有语言（中文库用中文、英文库用英文）。
- **安全默认**：不硬编码密钥/凭证/内网地址；不放宽既有权限校验；新依赖需在评审报告中列出并说明来源。
- **提交边界**：Phase 4 产出的代码变更必须可在会话 worktree 内独立编译通过（对应 Gate 必查"编译成功"）。

### 1.3 机械门禁（Gate 前必跑）

Phase 4/5 子步骤出口前，按项目可用工具执行（存在哪个跑哪个，全都不存在则记录 `none + 原因`）：

```text
lint    : 项目配置的 linter（eslint / ruff / golangci-lint / clang-tidy …）
format  : 格式检查（--check / --dry-run 模式，不直接改文件）
typecheck: 类型检查（tsc / mypy / go vet …）
compile : 编译/构建（Gate 必查项，由 gates.md 定义）
```

以上命令与退出码计入 Gate Record Evidence 四字段；lint/format 违规视同 Critical（对应 gates.md 的 Critical=0 要求）。

## 2. 生成命令规范（Evidence Command 与执行命令）

### 2.1 可复现性

- **无交互**：命令不得依赖交互输入（需要输入时用 flag/环境变量/管道喂入）。
- **确定性**：同输入同输出；禁止依赖相对 cwd（写完整命令含工作目录或使用绝对路径）。
- **Evidence 一致**：Gate Record 的 `Command:` 字段必须是**实际执行的完整命令**原样记录，不得事后改写、缩写或省略参数。

### 2.2 幂等与超时

- 修改共享资源（INDEX/wiki/memory/evolution/集成分支）的命令必须幂等、可重入（崩溃后重跑不产生脏状态）。
- 长时间命令（构建/测试）必须带超时机制（`timeout`/工具自带超时），超时视同 `fail` 进入 Stop-the-Line。

### 2.3 安全底线

- 任何命令必须先做退出码检查再声称结果（配合 `verification-before-completion` skill）。
- `git` 操作仅限会话 worktree 内自己的分支；跨分支/跨 worktree 操作仅允许出现在 integrate 序列（`parallel.md §4`）。
- 网络获取（curl/wget）必须落盘校验后再执行，禁止 `curl … | sh` 管道执行。

## 3. 危险命令黑名单（validator 机械强制）

Gate Record 任意 `Command:` 字段（含 Substep Evidence 表内命令）命中以下模式 → validator FAIL（`command.dangerous`），Mechanical Gate 强制 `blocked`：

| 模式 | 理由 |
|------|------|
| `rm -rf /`、`rm -rf ~`、`rm -rf /*` | 不可恢复破坏 |
| `git push --force`（含 `-f`）到共享分支 | 覆盖他人历史 |
| `git reset --hard` 作用于共享分支/主 checkout | 摧毁工作区状态 |
| `curl ... \| (ba)?sh`、`wget ... \| (ba)?sh` | 未审计远程代码执行 |
| `sudo `（治理工具链不需要提权） | 权限升级 |
| `chmod -R 777`、`chmod 777` 于共享路径 | 权限放开 |
| `mkfs`、`dd if=... of=/dev/` | 设备级破坏 |
| `:(){ :\|:& };:` fork 炸弹 | 资源耗尽 |
| `git worktree remove` 未带会话归属校验 | 误删他人会话（会话 worktree 仅可经 `session.py release` 删除） |

例外：经用户明确书面批准的运维类 change，可在 summary.md 声明 `command_exceptions`（逐条列出命令 + 批准证据），validator 对命中项降级为 WARN。

## 4. 挂载点

- Phase 4 / implementation、Phase 5 / unit-test 入口卡片"读取 Skills"区引用本文件（见 `flow-standard.md`）。
- Reviewer 子步骤以 §1.2 为评审基线之一；§1.3 机械项与 §3 黑名单由 validator 强制，评审不重复判定。
