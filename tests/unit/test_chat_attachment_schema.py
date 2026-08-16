from omichub.application.schemas.chat import ChatAttachment


def test_workspace_attachment_preserves_file_reference() -> None:
    attachment = ChatAttachment(
        type="file",
        url="/api/v1/files/00000000-0000-0000-0000-000000000001/download",
        name="docs/26.7.25/image copy 4.png",
        mime_type="image/png",
        file_id="file://00000000-0000-0000-0000-000000000001",
        source="workspace",
    )

    payload = attachment.model_dump()

    assert payload["file_id"].startswith("file://")
    assert payload["source"] == "workspace"


def test_workspace_directory_attachment_preserves_controlled_reference() -> None:
    attachment = ChatAttachment(
        type="directory",
        name="project/raw-data/",
        file_id="directory://00000000-0000-0000-0000-000000000001",
        source="workspace",
        recursive=True,
    )

    payload = attachment.model_dump()

    assert payload["type"] == "directory"
    assert payload["file_id"].startswith("directory://")
    assert payload["recursive"] is True
