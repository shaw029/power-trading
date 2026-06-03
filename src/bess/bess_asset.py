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

    _soc_mwh: float = field(init=False, repr=False)
    _degradation_cost: float = field(init=False, repr=False)

    def __post_init__(self) -> None:
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
        if new_soc > self.capacity_mwh and not math.isclose(
            new_soc, self.capacity_mwh, abs_tol=_SOC_TOL
        ):
            raise ValueError(
                f"Charge would exceed capacity: "
                f"{new_soc:.4f} MWh > {self.capacity_mwh} MWh"
            )
        self._soc_mwh = min(new_soc, self.capacity_mwh)
        self._degradation_cost += gross_mwh * self.degradation_cost_per_mwh

    def discharge(self, mw: float, duration_h: float) -> None:
        if mw > self.power_mw:
            raise ValueError(
                f"Discharge power {mw} MW exceeds limit {self.power_mw} MW"
            )
        released_mwh = mw * duration_h
        drawn_mwh = released_mwh / self.discharge_efficiency
        new_soc = self._soc_mwh - drawn_mwh
        if new_soc < 0 and not math.isclose(new_soc, 0.0, abs_tol=_SOC_TOL):
            raise ValueError(
                f"Discharge would deplete SOC: "
                f"{new_soc:.4f} MWh < 0 MWh"
            )
        self._soc_mwh = max(new_soc, 0.0)
        self._degradation_cost += released_mwh * self.degradation_cost_per_mwh

    def can_charge(self, mw: float, duration_h: float) -> bool:
        if mw > self.power_mw:
            return False
        stored_mwh = mw * duration_h * self.charge_efficiency
        new_soc = self._soc_mwh + stored_mwh
        return new_soc <= self.capacity_mwh or math.isclose(
            new_soc, self.capacity_mwh, abs_tol=_SOC_TOL
        )

    def can_discharge(self, mw: float, duration_h: float) -> bool:
        if mw > self.power_mw:
            return False
        drawn_mwh = mw * duration_h / self.discharge_efficiency
        new_soc = self._soc_mwh - drawn_mwh
        return new_soc >= 0 or math.isclose(new_soc, 0.0, abs_tol=_SOC_TOL)

    def reset(self, soc_pct: float | None = None) -> None:
        if soc_pct is not None:
            self.initial_soc_pct = soc_pct
        self._soc_mwh = self.initial_soc_pct * self.capacity_mwh
        self._degradation_cost = 0.0
