"""Deterministic, level-appropriate fallback replies used when the LLM fails (FR-5.4)."""

from __future__ import annotations

from typing import Literal, cast

from app.domain.modes import Mode

Event = Literal[
    "greeting",
    "correct",
    "incorrect",
    "hint",
    "reveal",
    "level_up",
    "break_offer",
    "checkin",
    "support",
    "distress",
    "generic",
    "conversation",
    "engagement",
    "story",
]

EVENT_MODES: dict[Event, tuple[Mode, ...]] = {
    "greeting": ("learning", "conversation", "engagement", "support"),
    "correct": ("learning",),
    "incorrect": ("learning",),
    "hint": ("learning",),
    "reveal": ("learning",),
    "level_up": ("learning",),
    "break_offer": ("learning",),
    "checkin": ("conversation", "engagement"),
    "support": ("support",),
    "distress": ("support",),
    "generic": ("learning", "conversation", "engagement", "support"),
    "conversation": ("conversation",),
    "engagement": ("engagement",),
    "story": ("engagement",),
}

TEMPLATES: dict[Event, dict[int, tuple[str, ...]]] = {
    "greeting": {
        1: ("Hi {nickname}!", "Hello {nickname}."),
        2: ("Hi {nickname}, good to see you!", "Hello {nickname}, let us begin."),
        3: ("Hi {nickname}, good to see you again!", "Hello {nickname}, ready to explore?"),
    },
    "correct": {
        1: ("Yes! Well done.", "That is right!"),
        2: ("Yes, that is correct!", "Well done, you got it!"),
        3: ("That is correct, nicely done!", "Correct! You are doing great!"),
    },
    "incorrect": {
        1: ("Nice try! Let us try again.", "Good try. Let us see."),
        2: ("Nice try! Let us try again together.", "Good effort. Let us try once more."),
        3: ("Nice try! Let us work it out together.", "Good effort. Let us try that again."),
    },
    "hint": {
        1: ("Here is a little hint.", "A small clue for you."),
        2: ("Here is a hint to help you.", "Let me give you a small clue."),
        3: ("Here is a hint to guide you.", "Let me offer a gentle clue."),
    },
    "reveal": {
        1: ("The answer is here. Let us look.", "Here is the answer. Good try."),
        2: (
            "Here is the answer. Let us look together.",
            "The answer is here. You did well trying.",
        ),
        3: (
            "Here is the answer. Let us see it together.",
            "Let us look at the answer together.",
        ),
    },
    "level_up": {
        1: ("Hooray {nickname}! You grew!", "Well done {nickname}! You moved up!"),
        2: (
            "Hooray {nickname}! You reached a new level!",
            "Well done {nickname}! You leveled up!",
        ),
        3: ("Hooray {nickname}! You are blooming!", "Well done {nickname}! Another step up!"),
    },
    "break_offer": {
        1: ("Let us take a little break.", "Shall we play now?"),
        2: ("Let us take a short break together.", "Shall we do something fun now?"),
        3: ("Let us pause and take a short break.", "Shall we try something fun for a while?"),
    },
    "checkin": {
        1: ("How do you feel today?", "How are you feeling?"),
        2: ("How are you feeling today?", "Tell me how you feel today."),
        3: ("How are you feeling today, {nickname}?", "Would you like to share how you feel?"),
    },
    "support": {
        1: (
            "I am here with you. 💛 Let us take a breath. Want to rest or play?",
            "Big feelings can be tricky. 💛 Take one slow breath. Shall we rest or chat?",
            "I hear you, {nickname}. 💛 Let us breathe together. Want to chat or play?",
        ),
        2: (
            (
                "It is okay to feel this way. 💛 Let us take one slow breath. "
                "Want to rest, chat, or play?"
            ),
            "I am right here with you. 💛 Let us pause and breathe. Would you like a rest or chat?",
        ),
        3: (
            (
                "I am right here beside you, {nickname}. 💛 "
                "Let us take one slow, calm breath together. Would you like to rest, chat, or play?"
            ),
            (
                "It is completely okay to feel like this. 💛 We can take a quiet breath together. "
                "Do you want to rest, talk, or play a gentle game?"
            ),
        ),
    },
    "distress": {
        1: ("Please tell a grown-up you trust.", "Talk to a grown-up you trust."),
        2: (
            "I want you to be safe. Please talk to a grown-up you trust.",
            "Please tell a grown-up you trust. They can help.",
        ),
        3: (
            "Thank you for telling me. Please talk to a grown-up you trust.",
            "I want you to be safe. Please talk to a grown-up you trust, they can help.",
        ),
    },
    "conversation": {
        1: (
            "I love chatting with you! 🌱 What do you like doing?",
            "That is fun to hear! 🌸 Tell me about your favorite thing.",
            "You are a great friend, {nickname}! 🌱 What shall we talk about?",
        ),
        2: (
            "I love sharing stories with you, {nickname}! 🌱 What fun thing did you see today?",
            "That sounds so fun to hear! 🌸 What is something you really enjoy doing?",
        ),
        3: (
            (
                "It is always a treat chatting with you, {nickname}! 🌱 "
                "What is the most exciting thing on your mind today?"
            ),
            "I really enjoy hearing all your thoughts! 🌸 What would you love to talk about next?",
        ),
    },
    "engagement": {
        1: (
            "Let us play a game! 🎈 Can you name a red fruit?",
            "Here is a fun little riddle! 🌟 What has yellow petals? A sunflower!",
            "Let us pretend together, {nickname}! 🎈 Can you hop like a bunny?",
        ),
        2: (
            (
                "Let us play a pretend game together! 🌟 Pretend you are flying high like a bird. "
                "Where will you fly first?"
            ),
            (
                "Here is a playful word riddle for you! 🌟 "
                "What has four wheels and goes zoom? A car!"
            ),
        ),
        3: (
            (
                "Here is a clever riddle for you, {nickname}! 🌟 "
                "I am crunchy, orange, and rabbits love eating me. The answer is a sweet carrot!"
            ),
            (
                "Let us play an imaginative pretend game together! 🌟 "
                "Imagine we are exploring a magical secret garden today. "
                "What amazing flowers do you find?"
            ),
        ),
    },
    "story": {
        1: (
            (
                "Once, a tiny seed woke up. 🌱 The warm sun smiled brightly. "
                "The seed grew into a flower!"
            ),
            (
                "A little puppy found a ball. 🐶 The ball bounced very high. "
                "The happy puppy caught it!"
            ),
        ),
        2: (
            (
                "A little frog found a green lily pad. 🐸 The happy frog sang a sweet song. "
                "All the friendly pond animals danced happily!"
            ),
            (
                "A tiny bird learned to fly today. 🐦 She fluttered high above the tall trees. "
                "The gentle wind carried her safely home!"
            ),
        ),
        3: (
            (
                "Deep inside a magical forest, a curious squirrel found a shiny golden acorn. 🐿️ "
                "When the squirrel tapped the acorn, bright colorful flowers blossomed all around. "
                "The whole garden sparkled with warm light!"
            ),
            (
                "A brave little hedgehog went on a sunny adventure across the meadow. 🦔 "
                "He shared sweet ripe berries with a kind deer he met. "
                "Together they watched the beautiful sunset over the hills!"
            ),
        ),
    },
    "generic": {
        1: (
            "Let us keep exploring together! 🌱",
            "I love playing with you, {nickname}! 🌸",
        ),
        2: (
            "Let us keep discovering new words together! 🌱",
            "You are doing wonderful today, {nickname}! 🌸",
        ),
        3: (
            "Let us keep exploring new and exciting words together! 🌱",
            "You are doing such a wonderful job today, {nickname}! 🌸",
        ),
    },
}

MAX_NICKNAME_CHARS = 20
DEFAULT_NICKNAME = "friend"


def _nickname_slot(nickname: str | None) -> str:
    if nickname is None:
        return DEFAULT_NICKNAME
    cleaned = " ".join(nickname.split())[:MAX_NICKNAME_CHARS]
    return cleaned or DEFAULT_NICKNAME


def _level_key(level: int) -> int:
    if level <= 1:
        return 1
    if level == 2:
        return 2
    return 3


def pick_template(
    mode: Mode,
    level: int,
    event: Event,
    seed: int,
    nickname: str | None,
) -> str:
    """Choose a deterministic, safe fallback reply for the given combination."""

    if event == "generic" and mode in EVENT_MODES and mode in TEMPLATES:
        chosen_event: Event = cast(Event, mode)
    elif mode in EVENT_MODES.get(event, ()):
        chosen_event = event
    else:
        chosen_event = "generic"

    variants = TEMPLATES[chosen_event][_level_key(level)]
    chosen = variants[seed % len(variants)]
    return chosen.replace("{nickname}", _nickname_slot(nickname))
