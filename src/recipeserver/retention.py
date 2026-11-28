"""Configurable retention policies for recipe revision history.

The recipe history (see ``history.py``) stores one immutable snapshot per
replaced version. Left alone, that directory grows without bound, so this
module prunes snapshots according to a server-level retention policy:

- ``gfs`` (Grandfather-Father-Son, the default) keeps every revision from
  the last 24 hours, one revision per hour for the last 7 days, one per day
  for the last 30 days, one per week for the last 12 months, and one per
  calendar month beyond that.
- ``unlimited`` keeps everything, preserving the historical behavior.

The tiered schedule lives in ``GFS_SCHEDULE`` and is the single place to
adjust the policy; nothing else hard-codes the intervals.

Retention runs in the background (``RetentionManager``): a periodic scan, a
pass at startup, a pass after each save (throttled per recipe), and a pass
after the configuration is saved. The HTTP handlers never prune inline, and
every pass is idempotent — deleting one file at a time, tolerating missing
files and filesystem errors, so an interrupted pass simply resumes on the
next run. Retention never modifies retained snapshots, never deletes the
newest revision of a timeline, and never empties a non-empty timeline.

A snapshot's authoritative creation time is the UTC timestamp embedded in
its identifier (``parse_snapshot_id``), not the file's mtime. Within a
retention interval the newest revision is kept as the most representative
of the interval.

Tests override the history root with ``RECIPE_SERVER_HISTORY_DIR`` (see
``history.py``) and can inject the current time through the ``now``
parameters instead of relying on real elapsed time.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event, Lock, Thread
from typing import Callable, Iterable

from ._logger import logger
from .history import (
    HistoryError,
    RECIPES_DIR_NAME,
    SNAPSHOT_SUFFIX,
    SnapshotInfo,
    history_directory,
    list_snapshots,
    recipe_history_directory,
)
from .recipe_utils import is_valid_recipe_id
from .retention_policy import (
    DEFAULT_RETENTION_POLICY,
    RETENTION_POLICY_GFS,
    RETENTION_POLICIES,
    RETENTION_POLICY_LABELS,
    RETENTION_POLICY_UNLIMITED,
    normalize_retention_policy,
    policy_provider,
)

# ----- The GFS schedule ----------------------------------------------------
# The single place to adjust the tiered Grandfather-Father-Son schedule.
# Tiers are evaluated in order; the first tier whose ``max_age`` covers the
# revision's age wins. A ``bucket`` of ``None`` keeps every revision;
# otherwise one revision per bucket is kept (the newest in the bucket, which
# best represents the end of the interval).
TWELVE_MONTHS = timedelta(days=365)


@dataclass(frozen=True)
class RetentionTier:
    """One tier of the GFS schedule.

    ``max_age`` is the inclusive upper bound of the tier (``None`` means
    "anything older"). ``bucket`` selects the interval a revision competes
    for: ``None`` keeps all revisions in the tier, otherwise one of
    ``"hour"``, ``"day"``, ``"week"`` (ISO week), or ``"month"``.
    """

    name: str
    max_age: timedelta | None
    bucket: str | None


GFS_SCHEDULE: tuple[RetentionTier, ...] = (
    RetentionTier("last 24 hours", timedelta(hours=24), None),
    RetentionTier("last 7 days", timedelta(days=7), "hour"),
    RetentionTier("last 30 days", timedelta(days=30), "day"),
    RetentionTier("last 12 months", TWELVE_MONTHS, "week"),
    RetentionTier("older than 12 months", None, "month"),
)

# Background execution: how often the periodic thread sweeps, the minimum
# interval between unforced full scans, and the minimum interval between
# per-recipe prunes scheduled by saves.
PERIODIC_SCAN_INTERVAL_SECONDS = 60 * 60
FULL_SCAN_MIN_INTERVAL_SECONDS = 60 * 60
RECIPE_PRUNE_MIN_INTERVAL_SECONDS = 60 * 5


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _bucket_key(created: datetime, bucket: str) -> str:
    if bucket == "hour":
        return created.strftime("%Y%m%dT%H")
    if bucket == "day":
        return created.strftime("%Y%m%d")
    if bucket == "week":
        iso = created.isocalendar()
        return f"{iso.year:04d}-W{iso.week:02d}"
    if bucket == "month":
        return created.strftime("%Y%m")
    raise ValueError(f"Unknown retention bucket: {bucket!r}")


def _tier_for_age(age: timedelta) -> RetentionTier:
    for tier in GFS_SCHEDULE:
        if tier.max_age is None or age <= tier.max_age:
            return tier
    # Unreachable: the last tier has max_age=None.
    raise AssertionError("GFS_SCHEDULE has no unbounded tier")  # pragma: no cover


def plan_retention(snapshots: Iterable[SnapshotInfo], now: datetime | None = None) -> set[str]:
    """Return the ids of the snapshots that GFS would prune.

    The newest revision is always kept, and every tier keeps its newest
    revision (the most representative of the interval), so a non-empty
    timeline never loses its last revision. Revisions in the future (clock
    skew) fall into the keep-everything tier.
    """
    now = _as_utc(now) if now is not None else datetime.now(timezone.utc)
    ordered = sorted((snapshot for snapshot in snapshots), key=lambda snap: (_as_utc(snap.created), snap.id))
    if not ordered:
        return set()

    keep: set[str] = {ordered[-1].id}
    buckets: dict[tuple[str, str], list[SnapshotInfo]] = {}
    for snapshot in ordered:
        created = _as_utc(snapshot.created)
        tier = _tier_for_age(now - created)
        if tier.bucket is None:
            keep.add(snapshot.id)
            continue
        buckets.setdefault((tier.name, _bucket_key(created, tier.bucket)), []).append(snapshot)

    for members in buckets.values():
        keep.add(max(members, key=lambda snap: (_as_utc(snap.created), snap.id)).id)

    return {snapshot.id for snapshot in ordered} - keep


@dataclass
class RetentionOutcome:
    """Summary of one retention pass (or of why none ran)."""

    recipe_id: str
    policy: str
    skipped: bool = False
    scanned: int = 0
    kept: int = 0
    pruned: int = 0
    missing: int = 0
    errors: int = 0


class RetentionManager:
    """Runs timeline retention in the background, outside HTTP requests.

    A single shared instance lives behind ``get_retention_manager()``; tests
    construct their own instances with an injected ``policy_provider``.
    """

    def __init__(self, policy_provider: Callable[[], object] | None = None) -> None:
        self._policy_provider = policy_provider or (lambda: DEFAULT_RETENTION_POLICY)
        self._state_lock = Lock()
        self._recipe_locks: dict[str, Lock] = {}
        self._full_scan_lock = Lock()
        self._last_full_scan_at = 0.0
        self._last_recipe_prune_at: dict[str, float] = {}
        self._stop_event = Event()
        self._periodic_thread: Thread | None = None

    # ----- policy -----------------------------------------------------------

    def configure(self, config) -> None:
        """Read the retention policy from a Configuration-like object."""
        self._policy_provider = policy_provider(config)

    def policy(self) -> str:
        try:
            value = self._policy_provider()
        except Exception:
            logger.exception("Unable to read the timeline retention policy; using the default")
            return DEFAULT_RETENTION_POLICY
        return normalize_retention_policy(value)

    # ----- locking ----------------------------------------------------------

    def recipe_lock(self, recipe_id: str) -> Lock:
        """Return the per-recipe lock shared by pruning and the restore path."""
        with self._state_lock:
            return self._recipe_locks.setdefault(recipe_id, Lock())

    # ----- synchronous passes (used by background threads and tests) --------

    def prune_recipe(self, recipe_id: str, *, now: datetime | None = None) -> RetentionOutcome:
        """Prune one timeline. Never raises for filesystem problems."""
        policy = self.policy()
        outcome = RetentionOutcome(recipe_id=recipe_id, policy=policy)
        if policy != RETENTION_POLICY_GFS:
            outcome.skipped = True
            return outcome
        if not is_valid_recipe_id(recipe_id):
            logger.warning(f"Refusing to prune history for invalid recipe_id {recipe_id!r}")
            outcome.errors += 1
            return outcome

        lock = self.recipe_lock(recipe_id)
        if not lock.acquire(blocking=False):
            # A pass (or a restore holding the same lock) is already running.
            outcome.skipped = True
            return outcome
        try:
            try:
                snapshots = list_snapshots(recipe_id)
            except Exception:
                logger.exception(f"Unable to list snapshots for recipe {recipe_id}")
                outcome.errors += 1
                return outcome

            outcome.scanned = len(snapshots)
            prune_ids = plan_retention(snapshots, now)
            outcome.kept = outcome.scanned - len(prune_ids)

            try:
                directory = recipe_history_directory(recipe_id)
            except HistoryError:
                logger.exception(f"Unable to resolve the history directory for recipe {recipe_id}")
                outcome.errors += 1
                return outcome

            for snapshot in snapshots:
                if snapshot.id not in prune_ids:
                    continue
                path = directory / f"{snapshot.id}{SNAPSHOT_SUFFIX}"
                try:
                    path.unlink()
                    outcome.pruned += 1
                except FileNotFoundError:
                    # Missing or already deleted: fine, the end state is the same.
                    outcome.missing += 1
                except OSError:
                    logger.exception(f"Unable to prune snapshot {path}")
                    outcome.errors += 1

            if outcome.pruned or outcome.errors:
                logger.info(
                    f"Retention pruned {outcome.pruned} snapshot(s) for recipe {recipe_id}"
                    f" (kept {outcome.kept}, missing {outcome.missing}, errors {outcome.errors})"
                )
            return outcome
        finally:
            lock.release()

    def prune_all(self, *, now: datetime | None = None) -> list[RetentionOutcome]:
        """Prune every timeline managed by this server."""
        started = time.monotonic()
        outcomes: list[RetentionOutcome] = []
        for recipe_id in self._list_recipe_ids():
            outcomes.append(self.prune_recipe(recipe_id, now=now))

        pruned = sum(outcome.pruned for outcome in outcomes)
        errors = sum(outcome.errors for outcome in outcomes)
        scanned = sum(outcome.scanned for outcome in outcomes)
        if outcomes:
            logger.info(
                f"Timeline retention pass complete: {len(outcomes)} timeline(s),"
                f" {scanned} snapshot(s) scanned, {pruned} pruned, {errors} error(s)"
            )
        with self._state_lock:
            self._last_full_scan_at = time.monotonic()
        logger.debug(f"Timeline retention pass took {time.monotonic() - started:.1f}s")
        return outcomes

    def _list_recipe_ids(self) -> list[str]:
        recipes = history_directory() / RECIPES_DIR_NAME
        try:
            entries = list(recipes.iterdir())
        except OSError:
            # No history yet (or unreadable root): nothing to do.
            return []
        return sorted(entry.name for entry in entries if entry.is_dir() and is_valid_recipe_id(entry.name))

    # ----- background scheduling --------------------------------------------

    def schedule_recipe_prune(self, recipe_id: str) -> None:
        """Schedule a throttled background prune for one timeline."""
        if self.policy() != RETENTION_POLICY_GFS:
            return
        monotonic = time.monotonic()
        with self._state_lock:
            last = self._last_recipe_prune_at.get(recipe_id, 0.0)
            if monotonic - last < RECIPE_PRUNE_MIN_INTERVAL_SECONDS:
                return
            self._last_recipe_prune_at[recipe_id] = monotonic

        thread = Thread(target=self._prune_recipe_guarded, args=(recipe_id,), name="RecipeServer-Retention-Recipe", daemon=True)
        thread.start()

    def _prune_recipe_guarded(self, recipe_id: str) -> None:
        try:
            self.prune_recipe(recipe_id)
        except Exception:
            logger.exception(f"Timeline retention failed for recipe {recipe_id}")

    def request_full_scan(self, *, force: bool = False) -> None:
        """Schedule a background full-history scan, throttled by default."""
        if self.policy() != RETENTION_POLICY_GFS:
            return
        if not force:
            with self._state_lock:
                if time.monotonic() - self._last_full_scan_at < FULL_SCAN_MIN_INTERVAL_SECONDS:
                    return
        if not self._full_scan_lock.acquire(blocking=False):
            return

        thread = Thread(target=self._full_scan_guarded, name="RecipeServer-Retention", daemon=True)
        thread.start()

    def _full_scan_guarded(self) -> None:
        try:
            self.prune_all()
        except Exception:
            logger.exception("Timeline retention pass failed")
        finally:
            self._full_scan_lock.release()

    def start(self) -> None:
        """Start the periodic retention thread and request a startup scan."""
        if self._periodic_thread is not None and self._periodic_thread.is_alive():
            return
        self._stop_event.clear()
        self._periodic_thread = Thread(target=self._periodic_scan, name="RecipeServer-Retention-Periodic", daemon=True)
        self._periodic_thread.start()
        self.request_full_scan(force=True)

    def _periodic_scan(self) -> None:
        while not self._stop_event.wait(PERIODIC_SCAN_INTERVAL_SECONDS):
            self.request_full_scan()

    def stop(self) -> None:
        """Stop the periodic thread. In-flight prunes finish (or are interrupted safely)."""
        self._stop_event.set()
        thread = self._periodic_thread
        self._periodic_thread = None
        if thread is not None:
            thread.join(timeout=5)


_manager = RetentionManager()


def get_retention_manager() -> RetentionManager:
    """Return the process-wide retention manager."""
    return _manager
