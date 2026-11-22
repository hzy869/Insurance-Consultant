from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from .repository import InsurancePlanRepository
from .schemas import InsurancePlanCreate


class InsurancePlanService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repository = InsurancePlanRepository(session)

    async def build_preview(self, plan: InsurancePlanCreate) -> dict | None:
        product_ids = [item.product_id for item in plan.items]
        products = await self.repository.get_active_products(product_ids)
        if len(products) != len(product_ids):
            return None

        return {
            "plan_name": plan.plan_name,
            "summary": plan.summary,
            "budget_note": plan.budget_note,
            "insured_profile": plan.insured_profile,
            "annual_premium_budget": (
                str(plan.annual_premium_budget) if plan.annual_premium_budget is not None else None
            ),
            "items": [
                {
                    **item.model_dump(mode="json"),
                    "name": products[item.product_id].name,
                    "category": products[item.product_id].category,
                    "image_url": products[item.product_id].image_url,
                }
                for item in plan.items
            ],
        }

    async def save(self, plan_id: UUID, user_id: int, plan: InsurancePlanCreate) -> None:
        async with self.session.begin():
            await self.repository.insert_plan(plan_id, user_id, plan)
