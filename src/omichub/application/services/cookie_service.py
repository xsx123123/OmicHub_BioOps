"""饼干积分应用服务 — 核心业务编排"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.application.schemas.cookie import (
    CookieAccountDTO,
    CookieDiscountDTO,
    CookieDiscountRequest,
    CookieStatsDTO,
    CookieTransactionDTO,
    CostEstimateDTO,
    PricingCreateRequest,
)
from omichub.core.config import get_settings
from omichub.core.exceptions import BusinessError, NotFoundError
from omichub.domain.cookie.entities import CookieAccount, CookiePricing, CookieTransaction
from omichub.domain.cookie.value_objects import (
    AccountStatus,
    PricingType,
    PricingUnit,
    TransactionType,
)
from omichub.infrastructure.database.models.cookie import (
    CookieAccountModel,
    CookieDiscountModel,
    CookieTransactionModel,
)
from omichub.infrastructure.database.repositories.cookie_repository import (
    SqlAlchemyAccountRepository,
    SqlAlchemyConsumptionLogRepository,
    SqlAlchemyPricingRepository,
    SqlAlchemyTransactionRepository,
)


class PricingEngine:
    """定价计算引擎 — 按 flow_category + resource_type + priority 匹配"""

    def __init__(self, session: AsyncSession):
        self._pricing_repo = SqlAlchemyPricingRepository(session)

    async def estimate_task_cost(
        self,
        flow_id: str,
        sample_count: int = 0,
        comparison_count: int = 0,
    ) -> Decimal:
        """估算任务费用：基础费 + 样本数 × 单样本费 + 比较组数 × 每组差异分析费。"""
        pricing = await self._pricing_repo.find_match(
            flow_category=flow_id, pricing_type=PricingType.TASK_TYPE.value
        )
        base = pricing.base_cost if pricing else Decimal("1.0")
        per_sample = pricing.per_sample_cost if pricing else Decimal("0")
        per_comparison = pricing.per_comparison_cost if pricing else Decimal("0")

        samples = Decimal(max(sample_count, 0))
        comparisons = Decimal(max(comparison_count, 0))
        total = base + per_sample * samples + per_comparison * comparisons
        return total.quantize(Decimal("0.01"))

    async def estimate_sandbox_cost(self, duration_hours: float = 1.0) -> Decimal:
        pricing = await self._pricing_repo.find_match(pricing_type=PricingType.SANDBOX.value)
        base = pricing.base_cost if pricing else Decimal("0.5")
        return base * Decimal(str(duration_hours))

    async def match_pricing(self, **kwargs: str) -> CookiePricing | None:
        return await self._pricing_repo.find_match(**kwargs)


class CookieService:
    """饼干积分核心服务 — check_balance / pre_deduct / settle / refund / freeze / unfreeze"""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._account_repo = SqlAlchemyAccountRepository(session)
        self._txn_repo = SqlAlchemyTransactionRepository(session)
        self._pricing_repo = SqlAlchemyPricingRepository(session)
        self._log_repo = SqlAlchemyConsumptionLogRepository(session)
        self._settings = get_settings()

    async def get_or_create_account(self, user_id: UUID) -> CookieAccount:
        """获取或创建账户（注册时自动建户 + 赠送初始饼干）"""
        account = await self._account_repo.get_by_user(user_id)
        if account is not None:
            return account
        initial = Decimal(str(self._settings.initial_cookie_balance))
        account = CookieAccount(user_id=user_id)
        account = await self._account_repo.save(account)
        await self._record_transaction(
            account,
            TransactionType.EARN,
            initial,
            source_type="signup",
            description=f"新用户注册赠送 {initial} 🥫",
        )
        return account

    async def get_account(self, user_id: UUID) -> CookieAccountDTO:
        account = await self.get_or_create_account(user_id)
        return self._account_to_dto(account)

    async def check_balance(self, user_id: UUID) -> Decimal:
        account = await self.get_or_create_account(user_id)
        return account.available_balance

    async def pre_deduct(
        self,
        user_id: UUID,
        amount: Decimal,
        source_type: str,
        source_id: str,
        description: str = "",
    ) -> CookieTransaction:
        """预扣饼干（冻结）— 任务提交前调用"""
        account = await self.get_or_create_account(user_id)
        if not account.can_spend(amount):
            raise BusinessError(f"饼干余额不足: 需要 {amount}, 可用 {account.available_balance}")
        return await self._record_transaction(
            account,
            TransactionType.FREEZE,
            -abs(amount),
            source_type=source_type,
            source_id=source_id,
            description=description or f"预扣 {amount} 🥫 ({source_type}:{source_id})",
        )

    async def settle(
        self,
        user_id: UUID,
        pre_deducted: Decimal,
        actual_cost: Decimal,
        source_type: str,
        source_id: str,
        task_type: str = "",
        resource_cores: int | None = None,
        execution_seconds: int | None = None,
    ) -> CookieTransaction:
        """结算（多退少补）— 任务完成时调用"""
        account = await self.get_or_create_account(user_id)
        diff = actual_cost - pre_deducted
        if diff > 0:
            return await self._record_transaction(
                account,
                TransactionType.SPEND,
                -abs(diff),
                source_type=source_type,
                source_id=source_id,
                task_type=task_type,
                resource_cores=resource_cores,
                execution_seconds=execution_seconds,
                description=f"结算补扣 {diff} 🥫 (实际{actual_cost}-预扣{pre_deducted})",
            )
        elif diff < 0:
            return await self._record_transaction(
                account,
                TransactionType.UNFREEZE,
                abs(diff),
                source_type=source_type,
                source_id=source_id,
                task_type=task_type,
                description=f"结算退还 {abs(diff)} 🥫 (预扣{pre_deducted}-实际{actual_cost})",
            )
        else:
            return await self._record_transaction(
                account,
                TransactionType.UNFREEZE,
                Decimal("0"),
                source_type=source_type,
                source_id=source_id,
                task_type=task_type,
                description=f"结算完成 (预扣=实际={actual_cost})",
            )

    async def refund(
        self,
        user_id: UUID,
        amount: Decimal,
        source_type: str,
        source_id: str,
        description: str = "",
    ) -> CookieTransaction:
        """退还预扣饼干 — 任务取消时调用"""
        account = await self.get_or_create_account(user_id)
        return await self._record_transaction(
            account,
            TransactionType.REFUND,
            abs(amount),
            source_type=source_type,
            source_id=source_id,
            description=description or f"退还预扣 {amount} 🥫",
        )

    async def spend_ai_tokens(
        self,
        user_id: UUID,
        tokens: int,
        source_id: str,
    ) -> Decimal:
        """AI 对话 token 计费 — 按 ai_token_cookie_rate 🥫/1K tokens 直接扣减。

        返回实际扣减的饼干数；余额不足时按可用余额封顶（不为负），
        账户非 active 或余额为 0 时跳过（准入闸门已在对话入口拦截）。
        """
        if tokens <= 0:
            return Decimal("0")
        _, rate, discount = await self.resolve_ai_token_rate()
        cost = (Decimal(tokens) / Decimal(1000) * rate).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        if cost <= 0:
            return Decimal("0")

        existing = await self._txn_repo.list_by_source("ai_chat", source_id)
        if any(txn.txn_type == TransactionType.SPEND for txn in existing):
            return Decimal("0")

        account = await self.get_or_create_account(user_id)
        if not account.is_active or account.available_balance <= 0:
            return Decimal("0")
        if cost > account.available_balance:
            cost = account.available_balance.quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        await self._record_transaction(
            account,
            TransactionType.SPEND,
            -cost,
            source_type="ai_chat",
            source_id=source_id,
            task_type="ai_chat",
            description=(
                f"AI 对话消耗 {tokens} tokens，扣减 {cost} 🥫（{rate} 🥫/1K tokens"
                f"{'，优惠：' + discount.name if discount else ''}）"
            ),
        )
        return cost

    async def resolve_ai_token_rate(
        self, at: datetime | None = None
    ) -> tuple[Decimal, Decimal, CookieDiscountModel | None]:
        base_rate = Decimal(str(self._settings.ai_token_cookie_rate))
        moment = at or datetime.now(UTC)
        result = await self._session.execute(
            select(CookieDiscountModel)
            .where(CookieDiscountModel.is_active == True)  # noqa: E712
            .order_by(CookieDiscountModel.priority.desc(), CookieDiscountModel.id.desc())
        )
        for discount in result.scalars().all():
            if self._discount_matches(discount, moment):
                effective = (base_rate * discount.discount_multiplier).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP
                )
                return base_rate, effective, discount
        return base_rate, base_rate, None

    async def get_ai_token_rate(self, at: datetime | None = None) -> dict:
        base_rate, effective_rate, discount = await self.resolve_ai_token_rate(at)
        return {
            "base_rate": base_rate,
            "effective_rate": effective_rate,
            "discount": self._discount_to_dto(discount) if discount else None,
        }

    async def list_discounts(self) -> list[CookieDiscountDTO]:
        result = await self._session.execute(
            select(CookieDiscountModel).order_by(
                CookieDiscountModel.priority.desc(), CookieDiscountModel.date_start.desc()
            )
        )
        return [self._discount_to_dto(item) for item in result.scalars().all()]

    async def create_discount(
        self, req: CookieDiscountRequest, admin_id: UUID
    ) -> CookieDiscountDTO:
        model = CookieDiscountModel(**req.model_dump(), created_by=admin_id)
        self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._discount_to_dto(model)

    async def update_discount(
        self, discount_id: int, req: CookieDiscountRequest, admin_id: UUID
    ) -> CookieDiscountDTO:
        model = await self._session.get(CookieDiscountModel, discount_id)
        if model is None:
            raise NotFoundError(f"优惠规则 {discount_id} 不存在")
        for key, value in req.model_dump().items():
            setattr(model, key, value)
        model.updated_by = admin_id
        await self._session.flush()
        await self._session.refresh(model)
        return self._discount_to_dto(model)

    async def delete_discount(self, discount_id: int) -> bool:
        model = await self._session.get(CookieDiscountModel, discount_id)
        if model is None:
            return False
        await self._session.delete(model)
        await self._session.flush()
        return True

    @staticmethod
    def _discount_matches(discount: CookieDiscountModel, moment: datetime) -> bool:
        try:
            timezone = ZoneInfo(discount.timezone)
        except ZoneInfoNotFoundError:
            timezone = ZoneInfo("Asia/Shanghai")
        local = moment.astimezone(timezone)
        local_date = local.date()
        if discount.daily_start is None or discount.daily_end is None:
            return discount.date_start <= local_date <= discount.date_end
        local_time = local.timetz().replace(tzinfo=None)
        if discount.daily_start <= discount.daily_end:
            return (
                discount.date_start <= local_date <= discount.date_end
                and discount.daily_start <= local_time < discount.daily_end
            )
        return (
            discount.date_start <= local_date <= discount.date_end
            and local_time >= discount.daily_start
        ) or (
            discount.date_start <= local_date - timedelta(days=1) <= discount.date_end
            and local_time < discount.daily_end
        )

    @staticmethod
    def _discount_to_dto(discount: CookieDiscountModel) -> CookieDiscountDTO:
        return CookieDiscountDTO.model_validate(discount)

    async def freeze_account(self, user_id: UUID, reason: str, admin_id: UUID) -> CookieAccountDTO:
        account = await self.get_or_create_account(user_id)
        account.status = AccountStatus.FROZEN
        account.frozen_reason = reason
        account.frozen_by = admin_id
        account.frozen_at = datetime.now()
        account = await self._account_repo.save(account)
        return self._account_to_dto(account)

    async def unfreeze_account(self, user_id: UUID) -> CookieAccountDTO:
        account = await self.get_or_create_account(user_id)
        account.status = AccountStatus.ACTIVE
        account.frozen_reason = ""
        account.frozen_by = None
        account.frozen_at = None
        account = await self._account_repo.save(account)
        return self._account_to_dto(account)

    async def suspend_account(self, user_id: UUID, reason: str, admin_id: UUID) -> CookieAccountDTO:
        account = await self.get_or_create_account(user_id)
        account.status = AccountStatus.SUSPENDED
        account.frozen_reason = reason
        account.frozen_by = admin_id
        account.frozen_at = datetime.now()
        account = await self._account_repo.save(account)
        return self._account_to_dto(account)

    async def adjust_balance(
        self, user_id: UUID, amount: Decimal, reason: str, admin_id: UUID
    ) -> CookieTransactionDTO:
        account = await self.get_or_create_account(user_id)
        txn = await self._record_transaction(
            account,
            TransactionType.ADJUST,
            amount,
            source_type="admin",
            admin_id=admin_id,
            adjust_reason=reason,
            description=f"管理员调整 {amount} 🥫: {reason}",
        )
        return self._txn_to_dto(txn)

    async def list_transactions(
        self, user_id: UUID, txn_type: str | None = None, offset: int = 0, limit: int = 50
    ) -> list[CookieTransactionDTO]:
        txns = await self._txn_repo.list_by_user(user_id, txn_type, offset, limit)
        return [self._txn_to_dto(t) for t in txns]

    async def list_pricing(self, active_only: bool = True) -> list[CookiePricing]:
        return await self._pricing_repo.list_all(active_only)

    async def create_pricing(self, req: PricingCreateRequest, admin_id: UUID) -> CookiePricing:
        pricing = CookiePricing(
            pricing_type=PricingType(req.pricing_type),
            resource_type=req.resource_type,
            flow_category=req.flow_category,
            base_cost=req.base_cost,
            per_sample_cost=req.per_sample_cost,
            per_comparison_cost=req.per_comparison_cost,
            unit=PricingUnit(req.unit),
            priority=req.priority,
            description=req.description,
            effective_until=req.effective_until,
            created_by=admin_id,
        )
        return await self._pricing_repo.save(pricing)

    async def update_pricing(
        self, pricing_id: int, req: PricingCreateRequest, admin_id: UUID
    ) -> CookiePricing:
        pricing = await self._pricing_repo.get_by_id(pricing_id)
        if pricing is None:
            raise NotFoundError(f"定价策略 {pricing_id} 不存在")
        pricing.pricing_type = PricingType(req.pricing_type)
        pricing.resource_type = req.resource_type
        pricing.flow_category = req.flow_category
        pricing.base_cost = req.base_cost
        pricing.per_sample_cost = req.per_sample_cost
        pricing.per_comparison_cost = req.per_comparison_cost
        pricing.unit = PricingUnit(req.unit)
        pricing.priority = req.priority
        pricing.description = req.description
        pricing.effective_until = req.effective_until
        pricing.updated_by = admin_id
        return await self._pricing_repo.save(pricing)

    async def delete_pricing(self, pricing_id: int) -> bool:
        return await self._pricing_repo.delete(pricing_id)

    async def estimate_cost(
        self,
        user_id: UUID,
        flow_id: str,
        sample_count: int = 0,
        comparison_count: int = 0,
    ) -> CostEstimateDTO:
        engine = PricingEngine(self._session)
        cost = await engine.estimate_task_cost(flow_id, sample_count, comparison_count)
        balance = await self.check_balance(user_id)
        return CostEstimateDTO(
            flow_id=flow_id,
            estimated_cost=cost,
            sample_count=sample_count,
            comparison_count=comparison_count,
            breakdown=[
                {"item": "task_base", "cost": str(cost)},
                {"item": "sample_count", "value": sample_count},
                {"item": "comparison_count", "value": comparison_count},
            ],
            affordable=balance >= cost,
            current_balance=balance,
        )

    async def get_stats(self) -> CookieStatsDTO:
        result = await self._session.execute(
            select(
                func.count(CookieAccountModel.id),
                func.count(CookieAccountModel.id).filter(CookieAccountModel.status == "active"),
                func.coalesce(func.sum(CookieAccountModel.balance), 0),
                func.coalesce(func.sum(CookieAccountModel.frozen_balance), 0),
                func.coalesce(func.sum(CookieAccountModel.total_earned), 0),
                func.coalesce(func.sum(CookieAccountModel.total_spent), 0),
            )
        )
        row = result.one()
        return CookieStatsDTO(
            total_accounts=row[0] or 0,
            active_accounts=row[1] or 0,
            total_balance=Decimal(str(row[2])),
            total_frozen=Decimal(str(row[3])),
            total_earned=Decimal(str(row[4])),
            total_spent=Decimal(str(row[5])),
        )

    async def list_all_accounts(
        self,
        status: str | None = None,
        search: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[dict]:
        """列出所有账户 — 关联用户身份与存储资产，支持按用户名/邮箱/用户ID检索。

        与 `GET /admin/users` 共用同一份 users↔cookie_accounts JOIN 视图，确保两页数据一致。
        """
        from omichub.infrastructure.database.models.user import UserModel

        query = (
            select(
                CookieAccountModel,
                UserModel.username,
                UserModel.nickname,
                UserModel.email,
                UserModel.role,
                UserModel.lab_group,
                UserModel.status.label("user_status"),
                UserModel.created_at.label("user_created_at"),
                UserModel.storage_quota,
                UserModel.used_storage,
            )
            .outerjoin(UserModel, CookieAccountModel.user_id == UserModel.id)
            .order_by(desc(CookieAccountModel.created_at))
        )
        if status:
            query = query.filter(CookieAccountModel.status == status)
        if search:
            kw = f"%{search.strip()}%"
            # search 命中用户名/邮箱模糊匹配，或精确命中 user_id（支持跨页跳转按 ID 过滤）
            try:
                uid = UUID(search.strip())
                query = query.where(
                    or_(
                        UserModel.username.ilike(kw),
                        UserModel.nickname.ilike(kw),
                        UserModel.email.ilike(kw),
                        CookieAccountModel.user_id == uid,
                    )
                )
            except (ValueError, AttributeError):
                query = query.where(
                    or_(
                        UserModel.username.ilike(kw),
                        UserModel.nickname.ilike(kw),
                        UserModel.email.ilike(kw),
                    )
                )
        query = query.offset(offset).limit(limit)
        result = await self._session.execute(query)
        rows = result.all()
        return [
            {
                **self._account_to_dto(self._account_repo._to_entity(a)).model_dump(),
                "username": username or "",
                "nickname": nickname,
                "email": email or "",
                "role": role or "",
                "lab_group": lab_group,
                "user_status": user_status or "",
                "user_created_at": user_created_at,
                "storage_quota": storage_quota or 0,
                "used_storage": used_storage or 0,
            }
            for (
                a,
                username,
                nickname,
                email,
                role,
                lab_group,
                user_status,
                user_created_at,
                storage_quota,
                used_storage,
            ) in rows
        ]

    async def list_all_transactions(
        self, offset: int = 0, limit: int = 50
    ) -> list[CookieTransactionDTO]:
        result = await self._session.execute(
            select(CookieTransactionModel)
            .order_by(desc(CookieTransactionModel.created_at))
            .offset(offset)
            .limit(limit)
        )
        return [
            CookieTransactionDTO(
                id=t.id,
                user_id=t.user_id,
                txn_type=t.txn_type,
                amount=t.amount,
                balance_after=t.balance_after,
                source_type=t.source_type or "",
                source_id=t.source_id or "",
                task_type=t.task_type or "",
                description=t.description or "",
                created_at=t.created_at,
            )
            for t in result.scalars().all()
        ]

    async def list_all_transactions_filtered(
        self,
        user_id: UUID | None = None,
        txn_type: str | None = None,
        source_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[CookieTransactionDTO]:
        """全局交易流水审计 — 支持多维度过滤 + 关联用户名"""
        from omichub.infrastructure.database.models.user import UserModel

        query = (
            select(
                CookieTransactionModel,
                UserModel.username,
                UserModel.nickname,
                UserModel.email,
            )
            .outerjoin(UserModel, CookieTransactionModel.user_id == UserModel.id)
            .order_by(desc(CookieTransactionModel.created_at))
        )
        if user_id is not None:
            query = query.where(CookieTransactionModel.user_id == user_id)
        if txn_type:
            query = query.where(CookieTransactionModel.txn_type == txn_type)
        if source_type:
            query = query.where(CookieTransactionModel.source_type == source_type)
        if date_from:
            query = query.where(CookieTransactionModel.created_at >= date_from)
        if date_to:
            query = query.where(CookieTransactionModel.created_at <= date_to)
        query = query.offset(offset).limit(limit)
        result = await self._session.execute(query)
        return [
            {
                **CookieTransactionDTO(
                    id=t.id,
                    user_id=t.user_id,
                    txn_type=t.txn_type,
                    amount=t.amount,
                    balance_after=t.balance_after,
                    source_type=t.source_type or "",
                    source_id=t.source_id or "",
                    task_type=t.task_type or "",
                    description=t.description or "",
                    created_at=t.created_at,
                ).model_dump(),
                "username": username or "",
                "nickname": nickname,
                "email": email or "",
            }
            for t, username, nickname, email in result.all()
        ]

    async def count_all_transactions_filtered(
        self,
        user_id: UUID | None = None,
        txn_type: str | None = None,
        source_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> int:
        """统计过滤后的交易总数"""
        query = select(func.count()).select_from(CookieTransactionModel)
        if user_id is not None:
            query = query.where(CookieTransactionModel.user_id == user_id)
        if txn_type:
            query = query.where(CookieTransactionModel.txn_type == txn_type)
        if source_type:
            query = query.where(CookieTransactionModel.source_type == source_type)
        if date_from:
            query = query.where(CookieTransactionModel.created_at >= date_from)
        if date_to:
            query = query.where(CookieTransactionModel.created_at <= date_to)
        result = await self._session.execute(query)
        return result.scalar() or 0

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _record_transaction(
        self,
        account: CookieAccount,
        txn_type: TransactionType,
        amount: Decimal,
        source_type: str = "",
        source_id: str = "",
        admin_id: UUID | None = None,
        adjust_reason: str = "",
        task_type: str = "",
        resource_cores: int | None = None,
        execution_seconds: int | None = None,
        description: str = "",
    ) -> CookieTransaction:
        """记录交易并更新账户（Python 端维护统计，替代 SQL 触发器）"""
        account.apply_transaction(
            CookieTransaction(
                id=None,
                account_id=account.id,
                user_id=account.user_id,
                txn_type=txn_type,
                amount=amount,
                balance_after=account.balance,
                source_type=source_type,
                source_id=source_id,
                admin_id=admin_id,
                adjust_reason=adjust_reason,
                task_type=task_type,
                resource_cores=resource_cores,
                execution_seconds=execution_seconds,
                description=description,
            )
        )
        await self._account_repo.save(account)
        txn = CookieTransaction(
            account_id=account.id,
            user_id=account.user_id,
            txn_type=txn_type,
            amount=amount,
            balance_after=account.balance,
            source_type=source_type,
            source_id=source_id,
            admin_id=admin_id,
            adjust_reason=adjust_reason,
            task_type=task_type,
            resource_cores=resource_cores,
            execution_seconds=execution_seconds,
            description=description,
        )
        txn = await self._txn_repo.add(txn)

        # 发布余额变更事件（WebSocket 实时推送）
        if self._settings.enable_cookie_system:
            try:
                from omichub.infrastructure.cache.cookie_pubsub import (
                    publish_cookie_balance,
                )

                await publish_cookie_balance(
                    user_id=account.user_id,
                    balance=account.balance,
                    frozen_balance=account.frozen_balance,
                    txn_type=txn_type.value,
                    amount=amount,
                    description=description,
                )
            except Exception:
                pass

        return txn

    @staticmethod
    def _account_to_dto(a: CookieAccount) -> CookieAccountDTO:
        return CookieAccountDTO(
            id=a.id,
            user_id=a.user_id,
            balance=a.balance,
            frozen_balance=a.frozen_balance,
            available_balance=a.available_balance,
            total_earned=a.total_earned,
            total_spent=a.total_spent,
            total_adjusted=a.total_adjusted,
            status=a.status.value,
            created_at=a.created_at,
        )

    @staticmethod
    def _txn_to_dto(t: CookieTransaction) -> CookieTransactionDTO:
        return CookieTransactionDTO(
            id=t.id,
            user_id=t.user_id,
            txn_type=t.txn_type.value,
            amount=t.amount,
            balance_after=t.balance_after,
            source_type=t.source_type,
            source_id=t.source_id,
            task_type=t.task_type,
            description=t.description,
            created_at=t.created_at,
        )
