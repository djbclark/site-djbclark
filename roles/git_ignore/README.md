# git_ignore

Tracks the global git excludes file (`~/.config/git/ignore`, git's XDG default
when `core.excludesFile` is unset) and installs it from `files/ignore`.

The repo copy is canonical. Edit `files/ignore`, commit, then `just git-ignore-apply`.

Drift: if the live file exists and differs from the repo copy, the play prints
the diff and fails; it never overwrites silently. Fold the live edits into
`files/ignore`, or force the replacement with
`just git-ignore-apply -e git_ignore_adopt=true` (Ansible keeps a timestamped
backup beside the live file). A symlink or directory at the path is refused.

The file is a plain copy (not a symlink into this checkout) so it survives the
checkout moving. It holds ignore patterns only: no secrets, no absolute paths.

| Recipe | Does |
| --- | --- |
| `just git-ignore-check` | `--check --diff`: shows what would change |
| `just git-ignore-apply` | installs the file |
