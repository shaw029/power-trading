import math
from dataclasses import dataclass, field

_SOC_TOL = 1e-9


@dataclass
class BESSAsset:
    capacity_mwh: float
    power_mw: float
    charge_efficiency: float
    discharge_efficiency: float
    degradation_cost_per_mwh: float
    initial_soc_pct: float
    min_soc_pct: float = 0.0
    max_soc_pct: float = 1.0

    _soc_mwh: float = field(init=False, repr=False)
    _min_soc_mwh: float = field(init=False, repr=False)
    _max_soc_mwh: float = field(init=False, repr=False)
    _degradation_cost: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_soc_pct <= self.max_soc_pct <= 1.0:
            raise ValueError(
                f"Invalid SOC bounds: require 0 <= min ({self.min_soc_pct}) "
                f"<= max ({self.max_soc_pct}) <= 1"
            )
        self._min_soc_mwh = self.min_soc_pct * self.capacity_mwh
        self._max_soc_mwh = self.max_soc_pct * self.capacity_mwh
        self._soc_mwh = self.initial_soc_pct * self.capacity_mwh
        self._degradation_cost = 0.0

    @property
    def soc_pct(self) -> float:
        return self._soc_mwh / self.capacity_mwh

    @property
    def degradation_cost(self) -> float:
        return self._degradation_cost

    def charge(self, mw: float, duration_h: float) -> None:
        if mw > self.power_mw:
            raise ValueError(
                f"Charge power {mw} MW exceeds limit {self.power_mw} MW"
            )
        gross_mwh = mw * duration_h
        stored_mwh = gross_mwh * self.charge_efficiency
        new_soc = self._soc_mwh + stored_mwh
        if new_soc > self._max_soc_mwh and not math.isclose(
            new_soc, self._max_soc_mwh, abs_tol=_SOC_TOL
        ):
            raise ValueError(
                f"Charge would exceed max SOC: "
                f"{new_soc:.4f} MWh > {self._max_soc_mwh} MWh"
            )
        self._soc_mwh = min(new_soc, self._max_soc_mwh)
        self._degradation_cost += gross_mwh * self.degradation_cost_per_mwh

    def discharge(self, mw: float, duration_h: float) -> None:
        if mw > self.power_mw:
            raise ValueError(
                f"Discharge power {mw} MW exceeds limit {self.power_mw} MW"
            )
        released_mwh = mw * duration_h
        drawn_mwh = released_mwh / self.discharge_efficiency
        new_soc = self._soc_mwh - drawn_mwh
        if new_soc < self._min_soc_mwh and not math.isclose(
            new_soc, self._min_soc_mwh, abs_tol=_SOC_TOL
        ):
            raise ValueError(
                f"Discharge would breach min SOC: "
                f"{new_soc:.4f} MWh < {self._min_soc_mwh} MWh"
            )
        self._soc_mwh = max(new_soc, self._min_soc_mwh)
        self._degradation_cost += released_mwh * self.degradation_cost_per_mwh

    def can_charge(self, mw: float, duration_h: float) -> bool:
        if mw > self.power_mw:
            return False
        stored_mwh = mw * duration_h * self.charge_efficiency
        new_soc = self._soc_mwh + stored_mwh
        return new_soc <= self._max_soc_mwh or math.isclose(
            new_soc, self._max_soc_mwh, abs_tol=_SOC_TOL
        )

    def can_discharge(self, mw: float, duration_h: float) -> bool:
        if mw > self.power_mw:
            return False
        drawn_mwh = mw * duration_h / self.discharge_efficiency
        new_soc = self._soc_mwh - drawn_mwh
        return new_soc >= self._min_soc_mwh or math.isclose(
            new_soc, self._min_soc_mwh, abs_tol=_SOC_TOL
        )

    def reset(self, soc_pct: float | None = None) -> None:
        if soc_pct is not None:
            if not self.min_soc_pct <= soc_pct <= self.max_soc_pct:
                raise ValueError(
                    f"Invalid SOC {soc_pct}: require "
                    f"{self.min_soc_pct} <= soc <= {self.max_soc_pct}"
                )
            self.initial_soc_pct = soc_pct
        self._soc_mwh = self.initial_soc_pct * self.capacity_mwh
        self._degradation_cost = 0.0
