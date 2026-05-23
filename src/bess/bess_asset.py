from dataclasses import dataclass, field


@dataclass
class BESSAsset:
    capacity_mwh: float
    power_mw: float
    round_trip_efficiency: float
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
        stored_mwh = gross_mwh * self.round_trip_efficiency
        new_soc = self._soc_mwh + stored_mwh
        if new_soc > self.capacity_mwh:
            raise ValueError(
                f"Charge would exceed capacity: "
                f"{new_soc:.4f} MWh > {self.capacity_mwh} MWh"
            )
        self._soc_mwh = new_soc
        self._degradation_cost += gross_mwh * self.degradation_cost_per_mwh

    def discharge(self, mw: float, duration_h: float) -> None:
        if mw > self.power_mw:
            raise ValueError(
                f"Discharge power {mw} MW exceeds limit {self.power_mw} MW"
            )
        released_mwh = mw * duration_h
        new_soc = self._soc_mwh - released_mwh
        if new_soc < 0:
            raise ValueError(
                f"Discharge would deplete SOC: "
                f"{new_soc:.4f} MWh < 0 MWh"
            )
        self._soc_mwh = new_soc
        self._degradation_cost += released_mwh * self.degradation_cost_per_mwh

    def can_charge(self, mw: float, duration_h: float) -> bool:
        if mw > self.power_mw:
            return False
        stored_mwh = mw * duration_h * self.round_trip_efficiency
        return self._soc_mwh + stored_mwh <= self.capacity_mwh

    def can_discharge(self, mw: float, duration_h: float) -> bool:
        if mw > self.power_mw:
            return False
        released_mwh = mw * duration_h
        return self._soc_mwh - released_mwh >= 0

    def reset(self) -> None:
        self._soc_mwh = self.initial_soc_pct * self.capacity_mwh
        self._degradation_cost = 0.0
