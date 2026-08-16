"""初始化默认饼干定价策略

用法: python scripts/init_cookies.py
或: docker exec omichub-web python scripts/init_cookies.py
"""

import asyncio
from decimal import Decimal


async def main() -> None:
    from omichub.infrastructure.database.session import get_session_factory
    from omichub.infrastructure.database.repositories.cookie_repository import (
        SqlAlchemyPricingRepository,
    )
    from omichub.domain.cookie.entities import CookiePricing
    from omichub.domain.cookie.value_objects import PricingType, PricingUnit

    default_pricing = [
        CookiePricing(
            pricing_type=PricingType.TASK_TYPE,
            flow_category="rna_seq",
            base_cost=Decimal("1.0"),
            per_sample_cost=Decimal("0.5"),
            per_comparison_cost=Decimal("0.3"),
            unit=PricingUnit.PER_SAMPLE,
            priority=10,
            description="RNA-seq 分析：1.0 基础 + 0.5/样本 + 0.3/比较组",
        ),
        CookiePricing(
            pricing_type=PricingType.TASK_TYPE,
            flow_category="atac_seq",
            base_cost=Decimal("1.0"),
            per_sample_cost=Decimal("0.6"),
            per_comparison_cost=Decimal("0.4"),
            unit=PricingUnit.PER_SAMPLE,
            priority=10,
            description="ATAC-seq 分析：1.0 基础 + 0.6/样本 + 0.4/比较组",
        ),
        CookiePricing(
            pricing_type=PricingType.TASK_TYPE,
            flow_category="scrna_seq",
            base_cost=Decimal("2.0"),
            per_sample_cost=Decimal("1.0"),
            per_comparison_cost=Decimal("0.5"),
            unit=PricingUnit.PER_SAMPLE,
            priority=10,
            description="单细胞 RNA-seq 分析：2.0 基础 + 1.0/样本 + 0.5/比较组",
        ),
        CookiePricing(
            pricing_type=PricingType.RESOURCE,
            resource_type="cpu_core_per_hour",
            base_cost=Decimal("0.1"),
            unit=PricingUnit.PER_CORE_HOUR,
            priority=5,
            description="CPU 核时费率",
        ),
        CookiePricing(
            pricing_type=PricingType.RESOURCE,
            resource_type="memory_gb_per_hour",
            base_cost=Decimal("0.05"),
            unit=PricingUnit.PER_GB_HOUR,
            priority=5,
            description="内存 GB 时费率",
        ),
        CookiePricing(
            pricing_type=PricingType.SANDBOX,
            base_cost=Decimal("0.5"),
            unit=PricingUnit.PER_HOUR,
            priority=10,
            description="沙盒每小时费用",
        ),
        CookiePricing(
            pricing_type=PricingType.BONUS,
            flow_category="signup",
            base_cost=Decimal("100.0"),
            unit=PricingUnit.PER_USER,
            priority=100,
            description="新用户注册赠送",
        ),
    ]

    factory = get_session_factory()
    async with factory() as session:
        repo = SqlAlchemyPricingRepository(session)
        for pricing in default_pricing:
            existing = await repo.find_match(
                flow_category=pricing.flow_category,
                resource_type=pricing.resource_type,
                pricing_type=pricing.pricing_type.value,
            )
            if existing is None:
                await repo.save(pricing)
                print(f"  + 创建: {pricing.pricing_type.value}/{pricing.flow_category or pricing.resource_type} = {pricing.base_cost} {pricing.unit.value}")
            else:
                print(f"  = 已存在: {pricing.pricing_type.value}/{pricing.flow_category or pricing.resource_type}")
        await session.commit()

    print(f"\n默认定价策略初始化完成 ({len(default_pricing)} 条)")


if __name__ == "__main__":
    asyncio.run(main())
