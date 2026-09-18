"""Spend cap enforced by reservation.

Budget is reserved before dispatch using a worst-case estimate, then reconciled
against the provider's actual token counts when the call returns. Reserving at
dispatch is the point: checking only at completion lets C concurrent calls sail
past the cap together.

The cap therefore binds on a conservative estimate, so a run aborts slightly
before the true limit rather than slightly after.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Literal

Phase = Literal["run", "judge"]


class BudgetExceeded(RuntimeError):
    """Raised when a reservation would breach the cap. Aborts the phase cleanly."""

    def __init__(self, phase: str, requested: float, committed: float, reserved: float, cap: float):
        self.phase = phase
        self.requested = requested
        self.committed = committed
        self.reserved = reserved
        self.cap = cap
        super().__init__(
            f"spend cap reached for phase {phase!r}: committed ${committed:.4f} + "
            f"in-flight ${reserved:.4f} + next call ${requested:.4f} would exceed "
            f"cap ${cap:.2f}"
        )


@dataclass
class Reservation:
    amount: float
    released: bool = False


@dataclass
class BudgetLedger:
    """Tracks committed and in-flight spend against a total and a per-phase cap."""

    max_total_usd: float
    phase: Phase = "run"
    phase_cap_usd: float | None = None
    estimate_headroom: float = 1.15
    abort_on_exceed: bool = True

    committed_usd: float = 0.0
    reserved_usd: float = 0.0
    calls_committed: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    @property
    def effective_cap(self) -> float:
        if self.phase_cap_usd is None:
            return self.max_total_usd
        return min(self.max_total_usd, self.phase_cap_usd)

    @property
    def outstanding(self) -> float:
        return self.committed_usd + self.reserved_usd

    @property
    def remaining(self) -> float:
        return max(0.0, self.effective_cap - self.outstanding)

    async def reserve(self, estimate_usd: float) -> Reservation:
        async with self._lock:
            return self._reserve_unlocked(estimate_usd)

    def _reserve_unlocked(self, estimate_usd: float) -> Reservation:
        if self.outstanding + estimate_usd > self.effective_cap:
            if self.abort_on_exceed:
                raise BudgetExceeded(
                    self.phase,
                    estimate_usd,
                    self.committed_usd,
                    self.reserved_usd,
                    self.effective_cap,
                )
        self.reserved_usd += estimate_usd
        return Reservation(amount=estimate_usd)

    async def commit(self, reservation: Reservation, actual_usd: float) -> None:
        """Replace a reservation with the real cost once the call has returned."""
        async with self._lock:
            if reservation.released:
                raise RuntimeError("reservation committed twice")
            reservation.released = True
            self.reserved_usd = max(0.0, self.reserved_usd - reservation.amount)
            self.committed_usd += actual_usd
            self.calls_committed += 1

    async def release(self, reservation: Reservation) -> None:
        """Give back a reservation for a call that never cost anything."""
        async with self._lock:
            if reservation.released:
                return
            reservation.released = True
            self.reserved_usd = max(0.0, self.reserved_usd - reservation.amount)

    def summary(self) -> dict[str, float | int | str]:
        return {
            "phase": self.phase,
            "cap_usd": round(self.effective_cap, 6),
            "committed_usd": round(self.committed_usd, 6),
            "reserved_usd": round(self.reserved_usd, 6),
            "remaining_usd": round(self.remaining, 6),
            "calls_committed": self.calls_committed,
        }
