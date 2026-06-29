#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

UPSTREAM_URL="${AYA_UPSTREAM_URL:-https://github.com/aya-rs/aya.git}"
UPSTREAM_REF="${AYA_UPSTREAM_REF:-main}"

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="${PYTHON:-python3}"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="${PYTHON:-python}"
else
  echo "错误: 找不到 python3/python" >&2
  exit 1
fi

if [ -n "${SYNC_TMP_DIR:-}" ]; then
  TMP_DIR="$SYNC_TMP_DIR"
  rm -rf "$TMP_DIR"
  mkdir -p "$TMP_DIR"
else
  TMP_DIR="$(mktemp -d)"
fi

cleanup() {
  if [ -z "${SYNC_TMP_DIR:-}" ]; then
    rm -rf "$TMP_DIR"
  fi
}
trap cleanup EXIT

UPSTREAM_DIR="$TMP_DIR/aya-upstream"

echo "- 克隆上游: $UPSTREAM_URL ($UPSTREAM_REF)"
git clone --depth=1 --branch "$UPSTREAM_REF" "$UPSTREAM_URL" "$UPSTREAM_DIR"

UPSTREAM_COMMIT="$(git -C "$UPSTREAM_DIR" rev-parse HEAD)"
UPSTREAM_COMMIT_SHORT="$(git -C "$UPSTREAM_DIR" rev-parse --short HEAD)"
UPSTREAM_COMMIT_DATE="$(git -C "$UPSTREAM_DIR" show -s --format=%cI HEAD)"

echo "- 上游 commit: $UPSTREAM_COMMIT_SHORT"
echo "- 裁剪 workspace: aya + aya-obj"

rm -rf "$REPO_ROOT/aya" "$REPO_ROOT/aya-obj"
cp -aL "$UPSTREAM_DIR/aya" "$REPO_ROOT/aya"
cp -aL "$UPSTREAM_DIR/aya-obj" "$REPO_ROOT/aya-obj"

cp -f "$UPSTREAM_DIR/LICENSE-APACHE" "$REPO_ROOT/LICENSE-APACHE"
cp -f "$UPSTREAM_DIR/LICENSE-MIT" "$REPO_ROOT/LICENSE-MIT"

"$PYTHON_BIN" "$SCRIPT_DIR/trim_workspace.py" "$UPSTREAM_DIR/Cargo.toml" "$REPO_ROOT/Cargo.toml"

cat > "$REPO_ROOT/UPSTREAM.md" <<EOF
# 上游同步状态

- 上游仓库：$UPSTREAM_URL
- 上游分支：$UPSTREAM_REF
- 上游 commit：$UPSTREAM_COMMIT
- 上游 commit 时间：$UPSTREAM_COMMIT_DATE

本仓库只保留上游 Aya 的 \`aya\` 和 \`aya-obj\` crate。
EOF

echo "- 同步完成"
