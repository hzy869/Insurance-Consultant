from app.modules.auth.router import current_user
from collections.abc import AsyncIterator
from typing import Annotated

from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import APIRouter, Depends, Request, Header
from fastapi.sse import EventSourceResponse, ServerSentEvent
from app.infra.database import get_session
from .schema import ChatRequest
from .service import ChatService

router = APIRouter(prefix="/api/v1/chat", tags=["与AI对话接口"])


def get_chat_service(
    request: Request,
    session: AsyncSession = Depends(get_session)
):
    # 1.创建ChatService
    agent = request.app.state.agent
    return ChatService(session, agent)

async def get_chat_stream(
    request: ChatRequest,
    user_id: Annotated[int, Depends(current_user)],
    service: ChatService = Depends(get_chat_service),
) -> AsyncIterator[AsyncIterator[ServerSentEvent]]:
    async with service.open_stream(user_id, request) as stream:
        yield stream


@router.post("", response_class=EventSourceResponse)
async def chat(stream: Annotated[AsyncIterator[ServerSentEvent], Depends(get_chat_stream)]):
    async for event in stream:
        yield event

