"""Tests for the timeline revision retention policies (retention.py)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from recipeserver import history, retention
from recipeserver.retention_policy import DEFAULT_RETENTION_POLICY, policy_provider
from test.helpers import read_metadata, request_json, running_recipe_server

NOW = datetime(2026, 11, 17, 12, 0, 0, tzinfo=timezone.utc)
RECIPE_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
RECIPE_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def test_policy_provider_reads_the_live_configuration_value():
    from types import SimpleNamespace

    config = SimpleNamespace(timeline_retention="unlimited")
    read = policy_provider(config)
    assert read() == "unlimited"
    config.timeline_retention = "gfs"
    assert read() == "gfs"
    assert policy_provider(SimpleNamespace())() == DEFAULT_RETENTION_POLICY


def make_manager(policy: object = "gfs") -> retention.RetentionManager:
    return retention.RetentionManager(policy_provider=lambda: policy)


def write_snapshot(recipe_id: str, created: datetime, content: str) -> str:
    directory = history.recipe_history_directory(recipe_id)
    directory.mkdir(parents=True, exist_ok=True)
    snapshot_id = history.make_snapshot_id(created)
    (directory / f"{snapshot_id}{history.SNAPSHOT_SUFFIX}").write_text(content, encoding="utf-8")
    return snapshot_id


def remaining_ids(recipe_id: str) -> list[str]:
    return [snapshot.id for snapshot in history.list_snapshots(recipe_id)]


def age(days: float = 0, hours: float = 0, microseconds: int = 0) -> timedelta:
    return timedelta(days=days, hours=hours, microseconds=microseconds)


# ----- policy selection -----------------------------------------------------


def test_default_policy_is_gfs():
    manager = retention.RetentionManager()

    assert manager.policy() == retention.RETENTION_POLICY_GFS


def test_unrecognized_policy_falls_back_to_gfs():
    assert retention.normalize_retention_policy("weekly") == retention.RETENTION_POLICY_GFS
    assert retention.normalize_retention_policy("") == retention.RETENTION_POLICY_GFS
    assert retention.normalize_retention_policy(None) == retention.RETENTION_POLICY_GFS
    assert retention.normalize_retention_policy("GFS") == retention.RETENTION_POLICY_GFS
    assert retention.normalize_retention_policy(" Unlimited ") == retention.RETENTION_POLICY_UNLIMITED


def test_unlimited_policy_retains_every_revision():
    manager = make_manager(retention.RETENTION_POLICY_UNLIMITED)
    created = [NOW - age(days=days) for days in (0.01, 2, 10, 60, 200, 400, 900)]
    for index, moment in enumerate(created):
        write_snapshot(RECIPE_A, moment, f"v{index}\n")

    outcome = manager.prune_recipe(RECIPE_A, now=NOW)

    assert outcome.skipped
    assert outcome.pruned == 0
    assert len(remaining_ids(RECIPE_A)) == len(created)


def test_switching_from_unlimited_to_gfs_prunes_only_in_a_safe_pass():
    holder = {"policy": retention.RETENTION_POLICY_UNLIMITED}
    manager = retention.RetentionManager(policy_provider=lambda: holder["policy"])

    kept_recent = write_snapshot(RECIPE_A, NOW - age(hours=3), "recent\n")
    old = write_snapshot(RECIPE_A, NOW - age(days=400), "old\n")
    older = write_snapshot(RECIPE_A, NOW - age(days=401), "older\n")

    # Merely switching the policy never deletes anything by itself.
    holder["policy"] = retention.RETENTION_POLICY_GFS
    assert (history.recipe_history_directory(RECIPE_A) / f"{old}{history.SNAPSHOT_SUFFIX}").is_file()
    assert (history.recipe_history_directory(RECIPE_A) / f"{older}{history.SNAPSHOT_SUFFIX}").is_file()

    # The next retention pass applies GFS safely: the recent revision stays,
    # and only the redundant older revision is pruned.
    outcome = manager.prune_recipe(RECIPE_A, now=NOW)

    remaining = remaining_ids(RECIPE_A)
    assert kept_recent in remaining
    assert outcome.scanned == 3
    assert outcome.pruned == 1
    assert older not in remaining


def test_switching_from_gfs_to_unlimited_stops_future_pruning():
    holder = {"policy": retention.RETENTION_POLICY_GFS}
    manager = retention.RetentionManager(policy_provider=lambda: holder["policy"])

    old_a = write_snapshot(RECIPE_A, NOW - age(days=400, hours=2), "old-a\n")
    old_b = write_snapshot(RECIPE_A, NOW - age(days=400, hours=1), "old-b\n")
    manager.prune_recipe(RECIPE_A, now=NOW)
    assert len(remaining_ids(RECIPE_A)) == 1

    holder["policy"] = retention.RETENTION_POLICY_UNLIMITED
    # A pass under Unlimited is a no-op, so redundant revisions stop disappearing.
    other = write_snapshot(RECIPE_A, NOW - age(days=401), "old-c\n")
    outcome = manager.prune_recipe(RECIPE_A, now=NOW)

    assert outcome.skipped
    assert set(remaining_ids(RECIPE_A)) == {old_b, other}


# ----- the GFS schedule -----------------------------------------------------


def test_gfs_keeps_every_revision_from_the_last_24_hours():
    manager = make_manager()
    moments = [NOW - age(hours=hours) for hours in (0.5, 5, 12, 23, 24)]
    for index, moment in enumerate(moments):
        write_snapshot(RECIPE_A, moment, f"v{index}\n")

    outcome = manager.prune_recipe(RECIPE_A, now=NOW)

    assert outcome.pruned == 0
    assert len(remaining_ids(RECIPE_A)) == len(moments)


def test_gfs_keeps_one_per_hour_between_24h_and_7_days():
    manager = make_manager()
    base = NOW - age(days=2)
    same_hour_early = write_snapshot(RECIPE_A, base.replace(minute=10), "early\n")
    same_hour_late = write_snapshot(RECIPE_A, base.replace(minute=50), "late\n")
    other_hour = write_snapshot(RECIPE_A, base.replace(hour=(base.hour + 3) % 24), "other hour\n")
    # Exactly 7 days old is still the hourly tier.
    boundary = write_snapshot(RECIPE_A, NOW - age(days=7), "seven days\n")

    manager.prune_recipe(RECIPE_A, now=NOW)

    remaining = remaining_ids(RECIPE_A)
    assert same_hour_late in remaining
    assert same_hour_early not in remaining
    assert other_hour in remaining
    assert boundary in remaining


def test_gfs_keeps_one_per_day_between_7_and_30_days():
    manager = make_manager()
    day = NOW - age(days=10)
    morning = write_snapshot(RECIPE_A, day.replace(hour=6, minute=0), "morning\n")
    evening = write_snapshot(RECIPE_A, day.replace(hour=18, minute=0), "evening\n")
    other_day = write_snapshot(RECIPE_A, NOW - age(days=12), "other day\n")
    # Exactly 30 days old is still the daily tier.
    boundary = write_snapshot(RECIPE_A, NOW - age(days=30), "thirty days\n")

    manager.prune_recipe(RECIPE_A, now=NOW)

    remaining = remaining_ids(RECIPE_A)
    assert evening in remaining
    assert morning not in remaining
    assert other_day in remaining
    assert boundary in remaining


def test_gfs_keeps_one_per_iso_week_between_30_and_365_days():
    manager = make_manager()
    monday = NOW - timedelta(days=NOW.weekday(), weeks=8)
    week_early = write_snapshot(RECIPE_A, monday + timedelta(hours=9), "week early\n")
    week_late = write_snapshot(RECIPE_A, monday + timedelta(hours=21), "week late\n")
    previous_week = write_snapshot(RECIPE_A, monday - timedelta(days=7), "previous week\n")
    # Exactly 365 days old is still the weekly tier.
    boundary = write_snapshot(RECIPE_A, NOW - age(days=365), "365 days\n")

    manager.prune_recipe(RECIPE_A, now=NOW)

    remaining = remaining_ids(RECIPE_A)
    assert week_late in remaining
    assert week_early not in remaining
    assert previous_week in remaining
    assert boundary in remaining


def test_gfs_keeps_one_per_calendar_month_beyond_12_months():
    manager = make_manager()
    month_early = write_snapshot(RECIPE_A, NOW - age(days=410), "month early\n")
    month_late = write_snapshot(RECIPE_A, NOW - age(days=400), "month late\n")
    other_month = write_snapshot(RECIPE_A, NOW - age(days=500), "other month\n")
    # One microsecond past 365 days is the monthly tier.
    past_boundary = write_snapshot(RECIPE_A, NOW - age(days=365, microseconds=1), "past boundary\n")

    manager.prune_recipe(RECIPE_A, now=NOW)

    remaining = remaining_ids(RECIPE_A)
    assert month_late in remaining
    assert month_early not in remaining
    assert other_month in remaining
    assert past_boundary in remaining


def test_gfs_prefers_the_newest_revision_within_an_interval():
    manager = make_manager()
    base = NOW - age(days=10)
    moments = [base.replace(hour=hour) for hour in (1, 7, 13, 19, 23)]
    ids = [write_snapshot(RECIPE_A, moment, f"v{moment.hour}\n") for moment in moments]

    manager.prune_recipe(RECIPE_A, now=NOW)

    remaining = remaining_ids(RECIPE_A)
    assert ids[-1] in remaining
    assert all(snapshot_id not in remaining for snapshot_id in ids[:-1])


def test_plan_retention_is_a_pure_decision():
    moments = (NOW - age(hours=1), NOW - age(days=10), NOW - age(days=10, hours=5), NOW - age(days=400))
    snapshots = [history.SnapshotInfo(id=history.make_snapshot_id(moment), created=moment, size=1) for moment in moments]

    pruned = retention.plan_retention(snapshots, NOW)

    # Same day as another revision: the earlier one loses.
    assert pruned == {snapshots[2].id}


def test_revision_exactly_24_hours_old_is_kept():
    manager = make_manager()
    boundary = write_snapshot(RECIPE_A, NOW - age(hours=24), "boundary\n")

    manager.prune_recipe(RECIPE_A, now=NOW)

    assert boundary in remaining_ids(RECIPE_A)


# ----- edge cases -----------------------------------------------------------


def test_the_only_revision_is_never_deleted():
    manager = make_manager()
    only = write_snapshot(RECIPE_A, NOW - age(days=900), "only\n")

    outcome = manager.prune_recipe(RECIPE_A, now=NOW)

    assert outcome.pruned == 0
    assert remaining_ids(RECIPE_A) == [only]


def test_the_newest_revision_is_always_kept():
    manager = make_manager()
    oldest = write_snapshot(RECIPE_A, (NOW - age(days=10)).replace(hour=8), "oldest\n")
    middle = write_snapshot(RECIPE_A, (NOW - age(days=10)).replace(hour=10), "middle\n")
    newest = write_snapshot(RECIPE_A, (NOW - age(days=10)).replace(hour=12), "newest\n")

    manager.prune_recipe(RECIPE_A, now=NOW)

    assert newest in remaining_ids(RECIPE_A)
    # Same-day interval: only the newest of the three survives.
    assert oldest not in remaining_ids(RECIPE_A)
    assert middle not in remaining_ids(RECIPE_A)


def test_empty_timeline_is_a_no_op():
    manager = make_manager()

    outcome = manager.prune_recipe(RECIPE_A, now=NOW)

    assert outcome.scanned == 0
    assert outcome.pruned == 0
    assert outcome.errors == 0
    assert not outcome.skipped


def test_invalid_recipe_id_is_rejected_without_raising():
    manager = make_manager()

    outcome = manager.prune_recipe("../escape", now=NOW)

    assert outcome.errors == 1
    assert outcome.pruned == 0


def test_multiple_timelines_are_pruned_independently():
    manager = make_manager()
    for recipe_id in (RECIPE_A, RECIPE_B):
        write_snapshot(recipe_id, NOW - age(days=400, hours=2), "old-a\n")
        write_snapshot(recipe_id, NOW - age(days=400, hours=1), "old-b\n")
        write_snapshot(recipe_id, NOW - age(hours=2), "fresh\n")

    outcomes = manager.prune_all(now=NOW)

    assert {outcome.recipe_id for outcome in outcomes} == {RECIPE_A, RECIPE_B}
    for recipe_id in (RECIPE_A, RECIPE_B):
        remaining = remaining_ids(recipe_id)
        assert len(remaining) == 2  # one per-month survivor + the fresh revision


def test_prune_all_skips_invalid_recipe_directories():
    recipes_root = history.history_directory() / history.RECIPES_DIR_NAME
    stray = recipes_root / "not-a-uuid"
    stray.mkdir(parents=True)
    (stray / "20200101T000000000000Z-deadbeef.md").write_text("stray\n", encoding="utf-8")
    write_snapshot(RECIPE_A, NOW - age(hours=1), "fresh\n")

    outcomes = make_manager().prune_all(now=NOW)

    assert [outcome.recipe_id for outcome in outcomes] == [RECIPE_A]
    assert (stray / "20200101T000000000000Z-deadbeef.md").is_file()


def test_unrelated_files_in_the_timeline_directory_are_left_alone():
    manager = make_manager()
    directory = history.recipe_history_directory(RECIPE_A)
    directory.mkdir(parents=True)
    stray = directory / "notes.txt"
    stray.write_text("keep me\n", encoding="utf-8")
    invalid = directory / "20200101T000000000000Z-nothex!!.md"
    invalid.write_text("keep me too\n", encoding="utf-8")
    write_snapshot(RECIPE_A, NOW - age(days=400), "old\n")

    manager.prune_recipe(RECIPE_A, now=NOW)

    assert stray.is_file()
    assert invalid.is_file()


def test_retained_revisions_are_not_modified():
    manager = make_manager()
    content = "exact content\nwith spacing preserved\n"
    kept = write_snapshot(RECIPE_A, NOW - age(hours=1), content)
    write_snapshot(RECIPE_A, NOW - age(days=10), "older-10d\n")
    write_snapshot(RECIPE_A, NOW - age(days=10, hours=3), "older-10d-3h\n")

    manager.prune_recipe(RECIPE_A, now=NOW)

    assert history.read_snapshot(RECIPE_A, kept) == content


def test_repeated_pruning_is_idempotent():
    manager = make_manager()
    for days in (1, 2, 2.5, 9, 9.5, 40, 200, 400):
        write_snapshot(RECIPE_A, NOW - age(days=days), f"v{days}\n")

    first = manager.prune_recipe(RECIPE_A, now=NOW)
    after_first = remaining_ids(RECIPE_A)
    second = manager.prune_recipe(RECIPE_A, now=NOW)
    after_second = remaining_ids(RECIPE_A)

    assert first.pruned > 0
    assert second.pruned == 0
    assert after_first == after_second


def test_interrupted_pruning_resumes_on_the_next_pass(monkeypatch):
    manager = make_manager()
    doomed = [write_snapshot(RECIPE_A, NOW - age(days=400, hours=offset), f"old-{offset}\n") for offset in (1, 2, 3, 4)]
    newest = write_snapshot(RECIPE_A, NOW - age(days=400, hours=0), "newest\n")

    real_unlink = Path.unlink
    blocked_name = f"{doomed[0]}{history.SNAPSHOT_SUFFIX}"

    def flaky_unlink(path, *args, **kwargs):
        if path.name == blocked_name:
            raise OSError("simulated crash mid-prune")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    interrupted = manager.prune_recipe(RECIPE_A, now=NOW)

    assert interrupted.errors == 1
    assert interrupted.pruned == len(doomed) - 1

    monkeypatch.setattr(Path, "unlink", real_unlink)
    resumed = manager.prune_recipe(RECIPE_A, now=NOW)

    assert resumed.errors == 0
    assert resumed.pruned == 1
    assert remaining_ids(RECIPE_A) == [newest]


def test_missing_revision_file_is_tolerated(monkeypatch):
    manager = make_manager()
    doomed = write_snapshot(RECIPE_A, NOW - age(days=400), "old\n")
    write_snapshot(RECIPE_A, NOW - age(days=399), "kept\n")  # same month bucket; the representative
    write_snapshot(RECIPE_A, NOW - age(hours=1), "fresh\n")

    real_unlink = Path.unlink

    def missing_unlink(path, *args, **kwargs):
        if path.name == f"{doomed}{history.SNAPSHOT_SUFFIX}":
            raise FileNotFoundError("already gone")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", missing_unlink)
    outcome = manager.prune_recipe(RECIPE_A, now=NOW)

    assert outcome.missing == 1
    assert outcome.errors == 0


def test_filesystem_errors_are_reported_and_do_not_abort_the_pass(monkeypatch):
    manager = make_manager()
    doomed = [write_snapshot(RECIPE_A, NOW - age(days=400, hours=offset), f"old-{offset}\n") for offset in (1, 2, 3, 4)]
    newest = write_snapshot(RECIPE_A, NOW - age(days=400), "newest\n")
    fresh = write_snapshot(RECIPE_A, NOW - age(hours=1), "fresh\n")

    real_unlink = Path.unlink

    def failing_unlink(path, *args, **kwargs):
        if path.name == f"{doomed[0]}{history.SNAPSHOT_SUFFIX}":
            raise OSError("disk is read-only")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failing_unlink)
    outcome = manager.prune_recipe(RECIPE_A, now=NOW)

    assert outcome.errors == 1
    assert outcome.pruned == 3  # the other redundant revisions were still removed
    assert fresh in remaining_ids(RECIPE_A)
    assert newest in remaining_ids(RECIPE_A)
    assert doomed[0] in remaining_ids(RECIPE_A)  # left for the next pass


# ----- existing history stays usable -----------------------------------------


def test_existing_history_and_restore_stay_intact_after_pruning(tmp_path: Path):
    source = tmp_path / "recipes"
    source.mkdir()
    recipe_id = RECIPE_A
    recipe = source / "recipe.md"
    original = f"---\nrecipe_id: {recipe_id}\nmeals:\n  - Dinner\n---\n# Soup\n\noriginal\n"
    recipe.write_text(original, encoding="utf-8")

    keep = write_snapshot(recipe_id, NOW - age(hours=2), "kept version\n")
    write_snapshot(recipe_id, NOW - age(days=400, hours=1), "old a\n")
    write_snapshot(recipe_id, NOW - age(days=400, hours=2), "old b\n")

    manager = make_manager()
    manager.prune_recipe(recipe_id, now=NOW)
    assert keep in remaining_ids(recipe_id)

    with running_recipe_server(source) as (base_url, _, _):
        status, body = request_json(f"{base_url}/api/history/restore", {"path": "recipe.md", "snapshot": keep})

    assert status == 200
    assert body["success"] is True
    assert recipe.read_text(encoding="utf-8").startswith("---")
    assert "kept version" in recipe.read_text(encoding="utf-8")
    assert read_metadata(recipe)["recipe_id"] == recipe_id


def test_prune_respects_the_snapshot_timestamp_not_the_file_mtime():
    # Both snapshot files have a brand-new mtime (created by the test);
    # the decision must follow the embedded timestamps, not the mtimes.
    manager = make_manager()
    older = write_snapshot(RECIPE_A, NOW - age(days=400, hours=2), "older\n")
    newer = write_snapshot(RECIPE_A, NOW - age(days=400, hours=1), "newer\n")
    directory = history.recipe_history_directory(RECIPE_A)
    os.utime(directory / f"{older}{history.SNAPSHOT_SUFFIX}", (NOW.timestamp(), NOW.timestamp()))

    outcome = manager.prune_recipe(RECIPE_A, now=NOW)

    assert outcome.scanned == 2
    assert outcome.pruned == 1
    assert older not in remaining_ids(RECIPE_A)
    assert newer in remaining_ids(RECIPE_A)
