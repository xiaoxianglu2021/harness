# Startup Evidence

## 原始环境诊断

- Command: `python3 .harness/tools/validate_change.py`
- Exit code: 49
- Output summary: 无 validator 输出；`command -v python3` 指向 `/c/Users/pro13/AppData/Local/Microsoft/WindowsApps/python3`。
- Artifact path: `startup-evidence.md`
- 根因: `python3` 命中 Windows 应用执行别名，没有运行真实 Python 解释器。
- Stop-the-Line: 暂停流程推进，定位解释器入口后再验证，未跳过校验。
- 恢复目标: Session Startup，然后 Phase 1。

## 比较验证

- Command: `python -B .harness/tools/validate_change.py`
- Exit code: 0
- Output summary: `WARN: index.no_active: No active change in INDEX.md; registry is idle.`；`PASS: 0 failure(s), 1 warning(s).`
- Artifact path: `startup-evidence.md`
- 解释: 证明本机可用 Python 能运行原 validator；不表示系统 python3 已修复。

## 会话入口恢复验证

- Command: `python3() { PYTHONUTF8=1 python -B -X utf8 "$@"; }; python3 --version && python3 .harness/tools/validate_change.py`
- Exit code: 0
- Output summary: `Python 3.10.9`；`WARN: index.no_active: No active change in INDEX.md; registry is idle.`；`PASS: 0 failure(s), 1 warning(s).`
- Artifact path: `startup-evidence.md`
- 限制: 函数仅当前 shell 有效；每次独立工具 shell 重新定义。未修改系统 PATH 或应用别名。

## 工作区基线

- Command: `git status --short`、`git diff -- .harness/tools/validate_change.py`、`git diff --cached --stat`、`git config --show-origin --get core.filemode`、`git config --show-origin --get core.autocrlf`
- Exit code: 0
- Output summary: 三个暂存新增生成文件为 `.harness/.DS_Store`、`.harness/skills/.DS_Store`、`.harness/tools/__pycache__/validate_change.cpython-37.pyc`；validator 只有 `100755 -> 100644` 模式差异；根 `.DS_Store` 与 `.idea/` 未跟踪；仓库 filemode=true，全局 autocrlf=true。
- Artifact path: `startup-evidence.md`
- Memory action: `.harness/memory/known-issues.md` 新增一条本机 python3 限制。
