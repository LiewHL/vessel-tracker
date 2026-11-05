"""Print the staff numbers (S1 S2 ...) that have ships and an address in STAFF_EMAILS.

Staff numbers come from the codes (see common.staff_of). Numbers with ships but no address are
skipped; only their count is printed as a warning (never addresses).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_roster, staff_of  # noqa: E402
from mailer import staff_address  # noqa: E402


def main():
    nums = sorted({staff_of(v["id"]) for v in load_roster()} - {""}, key=lambda s: int(s[1:]))
    ok = [s for s in nums if staff_address(s)]
    if len(ok) < len(nums):
        print(f"::warning::{len(nums) - len(ok)} staff number(s) have ships but no address in STAFF_EMAILS.", file=sys.stderr)
    print(" ".join(ok))
    return 0


if __name__ == "__main__":
    sys.exit(main())
