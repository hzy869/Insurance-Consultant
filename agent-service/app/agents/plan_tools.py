from uuid import NAMESPACE_URL, uuid5

from langchain.tools import ToolRuntime, tool
from langgraph.types import interrupt

from app.agents.schemas import InsuranceAgentContext
from app.infra.database import AsyncSessionFactory
from app.modules.insurance_plan.schemas import InsurancePlanCreate
from app.modules.insurance_plan.service import InsurancePlanService
from app.modules.business.router import plan_detail


@tool(response_format="content_and_artifact")
async def save_insurance_plan(
    plan: InsurancePlanCreate,
    runtime: ToolRuntime[InsuranceAgentContext],
) -> tuple[str, dict | None]:
    """展示保险组合，请当前用户确认后保存。方案项须引用查询出的真实产品 ID。"""
    thread_id = runtime.config.get("configurable", {}).get("thread_id")
    if not thread_id or not runtime.tool_call_id:
        return "请在有效的对话中发起保险方案确认。", None

    async with AsyncSessionFactory() as session:
        preview = await InsurancePlanService(session).build_preview(plan)
    if preview is None:
        return "方案包含无效或已下架的产品。请重新查询候选产品并调整方案。", None

    decision = interrupt(
        {
            "plan": preview,
            "confirm_info": "确认保存这套保险方案吗？",
            "action": ["approve", "reject"],
        }
    )
    if not isinstance(decision, dict):
        return "未收到有效的确认结果，本次未保存。", None
    if decision.get("action") != "approve":
        reason = decision.get("reject_reason")
        message = "用户取消了本次方案保存。"
        return f"{message} 用户说明：{reason}" if reason else message, None

    user_id = runtime.context.user_id
    # 工具在中断恢复或检查点重试后会重跑，同一次调用使用固定的方案 ID。
    plan_id = uuid5(NAMESPACE_URL, f"insurance-plan:{user_id}:{thread_id}:{runtime.tool_call_id}")
    async with AsyncSessionFactory() as session:
        await InsurancePlanService(session).save(plan_id, user_id, plan)
        saved = await plan_detail(session, user_id, plan_id)
    return f"保险方案保存成功。方案 ID：{plan_id}", {"plan_items": [{**item, "plan_id": str(plan_id)} for item in saved["items"]]}
