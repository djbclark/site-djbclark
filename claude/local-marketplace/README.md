# local-marketplace — Claude Code LSP plugin (`local-lsp`)

Registers language servers with Claude Code's `LSP` tool: basedpyright
(Python), marksman (Markdown), taplo (TOML), gopls (Go),
typescript-language-server (TS/JS), kotlin-lsp (Kotlin). Rust and C/C++ come
from the official `rust-analyzer-lsp` / `clangd-lsp` plugins.

Install (from any machine, after `brew install basedpyright marksman gopls
typescript-language-server taplo kotlin-lsp`):

    claude plugin marketplace add ~/ops/site-private/claude/local-marketplace
    claude plugin install local-lsp@local     # then /reload-plugins

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
