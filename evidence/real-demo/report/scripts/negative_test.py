#!/usr/bin/env python3
"""Negative tests: prove the validator's executive-summary checks actually fire.

Each case copies the workspace to a scratch directory, injects one defect, and
asserts that scripts/validate.py exits non-zero. A case that still passes means
the corresponding check is vacuous.
"""

import os
import shutil
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXEC_REL = os.path.join("artifacts", "executive-summary.md")
SUMMARY_REL = os.path.join("artifacts", "summary.csv")
MINUS = "\u2212"  # the minus sign used in the exec summary identity line


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def edit(path, old, new):
    text = read(path)
    assert old in text, f"anchor not found: {old!r}"
    write(path, text.replace(old, new, 1))


def exec_edit(work, old, new):
    edit(os.path.join(work, EXEC_REL), old, new)


CASES = [
    ("identity operand changed",
     lambda w: exec_edit(w, f"72,000 {MINUS} 45,000 = 27,000", f"72,000 {MINUS} 44,000 = 27,000"),
     "identity operands"),
    ("fabricated figure injected",
     lambda w: exec_edit(w, "客单价 96.64", "客单价 33,500"),
     "trace to source data"),
    ("gross profit renamed net profit",
     lambda w: exec_edit(w, "**不是净利润**", "**即净利润**"),
     "equates gross profit with net profit"),
    ("channel table value altered",
     lambda w: exec_edit(w, "45,000（62.50%）", "46,000（62.50%）"),
     "channel row website matches summary.csv"),
    ("forward target loses its label",
     lambda w: exec_edit(w, "两者均为目标值，非已实现结果", "两者均已实现"),
     "labels forward targets as targets"),
    ("required section removed",
     lambda w: exec_edit(w, "## 四、需要补充的数据", "## 四、其他"),
     "has section: 需要补充的数据"),
    ("data-gap item removed",
     lambda w: exec_edit(w, "新老客、客单价构成、流量与转化", "增长归因不明"),
     "data-gap section names"),
    ("summary.csv total tampered",
     lambda w: edit(os.path.join(w, SUMMARY_REL), "total,ALL,ALL,ALL,72000.00", "total,ALL,ALL,ALL,75000.00"),
     "total revenue == sum of months"),
    ("document exceeds one page",
     lambda w: exec_edit(w, "## 五、局限提醒", "## 五、局限提醒\n\n" + "补充说明。" * 200),
     "fits one page"),
]


def run_case(name, mutate, expect):
    work = tempfile.mkdtemp(prefix="negtest_")
    try:
        for item in ("artifacts", "scripts", "uploads"):
            shutil.copytree(os.path.join(BASE, item), os.path.join(work, item))
        mutate(work)
        proc = subprocess.run([sys.executable, os.path.join(work, "scripts", "validate.py")],
                              cwd=work, capture_output=True, text=True)
        out = proc.stdout + proc.stderr
        failed = [l.strip() for l in out.splitlines() if l.strip().startswith("FAIL")]
        caught = proc.returncode != 0
        hit = any(expect in f for f in failed)
        status = "CAUGHT" if (caught and hit) else "MISSED"
        print(f"  {status}  {name}")
        if status == "MISSED":
            print(f"          exit={proc.returncode} expected-substring={expect!r}")
            for f in failed:
                print(f"          {f}")
        return caught and hit
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    print("negative tests (each injection MUST be caught)")
    results = [run_case(*c) for c in CASES]
    print()
    print(f"{sum(results)}/{len(results)} injections correctly caught")
    if not all(results):
        print("FAILED: some defects slipped through")
        sys.exit(1)
    print("ALL NEGATIVE TESTS PASSED")


if __name__ == "__main__":
    main()
