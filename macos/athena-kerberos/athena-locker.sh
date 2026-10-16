# Source from a shell rc (install.sh adds it to ~/.bashrc.local).
# `add` must run in the current shell to change PATH, so it is a function that
# evals what `athena-locker add -b` prints. attach/detach/fsid are plain
# commands (~/.local/bin).
add() { eval "$(command add -b "$@")"; }
