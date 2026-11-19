"""Single-reservation LoRA admission policy, independent of vLLM queues."""
from collections import Counter
from dataclasses import dataclass


@dataclass
class Reservation:
    target: str
    adapter: int
    victim: int
    deadline: int
    released: bool = False
    followup: bool = False


class AdmissionPolicy:
    def __init__(self, mode, wait_ns, ttl_ns, cooldown_ns, emit, *,
                 cold_ids=(), hot_guard_ns=0, followup_ns=0):
        if mode not in {"B1", "B2", "B3"} or min(wait_ns, ttl_ns, cooldown_ns) <= 0:
            raise ValueError("Expected B1/B2/B3 and positive timing parameters")
        if mode == "B3" and (not cold_ids or min(hot_guard_ns, followup_ns) <= 0):
            raise ValueError("B3 requires cold adapter IDs and positive guard/window")
        self.mode = mode
        self.wait_ns = wait_ns
        self.ttl_ns = ttl_ns
        self.cooldown_ns = cooldown_ns
        self.emit = emit
        self.arrivals = {}
        self.cooldown = {}
        self.pending = None
        self.cold_ids = frozenset(cold_ids)
        self.hot_guard_ns = hot_guard_ns
        self.followup_ns = followup_ns
        self.followup_until = 0

    def queued(self, request_id, now):
        self.arrivals.setdefault(request_id, now)

    def event(self, name, **extra):
        state = self.pending
        self.emit(name, target_id=state.target, target_adapter=state.adapter,
                  victim_adapter=state.victim, mode=self.mode, **extra)

    def clear(self, now, reason):
        if reason == "upstream_preemption":
            self.followup_until = 0
        if self.pending is not None:
            self.event("reservation_closed", reason=reason)
            self.cooldown[self.pending.adapter] = now + self.cooldown_ns
            self.pending = None

    def finished(self, request_id, now):
        self.arrivals.pop(request_id, None)
        if self.pending is not None and self.pending.target == request_id:
            self.clear(now, "target_finished")

    def begin(self, now, running_adapters, candidates, limit):
        self.cooldown = {key: until for key, until in self.cooldown.items() if until > now}
        counts = Counter(running_adapters)
        eligible = {request_id: adapter for request_id, adapter in candidates
                    if request_id in self.arrivals}
        state = self.pending
        if state is not None:
            if now >= state.deadline:
                self.clear(now, "expired")
            elif state.target not in eligible:
                self.clear(now, "target_unavailable")
            elif state.adapter in counts:
                self.clear(now, "target_adapter_active")
            elif state.victim not in counts and len(counts) < limit:
                if not state.released:
                    state.released = True
                    self.event("slot_released", active=sorted(counts))
                return state.target if self.mode != "B1" else None
            return None
        if len(counts) != limit:
            return None
        ranked = [(self.arrivals[rid], rid, adapter) for rid, adapter in eligible.items()
                  if adapter not in counts and adapter not in self.cooldown
                  and now - self.arrivals[rid] >= self.wait_ns]
        if ranked:
            selected = min(ranked)
            has_credit = self.mode == "B3" and now < self.followup_until
            self.followup_until = 0
            followup = False
            guarded = False
            if has_credit:
                cold = [row for row in ranked if row[2] in self.cold_ids]
                guarded = any(adapter not in self.cold_ids and
                              now - self.arrivals[rid] >= self.hot_guard_ns
                              for rid, adapter in eligible.items())
                if cold and not guarded:
                    selected = min(cold)
                    followup = True
            arrived, target, adapter = selected
            victim = min(counts, key=lambda key: (counts[key], key))
            self.pending = Reservation(target, adapter, victim, now + self.ttl_ns, followup=followup)
            self.event("drain_started", waited_ns=now - arrived, deadline_ns=now + self.ttl_ns,
                       victim_running=counts[victim])
            if followup:
                self.event("cold_followup_selected")
            elif guarded:
                self.event("hot_guard_kept_order")
        return None

    def should_defer(self, adapter):
        state = self.pending
        return state is not None and not state.released and state.victim == adapter

    def admitted(self, request_id, adapter, active_before, limit, now):
        self.arrivals.pop(request_id, None)
        state = self.pending
        if state is None:
            return
        if request_id == state.target:
            if state.released:
                self.event("target_admitted", request_id=request_id)
                if self.mode == "B3" and adapter in self.cold_ids and not state.followup:
                    self.followup_until = now + self.followup_ns
            self.clear(now, "target_admitted")
        elif (state.released and adapter is not None and adapter not in active_before
              and len(active_before) + 1 == limit):
            self.event("slot_taken", request_id=request_id, adapter_id=adapter)
            self.clear(now, "slot_taken")
        elif adapter == state.adapter:
            self.clear(now, "target_adapter_active")

    def rejected(self, now, reason):
        if self.pending is not None and self.pending.released:
            self.clear(now, reason)
