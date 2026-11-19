"""Build the deck: compose, lint, write .pptx."""
from __future__ import annotations

import os
import sys

import build
import slides as deck

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")


def main():
    os.makedirs(OUT, exist_ok=True)
    sl = deck.all_slides()

    issues = []
    for s in sl:
        issues += s.lint()

    for i in issues:
        print("LINT", i)

    path = os.path.join(OUT, "FlashHandoff_v2.pptx")
    build.build(sl, path)

    print(f"\n{len(sl)} slides -> {path}")
    for s in sl:
        over = max((t.overflow() for t in s.texts), default=0)
        print(f"  {s.n:02d}  {s.title:<24}  items={len(s.items):3d}  texts={len(s.texts):2d}  "
              f"max-overflow={max(0, over):.0f}px")
    if issues:
        print(f"\n{len(issues)} lint issue(s)")
        return 1
    print("\nlint clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
