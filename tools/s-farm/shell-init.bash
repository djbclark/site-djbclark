# Interactive bash integration for the ~/s farm. Source it from the interactive
# part of ~/.bashrc, after anything that replaces PROMPT_COMMAND.
#
# While the working directory is inside ~/s, `just NAME` with a NAME that is
# not a recipe of ~/s/justfile changes to the matching directory in ~/src:
# exact name, glob, partial, abbreviation or typo (see go.py). One match is
# taken at once; several open an arrow-key list. Outside ~/s nothing is
# defined or changed: `just` is the real just.
#
# Why an alias: bash expands globs (and, with failglob, rejects unmatched
# ones) before any command sees them, so `just physi*` could never arrive
# intact. The alias switches globbing off for that one command line and
# _sfarm_just switches it back on. A prompt hook adds the alias on entering
# the farm and removes it on leaving.

_sfarm_tool=${BASH_SOURCE[0]%/*}

_sfarm_just() {
    set +f
    unset _sfarm_noglob
    local dest
    if [[ $# -eq 1 && $1 != -* && $1 != *=* ]] &&
        ! command just --summary 2>/dev/null | tr ' ' '\n' | grep -qxF -- "$1"; then
        dest=$("$_sfarm_tool/go.py" --src "${SFARM_SRC:-$HOME/src}" --farm "${SFARM_FARM:-$HOME/s}" "$1") || return
        cd -- "$dest" && pwd
        return
    fi
    command just "$@"
}

_sfarm_prompt() {
    local status=$? farm=${SFARM_FARM:-$HOME/s} here
    # A command line that died before _sfarm_just ran would leave globbing off.
    if [[ -n ${_sfarm_noglob-} ]]; then
        set +f
        unset _sfarm_noglob
    fi
    here=$(pwd -P)
    if [[ $here == "$farm" || $here == "$farm"/* ]]; then
        alias just='_sfarm_noglob=1; set -f; _sfarm_just'
    elif [[ $(alias just 2>/dev/null) == *_sfarm_just* ]]; then
        unalias just
    fi
    return $status
}

if [[ $(declare -p PROMPT_COMMAND 2>/dev/null) == "declare -a"* ]]; then
    [[ " ${PROMPT_COMMAND[*]} " == *" _sfarm_prompt "* ]] || PROMPT_COMMAND+=(_sfarm_prompt)
elif [[ ${PROMPT_COMMAND-} != *_sfarm_prompt* ]]; then
    PROMPT_COMMAND="${PROMPT_COMMAND:+${PROMPT_COMMAND%;};}_sfarm_prompt"
fi
