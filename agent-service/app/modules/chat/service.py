from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager

from fastapi import HTTPException
from fastapi.sse import ServerSentEvent
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.agents.schemas import InsuranceAgentContext
from app.core.logging import get_logger
from app.modules.chat_thread.exceptions import ChatThreadNotFound
from app.modules.chat_thread.repository import ChatThreadRepository
from app.modules.chat_thread.state import (
    display_messages,
    interrupt_payload,
    merge_additional_info,
    pending_plan_interrupt,
    thread_lock,
)
from .schema import ChatRequest


logger = get_logger(__name__)


class ChatService:
    def __init__(self, session: AsyncSession, agent: CompiledStateGraph):
        self.session = session
        self.agent = agent
        self.repository = ChatThreadRepository(session)

    @asynccontextmanager
    async def open_stream(
        self, user_id: int, request: ChatRequest,
    ) -> AsyncIterator[AsyncIterator[ServerSentEvent]]:
        """Validate and serialize the request before opening its SSE response."""
        thread_id = str(request.thread_id)
        async with thread_lock(thread_id):
            owned = await self.repository.required_owner(user_id, request.thread_id)
            await self.session.rollback()
            if owned is None:
                raise ChatThreadNotFound()

            config = {"configurable": {"thread_id": thread_id}}
            snapshot = await self.agent.aget_state(config)
            pending = pending_plan_interrupt(snapshot)
            if request.decision is not None:
                if pending is None:
                    raise HTTPException(409, "当前会话没有待确认的方案")
                if request.decision.interrupt_id not in (None, pending.id):
                    raise HTTPException(409, "待确认方案已变化，请刷新后重试")
                decision = request.decision.model_dump(exclude={"interrupt_id"}, exclude_none=True)
                graph_input = Command(resume={pending.id: decision})
            else:
                if pending is not None:
                    raise HTTPException(409, "请先确认或拒绝当前方案")
                graph_input = {"messages": [HumanMessage(content=request.message)]}

            previous_ids = {message.id for message in snapshot.values.get("messages", [])}
            events = self._stream(user_id, thread_id, graph_input, config, previous_ids, request.payload)
            async with aclosing(events):
                yield events

    async def _stream(
        self,
        user_id: int,
        thread_id: str,
        graph_input: dict | Command,
        config: dict,
        previous_ids: set[str | None],
        payload: dict,
    ) -> AsyncIterator[ServerSentEvent]:
        streamed_text = False
        try:
            stream = self.agent.astream(
                graph_input,
                config,
                context=InsuranceAgentContext(user_id=user_id, payload=payload),
                stream_mode="messages",
                subgraphs=True,
                version="v2",
            )
            async with aclosing(stream):
                async for part in stream:
                    message, metadata = part["data"]
                    if "nostream" in metadata.get("tags", ()):
                        continue
                    if isinstance(message, AIMessage) and message.text:
                        streamed_text = True
                        yield ServerSentEvent(data=message.text, event="message")

            await self.session.execute(text("UPDATE chat_threads SET updated_at=now() WHERE id=:id AND user_id=:uid"), {"id": thread_id, "uid": user_id})
            await self.session.commit()
            snapshot = await self.agent.aget_state(config)
            additional_info: dict = {}
            for message_id, message in display_messages(snapshot.values.get("messages", [])):
                if message.role != "assistant" or message_id in previous_ids:
                    continue
                if not streamed_text:
                    yield ServerSentEvent(data=message.content, event="message")
                if message.additional_info:
                    merge_additional_info(additional_info, message.additional_info)
            if additional_info:
                yield ServerSentEvent(data=additional_info, event="additional_info")

            pending = pending_plan_interrupt(snapshot)
            if pending is not None:
                yield ServerSentEvent(data=[interrupt_payload(pending)], event="interrupt")

            yield ServerSentEvent(
                data={"thread_id": thread_id, "finish_reason": "interrupt" if pending else "stop"},
                event="done",
            )
        except Exception:
            logger.exception("处理流式对话失败", thread_id=thread_id)
            yield ServerSentEvent(data={"message": "对话处理失败，请重试"}, event="error")
