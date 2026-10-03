#!/usr/bin/env bash
# book-to-kb installer. Idempotent — safe to re-run.
#
#   ./install.sh                 install everything
#   ./install.sh --check         report what is present, change nothing
#   BIN_DIR=... SKILL_DIRS="..." ./install.sh    override destinations
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
VENV="${BOOK_KB_VENV:-$HOME/.local/share/book-kb/venv}"
KB_ROOT="${KB_ROOT:-$HOME/kb}"
PY_VERSION="${BOOK_KB_PYTHON:-3.12}"
CHECK=0
[ "${1:-}" = "--check" ] && CHECK=1

say() { printf '\033[1m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[33m!!!\033[0m %s\n' "$*" >&2; }

# Every user-level skills directory this machine actually has. A skill is a
# directory containing SKILL.md, and all these agents read that same shape.
default_skill_dirs() {
  local d
  for d in "$HOME/.claude/skills" "$HOME/.agents/skills" "$HOME/.codex/skills" \
           "$HOME/.config/opencode/skills" "$HOME/.copilot/skills" \
           "$HOME/.config/agents/skills"; do
    [ -d "$(dirname "$d")" ] && echo "$d"
  done
}
read -r -a SKILL_TARGETS <<<"${SKILL_DIRS:-$(default_skill_dirs | tr '\n' ' ')}"

if [ "$CHECK" = 1 ]; then
  say "check only"
  printf '  %-22s %s\n' uv "$(command -v uv || echo MISSING)"
  printf '  %-22s %s\n' venv "$([ -x "$VENV/bin/docling" ] && echo "$VENV" || echo MISSING)"
  printf '  %-22s %s\n' book-kb "$(command -v book-kb || echo "not on PATH")"
  printf '  %-22s %s\n' KB_ROOT "$([ -d "$KB_ROOT" ] && echo "$KB_ROOT" || echo MISSING)"
  for d in "${SKILL_TARGETS[@]}"; do
    printf '  %-22s %s\n' "skill" "$d/book-to-kb $([ -e "$d/book-to-kb" ] && echo '(linked)' || echo '(absent)')"
  done
  exit 0
fi

# 1. uv — the only hard prerequisite. It manages the Python too, so the system
#    interpreter's version does not matter.
if ! command -v uv >/dev/null 2>&1; then
  warn "uv not found. Install it, then re-run:"
  warn "  curl -LsSf https://astral.sh/uv/install.sh | sh    # or: brew install uv"
  exit 1
fi

# 2. The docling toolchain, pinned to 3.12: torch has no 3.14 wheels, and several
#    distributions now default to 3.13+.
# --allow-existing, not --clear: re-running must not destroy a 1.2 GB venv.
if [ -x "$VENV/bin/python" ]; then
  say "reusing venv at $VENV"
  uv venv --python "$PY_VERSION" --allow-existing "$VENV" >/dev/null
else
  say "creating venv at $VENV (Python $PY_VERSION)"
  uv venv --python "$PY_VERSION" "$VENV" >/dev/null
fi
say "installing docling and the extractor libraries (~1.2 GB, a few minutes)"
uv pip install --python "$VENV/bin/python" --quiet \
  'docling-slim[standard,cli]' \
  ebooklib beautifulsoup4 trafilatura striprtf python-docx pypdf
# macOS gets Apple's Vision OCR, which needs no extra model download.
if [ "$(uname -s)" = "Darwin" ]; then
  uv pip install --python "$VENV/bin/python" --quiet 'docling-slim[feat-ocr-mac]' || \
    warn "ocrmac failed to install; OCR of scanned pages will need another engine"
fi

# 3. The CLI.
say "installing book-kb to $BIN_DIR"
mkdir -p "$BIN_DIR"
install -m 0755 "$HERE/bin/book-kb" "$BIN_DIR/book-kb"
[ -f "$HERE/bin/clip" ] && install -m 0755 "$HERE/bin/clip" "$BIN_DIR/clip"

# 4. The skill. Symlink rather than copy, so updating this checkout updates every
#    agent at once; copies drift.
for d in "${SKILL_TARGETS[@]}"; do
  mkdir -p "$d"
  if [ -e "$d/book-to-kb" ] && [ ! -L "$d/book-to-kb" ]; then
    warn "$d/book-to-kb exists and is not a symlink — leaving it alone"
    continue
  fi
  ln -sfn "$HERE/skills/book-to-kb" "$d/book-to-kb"
  say "linked skill into $d"
done

mkdir -p "$KB_ROOT/sources" "$KB_ROOT/raw" "$KB_ROOT/md"

say "done"
"$BIN_DIR/book-kb" doctor || true
cat <<EOF

Next:
  book-kb extract /path/to/book.epub
  book-kb list
  book-kb query '<regex>' <slug>

If $BIN_DIR is not on your PATH, add it:
  export PATH="\$PATH:$BIN_DIR"
EOF
