"""Thin wrapper around the Claude API with the checks this tool relies on.

* Structured output (Pydantic) so the reply is always machine-checkable.
* Server-side refusal fallback enabled.
* Every cited entry id is verified against the ids we actually sent; a reply
  that cites something we did not send is retried once, then rejected.
"""
from __future__ import annotations

import os
from typing import Type, TypeVar

from pydantic import BaseModel

MODEL = os.environ.get("WORKLOG_MODEL", "claude-opus-5-5")
T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def ask(system: str, user: str, schema: Type[T], allowed_ids: set[str],
        cited_ids, effort: str = "medium", retries: int = 1) -> T:
    """Call Claude and return a validated `schema` instance.

    `cited_ids(parsed) -> iterable[str]` lists the ids the reply cites; any id
    not in `allowed_ids` counts as fabrication.
    """
    import anthropic  # imported lazily so parsing/backtests work without the SDK

    client = anthropic.Anthropic()
    msg = user
    last_err = ""
    for _ in range(retries + 1):
        try:
            resp = client.beta.messages.parse(
                model=MODEL,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": effort},
                system=system,
                messages=[{"role": "user", "content": msg}],
                output_format=schema,
            )
        except anthropic.RateLimitError as e:
            raise LLMError(f"rate limited by Claude API: {e}") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"Claude API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"cannot reach Claude API: {e}") from e
        if resp.stop_reason == "refusal":
            raise LLMError("request declined by the model")
        if resp.stop_reason == "max_tokens":
            last_err = "reply was cut off"
            continue
        parsed = resp.parsed_output
        if parsed is None:
            last_err = "reply did not match the schema"
            continue
        bad = sorted(set(cited_ids(parsed)) - allowed_ids)
        if not bad:
            return parsed
        last_err = f"reply cited ids that were not provided: {bad[:5]}"
        msg = (user + "\n\nYour previous answer cited ids that do not exist: "
               f"{bad[:5]}. Cite only ids that appear in the input.")
    raise LLMError(last_err)
