"""Configurable audio state machine (Phase 3 spec §3; Phase 4 WP-A extensions).

Kept deliberately SEPARATE from every filter so filter behaviour and audio
behaviour can be measured independently: a filter emits climb-rate estimates;
this machine turns them into audio latch events under an explicit policy.

Default policy (identical across all filters, per spec):
    lift ON at +0.20 m/s, lift OFF at +0.05 m/s, no additional hold time.
Optional parameters (hold_s, min_on_s) exist so a policy variant can be
defined explicitly, but the benchmark default leaves them at zero.

Phase 4 (WP-A) additions — both DISABLED by default, so Phase 3 replays of
this module are bit-identical to before:
  fault veto:   update(t, v, fault=...) — while fault is true the latch is
                forced OFF and cannot turn ON (prevents continuous audio ON
                during sensor faults; the estimator's fault flag is the input)
  max_on_s:     safety valve — force OFF after one continuous ON episode
                longer than max_on_s (0 = disabled)

Everything uses actual replay timestamps — never assumed sample rates.
"""
from __future__ import annotations


class AudioStateMachine:
    """Two-state hysteresis latch (OFF/ON) with optional hold, min-on,
    fault veto and max-continuous-ON safety.

    update(t, v, fault=False) -> state after this sample ('on'/'off');
    transitions are recorded with their physical timestamps in .transitions
    as (t, new_state) pairs, and in .transitions_r as (t, new_state, reason).
    """

    def __init__(self, lift_on: float = 0.20, lift_off: float = 0.05,
                 hold_s: float = 0.0, min_on_s: float = 0.0,
                 max_on_s: float = 0.0):
        assert lift_on > lift_off >= 0.0
        self.lift_on = float(lift_on)
        self.lift_off = float(lift_off)
        self.hold_s = float(hold_s)
        self.min_on_s = float(min_on_s)
        self.max_on_s = float(max_on_s)
        self._state = "off"
        self._on_since = None      # timestamp of current ON transition
        self._off_pending = None   # timestamp a pending OFF was first eligible
        self.transitions = []      # (t, 'on'/'off') physical timestamps
        self.transitions_r = []    # (t, 'on'/'off', reason)

    def reset(self):
        self._state = "off"
        self._on_since = None
        self._off_pending = None
        self.transitions = []
        self.transitions_r = []

    @property
    def state(self):
        return self._state

    def _to_on(self, t, reason):
        self._state = "on"
        self._on_since = t
        self.transitions.append((t, "on"))
        self.transitions_r.append((t, "on", reason))

    def _to_off(self, t, reason):
        self._state = "off"
        self._on_since = None
        self._off_pending = None
        self.transitions.append((t, "off"))
        self.transitions_r.append((t, "off", reason))

    def update(self, t: float, v: float, fault: bool = False) -> str:
        if fault:
            # sensor-fault veto: never ON during a fault; force OFF immediately
            if self._state == "on":
                self._to_off(t, "fault_veto")
            return self._state
        if self._state == "off":
            if v >= self.lift_on:
                self._to_on(t, "lift")
        else:  # on
            # max-continuous-ON safety valve (0 = disabled)
            if (self.max_on_s > 0.0 and self._on_since is not None
                    and t - self._on_since >= self.max_on_s):
                self._to_off(t, "max_on")
            elif v < self.lift_off:
                if self._off_pending is None:
                    self._off_pending = t
                held = t - self._off_pending
                min_on_ok = (self._on_since is not None
                             and t - self._on_since >= self.min_on_s)
                if held >= self.hold_s and min_on_ok:
                    self._to_off(t, "below_lift_off")
            else:
                self._off_pending = None   # re-crossed: cancel pending OFF
        return self._state


def apply_audio(t, v, sm: AudioStateMachine, faults=None):
    """Run the state machine over an estimate stream. Returns
    (state_array, transitions). Pure replay — no filter side effects.
    `faults` is an optional per-sample boolean sequence (estimator fault
    flags); None means no faults (Phase 3 behaviour)."""
    states = []
    sm.reset()
    for i in range(len(t)):
        f = bool(faults[i]) if faults is not None else False
        states.append(sm.update(float(t[i]), float(v[i]), fault=f))
    return states, list(sm.transitions)
