"""产物 manifest 对账单测（sha256 实测 + 声明 glob 对账，OpenAI4S 契约语义）。"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from cygnusx.application.services.artifact_manifest import (
    build_file_entry,
    build_manifest,
    reconcile_declared,
    sha256_stream,
    unverified_paths,
    verified_paths,
)


@pytest.mark.unit
def test_sha256_stream_matches_reference(tmp_path: Path):
    target = tmp_path / "blob.bin"
    payload = b"omic-hub-wp2-" * 1000
    target.write_bytes(payload)
    assert sha256_stream(target) == hashlib.sha256(payload).hexdigest()


@pytest.mark.unit
def test_sha256_stream_missing_file_returns_empty(tmp_path: Path):
    assert sha256_stream(tmp_path / "nope.bin") == ""


@pytest.mark.unit
def test_build_file_entry_records_path_size_sha256(tmp_path: Path):
    target = tmp_path / "out" / "de.csv"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"gene,A\n")
    entry = build_file_entry(tmp_path, target)
    assert entry == {
        "path": "out/de.csv",
        "size": 7,
        "sha256": hashlib.sha256(b"gene,A\n").hexdigest(),
    }


@pytest.mark.unit
def test_build_file_entry_unreadable_marks_error_not_raise(tmp_path: Path):
    # 目录伪装成文件：stat 成功、open 失败 → 记 error，不抛出
    fake = tmp_path / "fake.txt"
    fake.mkdir()
    entry = build_file_entry(tmp_path, fake)
    assert entry["path"] == "fake.txt"
    assert entry["sha256"] is None and entry["size"] is None and entry["error"]


@pytest.mark.unit
def test_build_manifest_sorted_and_complete(tmp_path: Path):
    (tmp_path / "b.txt").write_bytes(b"b")
    (tmp_path / "a.txt").write_bytes(b"a")
    entries = build_manifest(tmp_path, [tmp_path / "b.txt", tmp_path / "a.txt"])
    assert [e["path"] for e in entries] == ["a.txt", "b.txt"]


@pytest.mark.unit
def test_reconcile_no_declaration_features_everything_verified():
    entries = [{"path": "x.csv", "size": 1, "sha256": "abc"}]
    featured, missing = reconcile_declared(entries, None)
    assert featured == ["x.csv"] and missing == []


@pytest.mark.unit
def test_reconcile_matches_path_and_basename_glob():
    entries = [
        {"path": "results/a.csv", "size": 1, "sha256": "h1"},
        {"path": "figures/b.png", "size": 2, "sha256": "h2"},
    ]
    featured, missing = reconcile_declared(entries, ["*.csv", "figures/*.png", "nope.*"])
    assert featured == ["results/a.csv", "figures/b.png"]
    assert missing == ["nope.*"]


@pytest.mark.unit
def test_reconcile_unverified_entry_cannot_satisfy_declaration():
    # 路径本身不是证据：没有 hash 的文件不能兑现声明（OpenAI4S 同款语义）
    entries = [{"path": "broken.csv", "size": None, "sha256": None, "error": "boom"}]
    featured, missing = reconcile_declared(entries, ["broken.csv"])
    assert featured == [] and missing == ["broken.csv"]
    assert unverified_paths(entries) == ["broken.csv"]
    assert verified_paths(entries) == []
