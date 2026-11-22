from collections.abc import Collection
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.product.models import Product

from .models import InsurancePlan, InsurancePlanItem
from .schemas import InsurancePlanCreate


class InsurancePlanRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_active_products(self, product_ids: Collection[int]) -> dict[int, Product]:
        query = select(Product).where(Product.id.in_(product_ids), Product.status == "active")
        products = (await self.session.scalars(query)).all()
        return {product.id: product for product in products}

    async def insert_plan(self, plan_id: UUID, user_id: int, plan: InsurancePlanCreate) -> None:
        statement = (
            insert(InsurancePlan)
            .values(
                id=plan_id,
                user_id=user_id,
                plan_name=plan.plan_name,
                summary=plan.summary,
                budget_note=plan.budget_note,
                insured_profile=plan.insured_profile,
                annual_premium_budget=plan.annual_premium_budget,
            )
            .on_conflict_do_nothing(index_elements=[InsurancePlan.id])
            .returning(InsurancePlan.id)
        )
        inserted_id = await self.session.scalar(statement)
        if inserted_id is None:
            existing_owner = await self.session.scalar(
                select(InsurancePlan.user_id).where(InsurancePlan.id == plan_id)
            )
            if existing_owner != user_id:
                raise ValueError("保险方案标识与当前用户不匹配")
            return

        self.session.add_all(
            [
                InsurancePlanItem(
                    id=uuid4(),
                    plan_id=inserted_id,
                    product_id=item.product_id,
                    priority=item.priority,
                    recommendation_reason=item.recommendation_reason,
                    annual_premium_budget=item.annual_premium_budget,
                )
                for item in plan.items
            ]
        )
