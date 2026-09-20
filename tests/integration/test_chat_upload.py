"""AI 助手聊天文件上传接口集成测试"""

import io
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from cygnusx.core.security import create_access_token
from cygnusx.infrastructure.config.storage_config import StorageConfig
from cygnusx.infrastructure.storage import reset_storage_backend
from cygnusx.infrastructure.storage.path_factory import get_path_factory


@pytest.fixture
def storage_path(tmp_path: Path, monkeypatch) -> Path:
    """把存储根目录指向临时目录，避免测试写 /data/cygnusx。"""
    root = tmp_path / "data"

    def _fake_config():
        return StorageConfig(data_root=str(root), users_subdir="users")

    # get_storage_config 被多个模块 import 到局部命名空间，需同步 patch 才能生效
    targets = [
        "cygnusx.infrastructure.config.storage_config.get_storage_config",
        "cygnusx.infrastructure.storage.path_factory.get_storage_config",
        "cygnusx.infrastructure.storage.backend.get_storage_config",
    ]
    for target in targets:
        monkeypatch.setattr(target, _fake_config)
    # 清除路径工厂与存储后端单例缓存，确保新配置生效
    get_path_factory.cache_clear()
    reset_storage_backend()
    return root


@pytest.fixture
async def client(storage_path: Path) -> AsyncIterator[AsyncClient]:
    """在临时存储目录配置就绪后再创建 ASGI 客户端。"""
    from cygnusx.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """生成测试用 Token（AuthMiddleware 仅校验签名，不查库）。"""
    token = create_access_token("test-user")
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_chat_upload_csv(client: AsyncClient, auth_headers: dict[str, str], storage_path: Path) -> None:
    """CSV 文件应被成功接收并保存到用户 workspace/chat-uploads。"""
    csv_content = "gene,log2FoldChange,pvalue\nA1BG,1.0,0.01\n"
    response = await client.post(
        "/api/v1/files/chat-upload",
        files={"file": ("volcano_test_data.csv", io.BytesIO(csv_content.encode()), "text/csv")},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "id" in body
    assert body["name"] == "volcano_test_data.csv"
    assert "/api/v1/files/chat-upload/test-user/" in body["url"]

    # 验证文件真实落盘到 workspace/chat-uploads
    expected_dir = storage_path / "users" / "test-user" / "workspace" / "chat-uploads"
    file_path = expected_dir / f"{body['id']}.csv"
    assert file_path.exists()
    assert file_path.read_text() == csv_content


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("ml_tree.iqtree", "IQ-TREE 2.3.0\nSeed: 42\n"),
        ("ml.treefile", "((A:0.1,B:0.2):0.3,C:0.4);\n"),
        ("ml.contree", "((A:0.1,B:0.2):0.3,C:0.4);\n"),
        ("nj.bionj", "((A:0.1,B:0.2):0.3,C:0.4);\n"),
        ("beast_run.trees", "#NEXUS\nBegin trees;\nEnd;\n"),
        ("ml.mldist", "3\nA 0.0 0.1 0.2\n"),
        ("ml.ufboot", "(A,B,C);\n"),
        ("iqtree_run.log", "IQ-TREE multicore version 2.3.0\n"),
        ("msa.aln", "CLUSTAL W alignment\n"),
        ("msa.phy", " 3 42\nA ACGT\n"),
        ("msa.phylip", " 3 42\nA ACGT\n"),
        ("rfam.sto", "# STOCKHOLM 1.0\n"),
        ("seqs.faa", ">protA\nMKLV\n"),
        ("cds.ffn", ">geneA\nATGC\n"),
        ("genes.gff3", "##gff-version 3\n"),
    ],
)
@pytest.mark.asyncio
async def test_chat_upload_accepts_phylogenetic_formats(
    client: AsyncClient,
    auth_headers: dict[str, str],
    storage_path: Path,
    filename: str,
    content: str,
) -> None:
    """建树产物（IQ-TREE/BEAST 等）与比对格式应被成功接收并落盘。"""
    suffix = Path(filename).suffix
    response = await client.post(
        "/api/v1/files/chat-upload",
        files={"file": (filename, io.BytesIO(content.encode()), "application/octet-stream")},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == filename

    expected_dir = storage_path / "users" / "test-user" / "workspace" / "chat-uploads"
    file_path = expected_dir / f"{body['id']}{suffix}"
    assert file_path.exists()
    assert file_path.read_text() == content


@pytest.mark.asyncio
async def test_chat_upload_rejects_unknown_suffix(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """未登记的扩展名仍应被拒绝（白名单语义不放松）。"""
    response = await client.post(
        "/api/v1/files/chat-upload",
        files={"file": ("mystery.xyz", io.BytesIO(b"x"), "application/octet-stream")},
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert "不支持的文件类型" in response.text


@pytest.mark.asyncio
async def test_chat_upload_rejects_executable(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    """可执行扩展名应被拒绝。"""
    response = await client.post(
        "/api/v1/files/chat-upload",
        files={"file": ("bad.exe", io.BytesIO(b"x"), "application/octet-stream")},
        headers=auth_headers,
    )
    assert response.status_code == 422
    assert "禁止上传可执行文件" in response.text


@pytest.mark.asyncio
async def test_chat_upload_requires_auth(client: AsyncClient) -> None:
    """未携带 Token 应返回 401。"""
    response = await client.post(
        "/api/v1/files/chat-upload",
        files={"file": ("volcano_test_data.csv", io.BytesIO(b"x"), "text/csv")},
    )
    assert response.status_code == 401
