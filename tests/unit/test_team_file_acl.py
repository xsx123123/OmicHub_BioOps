"""团队空间文件权限判定单元测试"""

from uuid import UUID, uuid4

import pytest

from omichub.application.services.file_service import FileService
from omichub.core.exceptions import AuthorizationError
from omichub.domain.file.entities import DataFile
from omichub.domain.file.value_objects import OwnerScope
from omichub.domain.team.value_objects import TeamRole


class _FakeFileRepo:
    def __init__(self, file: DataFile | None, role: TeamRole | None = None) -> None:
        self._file = file
        self._role = role

    async def get_visible(self, actor_user_id: UUID, file_id: UUID) -> DataFile | None:
        return self._file

    async def get_team_role(self, team_id: UUID, user_id: UUID) -> TeamRole | None:
        return self._role

    async def delete_visible(self, actor_user_id: UUID, file_id: UUID) -> bool:
        return self._file is not None


def _team_file(*, owner: UUID, actor_role: TeamRole, uploaded_by: UUID | None = None) -> tuple[FileService, DataFile, UUID]:
    actor = uuid4()
    team_id = uuid4()
    file = DataFile(
        id=uuid4(),
        user_id=uploaded_by or owner,
        path=f"teams/{team_id}/report.pdf",
        original_name="report.pdf",
        size=1024,
        owner_scope=OwnerScope.TEAM.value,
        team_id=team_id,
    )
    service = object.__new__(FileService)
    service._files = _FakeFileRepo(file, actor_role)
    return service, file, actor


@pytest.mark.asyncio
async def test_personal_owner_has_full_access() -> None:
    actor = uuid4()
    file = DataFile(
        id=uuid4(),
        user_id=actor,
        path=f"users/{actor}/data.txt",
        original_name="data.txt",
        size=10,
        owner_scope=OwnerScope.PERSONAL.value,
    )
    service = object.__new__(FileService)
    service._files = _FakeFileRepo(file)

    await service._require_read_access(file, actor)
    await service._require_write_access(file, actor)
    await service._require_delete_access(file, actor)


@pytest.mark.asyncio
async def test_other_user_cannot_access_personal_file() -> None:
    actor = uuid4()
    owner = uuid4()
    file = DataFile(
        id=uuid4(),
        user_id=owner,
        path=f"users/{owner}/data.txt",
        original_name="data.txt",
        size=10,
        owner_scope=OwnerScope.PERSONAL.value,
    )
    service = object.__new__(FileService)
    service._files = _FakeFileRepo(file)

    with pytest.raises(AuthorizationError):
        await service._require_read_access(file, actor)
    with pytest.raises(AuthorizationError):
        await service._require_write_access(file, actor)
    with pytest.raises(AuthorizationError):
        await service._require_delete_access(file, actor)


@pytest.mark.asyncio
async def test_team_reader_can_only_read() -> None:
    service, file, actor = _team_file(owner=uuid4(), actor_role=TeamRole.READER)

    await service._require_read_access(file, actor)
    with pytest.raises(AuthorizationError):
        await service._require_write_access(file, actor)
    with pytest.raises(AuthorizationError):
        await service._require_delete_access(file, actor)


@pytest.mark.asyncio
async def test_team_writer_can_write_and_delete_own_file() -> None:
    actor = uuid4()
    service, file, _ = _team_file(owner=uuid4(), actor_role=TeamRole.WRITER, uploaded_by=actor)

    await service._require_read_access(file, actor)
    await service._require_write_access(file, actor)
    await service._require_delete_access(file, actor)


@pytest.mark.asyncio
async def test_team_writer_cannot_delete_others_file() -> None:
    actor = uuid4()
    uploader = uuid4()
    service, file, _ = _team_file(owner=uuid4(), actor_role=TeamRole.WRITER, uploaded_by=uploader)

    await service._require_read_access(file, actor)
    await service._require_write_access(file, actor)
    with pytest.raises(AuthorizationError):
        await service._require_delete_access(file, actor)


@pytest.mark.asyncio
async def test_team_owner_has_full_access() -> None:
    owner_actor = uuid4()
    service, file, _ = _team_file(owner=owner_actor, actor_role=TeamRole.OWNER)

    await service._require_read_access(file, owner_actor)
    await service._require_write_access(file, owner_actor)
    await service._require_delete_access(file, owner_actor)
