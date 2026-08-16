from pathlib import Path


def test_sync_knowledge_target_imports_qc_and_cloud() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    target = makefile.split("sync-knowledge: wait-web", 1)[1].split("\ninit-admin:", 1)[0]

    assert "scripts/sync_knowledge_from_files.py" in target
    assert "scripts/import_qc_knowledge.py --auto-admin" in target
    assert "scripts/import_cloud_knowledge.py --auto-admin" in target


def test_docker_reload_invokes_sync_knowledge() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    target = makefile.split("docker-reload: docker-network", 1)[1].split(
        "\ndocker-dev-refresh:", 1
    )[0]

    assert "sync-knowledge" in target
