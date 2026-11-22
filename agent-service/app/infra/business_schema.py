from sqlalchemy import text

from app.infra.database import engine


async def ensure_business_schema():
    """为已有课程数据库补上方案版本和预算说明字段。"""
    async with engine.begin() as connection:
        await connection.execute(text("ALTER TABLE insurance_plans ADD COLUMN IF NOT EXISTS budget_note TEXT, ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1"))
