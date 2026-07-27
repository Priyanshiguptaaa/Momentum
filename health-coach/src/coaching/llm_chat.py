"""OpenAI chat — LLM-led scientist debate + human narration."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.coaching.llm_reasoner import llm_answer_with_trace
from src.db.config import settings
from src.db.models import ChatMessage, ChatThread, User

MAX_HISTORY_MESSAGES = 12


def _get_or_create_thread(db: Session, user_id: int, thread_id: int | None) -> ChatThread:
    if thread_id is not None:
        thread = db.scalar(
            select(ChatThread).where(ChatThread.id == thread_id, ChatThread.user_id == user_id)
        )
        if thread is None:
            raise LookupError(f"Chat thread {thread_id} not found")
        return thread
    thread = ChatThread(user_id=user_id, title="Momentum chat")
    db.add(thread)
    db.flush()
    return thread


def ask_health_question(
    db: Session,
    message: str,
    *,
    thread_id: int | None = None,
) -> dict[str, Any]:
    if not settings.openai_api_key:
        raise RuntimeError("HC_OPENAI_API_KEY is not set")

    user = db.scalar(select(User).order_by(User.id).limit(1))
    if user is None:
        raise RuntimeError("No users found. Sync health data first.")

    thread = _get_or_create_thread(db, user.id, thread_id)
    prior = list(
        db.scalars(
            select(ChatMessage)
            .where(ChatMessage.thread_id == thread.id)
            .order_by(ChatMessage.id.asc())
        ).all()
    )
    history = [
        {"role": m.role, "content": m.content}
        for m in prior[-MAX_HISTORY_MESSAGES:]
    ]

    result = llm_answer_with_trace(
        db,
        message.strip(),
        history=history,
        user_id=user.id,
    )
    trace = result["reasoning_trace"]
    reply = result.get("reply")
    if not reply:
        # Statistical mode or missing reply — build a short narration locally.
        top = ", ".join(f"{h.title} (~{h.probability:.0%})" for h in trace.hypotheses[:3])
        reply = (
            f"Leading explanations: {top}.\n\n{trace.recommended_action}\n\n"
            f"What would change my mind: {trace.what_would_change_my_mind}"
        )

    db.add(ChatMessage(thread_id=thread.id, role="user", content=message.strip()))
    db.add(
        ChatMessage(
            thread_id=thread.id,
            role="assistant",
            content=reply,
            metadata_json={
                "model": settings.openai_model,
                "mode": result.get("mode"),
                "primary_hypothesis_id": trace.primary_hypothesis_id,
            },
        )
    )
    thread.updated_at = datetime.now(UTC)
    if not thread.title or thread.title == "Momentum chat":
        thread.title = message.strip()[:80]
    db.commit()

    return {
        "reply": reply,
        "model": settings.openai_model,
        "context_days": int(result.get("evidence_days") or 0),
        "thread_id": thread.id,
        "patterns_used": int(result.get("patterns_used") or 0),
        "interventions_in_context": int(result.get("interventions_in_context") or 0),
        "reasoning_trace": trace.model_dump(mode="json"),
    }
