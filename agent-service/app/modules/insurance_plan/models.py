from decimal import Decimal
from uuid import UUID

from sqlalchemy import BigInteger, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.models import Base, CreateAtMixin, UpdateAtMixin


class InsurancePlan(Base, CreateAtMixin, UpdateAtMixin):
    __tablename__ = "insurance_plans"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    plan_name: Mapped[str] = mapped_column(String(120))
    summary: Mapped[str | None] = mapped_column(Text)
    budget_note: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    insured_profile: Mapped[dict] = mapped_column(JSONB)
    annual_premium_budget: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(String(30), server_default="uninsured")


class InsurancePlanItem(Base, CreateAtMixin, UpdateAtMixin):
    __tablename__ = "insurance_plan_items"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    plan_id: Mapped[UUID] = mapped_column(ForeignKey("insurance_plans.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    priority: Mapped[int] = mapped_column(Integer)
    recommendation_reason: Mapped[str | None] = mapped_column(Text)
    annual_premium_budget: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(String(30), server_default="uninsured")
