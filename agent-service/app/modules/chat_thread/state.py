from asyncio import Lock
from collections.abc import Iterable, Iterator
from weakref import WeakValueDictionary

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.types import Interrupt, StateSnapshot

from .schemas import ChatMessageResponse


_thread_locks: WeakValueDictionary[str, Lock] = WeakValueDictionary()


def thread_lock(thread_id: str) -> Lock:
    """Serialize changes to a conversation within this API process."""
    return _thread_locks.setdefault(thread_id.lower(), Lock())


def pending_plan_interrupt(snapshot: StateSnapshot) -> Interrupt | None:
    return next(
        (
            item for item in snapshot.interrupts
            if isinstance(item.value, dict) and "plan" in item.value
        ),
        None,
    )


def interrupt_payload(pending: Interrupt) -> dict:
    return {**pending.value, "interrupt_id": pending.id}


def merge_additional_info(target: dict, extra: dict) -> None:
    if sources := extra.get("clause_sources"):
        target.setdefault("clause_sources", {}).update(sources)
    for key in ("plan_items", "candidate_products", "policies"):
        if items := extra.get(key):
            target.setdefault(key, []).extend(items)


def display_messages(
    messages: Iterable[BaseMessage],
) -> Iterator[tuple[str | None, ChatMessageResponse]]:
    """Attach checkpointed tool artifacts to the assistant message they support."""
    pending: dict = {}
    for message in messages:
        if isinstance(message, HumanMessage):
            pending = {}
            if message.text:
                yield message.id, ChatMessageResponse(role="user", content=message.text)
        elif isinstance(message, ToolMessage) and isinstance(message.artifact, dict):
            merge_additional_info(pending, message.artifact)
        elif isinstance(message, AIMessage) and message.text:
            additional_info = None
            if not message.tool_calls:
                sources = pending.pop("clause_sources", {})
                cited = {
                    source_id: source for source_id, source in sources.items()
                    if f"[{source_id}]" in message.text
                }
                if cited:
                    pending["clause_sources"] = cited
                additional_info = pending or None
                pending = {}
            yield message.id, ChatMessageResponse(
                role="assistant", content=message.text, additional_info=additional_info,
            )
