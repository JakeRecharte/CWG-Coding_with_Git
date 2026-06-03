"""
CWG command-line dispatcher.

  cwg run [target]   — execute a CWG program
                       target = GitHub URL or .cwg file; empty = current repo
"""

import sys

_USAGE = (
    "usage: cwg run [target]\n"
    "  target  GitHub repo URL or .cwg file; omit to run the current repo's "
    "git history"
)


def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] != "run":
        print(_USAGE, file=sys.stderr)
        sys.exit(0 if not args else 2)

    sys.argv = [sys.argv[0]] + args[1:]
    from .runner import main as run_main
    run_main()
