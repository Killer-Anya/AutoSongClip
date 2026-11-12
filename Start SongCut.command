#!/bin/bash

cd -- "$(dirname -- "$0")" || exit 1

if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
    printf '%s\n' 'SongCut needs Python 3.10 or later. Install Python from https://www.python.org/downloads/, then reopen this file.' >&2
    if [[ -t 0 ]]; then read -r -p 'Press Enter to close.'; fi
    exit 1
fi

python3 site/server.py --open
songcut_exit=$?
if [[ "$songcut_exit" -ne 0 && -t 0 ]]; then read -r -p 'Press Enter to close.'; fi
exit "$songcut_exit"
