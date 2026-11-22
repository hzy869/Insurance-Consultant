from decimal import Decimal
from typing import Annotated, Any, Self

from pydantic import BaseModel, Field, StringConstraints, model_validator


MoneyAmount = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]


class InsurancePlanItemCreate(BaseModel):
    product_id: int = Field(gt=0)
    priority: int = Field(default=1, ge=1, le=2_147_483_647)
    recommendation_reason: str | None = None
    annual_premium_budget: MoneyAmount | None = None


class InsurancePlanCreate(BaseModel):
    plan_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    summary: str | None = None
    budget_note: str | None = None
    insured_profile: dict[str, Any] = Field(default_factory=dict)
    items: list[InsurancePlanItemCreate] = Field(min_length=1)

    @property
    def annual_premium_budget(self) -> Decimal | None:
        budgets = [item.annual_premium_budget for item in self.items if item.annual_premium_budget is not None]
        return sum(budgets, Decimal(0)) if budgets else None

    @model_validator(mode="after")
    def validate_items(self) -> Self:
        product_ids = {item.product_id for item in self.items}
        if len(product_ids) != len(self.items):
            raise ValueError("同一个产品只能出现在保险方案中一次")

        budget = self.annual_premium_budget
        if budget is not None and budget > Decimal("999999999999.99"):
            raise ValueError("方案年缴预算超出支持范围")
        return self
