from __future__ import annotations

import asyncio
import time
from typing import Any, get_type_hints

import pytest
from pydantic import ValidationError

from app.llm import FakeLLM, LLMClient, LLMOutput


def _valid_output(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "reply": "Hi friend!",
        "suggested_mode": "conversation",
        "confidence": 0.9,
        "mood": "positive",
    }
    data.update(overrides)
    return data


class TestLLMOutputSchema:
    def test_valid_output_parses(self) -> None:
        output = LLMOutput(**_valid_output())
        assert output.reply == "Hi friend!"
        assert output.suggested_mode == "conversation"
        assert output.confidence == 0.9
        assert output.mood == "positive"

    def test_reply_over_240_chars_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LLMOutput(**_valid_output(reply="a" * 241))

    def test_reply_exactly_240_chars_accepted(self) -> None:
        output = LLMOutput(**_valid_output(reply="a" * 240))
        assert len(output.reply) == 240

    @pytest.mark.parametrize("mode", ["learning", "conversation", "engagement", "support"])
    def test_all_four_modes_accepted(self, mode: str) -> None:
        output = LLMOutput(**_valid_output(suggested_mode=mode))
        assert output.suggested_mode == mode

    @pytest.mark.parametrize("mode", ["singing", "teaching", "", "Learning"])
    def test_invalid_suggested_mode_rejected(self, mode: str) -> None:
        with pytest.raises(ValidationError):
            LLMOutput(**_valid_output(suggested_mode=mode))

    @pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
    def test_confidence_bounds_inclusive(self, value: float) -> None:
        output = LLMOutput(**_valid_output(confidence=value))
        assert output.confidence == value

    @pytest.mark.parametrize("value", [-0.01, 1.01, 2.0])
    def test_confidence_out_of_range_rejected(self, value: float) -> None:
        with pytest.raises(ValidationError):
            LLMOutput(**_valid_output(confidence=value))

    @pytest.mark.parametrize("mood", ["positive", "neutral", "low", "unsure"])
    def test_all_four_moods_accepted(self, mood: str) -> None:
        output = LLMOutput(**_valid_output(mood=mood))
        assert output.mood == mood

    @pytest.mark.parametrize("mood", ["happy", "sad", "angry", "Positive", ""])
    def test_invalid_mood_rejected(self, mood: str) -> None:
        with pytest.raises(ValidationError):
            LLMOutput(**_valid_output(mood=mood))

    def test_missing_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LLMOutput(reply="hi", suggested_mode="conversation", confidence=0.9)

    def test_reply_must_be_string(self) -> None:
        with pytest.raises(ValidationError):
            LLMOutput(**_valid_output(reply=42))


class TestLLMClientProtocol:
    def test_is_protocol(self) -> None:
        assert LLMClient.__dict__.get("_is_protocol") is True

    def test_single_async_method(self) -> None:
        methods = [
            name
            for name, value in vars(LLMClient).items()
            if callable(value) and not name.startswith("_")
        ]
        assert methods == ["complete"]

    def test_complete_returns_llm_output(self) -> None:
        hints = get_type_hints(LLMClient.complete)
        assert hints["return"] is LLMOutput

    def test_fake_llm_satisfies_protocol_structurally(self) -> None:
        fake = FakeLLM()
        assert asyncio.iscoroutinefunction(fake.complete)


class TestFakeLLM:
    async def test_returns_llm_output_instance(self) -> None:
        scripted = LLMOutput(**_valid_output(reply="Hello!"))
        fake = FakeLLM(scripted)
        result = await fake.complete([])
        assert result is scripted

    async def test_returns_from_dict(self) -> None:
        fake = FakeLLM(_valid_output(reply="From dict!"))
        result = await fake.complete([])
        assert result.reply == "From dict!"
        assert result.suggested_mode == "conversation"

    async def test_returns_from_valid_json_string(self) -> None:
        import json

        fake = FakeLLM(json.dumps(_valid_output(reply="From JSON!")))
        result = await fake.complete([])
        assert result.reply == "From JSON!"

    async def test_default_output_when_none(self) -> None:
        fake = FakeLLM()
        result = await fake.complete([])
        assert result.reply == "Hi friend!"
        assert result.suggested_mode == "conversation"
        assert result.confidence == 0.9
        assert result.mood == "positive"

    async def test_raises_scripted_exception(self) -> None:
        fake = FakeLLM(RuntimeError("boom"))
        with pytest.raises(RuntimeError, match="boom"):
            await fake.complete([])

    async def test_simulates_timeout(self) -> None:
        fake = FakeLLM(TimeoutError("slow"))
        with pytest.raises(TimeoutError, match="slow"):
            await fake.complete([])

    async def test_invalid_json_raises_value_error(self) -> None:
        fake = FakeLLM("not { valid json")
        with pytest.raises(ValueError, match="Invalid JSON"):
            await fake.complete([])

    async def test_valid_json_missing_required_field_raises(self) -> None:
        import json

        fake = FakeLLM(json.dumps({"reply": "hi"}))
        with pytest.raises(ValidationError):
            await fake.complete([])

    async def test_simulates_delay(self) -> None:
        fake = FakeLLM()
        fake.set_delay(0.05)
        start = time.monotonic()
        await fake.complete([])
        elapsed = time.monotonic() - start
        assert elapsed >= 0.04

    async def test_no_delay_by_default(self) -> None:
        fake = FakeLLM()
        start = time.monotonic()
        await fake.complete([])
        elapsed = time.monotonic() - start
        assert elapsed < 0.01

    async def test_returns_unsafe_reply_intact(self) -> None:
        unsafe = LLMOutput(
            reply="You are stupid and I hate you.",
            suggested_mode="conversation",
            confidence=0.9,
            mood="positive",
        )
        fake = FakeLLM(unsafe)
        result = await fake.complete([])
        assert result.reply == "You are stupid and I hate you."

    async def test_passes_messages_through(self) -> None:
        fake = FakeLLM()
        messages = [{"role": "user", "content": "hello"}]
        await fake.complete(messages)

    async def test_legacy_reply_method(self) -> None:
        fake = FakeLLM(_valid_output(reply="Legacy hello!"))
        assert await fake.reply("hi") == "Legacy hello!"
