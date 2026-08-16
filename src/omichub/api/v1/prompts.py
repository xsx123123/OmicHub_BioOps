"""前端可用的外置用户提示词模板。"""

from typing import Any

from fastapi import APIRouter

from omichub.infrastructure.config.prompt_loader import prompt_registry

router = APIRouter()


@router.get("/user-templates/bio")
async def get_bio_prompt_templates() -> dict[str, Any]:
    return prompt_registry.get_mapping("user_templates.bio")
