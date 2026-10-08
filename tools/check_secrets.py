"""Scan every commit for secrets and for anything from private/.

check_publishable.py looks at the working tree. That is not enough before a
repo goes public, because git history is permanent: a key committed today and
deleted tomorrow is still in the history when the repo flips to public, and
so is every file that was ever tracked.

This scans all commits, all files, all the way back.

    python tools/check_secrets.py
    python tools/check_secrets.py --verbose

Exit 1 means do not push, or do not make it public, depending on what it
found. Read what it says: some findings mean rewrite history, some just mean
rotate a credential.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Patterns worth stopping a push for. Deliberately narrow: a scanner that
# cries wolf gets ignored, and this one has to be trusted the day it fires.
SECRETS = [
    ("AWS access key id", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("AWS secret access key", re.compile(
        r"aws_secret_access_key\s*=\s*\S{20,}", re.I)),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("bearer or api token assignment", re.compile(
        r"(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token)"
        r"\s*[:=]\s*['\"][A-Za-z0-9_\-]{20,}['\"]", re.I)),
    ("Tavily or Brave key", re.compile(r"\btvly-[A-Za-z0-9]{16,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("PayPal access token", re.compile(r"\bA21AA[A-Za-z0-9_\-]{40,}")),
    ("PayPal client id or secret", re.compile(
        r"PAYPAL_CLIENT_(ID|SECRET)\s*=\s*['\"]?[A-Za-z0-9_\-]{40,}")),
    ("LLM key", re.compile(r"LLM_API_KEY\s*=\s*['\"]?[A-Za-z0-9_\-.]{20,}")),
]

# Not secrets, but they identify the account or its people, and a public repo
# is free reconnaissance. Warned about rather than blocked.
IDENTIFYING = [
    ("AWS account id", re.compile(r"\b\d{12}\b")),
    ("SSO portal url", re.compile(r"https://d-[0-9a-z]{10}\.awsapps\.com")),
    ("Identity Center instance", re.compile(r"\bssoins-[0-9a-f]{16}\b")),
]

# Obvious placeholders written into the docs on purpose. A scanner that warns
# about its own examples forever is a scanner people learn to ignore, and the
# one real finding then goes past unread.
PLACEHOLDER = re.compile(
    r"1234567890|0123456789|x{6,}|X{6,}|abcdef0123|EXAMPLE|<[^>]+>", re.I)


def is_placeholder(hit):
    return bool(PLACEHOLDER.search(hit))


# Paths that must never appear in any commit.
FORBIDDEN_PATHS = [
    re.compile(r"^private/"),
    re.compile(r"(^|/)\.aws/"),
    re.compile(r"(^|/)\.env$"),
    re.compile(r"\.pem$"),
    re.compile(r"(^|/)credentials$"),
]

# Files where a 12-digit number is a coincidence rather than an account id.
NUMERIC_NOISE = re.compile(
    r"(embeddings\.json|\.lock$|package-lock|poetry\.lock|\.svg$)")


def git(*args):
    r = subprocess.run(["git"] + list(args), cwd=ROOT,
                       capture_output=True, text=True, errors="replace")
    return r.stdout if r.returncode == 0 else ""


def all_commits():
    out = git("rev-list", "--all")
    return [c for c in out.split() if c]


def main():
    verbose = "--verbose" in sys.argv
    commits = all_commits()
    if not commits:
        print("no commits yet, nothing to scan")
        return 0

    blocking, warnings = [], []

    # ---- 1. paths that were ever tracked ---------------------------------
    tracked = set()
    for line in git("log", "--all", "--pretty=format:", "--name-only").splitlines():
        line = line.strip()
        if line:
            tracked.add(line)
    for path in sorted(tracked):
        for pattern in FORBIDDEN_PATHS:
            if pattern.search(path):
                blocking.append(
                    "{} was committed at some point. It is in history even if "
                    "it is gone now.".format(path))

    # ---- 2. every unique blob, once ---------------------------------------
    # One `git show` per file per commit is O(commits x files) subprocesses and
    # takes minutes on Windows. A check that slow stops being run, which makes
    # it worse than no check. Stream every object instead, deduped by sha.
    blobs = {}
    for line in git("rev-list", "--objects", "--all").splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            blobs.setdefault(parts[0], parts[1])

    scanned = 0
    if blobs:
        proc = subprocess.Popen(
            ["git", "cat-file", "--batch"], cwd=ROOT,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        request = ("\n".join(blobs) + "\n").encode()
        raw, _ = proc.communicate(request)

        # Walk the stream by its own headers rather than by request order, and
        # take the path from the sha the response reports. `rev-list --objects`
        # yields trees as well as blobs, and skipping a tree's header without
        # its body desyncs everything after it, which shows up as findings
        # attributed to the wrong file. A scanner that names the wrong file is
        # worse than one that says nothing.
        offset = 0
        while offset < len(raw):
            header_end = raw.find(b"\n", offset)
            if header_end < 0:
                break
            header = raw[offset:header_end].split()
            if len(header) < 3:
                offset = header_end + 1
                continue
            sha = header[0].decode()
            kind = header[1]
            size = int(header[2])
            body = raw[header_end + 1:header_end + 1 + size]
            offset = header_end + 1 + size + 1
            if kind != b"blob":
                continue

            path = blobs.get(sha, "(unknown path)")
            try:
                text = body.decode("utf-8")
            except UnicodeDecodeError:
                continue
            scanned += 1

            for label, pattern in SECRETS:
                m = pattern.search(text)
                if m:
                    blocking.append("{} in {}: {}".format(
                        label, path, m.group(0)[:24] + "..."))
            if NUMERIC_NOISE.search(path):
                continue
            for label, pattern in IDENTIFYING:
                for m in pattern.finditer(text):
                    if is_placeholder(m.group(0)):
                        continue
                    warnings.append("{} in {}: {}".format(
                        label, path, m.group(0)))
                    break

    print("scanned {} commits".format(len(commits)))
    if verbose:
        print("  {} tracked paths, {} unique blobs scanned".format(
            len(tracked), scanned))

    # ---- 3. is private/ actually ignored, right now -----------------------
    if (ROOT / "private").exists():
        r = subprocess.run(["git", "check-ignore", "-q", "private"],
                           cwd=ROOT, capture_output=True)
        if r.returncode != 0:
            blocking.append("private/ exists and is NOT gitignored")

    seen = set()
    warnings = [w for w in warnings if not (w in seen or seen.add(w))]

    if warnings:
        print("\n{} identifying values (not secrets, but a public repo is "
              "free reconnaissance):".format(len(warnings)))
        for w in warnings[:12]:
            print("  ? " + w)
        if len(warnings) > 12:
            print("  ... and {} more".format(len(warnings) - 12))

    if blocking:
        print("\n{} BLOCKING".format(len(blocking)))
        for b in blocking:
            print("  x " + b)
        print("\nA secret already committed is compromised whether or not you "
              "rewrite history.\nRotate it first, then clean the history.")
        return 1

    print("no secrets found in history")
    if warnings:
        print("Safe to push private. Clear the warnings above before making "
              "the repo public.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
