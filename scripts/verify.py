#!/usr/bin/env python3
"""Pre-submission sanity check.

Run from repo root: `make verify` (or `python scripts/verify.py`).

Exits 0 if every required artifact is present + REFLECTION.md has been
edited beyond the template. Exits non-zero with a checklist of what's
missing — no files written.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Patterns that indicate the REFLECTION.md is still the template (placeholders left in).
TEMPLATE_MARKERS = [
    r"<Họ Tên>",
    r"<A20-K1 / A20-K2",
    r"<YYYY-MM-DD>",
    r"<macOS 14 / Windows 11",
    r"^_Answer here\._?\s*$",
]


def check_file(path: Path, label: str, problems: list[str]) -> bool:
    if not path.exists():
        problems.append(f"MISSING  {label}: {path}")
        return False
    if path.stat().st_size == 0:
        problems.append(f"EMPTY    {label}: {path}")
        return False
    return True


def check_screenshots(folder: Path, min_count: int, problems: list[str]) -> int:
    if not folder.exists():
        problems.append(f"MISSING  submission/screenshots/ folder")
        return 0
    images = [p for p in folder.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg"}]
    if len(images) < min_count:
        problems.append(
            f"TOO FEW  submission/screenshots/: have {len(images)}, need at least {min_count}. "
            f"See submission/screenshots/README.md for the list."
        )
    return len(images)


def check_reflection_edited(path: Path, problems: list[str]) -> bool:
    if not path.exists():
        problems.append(f"MISSING  submission/REFLECTION.md")
        return False
    text = path.read_text(encoding="utf-8")
    leftover = []
    for pattern in TEMPLATE_MARKERS:
        # Some patterns are line-anchored (start with ^), others are inline.
        flags = re.MULTILINE if pattern.startswith("^") else 0
        if re.search(pattern, text, flags):
            leftover.append(pattern)
    if len(leftover) >= 3:
        problems.append(
            f"UNEDITED submission/REFLECTION.md still has {len(leftover)} template placeholders. "
            f"Fill in your own numbers and answers."
        )
        return False
    return True


def check_active_model(active_json: Path, problems: list[str]) -> bool:
    if not check_file(active_json, "models/active.json", problems):
        return False
    try:
        cfg = json.loads(active_json.read_text(encoding="utf-8"))
    except Exception as exc:
        problems.append(f"CORRUPT  models/active.json — {exc}")
        return False
    primary = Path(cfg.get("primary_model", ""))
    if not primary.exists():
        problems.append(
            f"MISSING  primary GGUF file referenced by models/active.json: {primary}"
        )
        return False
    return True


def maybe_check_server(problems: list[str]) -> None:
    """Optional: if a llama-server is running on :8080, hit it. If not, silent."""
    try:
        import httpx  # noqa: WPS433  — optional import
    except ImportError:
        return
    try:
        r = httpx.post(
            "http://localhost:8080/v1/chat/completions",
            json={
                "model": "local",
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 4,
            },
            timeout=3.0,
        )
        if r.status_code == 200:
            print("  ✓ llama-server reachable on :8080 — serving OpenAI-compat OK")
        else:
            problems.append(
                f"WARN     llama-server on :8080 returned {r.status_code} — "
                f"check it before recording load-test screenshots"
            )
    except Exception:
        # Server not running — that's fine, students may run verify before starting it.
        pass


def main() -> int:
    # Windows consoles default to cp1252, which can't encode the ✓/✗ glyphs
    # below. Force UTF-8 so `make verify` runs clean on a fresh Windows clone.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    repo = Path(__file__).resolve().parent.parent
    problems: list[str] = []

    print(f"==> Verifying submission readiness at {repo}\n")

    # 00-setup artifacts
    check_file(repo / "hardware.json", "hardware.json", problems)
    check_active_model(repo / "models" / "active.json", problems)

    # Track 01
    check_file(
        repo / "benchmarks" / "01-quickstart-results.md",
        "Track 01 results (run `make bench`)",
        problems,
    )

    # Track 02 — at least one of the two evidences should exist
    server_evidence = (
        (repo / "benchmarks" / "02-server-metrics.csv").exists()
        or (repo / "benchmarks" / "02-server-results.md").exists()
    )
    if not server_evidence:
        problems.append(
            "MISSING  Track 02 evidence — neither benchmarks/02-server-metrics.csv "
            "nor benchmarks/02-server-results.md exists. Run a locust load + record-metrics."
        )

    # Submission artifacts
    check_reflection_edited(repo / "submission" / "REFLECTION.md", problems)
    n_shots = check_screenshots(repo / "submission" / "screenshots", min_count=6, problems=problems)
    if n_shots:
        print(f"  ✓ submission/screenshots/ has {n_shots} image(s)")

    # Optional: server health
    maybe_check_server(problems)

    print()
    if not problems:
        print("✓ All checks passed. Push your repo (public!) and paste the URL into LMS.")
        return 0

    print("✗ Submission not ready yet:\n")
    for line in problems:
        print(f"  - {line}")
    print(
        "\nFix the items above and rerun `make verify`. See rubric.md for full grading details."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
