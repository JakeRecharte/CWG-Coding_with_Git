"""
CWG command-line dispatcher.

  cwg run <file.cwg|url>   — execute a .cwg program or git repo
  cwg [scrape] [repo]      — scrape a git repo (default behaviour)
"""

import sys


def main() -> None:
    args = sys.argv[1:]

    if args and args[0] == "run":
        sys.argv = [sys.argv[0]] + args[1:]
        from .runner import main as run_main
        run_main()
    else:
        from .gpScraper import main as scrape_main
        scrape_main()
