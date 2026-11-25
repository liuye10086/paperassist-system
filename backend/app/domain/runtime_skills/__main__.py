"""Build-time and operator check for the installed Skills release."""

import argparse
import os
from pathlib import Path

from .registry import SkillError, check_release, publish
from .runtime import skills_root, verify_steps


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--write', action='store_true', help='publish the current source files and version history')
    args = parser.parse_args()
    try:
        root = args.root or skills_root()
        if args.write:
            pack = publish(root, verify=verify_steps)
        else:
            pack = check_release(root, expected_sha256=os.getenv('PAPERASSIST_SKILLS_MANIFEST_SHA256') or None)
            verify_steps(pack)
    except SkillError as exc:
        parser.exit(1, f'Skills release error: {exc}\n')
    print(pack.sha256)


if __name__ == '__main__':
    main()
