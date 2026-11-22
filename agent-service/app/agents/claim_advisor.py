from fastapi.encoders import jsonable_encoder
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain.tools import ToolRuntime, tool
from langgraph.graph.state import CompiledStateGraph

from app.core.config import settings
from app.infra.database import AsyncSessionFactory
from app.modules.claim.repository import ClaimRepository

from .schemas import InsuranceAgentContext
from .tools import retrieve_insurance_clause


CLAIM_PROMPT = """
你负责「AI 保险顾问」的理赔咨询，只提供理赔指引和记录查询。

- 用户询问自己的理赔进度时，必须调用 `query_claim_progress` 并根据返回的真实状态回答。
  已提供案件号或保单号时，把该编号用作查询条件。没有编号时，可以查询近期案件；有多条且
  用户意图不明确时，请用户选择。工具未查到记录时，如实说明当前账号下未查到匹配案件。
- 用户需要按自己的保单了解材料或办理流程时，调用 `list_user_policies` 确定保单及产品。
  涉及某个产品的条款、报案时限或材料要求时，确认产品 ID 后调用 `retrieve_insurance_clause`，
  并沿用工具提供的引用编号。缺少保单、产品或相关条款时，说明缺少的依据并追问。
- 一般理赔流程可以简述为联系承保公司报案、按要求准备材料、提交申请并跟踪进度。
  将通用指引与保单、案件和条款查得的事实分开说明。赔付结论、审核和支付由承保公司负责。
- 已知理赔状态：submitted 为已提交，reviewing 为审核中，approved 为已通过，
  rejected 为已拒赔，paid 为已支付。不得编造案件、状态、承保结论或办理结果。
- 本顾问不受理、提交、审核或支付理赔，也不需要身份证号码、联系电话或就诊记录。
""".strip()


@tool(response_format="content_and_artifact")
async def list_user_policies(
    runtime: ToolRuntime[InsuranceAgentContext], policy_number: str | None = None
) -> dict:
    """查询当前用户的保单，为理赔指引确认保险产品。

    Args:
        policy_number: 指定保单号。不提供时最多返回最近 10 张保单。
    """
    policy_number = (policy_number or "").strip() or None
    async with AsyncSessionFactory() as session:
        policies = await ClaimRepository(session).list_policies(runtime.context.user_id, policy_number)
    return {"policies": jsonable_encoder(policies)}, {"policies": jsonable_encoder(policies)}


@tool
async def query_claim_progress(
    runtime: ToolRuntime[InsuranceAgentContext],
    claim_number: str | None = None,
    policy_number: str | None = None,
) -> dict:
    """查询当前用户的理赔进度。

    Args:
        claim_number: 指定理赔案件号。
        policy_number: 指定关联保单号。每次最多返回最近 10 条匹配记录。
    """
    claim_number = (claim_number or "").strip() or None
    policy_number = (policy_number or "").strip() or None
    async with AsyncSessionFactory() as session:
        claims = await ClaimRepository(session).list_claims(
            runtime.context.user_id, claim_number, policy_number
        )
    return {"claims": jsonable_encoder(claims)}


async def init_claim_advisor() -> CompiledStateGraph:
    model = init_chat_model(
        model=settings.llm.chat_model,
        api_key=settings.llm.api_key,
        extra_body={"thinking": {"type": "disabled"}},
    )
    return create_agent(
        model=model,
        tools=[list_user_policies, query_claim_progress, retrieve_insurance_clause],
        system_prompt=CLAIM_PROMPT,
        context_schema=InsuranceAgentContext,
        checkpointer=True,
        name="claim_advisor",
    )
