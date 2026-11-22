from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class ChatDecision(BaseModel):
    action: Literal["approve", "reject"]
    reject_reason: str | None = Field(default=None, max_length=500)
    interrupt_id: str | None = Field(default=None, min_length=1, max_length=128)


class ChatRequest(BaseModel):
    """发送一条新消息，或处理同一会话中的待确认方案。"""

    thread_id: UUID
    message: str | None = Field(default=None, min_length=1)
    decision: ChatDecision | None = None
    payload: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_input(self) -> Self:
        if self.message is None and self.decision is None:
            raise ValueError("message 和 decision 至少提交一项")
        if self.message is not None and not self.message.strip():
            raise ValueError("消息内容不能为空")
        if self.decision and self.decision.action == "reject" and not (self.decision.reject_reason or "").strip():
            raise ValueError("拒绝方案时请填写原因")
        return self
