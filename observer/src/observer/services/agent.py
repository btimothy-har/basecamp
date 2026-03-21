"""Claude CLI subprocess runner for LLM-based extraction.

Invokes ``claude -p`` as an isolated subprocess — no SDK dependency,
leverages existing auth and model routing infrastructure.
"""

import json
import logging
import subprocess
from dataclasses import dataclass

from observer.constants import EXTRACTION_TIMEOUT
from observer.exceptions import (
    ExtractionParseError,
    ExtractionResponseError,
    ExtractionSubprocessError,
    ExtractionTimeoutError,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AgentResponse:
    """Parsed response from a ``claude -p`` invocation."""

    result: str
    cost_usd: float
    duration_ms: int
    session_id: str


class Agent:
    """Wrapper around ``claude -p`` for single-turn LLM calls."""

    def __init__(
        self,
        *,
        system_prompt: str,
        model: str,
        timeout: int = EXTRACTION_TIMEOUT,
    ) -> None:
        self.system_prompt = system_prompt
        self.model = model
        self.timeout = timeout

    def run(
        self,
        prompt: str,
        *,
        json_schema: dict | None = None,
    ) -> AgentResponse:
        """Run a single ``claude -p`` call and return the parsed response.

        Raises ``ExtractionError`` on non-zero exit, timeout, or unparseable output.
        """
        cmd = [
            "claude",
            "-p",
            "--output-format",
            "json",
            "--model",
            self.model,
            "--no-session-persistence",
            "--tools",
            "",
            "--system-prompt",
            self.system_prompt,
            # Isolation: block all settings, MCP servers, and skills.
            # Auth lives outside settings.json (OAuth/keychain).
            "--setting-sources",
            "",
            "--strict-mcp-config",
            "--disable-slash-commands",
        ]

        if json_schema is not None:
            cmd.extend(["--json-schema", json.dumps(json_schema)])

        try:
            proc = subprocess.run(
                cmd,
                input=prompt,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            logger.warning("claude -p timed out after %ds, retrying once", self.timeout)
            try:
                proc = subprocess.run(
                    cmd,
                    input=prompt,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                )
            except subprocess.TimeoutExpired as exc:
                raise ExtractionTimeoutError(self.timeout) from exc

        if proc.returncode != 0:
            stderr = proc.stderr.strip()[:500] if proc.stderr else "(no stderr)"
            raise ExtractionSubprocessError(proc.returncode, stderr)

        try:
            envelope = json.loads(proc.stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ExtractionParseError(proc.stdout[:500]) from exc

        # --json-schema puts structured output in a separate field as a
        # parsed dict; serialize it back so callers can use model_validate_json.
        structured = envelope.get("structured_output")
        if structured is not None:
            result = json.dumps(structured)
        elif "result" in envelope:
            result = envelope["result"]
        else:
            raise ExtractionResponseError(list(envelope.keys()))

        return AgentResponse(
            result=result,
            cost_usd=envelope.get("cost_usd", 0.0),
            duration_ms=envelope.get("duration_ms", 0),
            session_id=envelope.get("session_id", ""),
        )
