"""Check that nothing from the real export reaches a tracked file.

Reads the real counterparty names and identifiers from private/ (which only
exists on the maintainer's machine) and looks for them in every file git
tracks or is about to track. Exit 1 means do not commit.

    python tools/check_publishable.py
"""

from __future__ import annotations

import csv
import io
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRIVATE = ROOT / "private"
EXPORTS = [PRIVATE / "reports" / "Download.CSV", PRIVATE / "Download.CSV"]
FIELDS = ("Name", "From Email Address", "To Email Address", "Transaction ID", "Reference Txn ID",
          "Item Title", "Subject", "Note", "Contact Phone Number", "Address Line 1", "Invoice Number")
GENERIC = {"limited", "company", "international", "services", "payments", "payment", "commerce",
           "corporation", "online", "technologies", "unlimited", "festival", "ireland", "finland",
           "netherlands", "nordic"}
# Company names that appear in the repo for reasons unrelated to the account: Google AP2 is named
# as prior art, and Dropbox as the file-sync tool that locks files on the build machine.
ALLOWED = {"google", "dropbox"}


def secrets_from_private() -> tuple[set[str], set[str]]:
    values: set[str] = set()
    words: set[str] = set()
    for path in EXPORTS:
        if not path.exists():
            continue
        text = path.read_bytes().decode("utf-8-sig", errors="replace")
        for row in csv.DictReader(io.StringIO(text)):
            for f in FIELDS:
                v = (row.get(f) or "").strip()
                if len(v) >= 4:
                    values.add(v.lower())
            words |= {w.lower() for w in re.findall(r"[A-Za-z]{5,}", row.get("Name") or "")}
    raw = PRIVATE / "autopay_raw.txt"
    if raw.exists():
        text = raw.read_text(encoding="utf-8", errors="replace")
        values |= {m.lower() for m in re.findall(r"\bB-[0-9A-Z]{10,}\b", text)}
        values |= {m.lower() for m in re.findall(r"https?://[^\s/]+", text) if "paypal.com" not in m}
    cats = PRIVATE / "merchant_categories.yml"
    if cats.exists():
        for line in cats.read_text(encoding="utf-8").splitlines():
            if ":" in line and not line.startswith("#"):
                name = line.rsplit(":", 1)[0].strip()
                values.add(name.lower())
                words |= {w.lower() for w in re.findall(r"[A-Za-z]{5,}", name)}
    return {v for v in values if v not in ALLOWED}, words - GENERIC - ALLOWED


def tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                         cwd=ROOT, capture_output=True, text=True).stdout
    return [ROOT / p for p in out.splitlines() if p]


def main() -> int:
    values, words = secrets_from_private()
    if not values:
        print("private/ has no export here; nothing to compare against (fine on CI or a clone)")
        return 0
    problems = []
    for path in tracked_files():
        if not path.is_file() or path.suffix in (".pyc", ".png", ".jpg", ".zip"):
            continue
        low = path.read_text(encoding="utf-8", errors="replace").lower()
        rel = path.relative_to(ROOT).as_posix()
        for v in values:
            if v in low:
                problems.append(f"{rel}: contains a value from the real export ({v[:3]}...)")
        for w in words:
            if re.search(rf"\b{re.escape(w)}\b", low):
                problems.append(f"{rel}: contains a word from a real counterparty name ({w[:3]}...)")
    print(f"compared {len(values)} values and {len(words)} name words against {len(tracked_files())} files")
    if problems:
        print(f"\n{len(problems)} PROBLEMS - do not commit")
        for p in sorted(set(problems)):
            print("  x " + p)
        return 1
    print("nothing from the real export appears in tracked files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
