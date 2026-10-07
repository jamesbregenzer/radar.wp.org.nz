#!/usr/bin/env python3
"""Run one unattended Radar V2 acquisition, processing, and publication cycle."""
from __future__ import annotations
import argparse, fcntl, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from acquire import acquire_run  # noqa: E402
from process import build_feed, load_input  # noqa: E402

LOCK = ROOT / "data" / ".radar-run.lock"
FEED = ROOT / "data" / "candidate-feed.json"

def validate_feed(feed: dict) -> None:
    if feed.get("schema") != "radar-candidate-feed.v2": raise ValueError("invalid candidate feed schema")
    if not isinstance(feed.get("candidates"), list) or feed.get("candidateCount") != len(feed["candidates"]): raise ValueError("invalid candidate feed candidate count")
    if not feed.get("feedRevision"): raise ValueError("candidate feed has no revision")

def git(*args: str) -> None:
    subprocess.run(["git", *args], cwd=ROOT, check=True)

def run_once() -> int:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open("a+") as handle:
        try: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return 2
        manifest = acquire_run()
        if not manifest.get("success"): raise RuntimeError("no source acquired successfully")
        previous_feed = load_input(FEED) if FEED.exists() else None
        old_text = FEED.read_text(encoding="utf-8") if FEED.exists() else None
        feed = build_feed(manifest, previous=previous_feed)
        validate_feed(feed)
        FEED.write_text(json.dumps(feed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        git("add", "data/candidate-feed.json")
        if old_text != FEED.read_text(encoding="utf-8"):
            git("add", f"data/raw/{manifest['runId']}")
        changed = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode != 0
        if changed:
            git("commit", "-m", "Update Radar V2 candidate feed")
            git("pull", "--rebase")
            git("push")
        return 0

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.parse_args(); return run_once()
if __name__ == "__main__": raise SystemExit(main())
