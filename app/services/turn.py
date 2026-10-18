"""Turn orchestration: one chat turn from command to persisted outcome (ARCHITECTURE 5)."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Literal, cast

from pydantic import BaseModel, Field, ValidationError

from app.core.config import Settings
from app.core.errors import InvalidInputError, NotFoundError
from app.domain.checking import AttemptResult, check_answer
from app.domain.curriculum.loader import get_item_by_id, load_curriculum
from app.domain.curriculum.models import Item, PublicChoice, PublicItem, public_view
from app.domain.curriculum.selector import ItemSelector, shuffled_choices
from app.domain.errors import UnknownChoiceError
from app.domain.modes import (
    Mode,
    ModeDecision,
    decide_mode,
    detect_signals,
    validate_suggestion,
)
from app.domain.progression import (
    AttemptDecision,
    CountedAttempt,
    ProgressDecision,
    ProgressSettings,
    apply_attempt,
    evaluate_progress,
)
from app.domain.safety import (
    distress_reply,
    needs_distress_escalation,
    sanitize,
    validate_reply,
)
from app.domain.sel import (
    EFFORT_PRAISE,
    FEELINGS_BY_ID,
    TRY_AGAIN_LINE,
    FeelingCheckin,
    checkin_due,
    feeling_checkin,
)
from app.fallbacks.templates import Event, pick_template
from app.llm import LLMClient, build_context, build_messages
from app.llm.client import LLMUnavailable
from app.repositories.base import (
    AttemptResultName,
    ModeName,
    NewAttempt,
    NewLevelEvent,
    NewMessage,
    Repository,
    SessionRecord,
    SessionUpdate,
    TurnCommit,
    TurnState,
)

logger = logging.getLogger("app.turn")

RECENT_ITEM_CAP = 12


class TurnCommand(BaseModel):
    """One child turn after edge validation."""

    text: str = Field(default="", max_length=200)
    choice_id: str | None = None
    feeling: str | None = None
    request_id: str | None = None


class TurnMessageOut(BaseModel):
    role: Literal["child", "bot"]
    content: str
    mode: ModeName | None = None


class ProgressSnapshot(BaseModel):
    level: int
    correct_in_window: int
    window: int
    required: int


class TurnMeta(BaseModel):
    fallback: bool
    llm_ms: int
    total_ms: int
    request_id: str


class TurnOutcome(BaseModel):
    messages: list[TurnMessageOut]
    mode: ModeName
    level: int
    level_up: bool
    feedback: str | None
    result: AttemptResultName | None = None
    hint: str | None = None
    activity: PublicItem | FeelingCheckin | None
    progress: ProgressSnapshot
    meta: TurnMeta


def _counted_from(state: TurnState) -> list[CountedAttempt]:
    return [
        CountedAttempt(skill=a.skill_tag, correct=(a.result == "correct"))
        for a in state.recent_attempts
    ]


def build_progress_snapshot(state: TurnState, settings: ProgressSettings) -> ProgressSnapshot:
    """Single source of truth for the progress snapshot (turn response and GET /v1/progress)."""

    decision = evaluate_progress(_counted_from(state), state.session.level, settings)
    return ProgressSnapshot(
        level=state.session.level,
        correct_in_window=decision.correct_in_window,
        window=settings.progress_window,
        required=settings.progress_required_correct,
    )


class TurnService:
    """Runs the deterministic pipeline for one chat turn."""

    def __init__(
        self,
        repository: Repository,
        llm: LLMClient,
        settings: Settings,
        selector: ItemSelector | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._llm = llm
        self._settings = settings
        self._selector = selector or ItemSelector(load_curriculum())
        self._clock = clock or (lambda: datetime.now(UTC))

    async def run(self, session: SessionRecord, command: TurnCommand) -> TurnOutcome:
        """Execute the ARCH 5 pipeline and persist exactly one turn transaction."""

        started = perf_counter()
        request_id = command.request_id or uuid.uuid4().hex

        state = await self._repository.get_turn_state(session.id)
        if state is None:
            raise NotFoundError("We could not find that.")

        text_present = bool(command.text.strip())
        if not text_present and command.choice_id is None and command.feeling is None:
            raise InvalidInputError("Please say something first.")

        feeling = command.feeling
        if feeling is not None and feeling not in FEELINGS_BY_ID:
            raise InvalidInputError("That feeling is not on the list.")

        clean_text, _flags = sanitize(command.text)
        seed = session.id.int
        level = state.session.level
        nickname = state.session.nickname

        pending_item_id = state.session.pending_item_id
        pending_attempts = state.session.pending_attempts
        learning_streak = state.session.learning_streak
        turns_since_checkin = state.session.turns_since_checkin
        last_feeling = state.session.last_feeling
        turn_count = state.session.turn_count

        reply = ""
        fallback = False
        llm_ms = 0
        final_mode: ModeName = "conversation"
        feedback: str | None = None
        activity: PublicItem | FeelingCheckin | None = None
        new_attempt: NewAttempt | None = None
        checkin_delivered = False

        # Feeling answer (child tapped a check-in choice): no text, no quiz.
        if feeling is not None and not text_present and command.choice_id is None:
            progress = self._progress_from_state(state)
            return await self._persist(
                state,
                clean_text="",
                reply=pick_template("conversation", level, "generic", seed, nickname),
                mode="conversation",
                feedback=None,
                activity=None,
                new_attempt=None,
                level=level,
                leveled_up=False,
                pending_item_id=pending_item_id,
                pending_attempts=pending_attempts,
                learning_streak=0,
                turns_since_checkin=turns_since_checkin + 1,
                last_feeling=feeling,
                turn_count=turn_count + 1,
                progress=progress,
                fallback=False,
                llm_ms=0,
                started=started,
                request_id=request_id,
            )

        # Serious distress: deterministic, no LLM, no quiz.
        if needs_distress_escalation(clean_text):
            progress = self._progress_from_state(state)
            return await self._persist(
                state,
                clean_text=clean_text,
                reply=distress_reply(level),
                mode="support",
                feedback=None,
                activity=None,
                new_attempt=None,
                level=level,
                leveled_up=False,
                pending_item_id=pending_item_id,
                pending_attempts=pending_attempts,
                learning_streak=0,
                turns_since_checkin=turns_since_checkin + 1,
                last_feeling=last_feeling,
                turn_count=turn_count + 1,
                progress=progress,
                fallback=False,
                llm_ms=0,
                started=started,
                request_id=request_id,
            )

        # Mode decision from deterministic signals and pacing.
        signals = detect_signals(clean_text)

        # Attempt branch: a pending item plus any text or choice is an attempt,
        # UNLESS the child expresses support needs or engagement requests via text.
        attempt_action: str | None = None
        attempt_result: AttemptResult | None = None
        item: Item | None = None
        level_at_attempt = level
        decision: AttemptDecision | None = None
        chosen_label: str | None = None

        is_attempt = pending_item_id is not None and command.choice_id is not None
        if pending_item_id is not None and command.choice_id is None and text_present:
            is_correct_answer = False
            item_peek = get_item_by_id(pending_item_id)
            if item_peek is not None and item_peek.answer and item_peek.answer.accepted_words:
                norm = clean_text.strip().lower()
                if norm in [w.lower() for w in item_peek.answer.accepted_words]:
                    is_correct_answer = True

            if not is_correct_answer and (
                signals.support or signals.wants_story or signals.wants_play
            ):
                is_attempt = False
                pending_item_id = None
                pending_attempts = 0
            else:
                is_attempt = True

        if is_attempt:
            assert pending_item_id is not None
            item = get_item_by_id(pending_item_id)
            if item is None:
                pending_item_id = None
                pending_attempts = 0
                is_attempt = False
            else:
                if command.choice_id is not None and item.choices:
                    chosen_choice = next(
                        (c for c in item.choices if c.id == command.choice_id), None
                    )
                    if chosen_choice:
                        chosen_label = chosen_choice.label
                        if not clean_text:
                            clean_text = chosen_label
                try:
                    attempt_result = check_answer(item, command.choice_id, clean_text or None)
                except UnknownChoiceError as exc:
                    raise InvalidInputError("That button is not here. Please try again.") from exc
                decision = apply_attempt(pending_attempts, attempt_result, self._settings)
                attempt_action = decision.action
                level_at_attempt = state.session.level

                if command.choice_id is not None:
                    # When tapping an option, advance to next question
                    pending_item_id = None
                    pending_attempts = 0
                elif decision.clears_pending:
                    pending_item_id = None
                    pending_attempts = 0
                else:
                    pending_attempts = decision.miss_count

                new_attempt = NewAttempt(
                    item_id=item.id,
                    level=level_at_attempt,
                    skill_tag=item.skill,
                    attempt_no=state.session.pending_attempts + 1,
                    result=self._result_name(attempt_result, decision),
                    counted=decision.counted,
                )
                feedback = self._attempt_feedback(attempt_result, decision, item, seed)

        has_pending_attempt = pending_item_id is not None and pending_attempts > 0
        if command.choice_id is not None:
            # Child tapped an option in a quiz: stay in learning mode to show the next question
            mode_decision = ModeDecision("learning", ("learning",), True)
        else:
            mode_decision = decide_mode(
                signals, has_pending_attempt, learning_streak, self._settings
            )

        # Progression: evaluate after the attempt (or report the existing window).
        counted = self._counted_attempts(state)
        if new_attempt is not None and attempt_result is not None and new_attempt.counted:
            assert item is not None
            counted.append(CountedAttempt(skill=item.skill, correct=attempt_result.correct))
        progress = evaluate_progress(counted, level_at_attempt, self._settings)
        leveled_up = progress.leveled_up
        if leveled_up:
            level = progress.next_level

        # Feeling check-in when due (never mid-item, never in Support).
        checkin_mode = self._concrete(mode_decision.mode)
        if checkin_due(
            turns_since_checkin + 1,
            has_pending_item=pending_item_id is not None,
            mode=checkin_mode,
            settings=self._settings,
        ):
            activity = feeling_checkin()
            reply = pick_template("conversation", level, "checkin", seed, nickname)
            final_mode = "conversation"
            checkin_delivered = True
            turns_since_checkin = 0
        else:
            turns_since_checkin += 1

        if not checkin_delivered:
            reply, final_mode, fallback, llm_ms = await self._compose_reply(
                state=state,
                clean_text=clean_text,
                mode_decision=mode_decision,
                attempt_action=attempt_action,
                attempt_result=attempt_result,
                item=item,
                chosen_label=chosen_label,
                is_attempt=is_attempt,
                signals_support=signals.support,
                signals_wants_learning=signals.wants_learning,
                leveled_up=leveled_up,
                level=level,
                turn_count=turn_count,
                seed=seed,
                nickname=nickname,
            )
            if not reply and feedback and attempt_action in ("hint", "reveal"):
                reply = feedback

        # Attach the next learning item when pacing allows it.
        if (
            final_mode == "learning"
            and mode_decision.allows_new_item
            and pending_item_id is None
        ):
            chosen = self._selector.select_next(
                level,
                state.skill_accuracy,
                self._recent_item_ids(state),
                seed + turn_count,
            )
            pending_item_id = chosen.id
            pending_attempts = 0
            activity = self._public_activity(chosen, session.id)

        learning_streak = learning_streak + 1 if final_mode == "learning" else 0

        return await self._persist(
            state,
            clean_text=clean_text,
            reply=reply,
            mode=final_mode,
            feedback=feedback,
            result=new_attempt.result if new_attempt is not None else None,
            hint=feedback if attempt_action in ("hint", "reveal") else None,
            activity=activity,
            new_attempt=new_attempt,
            level=level,
            leveled_up=leveled_up,
            pending_item_id=pending_item_id,
            pending_attempts=pending_attempts,
            learning_streak=learning_streak,
            turns_since_checkin=turns_since_checkin,
            last_feeling=last_feeling,
            turn_count=turn_count + 1,
            progress=progress,
            fallback=fallback,
            llm_ms=llm_ms,
            started=started,
            request_id=request_id,
        )

    async def _compose_reply(
        self,
        *,
        state: TurnState,
        clean_text: str,
        mode_decision: ModeDecision,
        attempt_action: str | None,
        attempt_result: AttemptResult | None,
        item: Item | None = None,
        chosen_label: str | None = None,
        is_attempt: bool = False,
        signals_support: bool,
        signals_wants_learning: bool,
        leveled_up: bool,
        level: int,
        turn_count: int,
        seed: int,
        nickname: str | None,
    ) -> tuple[str, Mode, bool, int]:
        """Return (reply, final_mode, fallback, llm_ms) for the non-checkin path."""

        if leveled_up:
            reply = pick_template("learning", level, "level_up", seed, nickname)
            return reply, self._concrete(mode_decision.mode), False, 0

        if not is_attempt and signals_wants_learning and not leveled_up:
            # On learning start, only show questions with options (no repeated message)
            return "", "learning", False, 0

        if attempt_action == "hint" or attempt_action == "reveal":
            # The canonical hint/reveal text is returned via `feedback`.
            return "", self._concrete(mode_decision.mode), False, 0

        if (
            mode_decision.mode == "auto"
            and "learning" not in mode_decision.allowed_modes
            and signals_wants_learning
        ):
            reply = pick_template("learning", level, "break_offer", seed, nickname)
            return reply, "conversation", False, 0

        if attempt_result is not None and item is not None and (chosen_label or clean_text):
            answer_label = chosen_label or clean_text
            if attempt_result.correct:
                prompt_text = (
                    f'Child answered "{item.prompt}" with "{answer_label}". {item.reveal} '
                    "Praise enthusiastically in short words (under 8 words). Never say wrong."
                )
            else:
                prompt_text = (
                    f'Child answered "{item.prompt}" with "{answer_label}". Answer: {item.reveal} '
                    "Encourage effort kindly and say the answer (under 8 words). Never say wrong."
                )
            attempt_msgs = build_messages(
                build_context(state), "learning", ("learning",), prompt_text
            )
            started = perf_counter()
            try:
                output = await self._llm.complete(attempt_msgs)
                llm_ms = int((perf_counter() - started) * 1000)
                ok, attempt_reasons = validate_reply(output.reply, level)
                if ok and output.reply.strip():
                    return output.reply, "learning", False, llm_ms
                self._log_fallback_reason("validation", attempt_reasons)
            except Exception as exc:
                llm_ms = int((perf_counter() - started) * 1000)
                logger.warning("llm_call_failed")
                self._log_fallback_reason(exc)

            return self._fallback_reply(
                mode_decision,
                attempt_action,
                attempt_result,
                item,
                signals_support,
                level,
                seed,
                nickname,
                clean_text,
            )

        messages: list[dict[str, Any]] = build_messages(
            build_context(state), mode_decision.mode, mode_decision.allowed_modes, clean_text
        )
        started = perf_counter()
        try:
            output = await self._llm.complete(messages)
            llm_ms = int((perf_counter() - started) * 1000)
        except Exception as exc:
            llm_ms = int((perf_counter() - started) * 1000)
            logger.warning("llm_call_failed")
            self._log_fallback_reason(exc)
            return self._fallback_reply(
                mode_decision,
                attempt_action,
                attempt_result,
                item,
                signals_support,
                level,
                seed,
                nickname,
                clean_text,
            )

        ok, reasons = validate_reply(output.reply, level)
        if not ok or not output.reply.strip():
            self._log_fallback_reason("validation", reasons)
            return self._fallback_reply(
                mode_decision,
                attempt_action,
                attempt_result,
                item,
                signals_support,
                level,
                seed,
                nickname,
                clean_text,
            )

        if mode_decision.mode == "auto":
            if attempt_action == "advance":
                # A correct answer keeps the lesson going: stay in Learning.
                final_mode: Mode = "learning"
            else:
                final_mode = validate_suggestion(
                    output.suggested_mode, output.confidence, mode_decision.allowed_modes
                )
        else:
            final_mode = mode_decision.mode
        return output.reply, final_mode, False, llm_ms

    def _log_fallback_reason(
        self, exc_or_type: Exception | str, reasons: list[str] | None = None
    ) -> None:
        if isinstance(exc_or_type, LLMUnavailable):
            if exc_or_type.reason == "api_error" and exc_or_type.detail:
                logger.info("fallback_reason=api_error error_class=%s", exc_or_type.detail)
            else:
                logger.info("fallback_reason=%s", exc_or_type.reason)
        elif isinstance(exc_or_type, (TimeoutError, asyncio.TimeoutError)) or (
            isinstance(exc_or_type, Exception) and "timeout" in str(exc_or_type).lower()
        ):
            logger.info("fallback_reason=timeout")
        elif isinstance(exc_or_type, json.JSONDecodeError) or (
            isinstance(exc_or_type, ValueError) and "json" in str(exc_or_type).lower()
        ):
            logger.info("fallback_reason=invalid_json")
        elif isinstance(exc_or_type, ValidationError):
            logger.info("fallback_reason=schema_mismatch")
        elif isinstance(exc_or_type, Exception):
            logger.info("fallback_reason=api_error error_class=%s", type(exc_or_type).__name__)
        elif exc_or_type == "validation":
            r = reasons or []
            if "reading_level" in r:
                logger.info("fallback_reason=reading_level")
            else:
                logger.info("fallback_reason=unsafe_output")
        else:
            logger.info("fallback_reason=%s", exc_or_type)

    def _fallback_reply(
        self,
        mode_decision: ModeDecision,
        attempt_action: str | None,
        attempt_result: AttemptResult | None,
        item: Item | None,
        signals_support: bool,
        level: int,
        seed: int,
        nickname: str | None,
        clean_text: str = "",
    ) -> tuple[str, Mode, bool, int]:
        if attempt_action == "advance" or attempt_result is not None:
            final_mode: Mode = "learning"
        else:
            final_mode = self._concrete(mode_decision.mode)
        if attempt_result is not None and attempt_result.reason == "correct":
            if item is not None and item.reveal:
                reply = f"Yes! {item.reveal}"
            else:
                reply = pick_template("learning", level, "correct", seed, nickname)
            return reply, "learning", True, 0
        elif attempt_result is not None:
            if item is not None and item.reveal:
                reply = f"Good try! {item.reveal}"
            else:
                reply = pick_template("learning", level, "incorrect", seed, nickname)
            return reply, "learning", True, 0
        elif signals_support or final_mode == "support":
            event: Event = "support"
            template_mode: Mode = "support"
        elif final_mode == "engagement":
            event = "story" if "story" in clean_text.lower() else "engagement"
            template_mode = "engagement"
        elif final_mode == "conversation":
            event = "conversation"
            template_mode = "conversation"
        else:
            event = "generic"
            template_mode = final_mode
        reply = pick_template(template_mode, level, event, seed, nickname)
        return reply, final_mode, True, 0

    async def _persist(
        self,
        state: TurnState,
        *,
        clean_text: str,
        reply: str,
        mode: ModeName,
        feedback: str | None,
        result: AttemptResultName | None = None,
        hint: str | None = None,
        activity: PublicItem | FeelingCheckin | None = None,
        new_attempt: NewAttempt | None = None,
        level: int,
        leveled_up: bool,
        pending_item_id: str | None,
        pending_attempts: int,
        learning_streak: int,
        turns_since_checkin: int,
        last_feeling: str | None,
        turn_count: int,
        progress: ProgressDecision,
        fallback: bool,
        llm_ms: int,
        started: float,
        request_id: str,
    ) -> TurnOutcome:
        """Write one TurnCommit and build the outcome."""

        messages: list[NewMessage] = []
        out_messages: list[TurnMessageOut] = []
        if clean_text:
            messages.append(NewMessage(role="child", content=clean_text))
            out_messages.append(TurnMessageOut(role="child", content=clean_text))
        messages.append(NewMessage(role="bot", content=reply, mode=mode))
        out_messages.append(TurnMessageOut(role="bot", content=reply, mode=mode))

        level_events: tuple[NewLevelEvent, ...] = ()
        if leveled_up:
            level_events = (NewLevelEvent(from_level=state.session.level, to_level=level),)

        commit = TurnCommit(
            session_id=state.session.id,
            session=SessionUpdate(
                level=level,
                learning_streak=learning_streak,
                turns_since_checkin=turns_since_checkin,
                turn_count=turn_count,
                pending_item_id=pending_item_id,
                pending_attempts=pending_attempts,
                last_feeling=last_feeling,
                last_active_at=self._clock(),
            ),
            messages=tuple(messages),
            attempts=(new_attempt,) if new_attempt is not None else (),
            level_events=level_events,
        )
        await self._repository.persist_turn(commit)

        total_ms = int((perf_counter() - started) * 1000)
        return TurnOutcome(
            messages=out_messages,
            mode=mode,
            level=level,
            level_up=leveled_up,
            feedback=feedback,
            result=result,
            hint=hint,
            activity=activity,
            progress=ProgressSnapshot(
                level=level,
                correct_in_window=progress.correct_in_window,
                window=self._settings.progress_window,
                required=self._settings.progress_required_correct,
            ),
            meta=TurnMeta(
                fallback=fallback,
                llm_ms=llm_ms,
                total_ms=total_ms,
                request_id=request_id,
            ),
        )

    def _progress_from_state(self, state: TurnState) -> ProgressDecision:
        return evaluate_progress(
            self._counted_attempts(state), state.session.level, self._settings
        )

    def _counted_attempts(self, state: TurnState) -> list[CountedAttempt]:
        return _counted_from(state)

    @staticmethod
    def _concrete(mode: str) -> Mode:
        if mode == "auto":
            return "conversation"
        return cast(Mode, mode)

    @staticmethod
    def _result_name(result: AttemptResult, decision: AttemptDecision) -> AttemptResultName:
        if decision.action == "reveal":
            return "revealed"
        return result.reason

    @staticmethod
    def _attempt_feedback(
        result: AttemptResult,
        decision: AttemptDecision,
        item: Item,
        seed: int,
    ) -> str | None:
        if decision.action == "hint":
            return item.hint
        if decision.action == "reveal":
            return item.reveal
        if result.reason == "correct":
            return EFFORT_PRAISE[seed % len(EFFORT_PRAISE)]
        if result.reason in ("unsure", "skipped"):
            return None
        return TRY_AGAIN_LINE

    @staticmethod
    def _recent_item_ids(state: TurnState) -> list[str]:
        seen: list[str] = []
        for attempt in state.recent_attempts:
            if attempt.item_id not in seen:
                seen.append(attempt.item_id)
        for win in state.recent_wins:
            if win.item_id not in seen:
                seen.append(win.item_id)
        return seen[-RECENT_ITEM_CAP:]

    @staticmethod
    def _public_activity(item: Item, session_id: uuid.UUID) -> PublicItem:
        if item.choices:
            ordered = shuffled_choices(item, str(session_id))
            return public_view(item).model_copy(
                update={
                    "choices": [
                        PublicChoice(id=c.id, label=c.label, emoji=c.emoji) for c in ordered
                    ]
                }
            )
        return public_view(item)
