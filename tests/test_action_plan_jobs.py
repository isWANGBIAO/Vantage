import asyncio
import copy
import json
import unittest

from src.services.action_plan_jobs import ActionPlanJobService, complete_plan, normalize_plan_date


def saved_plan(identity="one"):
    return {"exists": True, "id": identity, "filename": f"action_plan_{identity}.json",
            "date": "20260930", "analysis": {"body": "Analysis"},
            "plan": {"body": "Plan"}, "meta": {"stats": {"total_tokens": 12}}}


class ActionPlanJobTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.saved = {"exists": False, "date": "20260930"}
        self.services = []

    async def asyncTearDown(self):
        for service in self.services:
            await service.close()

    def service(self, generate, **kwargs):
        async def read_today():
            return copy.deepcopy(self.saved)

        async def revision():
            return "revision-one"

        service = ActionPlanJobService(generate, read_today, revision, **kwargs)
        self.services.append(service)
        return service

    async def succeed(self, request):
        yield {"log": 'STREAM_ANALYSIS_CONTENT:"Analysis"'}
        self.saved = saved_plan()
        yield {"done": True}

    async def test_success_requires_saved_result_and_has_stable_snapshot(self):
        service = self.service(self.succeed)
        started = await service.start({"model": "model-a", "api_key": "never-keep"})
        result = await service.wait(started["id"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["result"], self.saved)
        self.assertEqual(result["source_revision"], "revision-one")
        self.assertEqual(result["request"], {"model": "model-a"})
        result["result"]["plan"]["body"] = "mutated"
        self.assertEqual(service.get(started["id"])["result"]["plan"]["body"], "Plan")
        self.assertIsNone(service.active())
        self.assertTrue(service.events(started["id"])["events"][-1]["done"])

    async def test_concurrent_manual_and_scheduler_requests_deduplicate(self):
        gate = asyncio.Event()
        calls = []

        async def generate(request):
            calls.append(request)
            await gate.wait()
            self.saved = saved_plan()
            yield {"done": True}

        service = self.service(generate)
        first, second = await asyncio.gather(service.start({"model": "manual"}),
                                            service.start({"replace_today": True}, trigger="startup"))
        self.assertEqual(first["id"], second["id"])
        self.assertTrue(second["reused"])
        gate.set()
        await service.wait(first["id"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["model"], "manual")

    async def test_cancelling_subscriber_or_waiter_does_not_cancel_worker(self):
        gate = asyncio.Event()

        async def generate(request):
            yield {"log": "running"}
            await gate.wait()
            self.saved = saved_plan()
            yield {"done": True}

        service = self.service(generate)
        job = await service.start()
        stream = service.iterate_events(job["id"])
        await anext(stream)
        await stream.aclose()
        waiter = asyncio.create_task(service.wait(job["id"]))
        await asyncio.sleep(0)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await waiter
        self.assertIn(service.get(job["id"])["status"], {"queued", "running"})
        gate.set()
        self.assertEqual((await service.wait(job["id"]))["status"], "succeeded")

    async def test_done_is_not_published_until_stream_ends_and_save_is_verified(self):
        gate = asyncio.Event()
        emitted_done = asyncio.Event()

        async def generate(request):
            yield {"done": True}
            emitted_done.set()
            await gate.wait()
            self.saved = saved_plan()

        service = self.service(generate)
        job = await service.start()
        await emitted_done.wait()
        self.assertFalse(any(event.get("done") for event in service.events(job["id"])["events"]))
        self.assertEqual(service.get(job["id"])["status"], "running")
        gate.set()
        self.assertEqual((await service.wait(job["id"]))["status"], "succeeded")

    async def test_missing_done_partial_save_and_stale_save_fail(self):
        cases = [(False, saved_plan(), "missing_done"),
                 (True, {"exists": False}, "incomplete_result"),
                 (True, {**saved_plan(), "plan": {"body": ""}}, "incomplete_result"),
                 (True, saved_plan("old"), "result_not_saved")]
        for done, save, error_code in cases:
            with self.subTest(error_code=error_code):
                self.saved = saved_plan("old")

                async def generate(request, save=save, done=done):
                    self.saved = save
                    yield {"done": True} if done else {"log": "ended"}

                service = self.service(generate)
                job = await service.start()
                result = await service.wait(job["id"])
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["error"]["code"], error_code)
                self.assertFalse(any(e.get("done") for e in service.events(job["id"])["events"]))

    async def test_stream_errors_even_after_done_cannot_succeed(self):
        for error in ({"error": "secret path"}, {"log": 'STREAM_PLAN_ERROR:"secret"'}):
            self.saved = {"exists": False}

            async def generate(request, error=error):
                self.saved = saved_plan()
                yield {"done": True}
                yield error

            service = self.service(generate)
            job = await service.start()
            result = await service.wait(job["id"])
            self.assertEqual(result["status"], "failed")
            self.assertNotIn("secret", result["error"]["message"])

    async def test_exception_details_do_not_leak_into_error_summary(self):
        async def generate(request):
            raise RuntimeError("api_key=private path=/user/private")
            yield

        service = self.service(generate)
        job = await service.start()
        result = await service.wait(job["id"])
        self.assertEqual(result["error"]["code"], "generation_failed")
        self.assertNotIn("private", json.dumps(result))

    async def test_cancel_awaits_generator_cleanup_and_holds_single_flight(self):
        running = asyncio.Event()
        cleaning = asyncio.Event()
        cleanup_gate = asyncio.Event()
        cleaned = []

        async def generate(request):
            try:
                running.set()
                await asyncio.Event().wait()
                yield {"done": True}
            finally:
                cleaning.set()
                await cleanup_gate.wait()
                cleaned.append(True)

        service = self.service(generate)
        job = await service.start()
        await running.wait()
        cancellation = asyncio.create_task(service.cancel(job["id"]))
        await cleaning.wait()
        duplicate = await service.start(trigger="source_changed")
        self.assertTrue(duplicate["reused"])
        self.assertEqual(duplicate["id"], job["id"])
        self.assertFalse(cancellation.done())
        cleanup_gate.set()
        cancelled = await cancellation
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertTrue(cleaned)
        self.assertIsNone(service.active())

    async def test_queued_cancel_and_shutdown_are_safe_and_idempotent(self):
        service = self.service(self.succeed)
        job = await service.start()
        result = await service.cancel(job["id"])
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual((await service.wait(job["id"]))["status"], "cancelled")
        await service.close()
        await service.close()
        with self.assertRaises(RuntimeError):
            await service.start()

    async def test_bounded_replay_reports_truncation_and_multiple_subscribers_finish(self):
        async def generate(request):
            for index in range(20):
                yield {"log": str(index)}
            self.saved = saved_plan()
            yield {"done": True}

        service = self.service(generate, event_limit=3, event_buffer_bytes=512)
        job = await service.start()
        await service.wait(job["id"])
        batch = service.events(job["id"])
        self.assertTrue(batch["truncated"])
        self.assertLessEqual(len(batch["events"]), 3)
        self.assertLessEqual(service._jobs[job["id"]].event_bytes, 512)
        for _ in range(2):
            replay = [event async for event in service.iterate_events(job["id"])]
            self.assertTrue(replay[0]["truncated"])
            self.assertTrue(replay[-1]["done"])
        cursor = batch["events"][0]["sequence"]
        self.assertFalse(service.events(job["id"], cursor)["truncated"])

    async def test_ndjson_accepts_split_unicode_chunks_and_unterminated_final_line(self):
        async def generate(request):
            stream = json.dumps({"log": "中文"}, ensure_ascii=False).encode() + b"\n"
            for byte in stream:
                yield bytes([byte])
            self.saved = saved_plan()
            yield '{"done": true}'

        service = self.service(generate)
        job = await service.start()
        self.assertEqual((await service.wait(job["id"]))["status"], "succeeded")
        self.assertIn("中文", [event.get("log") for event in service.events(job["id"])["events"]])

    async def test_invalid_and_oversized_ndjson_fail_without_unbounded_buffer(self):
        for chunk in ("[]\n", "bad json\n", "x" * 101):
            async def generate(request, chunk=chunk):
                yield chunk

            service = self.service(generate, max_stream_line_bytes=100)
            job = await service.start()
            self.assertEqual((await service.wait(job["id"]))["error"]["code"], "invalid_stream")

    async def test_completed_job_retention_is_bounded(self):
        counter = 0

        async def generate(request):
            nonlocal counter
            counter += 1
            self.saved = saved_plan(str(counter))
            yield {"done": True}

        service = self.service(generate, retained_jobs=2)
        for _ in range(5):
            job = await service.start()
            await service.wait(job["id"])
        self.assertEqual(len(service.list_jobs()), 2)

    async def test_source_unavailability_prevents_model_call(self):
        called = []

        async def generate(request):
            called.append(True)
            yield {"done": True}

        async def revision():
            raise FileNotFoundError("sensitive path")

        service = self.service(generate)
        service._read_revision = revision
        job = await service.start()
        self.assertEqual((await service.wait(job["id"]))["error"]["code"], "source_unavailable")
        self.assertEqual(called, [])

    def test_complete_plan_rejects_empty_and_error_payloads(self):
        self.assertFalse(complete_plan(None))
        self.assertFalse(complete_plan({**saved_plan(), "error": "failed"}))
        self.assertFalse(complete_plan({**saved_plan(), "analysis": "string"}))

    async def test_slow_subscriber_survives_other_reader_and_completed_job_eviction(self):
        gate = asyncio.Event()
        counter = 0

        async def generate(request):
            nonlocal counter
            await gate.wait()
            counter += 1
            self.saved = saved_plan(str(counter))
            yield {"done": True}

        service = self.service(generate, retained_jobs=1)
        first = await service.start()
        slow_reader = service.iterate_events(first["id"])
        self.assertEqual((await anext(slow_reader))["job_status"], "queued")
        gate.set()
        await service.wait(first["id"])
        other_events = [event async for event in service.iterate_events(first["id"])]
        self.assertTrue(other_events[-1]["done"])
        second = await service.start()
        await service.wait(second["id"])
        with self.assertRaises(KeyError):
            service.get(first["id"])

        async def read_rest():
            return [event async for event in slow_reader]

        remainder = await asyncio.wait_for(read_rest(), timeout=1)
        self.assertTrue(remainder[-1]["done"])

    async def test_completion_listener_keeps_single_flight_until_state_is_recorded(self):
        entered = asyncio.Event()
        gate = asyncio.Event()

        async def listener(job):
            entered.set()
            await gate.wait()

        service = self.service(self.succeed)
        service.add_completion_listener(listener)
        job = await service.start()
        await entered.wait()
        duplicate = await service.start(trigger="source_changed")
        self.assertEqual(duplicate["id"], job["id"])
        self.assertTrue(duplicate["reused"])
        gate.set()
        await service.wait(job["id"])
        self.assertIsNone(service.active())

    async def test_shutdown_cancels_running_worker_and_waits_for_cleanup(self):
        running = asyncio.Event()
        cleaned = []

        async def generate(request):
            try:
                running.set()
                await asyncio.Event().wait()
                yield {"done": True}
            finally:
                await asyncio.sleep(0)
                cleaned.append(True)

        service = self.service(generate)
        job = await service.start()
        await running.wait()
        await service.close()
        self.assertEqual(cleaned, [True])
        self.assertEqual(service.get(job["id"])["status"], "cancelled")

    def test_plan_dates_accept_both_wire_formats_and_reject_invalid_calendar_dates(self):
        for value, expected in (("20260930", "20260930"), ("2026-09-30", "20260930"),
                                ("2024-02-29", "20240229"), ("0001-01-01", "00010101")):
            with self.subTest(date=value):
                self.assertEqual(normalize_plan_date(value), expected)
                self.assertTrue(complete_plan({**saved_plan(), "date": value}))
        for value in (None, "", "2026-9-30", "20260931", "2026-02-29", "20261301",
                      "2026-09-30T12:00:00", " 2026-09-30", 20260930):
            with self.subTest(invalid_date=value):
                self.assertIsNone(normalize_plan_date(value))
                self.assertFalse(complete_plan({**saved_plan(), "date": value}))

    async def test_invalid_saved_date_cannot_mark_job_successful(self):
        async def generate(request):
            self.saved = {**saved_plan(), "date": "2026-02-30"}
            yield {"done": True}

        service = self.service(generate)
        job = await service.start()
        result = await service.wait(job["id"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"]["code"], "incomplete_result")

    async def test_iso_result_date_is_preserved_without_transport_rewriting(self):
        async def generate(request):
            self.saved = {**saved_plan(), "date": "2026-09-30"}
            yield {"done": True}

        service = self.service(generate)
        job = await service.start()
        result = await service.wait(job["id"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["result"]["date"], "2026-09-30")
