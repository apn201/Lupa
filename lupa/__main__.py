"""Command line: python -m lupa import [csv] [merchants.yml] [--no-shift] | sync | expire | openapi | reset"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .config import ROOT, settings_from_env

DATA = ROOT / "data"


def default_sample() -> tuple[Path, Path]:
    real = DATA / "sample_activity_anonymized.csv"
    if real.exists():
        return real, DATA / "merchants.yml"
    return DATA / "sample_activity_synthetic.csv", DATA / "merchants_synthetic.yml"


def openapi_markdown() -> str:
    from .api.app import create_app
    spec = create_app(workers=False).openapi()
    lines = [f"# {spec['info']['title']}", "", spec["info"].get("description", ""), "",
             "Generated from the OpenAPI document FastAPI emits (`make openapi`). Do not edit by hand.", ""]
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            tag = (op.get("tags") or [""])[0]
            lines.append(f"## {tag} `{method.upper()} {path}`")
            lines.append("")
            if op.get("summary"):
                lines.append(f"**{op['summary']}**")
                lines.append("")
            if op.get("description"):
                lines.append(op["description"].strip())
                lines.append("")
            params = op.get("parameters") or []
            if params:
                lines.append("| parameter | in | required |")
                lines.append("|---|---|---|")
                for p in params:
                    lines.append(f"| `{p['name']}` | {p['in']} | {p.get('required', False)} |")
                lines.append("")
            body = (op.get("requestBody") or {}).get("content", {}).get("application/json", {}).get("schema")
            if body:
                ref = body.get("$ref", "").split("/")[-1]
                schema = spec["components"]["schemas"].get(ref, body)
                lines.append(f"Body `{ref or 'object'}`:")
                lines.append("")
                lines.append("| field | type | default |")
                lines.append("|---|---|---|")
                for name, prop in schema.get("properties", {}).items():
                    typ = prop.get("type") or " | ".join(
                        x.get("type", x.get("$ref", "").split("/")[-1]) for x in prop.get("anyOf", [])) or \
                        prop.get("$ref", "").split("/")[-1]
                    if "enum" in prop:
                        typ = " \\| ".join(prop["enum"])
                    default = "required" if name in schema.get("required", []) else json.dumps(prop.get("default"))
                    lines.append(f"| `{name}` | {typ} | {default} |")
                lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "help"
    if cmd == "openapi":
        out = ROOT / "docs" / "api.md"
        out.write_text(openapi_markdown(), encoding="utf-8")
        (ROOT / "docs" / "openapi.json").write_text(
            json.dumps(__import__("lupa.api.app", fromlist=["create_app"]).create_app(workers=False).openapi(),
                       indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"wrote {out.relative_to(ROOT)} and docs/openapi.json")
        return 0

    from .service import Lupa
    s = settings_from_env()
    if cmd == "reset":
        p = Path(s.db_path)
        for f in (p, p.with_name(p.name + "-wal"), p.with_name(p.name + "-shm")):
            if f.exists():
                f.unlink()
        print(f"removed {s.db_path}")
        return 0
    lp = Lupa(s)
    if cmd == "import":
        shift = "--no-shift" not in argv
        argv = [a for a in argv if a != "--no-shift"]
        csv_path, known = default_sample()
        if len(argv) > 1:
            csv_path = Path(argv[1])
        if len(argv) > 2:
            known = Path(argv[2])
        print(lp.import_csv(str(csv_path), str(known), shift_to_now=shift))
        print(lp.headline()["text"])
        return 0
    if cmd == "sync":
        print(lp.sync())
        return 0
    if cmd == "expire":
        print(lp.expire_holds())
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
