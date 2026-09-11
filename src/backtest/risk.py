"""Prospective stress budgets for auction books; not a VaR or loss guarantee."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class BookRiskPolicy:
    """A common account policy, independent of which exit earns more in sample.

    The adverse price move is a declared scenario, not an executable stop.
    Gross MWh are charged without diversification credit across half-hours.
    Pending books retain their entry stress allocations until publication.
    Drawdown uses only equity observable at the auction and its running peak.
    """

    daily_loss_budget_pct: float = 0.01
    outstanding_loss_budget_pct: float = 0.02
    stress_move_gbp_per_mwh: float = 50.0
    reduce_at_drawdown: float = 0.05
    minimum_at_drawdown: float = 0.15
    minimum_scale: float = 0.25

    def __post_init__(self):
        values = vars(self).values()
        if not all(math.isfinite(x) for x in values):
            raise ValueError("Book risk policy values must be finite")
        if not 0 < self.daily_loss_budget_pct <= self.outstanding_loss_budget_pct <= 1:
            raise ValueError("Require 0 < daily budget <= outstanding budget <= 1")
        if self.stress_move_gbp_per_mwh <= 0:
            raise ValueError("Stress move must be positive")
        if not 0 <= self.reduce_at_drawdown < self.minimum_at_drawdown < 1:
            raise ValueError("Require 0 <= reduction drawdown < minimum drawdown < 1")
        if not 0 < self.minimum_scale <= 1:
            raise ValueError("Minimum scale must be in (0, 1]")

    def scale(self, equity: float, peak: float) -> float:
        drawdown = max(0.0, 1.0 - equity / peak)
        progress = min(
            1.0,
            max(
                0.0,
                (drawdown - self.reduce_at_drawdown)
                / (self.minimum_at_drawdown - self.reduce_at_drawdown),
            ),
        )
        return 1.0 - progress * (1.0 - self.minimum_scale)

    def new_book_budget(self, equity: float, peak: float, pending_stress: float) -> float:
        daily = equity * self.daily_loss_budget_pct * self.scale(equity, peak)
        remaining = max(0.0, equity * self.outstanding_loss_budget_pct - pending_stress)
        return min(daily, remaining)
