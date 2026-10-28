#!/usr/bin/env python3
"""Bidirectional DB shard CLI used by GitHub Actions workflows.

Usage:
    python scripts/db_shard.py shard      <db_path>    <output_dir>
    python scripts/db_shard.py reassemble <input_dir>  <db_path>

Reads the v2 password from STUID + UISPSW env vars. Reassembly can fall
back to PREVIOUS_UISPSW after a password change; writes always use UISPSW.
Both subcommands
operate on the layout produced by `src.sharder`:
    <dir>/icourse-index.enc
    <dir>/shards/shard-NNNN.db.gz.enc
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.crypto_box import derive_new_password
from src.data.sharder import (
    INDEX_FILENAME,
    SHARDS_DIR,
    load_index,
    reassemble_database,
    shard_database,
)


def _password(previous: bool = False) -> str:
    stuid = os.environ.get("STUID") or os.environ.get("StuId", "")
    uispsw = (os.environ.get("PREVIOUS_UISPSW", "") if previous else
              os.environ.get("UISPSW") or os.environ.get("UISPsw", ""))
    if not stuid or not uispsw:
        print("error: STUID and UISPSW env vars required", file=sys.stderr)
        sys.exit(2)
    return derive_new_password(stuid, uispsw)


def _cmd_shard(db_path: str, output_dir: str):
    if not os.path.isfile(db_path):
        print(f"error: not a file: {db_path}", file=sys.stderr)
        sys.exit(1)
    os.makedirs(output_dir, exist_ok=True)
    index = shard_database(db_path, output_dir, _password())
    n = len(index["shards"])
    print(f"sharded → {n} shard(s) under {output_dir}/")


def _cmd_reassemble(input_dir: str, db_path: str):
    index_path = os.path.join(input_dir, INDEX_FILENAME)
    if not os.path.isfile(index_path):
        print(f"error: index not found at {index_path}", file=sys.stderr)
        sys.exit(1)
    pw = _password()
    version = "current"
    try:
        index = load_index(index_path, pw)
    except ValueError:
        if not os.environ.get("PREVIOUS_UISPSW"):
            raise ValueError(
                "Cannot decrypt database index. If UISPSW changed, add the "
                "old password as the PREVIOUS_UISPSW Actions secret and retry. "
                "The existing database has not been replaced."
            ) from None
        pw = _password(previous=True)
        try:
            index = load_index(index_path, pw)
        except ValueError:
            raise ValueError(
                "Cannot decrypt database index with UISPSW or PREVIOUS_UISPSW. "
                "Check the credentials and encrypted data; no database was replaced."
            ) from None
        version = "previous"
    if (not isinstance(index, dict) or not index.get("shards")
            or not isinstance(index["shards"], list)):
        raise ValueError("Invalid database index: expected a non-empty shard list")
    shards_dir = os.path.join(input_dir, SHARDS_DIR)
    # Reassembly writes incrementally. Never expose a partial DB to the
    # workflow's always-run deploy step if a later shard is missing/corrupt.
    parent = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(parent, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".reassemble-", suffix=".db", dir=parent)
    os.close(fd)
    try:
        reassemble_database(index, shards_dir, temporary, pw)
        conn = sqlite3.connect(temporary)
        try:
            if conn.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise ValueError("Reassembled database failed SQLite integrity check")
        finally:
            conn.close()
        os.replace(temporary, db_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a", encoding="utf-8") as f:
            f.write(f"db_key_version={version}\n")
    if version == "previous":
        print("Recovered with PREVIOUS_UISPSW; deploy will encrypt with current UISPSW.")
    n = len(index["shards"])
    print(f"reassembled {n} shard(s) → {db_path}")


def main():
    if len(sys.argv) != 4:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    cmd, a, b = sys.argv[1], sys.argv[2], sys.argv[3]
    if cmd == "shard":
        _cmd_shard(a, b)
    elif cmd == "reassemble":
        _cmd_reassemble(a, b)
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
