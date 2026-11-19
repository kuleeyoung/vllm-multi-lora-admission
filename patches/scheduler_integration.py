"""Source edits for the pinned vLLM waiting loop."""


def integrate(source):
    def replace(old, new):
        nonlocal source
        if source.count(old) != 1:
            raise ValueError(f"Expected exactly one scheduler anchor: {old!r}")
        source = source.replace(old, new)

    replace('_trace("scheduler_loaded", source=__file__)', '''from admission_policy import AdmissionPolicy

_admission_mode = _trace_os.environ.get("LORA_ADMISSION_MODE", "B0")
if _admission_mode not in {"B0", "B1", "B2", "B3"}:
    raise ValueError("LORA_ADMISSION_MODE must be B0, B1, B2 or B3")


def _adapter_id(request):
    return request.lora_request.lora_int_id if request.lora_request else None


def _fresh_lora(request):
    return (request.status == RequestStatus.WAITING and _adapter_id(request) is not None
            and request.num_computed_tokens == 0 and not request.resumable)


_trace("scheduler_loaded", source=__file__, mode=_admission_mode,
       hot_guard_ms=int(_trace_os.environ.get("LORA_HOT_GUARD_MS", "0")))''')
    replace("        self.waiting = create_request_queue(self.policy)", '''        self._admission = None
        if _admission_mode != "B0":
            if (not self.lora_config or self.policy != SchedulingPolicy.FCFS
                    or self.connector is not None or self.parallel_config.data_parallel_size != 1
                    or self.parallel_config.pipeline_parallel_size != 1
                    or self.parallel_config.tensor_parallel_size != 1
                    or vllm_config.speculative_config is not None):
                raise ValueError("B1/B2/B3 require single-device local FCFS LoRA without speculative decoding")
            self._admission = AdmissionPolicy(
                _admission_mode,
                int(_trace_os.environ.get("LORA_WAIT_MS", "500")) * 1_000_000,
                int(_trace_os.environ.get("LORA_RESERVATION_TTL_MS", "10000")) * 1_000_000,
                int(_trace_os.environ.get("LORA_COOLDOWN_MS", "1000")) * 1_000_000,
                _trace,
                cold_ids=tuple(int(v) for v in _trace_os.environ.get("LORA_COLD_ADAPTER_IDS", "").split(",") if v),
                hot_guard_ns=int(_trace_os.environ.get("LORA_HOT_GUARD_MS", "0")) * 1_000_000,
                followup_ns=int(_trace_os.environ.get("LORA_FOLLOWUP_MS", "0")) * 1_000_000,
            )
        self._trace_schedule_calls = 0
        _trace("scheduler_capacity", mode=_admission_mode,
               max_loras=self.lora_config.max_loras if self.lora_config else None)
        self.waiting = create_request_queue(self.policy)''')
    replace("        scheduled_timestamp = time.monotonic()", '''        scheduled_timestamp = time.monotonic()
        sample_started_ns = None
        if _trace_sample_every:
            self._trace_schedule_calls += 1
            if self._trace_schedule_calls % _trace_sample_every == 0:
                sample_started_ns = time.monotonic_ns()''')
    replace("        return scheduler_output", '''        if sample_started_ns is not None:
            _trace("schedule_sample", cpu_ns=time.monotonic_ns() - sample_started_ns,
                   batch_requests=len(num_scheduled_tokens), scheduled_tokens=total_num_scheduled_tokens,
                   max_active_requests=self.max_num_active_reqs)
        return scheduler_output''')
    replace('            _trace("queued", request)', '''            _trace("queued", request)
            if self._admission is not None and _fresh_lora(request):
                self._admission.queued(request.request_id, time.monotonic_ns())''')
    replace('        _trace("finished", request)', '''        _trace("finished", request)
        if self._admission is not None:
            self._admission.finished(request.request_id, time.monotonic_ns())''')
    replace('\n        request.status = RequestStatus.PREEMPTED\n', '''
        _trace("preempted", request)
        if self._admission is not None:
            self._admission.clear(time.monotonic_ns(), "upstream_preemption")
        request.status = RequestStatus.PREEMPTED
''')
    replace("        # Next, schedule the WAITING requests.", '''        admission = self._admission
        priority_id = None
        priority_attempt = False
        failed_priority = None
        if admission is not None:
            priority_id = admission.begin(
                time.monotonic_ns(),
                (_adapter_id(req) for req in self.running if _adapter_id(req) is not None),
                ((req.request_id, _adapter_id(req)) for req in self.waiting if _fresh_lora(req)),
                self.lora_config.max_loras,
            )

        def reject_priority(reason):
            nonlocal priority_attempt, failed_priority
            if not priority_attempt:
                return False
            admission.rejected(time.monotonic_ns(), reason)
            priority_attempt = False
            failed_priority = priority_id
            return True

        # Next, schedule the WAITING requests.''')
    replace("                request_to_skip = from_queue.pop_request()", '''                if reject_priority("target_skipped"):
                    return
                request_to_skip = from_queue.pop_request()''')
    replace("                request = request_queue.peek_request()\n                request_id = request.request_id", '''                priority_attempt = bool(priority_id and failed_priority is None
                                        and request_queue is self.waiting)
                request = self.requests[priority_id] if priority_attempt else request_queue.peek_request()
                request_id = request.request_id
                if priority_attempt:
                    admission.event("handoff_attempt")
                elif request_id == failed_priority:
                    skip_request(request_queue)
                    continue
                if admission is not None and _fresh_lora(request) and admission.should_defer(_adapter_id(request)):
                    if _trace_detailed:
                        _trace("drain_deferred", request)
                    skip_request(request_queue)
                    continue''')
    for anchor, reason in (
        ("                    # compute to a cadence-aligned step.", "prefill_deferred"),
        ("                        # we can stop the scheduling here.", "token_budget"),
        ("                            if padded_num_tokens > request_token_budget:", "token_budget"),
        ("                        if num_new_tokens == 0:", "token_alignment"),
        ("                        self.encoder_cache_manager.free(request)\n                    break", "kv_budget"),
    ):
        if reason == "kv_budget":
            replace(anchor + "\n\n                # KVTransfer:", anchor.rsplit("\n", 1)[0]
                    + '\n                    if reject_priority("kv_budget"):\n'
                    + "                        continue\n                    break\n\n                # KVTransfer:")
            continue
        start = source.index(anchor)
        end = source.index("\n", source.index("break", start + len(anchor)))
        block = source[start:end]
        prefix = block.rsplit("\n", 1)[1].removesuffix("break")
        replace(block, block.removesuffix("break") + f'if reject_priority("{reason}"):\n'
                + prefix + "    continue\n" + prefix + "break")
    replace("                request = request_queue.pop_request()\n                self.deferred_waiting.discard(request)", '''                if priority_attempt:
                    request_queue.remove_request(request)
                    priority_id = None
                    priority_attempt = False
                else:
                    request = request_queue.pop_request()
                self.deferred_waiting.discard(request)''')
    replace('                _trace("admit", request, active_before=sorted(scheduled_loras))', '''                _trace("admit", request, active_before=sorted(scheduled_loras))
                if admission is not None:
                    admission.admitted(request_id, _adapter_id(request), scheduled_loras,
                                       self.lora_config.max_loras, time.monotonic_ns())
                    if admission.pending is None:
                        priority_id = None''')
    replace("        # Check if the scheduling constraints are satisfied.", '''        if admission is not None:
            admission.rejected(time.monotonic_ns(), "round_resources_unavailable")

        # Check if the scheduling constraints are satisfied.''')
    return source
