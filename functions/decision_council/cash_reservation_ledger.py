"""Idempotent in-memory cash reservations for one decision registration."""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class CashReservation:
    reservation_id: str
    amount: float
    funding_type: str
    pair_id: str = ""


class CashReservationLedger:
    """Track each planned cash use once and expose auditable availability."""

    def __init__(self, *, cash_amount: float, minimum_buffer: float = 0.0):
        self.cash_amount = _non_negative(cash_amount, "cash_amount")
        self.minimum_buffer = _non_negative(minimum_buffer, "minimum_buffer")
        self._reservations: dict[str, CashReservation] = {}

    def reserve(
        self,
        reservation_id: str,
        amount: float,
        *,
        funding_type: str = "cash",
        pair_id: str = "",
    ) -> CashReservation:
        key = str(reservation_id)
        if not key:
            raise ValueError("reservation_id is required")
        reservation = CashReservation(
            reservation_id=key,
            amount=_non_negative(amount, "amount"),
            funding_type=str(funding_type),
            pair_id=str(pair_id),
        )
        existing = self._reservations.get(key)
        if existing is not None and existing != reservation:
            raise ValueError(f"reservation_id collision: {key}")
        self._reservations[key] = reservation
        return reservation

    def release(self, reservation_id: str) -> CashReservation | None:
        return self._reservations.pop(str(reservation_id), None)

    @property
    def reserved_total(self) -> float:
        return float(sum(item.amount for item in self._reservations.values()))

    def reserved_for_pair(self, pair_id: str) -> float:
        key = str(pair_id)
        return float(
            sum(
                item.amount
                for item in self._reservations.values()
                if item.pair_id == key
            )
        )

    def available(
        self,
        *,
        excluding_reservation_id: str = "",
        conditional_credit: float = 0.0,
        after_buffer: bool = False,
    ) -> float:
        excluded = self._reservations.get(str(excluding_reservation_id))
        reserved = self.reserved_total - (excluded.amount if excluded else 0.0)
        available = (
            self.cash_amount
            - reserved
            + _non_negative(conditional_credit, "conditional_credit")
        )
        if after_buffer:
            available -= self.minimum_buffer
        return max(float(available), 0.0)

    def snapshot(self) -> tuple[dict, ...]:
        return tuple(item.__dict__.copy() for item in self._reservations.values())


def _non_negative(value: float, name: str) -> float:
    numeric = float(value)
    if not math.isfinite(numeric) or numeric < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")
    return numeric
