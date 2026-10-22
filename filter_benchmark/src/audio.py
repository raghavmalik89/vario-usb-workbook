"""Configurable audio state machine (Phase 3, spec §3).

Kept deliberately SEPARATE from every filter so filter behaviour and audio
behaviour can be measured independently: a filter emits climb-rate estimates;
this machine turns them into audio latch events under an explicit policy.

Default policy (identical across all filters, per spec):
    lift ON at +0.20 m/s, lift OFF at +0.05 m/s, no additional hold time.
Optional parameters (hold_s, min_on_s) exist so a policy variant can be
defined explicitly, but the benchmark default leaves them at zero.

Everything uses actual replay timestamps — never assumed sample rates.
"""
from __future__ import annotations


class AudioStateMachine:
    """Two-state hysteresis latch (OFF/ON) with optional hold and min-on.

    update(t, v) -> state after this sample ('on'/'off'); transitions are
    recorded with their physical timestamps in .transitions as
    (t, new_state) pairs.
    """

    def __init__(self, lift_on: float = 0.20, lift_off: float = 0.05,
                 hold_s: float = 0.0, min_on_s: float = 0.0):
        assert lift_on > lift_off >= 0.0
        self.lift_on = float(lift_on)
        self.lift_off = float(lift_off)
        self.hold_s = float(hold_s)
        self.min_on_s = float(min_on_s)
        self._state = "off"
        self._on_since = None      # timestamp of current ON transition
        self._off_pending = None   # timestamp a pending OFF was first eligible
        self.transitions = []      # (t, 'on'/'off') physical timestamps

    def reset(self):
        self._state = "off"
        self._on_since = None
        self._off_pending = None
        self.transitions = []

    @property
    def state(self):
        return self._state

    def update(self, t: float, v: float) -> str:
        if self._state == "off":
            if v >= self.lift_on:
                self._state = "on"
                self._on_since = t
                self.transitions.append((t, "on"))
        else:  # on
            if v < self.lift_off:
                if self._off_pending is None:
                    self._off_pending = t
                held = t - self._off_pending
                min_on_ok = (self._on_since is not None
                             and t - self._on_since >= self.min_on_s)
                if held >= self.hold_s and min_on_ok:
                    self._state = "off"
                    self._on_since = None
                    self._off_pending = None
                    self.transitions.append((t, "off"))
            else:
                self._off_pending = None   # re-crossed: cancel pending OFF
        return self._state


def apply_audio(t, v, sm: AudioStateMachine):
    """Run the state machine over an estimate stream. Returns
    (state_array, transitions). Pure replay — no filter side effects."""
    states = []
    sm.reset()
    for i in range(len(t)):
        states.append(sm.update(float(t[i]), float(v[i])))
    return states, list(sm.transitions)
