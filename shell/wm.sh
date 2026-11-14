# Source from ~/.bashrc or ~/.zshrc. A child process cannot change the parent cwd.
wmcd() {
    if [ "$#" -ne 1 ]; then
        printf '%s\n' 'Usage: wmcd <workspace-name-or-id>' >&2
        return 2
    fi
    local wm_destination
    wm_destination=$(wm workspace select "$1" --print-path) || return
    cd -- "$wm_destination" || return
}
