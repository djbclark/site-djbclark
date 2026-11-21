# local-marketplace — Claude Code LSP plugin (`local-lsp`)

Registers language servers with Claude Code's `LSP` tool: basedpyright
(Python), marksman (Markdown), taplo (TOML), gopls (Go),
typescript-language-server (TS/JS), kotlin-lsp (Kotlin). Rust and C/C++ come
from the official `rust-analyzer-lsp` / `clangd-lsp` plugins.

Install (from any machine, after `brew install basedpyright marksman gopls
typescript-language-server taplo kotlin-lsp`):

    claude plugin marketplace add ~/ops/site-public-djbclark/claude/local-marketplace
    claude plugin install local-lsp@local     # then /reload-plugins

RAM guard (basedpyright, marksman, typescript-language-server):
- These entries start through `lsp-root-guard` from the djbclark-ade checkout
  (`ade update` links it into `~/.local/bin`). It starts the server with no
  workspace root when Claude Code's root is a container such as `~` or
  `~/src`, so one server does not index every repo.
- If the guard is off, missing from PATH, or fails `lsp-root-guard --check /`
  (for example an import error), the plain server starts UNGUARDED and one
  line goes to stderr (visible with `claude --debug`) and to
  `~/.local/state/lsp-guard/unguarded.log`.
- Off switch: `ADE_LSP_ROOT_GUARD=off` in `~/.claude/settings.json` `env`,
  then restart sessions (only the exact lowercase `off` counts). A guard that
  starts and then crashes is not covered.

Notes:
- Claude Code caches the plugin: **bump `version`** in both `marketplace.json`
  and `plugin.json` after editing `.lsp.json`, then `claude plugin update
  local-lsp@local` and `/reload-plugins`.
- One server per file extension. Python uses basedpyright (navigation, hover,
  types). Ruff's server has no hover/definition/references, so it is not a
  substitute; ruff stays the linter/formatter (pre-commit, `just`).
- TypeScript: typescript-language-server needs a JS-based `tsserver.js`, which
  TypeScript 7 (native, Homebrew's `tsc`) does not ship. TS 5 is installed
  privately for the LSP only, so `tsc` stays at 7:
  `npm i --prefix ~/.local/share/tsserver-ts5 typescript@5`.
- kotlin-lsp is a cask that macOS quarantines; see `bin/brew-unquarantine`.
