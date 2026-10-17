"""Pure domain exceptions. No framework imports."""

from __future__ import annotations


class DomainError(Exception):
    """Base class for expected, handleable domain failures."""


class UnknownChoiceError(DomainError):
    """Raised when a choice id does not exist on the item."""

    def __init__(self, item_id: str) -> None:
        super().__init__(f"unknown choice for item {item_id}")
        self.item_id = item_id
