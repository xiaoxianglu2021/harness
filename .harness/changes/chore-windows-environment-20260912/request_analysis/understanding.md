# Understanding

## Problem Statement

用户要求整理项目以适应当前电脑。目标读者是本项目维护者。当前 Windows 10 + Git Bash 中 `python3` 命中 WindowsApps 占位入口，而 Anaconda 的 Python 3.10.9 可以运行原 validator。工作区还混入 macOS 元数据、Python 缓存和 IDE 配置，Git 将执行位差异显示为修改。

目标是让本机开发与验证可用，减少跨系统 Git 噪声，同时保留现有工作和 macOS/Linux 兼容性。

## Recommended Direction

采用用户已批准的项目级最小方案：新增根 `.gitignore` 与 `.gitattributes`，补充 README 使用说明，只取消暂存三个已核实生成物、保留磁盘原件；仅仓库设置 `core.filemode=false`。

运行规范中的 `python3` 命令时，在当前 Git Bash 声明转交已验证 Python 3 的函数，并启用 UTF-8。相比安装全局 Python、改系统 PATH 或批量改写历史命令，项目级方案范围更小，不影响其他仓库。该函数不是永久系统修复。

## Key Assumptions

- 本机 `python` 是已核实的 Anaconda Python 3.10.9；共享文档以版本检查为前置条件，不硬编码机器路径。
- Git Bash 函数只作用于当前 shell；独立工具 shell 必须重新定义，PowerShell/CMD 使用其适用的直接 Python 命令。
- 当前 validator 源码没有内容修改，无需改变校验语义。
- 全局 Git 配置和系统应用别名保持不变。
- 既有本地文件不得以清理为由删除；`.idea` 保留并忽略，可能共享的 VS Code 配置不整体忽略。

## MVP Scope

### In scope

1. `.gitignore`：OS 元数据、Python 字节码及缓存、`.idea/`、本地虚拟环境。
2. `.gitattributes`：主要文本格式固定 LF，二进制自动识别；不批量重新规范化历史文件。
3. README：项目性质、Windows Git Bash/PowerShell 与 macOS/Linux 的实际验证入口、Python 版本检查、UTF-8、测试命令和会话作用域。
4. 仅取消暂存 `.harness/.DS_Store`、`.harness/skills/.DS_Store`、`.harness/tools/__pycache__/validate_change.cpython-37.pyc`，保留原件。
5. 本仓库 `core.filemode=false`，保留索引中的执行位。
6. 使用现有 validator 与 unittest 验证，不引入额外依赖。

### Acceptance Criteria

- 生成物被 Git 忽略，三个指定文件仍存在且不再暂存，其他已有改动保留。
- `git check-attr` 显示主要文本采用预期换行策略；不出现全仓库换行差异。
- README 命令说明真实可用，明确 shell 差异和会话函数非持久性。
- `core.filemode=false` 只作用于本仓库，不再显示 validator 的执行位伪改动。
- 完整 validator 与现有测试通过；无 active 时的启动 WARN 不应作为建立 active 后仍须保留的验收条件。
- 不修改 validator 业务逻辑、不提交、不推送。

## Not Doing

- 不安装 Python，不改系统 PATH、应用别名、全局 Git 或用户 shell 配置。
- 不重置工作树、不删除本地 IDE 文件、不清理历史 change。
- 不全库替换 python3、不修改治理规则或测试期望来掩盖环境问题。
- 不将会话入口恢复宣称为系统 python3 永久修复。

## Open Questions

- none；用户已批准项目级适配方向。后续阶段仍按项目规定逐阶段确认。

## Evidence

下列实测由 Orchestrator 提供给隔离 Planner；完整命令、退出码和输出存于 `startup-evidence.md`。

| Command / Action | Exit code / Result | Output summary | Artifact reference |
|------------------|--------------------|----------------|-------------------|
| 原 WindowsApps python3 执行 validator | 49 | 未进入 validator，解释器入口不可用 | `startup-evidence.md` |
| `python -B .harness/tools/validate_change.py` | 0 | PASS，0 failures，1 index.no_active WARN | `startup-evidence.md` |
| 会话内定义 python3 函数后检查版本并运行相同 validator | 0 | Python 3.10.9；PASS，0 failures，1 warning | `startup-evidence.md` |
| Git diff / status / config 检查 | 0 | 三个暂存生成物；validator 只有模式差异 | `startup-evidence.md` |

## Planner Review

- Status: DONE_WITH_CONCERNS
- Concern: 会话函数不跨 shell 持久，必须在 README 明确；未阻塞当前范围。
- Orchestrator correction: Planner 将初始 `index.no_active` WARN 写为后续验收要求，已改为仅启动时预期；创建 active 后以实际 validator 结果为准。补全了实际 `python -B` 命令及正确的 shell 连接符。
- Boundary Compliance: 未写文件、未推进 Phase、未判定 Gate、未请求批准、未读取禁止的 Harness 元文件、未实现代码。

## Memory Check

- Architecture/governance decision made: no
- Agent/process lesson found: yes; Gate 路径应相对于 change 目录，见 summary 的恢复记录
- Known issue or governance debt found: yes; 系统 python3 占位入口仍存在
- Memory action: `.harness/memory/known-issues.md`、`.harness/memory/lessons-learned.md`
- Memory recorded: 2 entries
- Template completeness verified: yes
