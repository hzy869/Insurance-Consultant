from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langgraph.graph.state import CompiledStateGraph

from app.core.config import settings
from app.core.logging import get_logger
from .plan_tools import save_insurance_plan
from .schemas import InsuranceAgentContext
from .tools import query_candidate_products, retrieve_insurance_clause

logger = get_logger(__name__)

SYSTEM_PROMPT = """
你是“安心保”的智能保险顾问。
你需要使用专业、准确、容易理解的语言回答用户的保险问题。
当信息不足时，应先向用户追问，不要编造保险产品或保障内容。
当用户询问保险条款问题时，必须调用工具查询条款，然后根据条款回答，不能自己编造。
根据条款回答时，在相关结论后原样标注工具返回的 [ref-...] 编号。
用户要求制定方案时，先收集必要的需求和预算，再查询候选产品。仅使用查询得到的产品 ID，
将整理好的方案交给 save_insurance_plan 展示并等待用户确认，每轮最多调用一次保存工具。
用户拒绝保存后，简要告知结果，等待用户给出新的修改需求。只有保存工具返回成功时才告知已保存。
"""


# agent在整个系统中，只初始化一次，
async def init_insurance_advisor() -> CompiledStateGraph:
    # 1.初始化模型
    model = init_chat_model(
        model=settings.llm.chat_model,
        api_key=settings.llm.api_key,
        extra_body={"thinking": {"type": "disabled"}}
    )

    # 2.创建Agent，绑定model、tools、Checkpointer
    agent = create_agent(
        model=model,
        tools=[query_candidate_products, retrieve_insurance_clause, save_insurance_plan],
        context_schema=InsuranceAgentContext,
        checkpointer=True,
        system_prompt=SYSTEM_PROMPT
    )

    logger.info("保险顾问Agent初始化完毕~✅️")
    return agent
