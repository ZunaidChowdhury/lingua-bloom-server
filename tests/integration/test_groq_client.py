"""Call the real Groq API once and parse a valid LLMOutput.

Skipped unless GROQ_API_KEY holds a real key (not the test placeholder).
Run with: pytest -m integration
"""

from __future__ import annotations

import os

import pytest

from app.llm.client import GroqClient
from app.llm.schema import LLMOutput

pytestmark = pytest.mark.integration

_MODEL = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")


async def test_real_groq_returns_valid_llm_output() -> None:
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key or api_key == "test-key":
        pytest.skip("GROQ_API_KEY is not set to a real key")

    client = GroqClient(api_key=api_key, model=_MODEL, timeout_s=1.5)
    try:
        output = await client.complete(
            [
                {
                    "role": "system",
                    "content": (
                        "Reply only with a JSON object with keys: reply (one short"
                        " sentence), suggested_mode (one of learning, conversation,"
                        " engagement, support), confidence (0 to 1), mood (one of"
                        " positive, neutral, low, unsure)."
                    ),
                },
                {"role": "user", "content": "hello"},
            ]
        )
    finally:
        await client.close()

    assert isinstance(output, LLMOutput)
    assert output.reply
    assert output.suggested_mode in ("learning", "conversation", "engagement", "support")
    assert 0.0 <= output.confidence <= 1.0
    assert output.mood in ("positive", "neutral", "low", "unsure")
