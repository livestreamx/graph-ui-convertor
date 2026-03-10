from __future__ import annotations

from typing import Any

from scripts.seed_s3 import clear_prefix


class FakeS3Client:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.list_calls: list[dict[str, Any]] = []
        self.delete_calls: list[dict[str, Any]] = []

    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]:
        self.list_calls.append(kwargs)
        if not self._responses:
            raise AssertionError("Unexpected list_objects_v2 call")
        return self._responses.pop(0)

    def delete_objects(self, **kwargs: Any) -> dict[str, Any]:
        self.delete_calls.append(kwargs)
        return {"Deleted": kwargs["Delete"]["Objects"]}


def test_clear_prefix_deletes_existing_objects_before_seed() -> None:
    client = FakeS3Client(
        [
            {
                "IsTruncated": False,
                "Contents": [
                    {"Key": "markup/stale.json"},
                    {"Key": "markup/legacy/old.json"},
                ],
            }
        ]
    )

    removed_count = clear_prefix(client, "cjm-markup", "markup")

    assert removed_count == 2
    assert client.list_calls == [{"Bucket": "cjm-markup", "Prefix": "markup/"}]
    assert client.delete_calls == [
        {
            "Bucket": "cjm-markup",
            "Delete": {
                "Objects": [
                    {"Key": "markup/stale.json"},
                    {"Key": "markup/legacy/old.json"},
                ],
                "Quiet": True,
            },
        }
    ]


def test_clear_prefix_handles_empty_prefix_without_deletes() -> None:
    client = FakeS3Client([{"IsTruncated": False, "Contents": []}])

    removed_count = clear_prefix(client, "cjm-markup", "markup/")

    assert removed_count == 0
    assert client.list_calls == [{"Bucket": "cjm-markup", "Prefix": "markup/"}]
    assert client.delete_calls == []
