"""RawEvent domain model."""

from __future__ import annotations

import json
from datetime import datetime
from functools import cached_property
from typing import Self

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from observer.constants import EXTRACTABLE_EVENT_TYPES
from observer.data.enums import RawEventStatus
from observer.data.schemas import RawEventSchema
from observer.services.db import Database


class RawEvent(BaseModel):
    model_config = ConfigDict(from_attributes=True, ignored_types=(cached_property,))

    id: int | None = None
    transcript_id: int
    event_type: str
    timestamp: datetime
    content: str
    message_uuid: str | None = None
    processed: RawEventStatus = RawEventStatus.PENDING

    def save(self, session: Session) -> Self:
        data = self.model_dump()
        merged = session.merge(RawEventSchema(**data))
        session.flush()
        return type(self).model_validate(merged)

    @classmethod
    def get(cls, event_id: int) -> Self | None:
        with Database().session() as session:
            row = session.get(RawEventSchema, event_id)
            return cls.model_validate(row) if row else None

    @classmethod
    def has_unprocessed(cls) -> bool:
        with Database().session() as session:
            row = (
                session.query(RawEventSchema.id)
                .filter(RawEventSchema.processed == RawEventStatus.PENDING)
                .limit(1)
                .first()
            )
            return row is not None

    @classmethod
    def get_unprocessed(cls, *, limit: int) -> list[Self]:
        with Database().session() as session:
            rows = (
                session.query(RawEventSchema)
                .filter(RawEventSchema.processed == RawEventStatus.PENDING)
                .order_by(RawEventSchema.timestamp)
                .limit(limit)
                .all()
            )
            return [cls.model_validate(r) for r in rows]

    @cached_property
    def _parsed(self) -> tuple[dict, str | list, dict]:
        """Parse JSON content once. Returns (message, content, raw_data)."""
        try:
            data = json.loads(self.content)
        except (json.JSONDecodeError, TypeError):
            return {}, "", {}
        message = data.get("message", {})
        return message, message.get("content", ""), data

    def format(self) -> str:
        """Format into readable text for LLM consumption."""
        message, content, _ = self._parsed
        if not message and not content:
            return f"[{self.event_type}] {self.content[:500]}"

        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        parts.append(f"[Tool: {block.get('name', 'unknown')}]")
                    elif block.get("type") == "tool_result":
                        parts.append(f"[Tool Result: {block.get('tool_use_id', '')}]")
                elif isinstance(block, str):
                    parts.append(block)
            text = "\n".join(parts)
        else:
            text = str(content)

        role = message.get("role", self.event_type)
        return f"[{role}]\n{text}"

    def brief_description(self) -> str:
        """One-line description for non-extractable events (buffer context)."""
        message, content, _ = self._parsed
        if not message and not content:
            return f"[{self.event_type}]"

        if isinstance(content, list):
            types = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "tool_result":
                        tool_id = block.get("tool_use_id", "")
                        types.append(f"Tool Result: {tool_id}")
                    else:
                        types.append(block.get("type", "unknown"))
            return f"[{self.event_type}: {', '.join(types)}]"

        return f"[{self.event_type}]"

    def is_extractable(self) -> bool:
        """Whether this event should be processed by the LLM.

        User events are only extractable if they contain text content (not tool results).
        Assistant events are extractable if they meet the minimum length.
        System-injected content (starting with '<' or isMeta) is filtered out.
        """
        if self.event_type not in EXTRACTABLE_EVENT_TYPES:
            return False

        message, content, data = self._parsed

        if not message and not content:
            return False

        if data.get("isMeta", False):
            return False

        if data.get("isCompactSummary", False):
            return False

        if self.event_type == "user":
            if isinstance(content, str):
                return True
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        return False
                    if isinstance(block, str):
                        return True
                    if isinstance(block, dict) and block.get("type") == "text":
                        return True
                return False
            return False

        if self.event_type == "assistant":
            if isinstance(content, str):
                return True
            if isinstance(content, list):
                return any(isinstance(b, dict) and b.get("type") in ("text", "tool_use") for b in content)
            return False

        return False

    def extract_user_text(self) -> str | None:
        """Extract raw user text, or None if not a user text event."""
        if self.event_type != "user":
            return None

        _, content, _ = self._parsed

        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            return "\n".join(parts) if parts else None
        return None

    def is_user_prompt(self) -> bool:
        """User text event (delegates to is_extractable)."""
        return self.event_type == "user" and self.is_extractable()

    def is_tool_use(self) -> bool:
        """Assistant event with tool_use blocks."""
        if self.event_type != "assistant":
            return False
        _, content, _ = self._parsed
        if isinstance(content, list):
            return any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content)
        return False

    def is_tool_result(self) -> bool:
        """User event with tool_result blocks."""
        if self.event_type != "user":
            return False
        _, content, _ = self._parsed
        if isinstance(content, list):
            return any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
        return False

    def is_thinking(self) -> bool:
        """Assistant event with thinking blocks only (no tool_use or visible text)."""
        if self.event_type != "assistant":
            return False
        _, content, _ = self._parsed
        if isinstance(content, list):
            has_thinking = any(isinstance(b, dict) and b.get("type") == "thinking" for b in content)
            has_tool_use = any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content)
            has_text = any(isinstance(b, dict) and b.get("type") == "text" for b in content)
            return has_thinking and not has_tool_use and not has_text
        return False

    def extract_thinking_text(self) -> str | None:
        """Extract text from thinking blocks. Field is 'thinking', not 'text'."""
        if self.event_type != "assistant":
            return None
        _, content, _ = self._parsed
        if isinstance(content, list):
            parts = [b.get("thinking", "") for b in content if isinstance(b, dict) and b.get("type") == "thinking"]
            text = "\n".join(p for p in parts if p)
            return text if text else None
        return None

    def is_agent_text(self) -> bool:
        """Assistant text-only event (no tool_use)."""
        if self.event_type != "assistant":
            return False
        _, content, _ = self._parsed
        if isinstance(content, str):
            return True
        if isinstance(content, list):
            has_tool_use = any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content)
            if has_tool_use:
                return False
            return any(isinstance(b, dict) and b.get("type") == "text" for b in content)
        return False

    def get_tool_use_id(self) -> str | None:
        """Extract id from the first tool_use block."""
        _, content, _ = self._parsed
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    return b.get("id")
        return None

    def get_tool_use_ids(self) -> frozenset[str]:
        """Extract ids from all tool_use blocks."""
        _, content, _ = self._parsed
        if isinstance(content, list):
            return frozenset(
                b["id"] for b in content if isinstance(b, dict) and b.get("type") == "tool_use" and "id" in b
            )
        return frozenset()

    def get_tool_result_id(self) -> str | None:
        """Extract tool_use_id from the first tool_result block."""
        _, content, _ = self._parsed
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    return b.get("tool_use_id")
        return None

    def get_tool_result_ids(self) -> frozenset[str]:
        """Extract tool_use_ids from all tool_result blocks."""
        _, content, _ = self._parsed
        if isinstance(content, list):
            return frozenset(
                b["tool_use_id"]
                for b in content
                if isinstance(b, dict) and b.get("type") == "tool_result" and "tool_use_id" in b
            )
        return frozenset()

    def get_tool_name(self) -> str | None:
        """Tool name from the first tool_use block."""
        _, content, _ = self._parsed
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    return b.get("name")
        return None

    def get_tool_input(self) -> dict | None:
        """Input dict from the first tool_use block."""
        _, content, _ = self._parsed
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    return b.get("input")
        return None

    def get_tool_result_content(self) -> str | None:
        """Text content from the first tool_result block."""
        _, content, _ = self._parsed
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    result_content = b.get("content")
                    if isinstance(result_content, str):
                        return result_content
                    if isinstance(result_content, list):
                        parts = []
                        for part in result_content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                parts.append(part.get("text", ""))
                            elif isinstance(part, str):
                                parts.append(part)
                        return "\n".join(parts) if parts else None
        return None

    def extract_agent_text(self) -> str | None:
        """Text content from text-only assistant event, or None."""
        if self.event_type != "assistant":
            return None
        _, content, _ = self._parsed
        if isinstance(content, str):
            return content or None
        if isinstance(content, list):
            has_tool_use = any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content)
            if has_tool_use:
                return None
            parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            text = "\n".join(parts)
            return text or None
        return None
