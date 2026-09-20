from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from cygnusx.core.config import Settings
from cygnusx.core.exceptions import BusinessError
from cygnusx.infrastructure.storage.minio_store import MinioStore


class FakeClient:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def bucket_exists(self, bucket: str) -> bool:
        return True

    def fput_object(self, bucket: str, key: str, path: str, content_type: str | None = None) -> None:
        self.objects[f"{bucket}/{key}"] = Path(path).read_bytes()

    def fget_object(self, bucket: str, key: str, path: str) -> None:
        Path(path).write_bytes(self.objects[f"{bucket}/{key}"])

    def get_object(self, bucket: str, key: str):
        payload = self.objects[f"{bucket}/{key}"]

        class Response:
            def read(self, size: int) -> bytes:
                return payload[:size]

            def close(self) -> None:
                return None

            def release_conn(self) -> None:
                return None

        return Response()

    def presigned_get_object(self, bucket: str, key: str, *, expires: object) -> str:
        return f"https://minio.local/{bucket}/{key}"

    def list_objects(self, bucket: str, *, prefix: str, recursive: bool) -> list[object]:
        return [
            SimpleNamespace(object_name=key[len(bucket) + 1 :], size=len(value), etag="etag")
            for key, value in self.objects.items()
            if key.startswith(f"{bucket}/{prefix}")
        ]

    def remove_object(self, bucket: str, key: str) -> None:
        del self.objects[f"{bucket}/{key}"]


def test_minio_store_round_trip(tmp_path: Path) -> None:
    client = FakeClient()
    store = MinioStore(Settings(), client=client)
    source = tmp_path / "report.txt"
    source.write_text("complete evidence", encoding="utf-8")

    uri = store.put_case_object("case-1", "work-1/report.txt", source)
    destination = tmp_path / "downloaded.txt"

    assert uri == "s3://agentteams-evidence/case-1/work-1/report.txt"
    assert store.presigned_get("case-1", "work-1/report.txt").endswith(uri[5:])
    assert store.fetch_case_object("case-1", "work-1/report.txt", destination) == destination
    assert destination.read_text(encoding="utf-8") == "complete evidence"
    assert store.read_case_object("case-1", "work-1/report.txt", max_bytes=100) == b"complete evidence"
    assert store.list_case_objects("case-1")[0].key == "work-1/report.txt"
    store.delete_case_prefix("case-1")
    assert store.list_case_objects("case-1") == []


@pytest.mark.parametrize(
    ("case_id", "key"),
    [("../case", "work/file"), ("case", "../file"), ("case", "work/../file")],
)
def test_minio_store_rejects_path_traversal(case_id: str, key: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        MinioStore(Settings(), client=FakeClient()).put_case_object(case_id, key, tmp_path / "x")


def test_minio_store_unavailable_is_business_error() -> None:
    with pytest.raises(BusinessError, match="对象存储不可用"):
        MinioStore(Settings(), client=None, probe=False).list_case_objects("case-1")
