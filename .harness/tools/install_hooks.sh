#!/usr/bin/env bash
# Install harness governance hooks. Production guard against cross-session
# contamination at the git layer (see .harness/rules/parallel.md §6).
set -euo pipefail
REPO_ROOT="$(git rev-parse --show-toplevel)"
HOOK="$REPO_ROOT/.git/hooks/pre-commit"
mkdir -p "$REPO_ROOT/.git/hooks"

cat > "$HOOK" <<'EOF'
#!/usr/bin/env bash
# Harness parallel-session pre-commit guard.
set -euo pipefail
SID="${HARNESS_SESSION:-}"
RULES=".harness/rules .harness/agents .harness/tools"
STAGED=$(git diff --cached --name-only)

# 1) Governance files may only be committed from the main repo (not a session worktree)
for f in $STAGED; do
  case "$f" in
    .harness/rules/*|.harness/agents/*|.harness/skills/*|.harness/tools/*)
      if [ -n "$SID" ]; then
        echo "COMMIT-BLOCKED: session $SID may not modify governance file: $f"
        echo "  Governance changes go through the main-branch governance flow (rules/parallel.md §2.3)."
        exit 1
      fi
      ;;
  esac
done

# 2) Never touch another session's change directory
for f in $STAGED; do
  case "$f" in
    .harness/changes/*)
      if [ -n "$SID" ] && [ -n "${HARNESS_CHANGE:-}" ]; then
        case "$f" in
          ".harness/changes/$HARNESS_CHANGE"/*|".harness/changes/$HARNESS_CHANGE") ;;
          .harness/changes/INDEX.md|.harness/changes/README.md|.harness/changes/structure.md|.harness/changes/templates.md) ;;
          *)
            echo "COMMIT-BLOCKED: session $SID staged foreign change path: $f"
            exit 1
            ;;
        esac
      fi
      ;;
  esac
done

# 3) INDEX.md edits must hold the index lock (or be a session-managed flow)
if git diff --cached --name-only | grep -qx '.harness/changes/INDEX.md'; then
  if [ -n "$SID" ] && [ ! -f ".harness/locks/index.lock" ]; then
    echo "COMMIT-BLOCKED: INDEX.md change without index lock (use tools/session.py or lock.py)"
    exit 1
  fi
fi

exit 0
EOF
chmod +x "$HOOK"
echo "Installed pre-commit hook: $HOOK"
