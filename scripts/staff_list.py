import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_roster, staff_of
from mailer import staff_address


def main():
    nums = sorted({staff_of(v["id"]) for v in load_roster()} - {""}, key=lambda s: int(s[1:]))
    ok = [s for s in nums if staff_address(s)]
    if len(ok) < len(nums):
        print(f"::warning::{len(nums) - len(ok)} staff number(s) have ships but no address in STAFF_EMAILS.", file=sys.stderr)
    print(" ".join(ok))
    return 0


if __name__ == "__main__":
    sys.exit(main())
