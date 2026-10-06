#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

UPSTREAM_URL="${AYA_UPSTREAM_URL:-https://github.com/aya-rs/aya.git}"
UPSTREAM_REF="${AYA_UPSTREAM_REF:-main}"

if [ -n "${PYTHON:-}" ]; then
  PYTHON_BIN="$PYTHON"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN=python
else
  echo "错误: 找不到 python3/python" >&2
  exit 1
fi

# Treat SYNC_TMP_DIR as a parent, never erase a caller-supplied directory.
TMP_PARENT="${SYNC_TMP_DIR:-${TMPDIR:-/tmp}}"
mkdir -p "$TMP_PARENT"
TMP_PARENT="$(cd "$TMP_PARENT" && pwd -P)"
TMP_DIR="$(mktemp -d "$TMP_PARENT/appopt-sync.XXXXXX")"

cleanup() {
  # Only remove the unique child created by mktemp above.
  case "$TMP_DIR" in
    "$TMP_PARENT"/appopt-sync.?*) rm -rf -- "$TMP_DIR" ;;
    *) echo "拒绝清理非预期临时路径: $TMP_DIR" >&2 ;;
  esac
}
trap cleanup EXIT

UPSTREAM_DIR="$TMP_DIR/aya-upstream"

echo "- 克隆上游: $UPSTREAM_URL ($UPSTREAM_REF)"
git init -q "$UPSTREAM_DIR"
git -C "$UPSTREAM_DIR" remote add origin "$UPSTREAM_URL"
# Fetch accepts branches, tags and exact commits (useful for failure replay).
git -C "$UPSTREAM_DIR" fetch --depth=1 origin "$UPSTREAM_REF"
git -C "$UPSTREAM_DIR" checkout -q --detach FETCH_HEAD

UPSTREAM_COMMIT="$(git -C "$UPSTREAM_DIR" rev-parse HEAD)"
UPSTREAM_COMMIT_SHORT="$(git -C "$UPSTREAM_DIR" rev-parse --short HEAD)"
UPSTREAM_COMMIT_DATE="$(git -C "$UPSTREAM_DIR" show -s --format=%cI HEAD)"

echo "- 上游 commit: $UPSTREAM_COMMIT_SHORT"
echo "- 裁剪 workspace: aya + aya-obj"

STAGED_ROOT="$TMP_DIR/patched"
mkdir -p "$STAGED_ROOT"
cp -aL "$UPSTREAM_DIR/aya" "$STAGED_ROOT/aya"
cp -aL "$UPSTREAM_DIR/aya-obj" "$STAGED_ROOT/aya-obj"

cp -f "$UPSTREAM_DIR/LICENSE-APACHE" "$STAGED_ROOT/LICENSE-APACHE"
cp -f "$UPSTREAM_DIR/LICENSE-MIT" "$STAGED_ROOT/LICENSE-MIT"

"$PYTHON_BIN" "$SCRIPT_DIR/trim_workspace.py" "$UPSTREAM_DIR/Cargo.toml" "$STAGED_ROOT/Cargo.toml"
"$PYTHON_BIN" "$SCRIPT_DIR/apply-appopt-patches.py" --root "$STAGED_ROOT"
"$PYTHON_BIN" "$SCRIPT_DIR/apply-appopt-patches.py" --root "$STAGED_ROOT" --check

cat > "$STAGED_ROOT/UPSTREAM.md" <<EOF
# 上游同步状态

- 上游仓库：$UPSTREAM_URL
- 上游分支：$UPSTREAM_REF
- 上游 commit：$UPSTREAM_COMMIT
- 上游 commit 时间：$UPSTREAM_COMMIT_DATE

本仓库只保留上游 Aya 的 \`aya\` 和 \`aya-obj\` crate。
EOF

# Only replace the vendored sources after every patch passed validation.
# These are fixed children of the script's repository, never env-provided paths.
for crate in aya aya-obj; do
  if [ -L "$REPO_ROOT/$crate" ]; then
    echo "拒绝替换符号链接: $REPO_ROOT/$crate" >&2
    exit 1
  fi
done
rm -rf -- "$REPO_ROOT/aya" "$REPO_ROOT/aya-obj"
cp -a "$STAGED_ROOT/aya" "$STAGED_ROOT/aya-obj" "$REPO_ROOT/"
cp -f "$STAGED_ROOT/Cargo.toml" "$STAGED_ROOT/LICENSE-APACHE" \
  "$STAGED_ROOT/LICENSE-MIT" "$STAGED_ROOT/UPSTREAM.md" "$REPO_ROOT/"

echo "- 同步完成"
