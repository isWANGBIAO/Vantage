import asyncio
import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from src.services.action_plan_jobs import ActionPlanJobService
from src.services.action_plan_scheduler import ActionPlanScheduler, _revision_digest


class ActionPlanSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "scheduler.json"
        self.date = "20260930"
        self.clock = 100.0
        self.settings = {"onboarding_completed": True, "action_plan_auto_generate": True,
                         "action_plan_check_interval_minutes": 60, "api_key": "secret"}
        self.saved = {"exists": False, "date": self.date}
        self.revision = "r1"
        self.revision_calls = 0
        self.calls = []
        self.fail = False
        self.use_real_payload = False
        self.block = None
        self.schedulers = []
        self.jobs = ActionPlanJobService(self.generate, self.read_today, self.read_revision)
        self.scheduler = self.make_scheduler()

    async def asyncTearDown(self):
        await self.jobs.close()
        for scheduler in self.schedulers:
            await scheduler.close()
        self.directory.cleanup()

    def make_scheduler(self):
        scheduler = ActionPlanScheduler(self.jobs, lambda: self.settings, self.read_today,
                                        self.read_revision, self.path, today=lambda: self.date,
                                        monotonic=lambda: self.clock, poll_seconds=0.01)
        self.schedulers.append(scheduler)
        return scheduler

    async def read_today(self):
        return copy.deepcopy(self.saved)

    async def read_revision(self):
        self.revision_calls += 1
        if self.revision is None:
            raise FileNotFoundError("private source")
        return self.revision

    async def generate(self, request):
        self.calls.append(request)
        if self.block is not None:
            await self.block.wait()
        if self.fail:
            yield {"error": "failed"}
            return
        self.saved = {"exists": True, "id": str(len(self.calls)), "date": self.date,
                      "analysis": {"body": "Private analysis"}, "plan": {"body": "Private plan"},
                      "meta": {"api_key": "do-not-persist"}}
        if self.use_real_payload:
            self.saved = self.real_saved_plan(sequence=len(self.calls))
        yield {"done": True}

    def real_saved_plan(self, *, date=None, sequence=0):
        from src.scripts.run_prompt import build_action_plan_payload

        generated_at = datetime.strptime(date or self.date, "%Y%m%d").replace(hour=12, second=sequence)
        return {"exists": True, **build_action_plan_payload(
            generated_at=generated_at, analysis_body="Real analysis", plan_body="Real plan",
            stats={}, metadata={},
        )}

    async def run_tick(self, **kwargs):
        outcome = await self.scheduler.tick(**kwargs)
        if outcome.get("outcome") == "started":
            outcome["job"] = await self.jobs.wait(outcome["job_id"])
        return outcome

    def existing_plan(self):
        self.saved = {"exists": True, "id": "old", "date": self.date,
                      "analysis": {"body": "old"}, "plan": {"body": "old"}}

    async def test_startup_is_independent_of_zero_revision_interval(self):
        self.settings["action_plan_check_interval_minutes"] = 0
        result = await self.run_tick()
        self.assertEqual(result["trigger"], "startup")
        self.assertEqual(result["job"]["status"], "succeeded")
        self.assertTrue(self.calls[0]["replace_today"])
        self.assertTrue(self.calls[0]["wait_for_provider_ready"])
        calls = self.revision_calls
        self.revision = "r2"
        self.clock += 86400
        self.assertEqual((await self.run_tick(force_check=True))["outcome"], "idle")
        self.assertEqual(self.revision_calls, calls)

    async def test_onboarding_blocks_startup_and_revision_model_work(self):
        self.settings["onboarding_completed"] = False
        self.assertEqual((await self.run_tick())["outcome"], "awaiting_onboarding")
        self.assertEqual(self.revision_calls, 0)
        self.assertEqual(self.calls, [])
        self.settings["onboarding_completed"] = True
        self.assertEqual((await self.run_tick())["job"]["status"], "succeeded")

    async def test_startup_disabled_still_checks_revisions(self):
        self.settings["action_plan_auto_generate"] = False
        first = await self.run_tick()
        self.assertEqual(first["outcome"], "baseline_recorded")
        self.assertEqual(self.calls, [])
        self.revision = "r2"
        result = await self.run_tick(force_check=True)
        self.assertEqual(result["trigger"], "source_changed")
        self.assertEqual(result["job"]["status"], "succeeded")
        self.assertTrue(self.calls[0]["replace_today"])
        self.assertFalse(self.calls[0]["wait_for_provider_ready"])

    async def test_existing_plan_establishes_baseline_without_starting_model(self):
        self.existing_plan()
        self.assertEqual((await self.run_tick())["outcome"], "baseline_recorded")
        self.assertEqual((await self.run_tick(force_check=True))["outcome"], "unchanged")
        self.assertEqual(self.calls, [])

    async def test_failed_generation_never_advances_baseline_and_retries(self):
        self.existing_plan()
        await self.run_tick()
        old_metadata = self.path.read_text()
        self.revision = "r2"
        self.fail = True
        outcome = await self.run_tick(force_check=True)
        self.assertEqual(outcome["job"]["status"], "failed")
        self.assertEqual(self.path.read_text(), old_metadata)
        self.fail = False
        retry = await self.run_tick(force_check=True)
        self.assertEqual(retry["job"]["status"], "succeeded")
        self.assertEqual(self.scheduler.status()["baseline_revision"], _revision_digest("r2"))

    async def test_failed_startup_retries_on_interval_without_false_baseline(self):
        self.fail = True
        outcome = await self.run_tick()
        self.assertEqual(outcome["job"]["status"], "failed")
        self.assertFalse(self.path.exists())
        self.fail = False
        self.clock += 3600
        retry = await self.run_tick()
        self.assertEqual(retry["job"]["status"], "succeeded")

    async def test_restart_uses_persisted_generated_revision(self):
        await self.run_tick()
        await self.scheduler.close()
        self.scheduler = self.make_scheduler()
        self.assertEqual((await self.run_tick())["outcome"], "unchanged")
        self.assertEqual(len(self.calls), 1)
        await self.scheduler.close()
        self.revision = "r2"
        self.scheduler = self.make_scheduler()
        outcome = await self.run_tick()
        self.assertEqual(outcome["trigger"], "source_changed")
        self.assertEqual(len(self.calls), 2)

    async def test_manual_completion_updates_same_baseline_and_prevents_duplicate(self):
        self.existing_plan()
        await self.run_tick()
        self.revision = "r2"
        manual = await self.jobs.start({"model": "chosen"})
        await self.jobs.wait(manual["id"])
        self.assertEqual((await self.run_tick(force_check=True))["outcome"], "unchanged")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]["model"], "chosen")

    async def test_inflight_manual_job_is_not_replaced_by_scheduler(self):
        self.block = asyncio.Event()
        manual = await self.jobs.start({"model": "manual"})
        outcome = await self.run_tick()
        self.assertEqual(outcome["outcome"], "busy")
        self.assertEqual(outcome["job_id"], manual["id"])
        self.block.set()
        await self.jobs.wait(manual["id"])
        await self.run_tick(force_check=True)
        self.assertEqual(len(self.calls), 1)

    async def test_revision_changed_during_generation_remains_pending(self):
        self.block = asyncio.Event()
        outcome = await self.scheduler.tick()
        while not self.calls:
            await asyncio.sleep(0)
        self.revision = "r2"
        self.block.set()
        await self.jobs.wait(outcome["job_id"])
        self.assertEqual(self.scheduler.status()["baseline_revision"], _revision_digest("r1"))
        again = await self.run_tick(force_check=True)
        self.assertEqual(again["trigger"], "source_changed")
        self.assertEqual(len(self.calls), 2)

    async def test_date_rollover_resets_baseline_and_generates_missing_day(self):
        await self.run_tick()
        self.date = "20261001"
        self.saved = {"exists": False, "date": self.date}
        outcome = await self.run_tick()
        self.assertEqual(outcome["trigger"], "startup")
        self.assertEqual(outcome["job"]["result"]["date"], self.date)
        self.assertEqual(json.loads(self.path.read_text())["date"], self.date)

    async def test_dynamic_settings_disable_and_reenable_checks(self):
        self.existing_plan()
        await self.run_tick()
        self.revision = "r2"
        self.settings["action_plan_check_interval_minutes"] = 0
        self.clock += 3600
        self.assertEqual((await self.run_tick(force_check=True))["outcome"], "idle")
        self.settings["action_plan_check_interval_minutes"] = 1
        self.assertEqual((await self.run_tick())["outcome"], "idle")
        self.clock += 60
        self.assertEqual((await self.run_tick())["trigger"], "source_changed")

    async def test_missing_sources_do_not_call_model_or_advance_metadata(self):
        self.revision = None
        self.assertEqual((await self.run_tick())["outcome"], "source_unavailable")
        self.assertEqual(self.calls, [])
        self.assertFalse(self.path.exists())
        self.revision = "r1"
        self.clock += 5
        self.assertEqual((await self.run_tick())["job"]["status"], "succeeded")

    async def test_unreadable_saved_plan_is_not_overwritten(self):
        self.saved = {"exists": False, "error": "private path"}
        self.assertEqual((await self.run_tick())["outcome"], "plan_unavailable")
        self.assertEqual(self.calls, [])
        self.assertNotIn("private", json.dumps(self.scheduler.status()))

    async def test_metadata_contains_only_schema_date_and_digests(self):
        await self.run_tick()
        metadata = json.loads(self.path.read_text())
        self.assertEqual(set(metadata), {"version", "date", "baseline_revision",
                                        "generated_revision", "generated_plan_identity"})
        for key in ("baseline_revision", "generated_revision", "generated_plan_identity"):
            self.assertRegex(metadata[key], r"^[0-9a-f]{64}$")
        self.assertNotIn("Private", self.path.read_text())
        self.assertNotIn("secret", self.path.read_text())
        self.assertNotIn("do-not-persist", self.path.read_text())
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    async def test_corrupt_oversized_and_untrusted_metadata_are_safely_ignored(self):
        self.existing_plan()
        for content in ("broken json", "x" * 5000,
                        json.dumps({"version": 1, "date": self.date, "baseline_revision": "private"})):
            self.path.write_text(content)
            await self.scheduler.close()
            self.scheduler = self.make_scheduler()
            self.assertEqual((await self.run_tick())["outcome"], "baseline_recorded")
        self.assertEqual(self.calls, [])

    async def test_atomic_metadata_failure_preserves_old_file(self):
        self.existing_plan()
        await self.run_tick()
        previous = self.path.read_text()
        with patch("src.services.action_plan_scheduler.os.replace", side_effect=OSError("private path")):
            self.revision = "r2"
            result = await self.run_tick(force_check=True)
            self.assertEqual(result["job"]["status"], "succeeded")
        self.assertEqual(self.path.read_text(), previous)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])
        self.assertEqual(self.scheduler.status()["error"]["code"], "metadata_write_failed")

    async def test_lifespan_start_is_singleton_and_close_leaves_no_polling(self):
        self.settings["onboarding_completed"] = False
        first = self.scheduler.start()
        self.assertIs(first, self.scheduler.start())
        await asyncio.sleep(0.02)
        await self.scheduler.close()
        self.assertTrue(first.done())
        self.assertFalse(self.scheduler.status()["running"])
        self.assertEqual((await self.scheduler.tick())["outcome"], "closed")
        with self.assertRaises(RuntimeError):
            self.scheduler.start()

    async def test_metadata_write_retry_does_not_regenerate_already_saved_result(self):
        self.existing_plan()
        await self.run_tick()
        self.revision = "r2"
        with patch("src.services.action_plan_scheduler.os.replace", side_effect=OSError("disk")):
            result = await self.run_tick(force_check=True)
            self.assertEqual(result["job"]["status"], "succeeded")
            blocked = await self.run_tick(force_check=True)
            self.assertEqual(blocked["outcome"], "metadata_unavailable")
        recovered = await self.run_tick(force_check=True)
        self.assertEqual(recovered["outcome"], "unchanged")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(json.loads(self.path.read_text())["generated_revision"], _revision_digest("r2"))

    async def test_scheduler_close_does_not_wait_for_running_generation(self):
        self.block = asyncio.Event()
        self.scheduler.start()
        while not self.calls:
            await asyncio.sleep(0)
        await asyncio.wait_for(self.scheduler.close(), timeout=1)
        self.assertEqual(self.jobs.active()["status"], "running")
        await self.jobs.close()
        self.assertIsNone(self.jobs.active())

    async def test_startup_setting_can_be_enabled_without_revision_checks(self):
        self.settings["action_plan_auto_generate"] = False
        self.settings["action_plan_check_interval_minutes"] = 0
        self.assertEqual((await self.run_tick())["outcome"], "idle")
        self.assertEqual(self.revision_calls, 0)
        self.settings["action_plan_auto_generate"] = True
        self.assertEqual((await self.run_tick())["trigger"], "startup")

    async def test_real_iso_dated_existing_plan_prevents_startup_generation(self):
        self.saved = self.real_saved_plan()
        self.assertEqual(self.saved["date"], "2026-09-30")
        self.settings["action_plan_check_interval_minutes"] = 0
        result = await self.run_tick()
        self.assertEqual(result["outcome"], "plan_exists")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.revision_calls, 0)

    async def test_real_iso_dated_manual_success_advances_baseline(self):
        self.saved = self.real_saved_plan()
        await self.run_tick()
        self.use_real_payload = True
        self.revision = "r2"
        manual = await self.jobs.start()
        result = await self.jobs.wait(manual["id"])
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["result"]["date"], "2026-09-30")
        self.assertEqual(self.scheduler.status()["generated_revision"], _revision_digest("r2"))
        self.assertEqual((await self.run_tick(force_check=True))["outcome"], "unchanged")
        self.assertEqual(len(self.calls), 1)

    async def test_real_iso_dated_success_rolls_over_to_new_day_without_rewriting_date(self):
        self.use_real_payload = True
        first = await self.run_tick()
        self.assertEqual(first["job"]["status"], "succeeded")
        self.assertEqual(json.loads(self.path.read_text())["generated_revision"], _revision_digest("r1"))
        self.date = "20261001"
        # Even if an adapter returns yesterday's actual payload, it cannot count
        # as an existing plan for the new day.
        outcome = await self.run_tick()
        self.assertEqual(outcome["trigger"], "startup")
        self.assertEqual(outcome["job"]["result"]["date"], "2026-10-01")
        self.assertEqual(json.loads(self.path.read_text())["date"], "20261001")

    async def test_yesterdays_iso_result_cannot_certify_new_day_revision(self):
        self.date = "20261001"
        await self.scheduler._on_completed({
            "status": "succeeded", "source_revision": "r1",
            "result": self.real_saved_plan(date="20260930"),
        })
        self.assertIsNone(self.scheduler.status()["generated_revision"])
        self.assertFalse(self.path.exists())

    async def test_invalid_or_missing_existing_date_is_fail_safe(self):
        for value in ("2026-09-31", "2026-9-30", "20260230", None):
            with self.subTest(date=value):
                self.saved = {**self.real_saved_plan(), "date": value}
                self.clock += 10
                result = await self.run_tick(force_check=True)
                self.assertEqual(result["outcome"], "plan_unavailable")
                self.assertEqual(self.scheduler.status()["error"]["code"], "invalid_plan_date")
        self.assertEqual(self.calls, [])
        self.assertFalse(self.path.exists())

    async def test_injected_iso_today_is_normalized_only_for_scheduler_metadata(self):
        await self.scheduler.close()
        self.scheduler = ActionPlanScheduler(
            self.jobs, lambda: self.settings, self.read_today, self.read_revision, self.path,
            today=lambda: "2026-09-30", monotonic=lambda: self.clock,
        )
        self.schedulers.append(self.scheduler)
        self.use_real_payload = True
        result = await self.run_tick()
        self.assertEqual(result["job"]["result"]["date"], "2026-09-30")
        self.assertEqual(json.loads(self.path.read_text())["date"], "20260930")
