"""Filter base class — the contract every benchmark filter implements.

Contract (task spec §4):
  - reset()                      re-initialize all state
  - update(sample, timestamp)    one chronological sample; timestamp is
                                 PHYSICAL sample time in seconds (float).
                                 Returns the current vertical-speed estimate.
  - get_estimate()               last estimate (m/s) without new data
  - explicit configuration       constructor kwargs only
  - deterministic causal         no future samples, no centered windows

Sampling intervals are ALWAYS derived from timestamps (delta t between
consecutive updates), never assumed constant. Filters that internally need
per-sample coefficients (IIR designs) recompute them when dt changes by
more than DT_RECOMP_TOLERANCE, so 45/50 Hz and 100 Hz sessions run through
physically equivalent parameterizations (seconds, not samples).
"""
from __future__ import annotations

DT_RECOMP_TOLERANCE = 0.02       # refit internal coefficients beyond 2% dt change


class Filter:
    """Common timestamp bookkeeping. Subclasses implement _on_update."""

    name = "filter"
    requires_imu = False          # fusion filters only (Group F, deferred)

    def __init__(self):
        self.reset()

    def reset(self):
        self._t_prev = None
        self._dt = None
        self._initialized = False
        self._v = 0.0
        self._init_state()

    # --- subclass hooks -----------------------------------------------------
    def _init_state(self):
        pass

    def _on_first(self, t: float, z: float):
        """Handle the very first sample (no dt available)."""
        self._v = 0.0

    def _on_update(self, t: float, z: float, dt: float) -> float:
        raise NotImplementedError

    # --- public API -----------------------------------------------------------
    def update(self, sample: float, timestamp: float) -> float:
        t = float(timestamp)
        z = float(sample)
        if self._t_prev is None:
            self._t_prev = t
            self._initialized = True
            self._on_first(t, z)
            return self.get_estimate()
        dt = t - self._t_prev
        if dt <= 0:
            # out-of-order or duplicate timestamp: repeat last estimate
            # without advancing state (engine flags these in diagnostics)
            return self.get_estimate()
        self._dt = dt
        self._t_prev = t
        self._v = float(self._on_update(t, z, dt))
        return self.get_estimate()

    def get_estimate(self) -> float:
        return float(self._v)

    # convenience for metrics that want altitude too
    def get_altitude(self) -> float:
        return float(getattr(self, "_h", 0.0))

    def __repr__(self):
        return f"{self.name}({self._config_repr()})"

    def _config_repr(self) -> str:
        return ""
