"""Tests for daemon polling loop, worker, PID utilities, and shutdown."""

import fcntl
import json
import os
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from observer.daemon import Daemon
from observer.daemon.workers import index_worker, ingest_worker, process_worker, refine_worker
from observer.data.project import Project
from observer.data.transcript import Transcript

NOW = datetime.now(UTC)


def _make_event(
    event_type: str = "user",
    timestamp: str = "2025-01-15T10:00:00Z",
    uuid: str | None = "abc-123",
) -> dict:
    d: dict = {"type": event_type, "timestamp": timestamp}
    if uuid is not None:
        d["uuid"] = uuid
    return d


def _write_jsonl(path, lines: list[dict]) -> None:
    with open(path, "w") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")


@pytest.fixture()
def lock_dir(tmp_path):
    d = tmp_path / "locks"
    d.mkdir()
    return d


@pytest.fixture()
def daemon(tmp_path):
    return Daemon(pid_file=tmp_path / "test.pid")


def _run_one_poll(daemon: Daemon) -> None:
    """Run the daemon for exactly one ingest tick then shut down."""

    def fake_wait(**_):
        daemon._shutdown_event.set()
        return True

    # Force the scheduler into the ingest branch for this single tick
    fixed_time = 100.0
    daemon._last_index_at = fixed_time
    daemon._last_process_at = fixed_time
    daemon._last_refine_at = fixed_time

    with (
        patch.object(daemon._shutdown_event, "wait", side_effect=fake_wait),
        patch("observer.daemon.daemon.time.monotonic", return_value=fixed_time),
    ):
        daemon.run(foreground=True)


@pytest.fixture()
def setup(db, tmp_path):
    """Create a project + transcript + JSONL file with events."""
    transcript_path = tmp_path / "transcript.jsonl"
    _write_jsonl(
        transcript_path,
        [
            _make_event("user", uuid="u-1"),
            _make_event("assistant", uuid="a-1"),
        ],
    )

    with db.session() as s:
        p = Project(name="proj", repo_path="/repo").save(s)
        t = Transcript(
            project_id=p.id,
            session_id="s1",
            path=str(transcript_path),
            started_at=NOW,
        ).save(s)

    return t, transcript_path


class TestPidUtilities:
    def test_is_process_running_self(self):
        assert Daemon.is_process_running(os.getpid()) is True

    def test_is_process_running_dead(self):
        assert Daemon.is_process_running(2**20) is False

    def test_check_running_alive(self, tmp_path):  # noqa: ARG002
        pid_file = tmp_path / "test.pid"
        pid_file.write_text(str(os.getpid()))
        d = Daemon(pid_file=pid_file)

        with patch.object(Daemon, "_is_own_daemon", return_value=True):
            result = d.check_running()
        assert result == os.getpid()

    def test_check_running_alive_foreign_process(self, tmp_path):  # noqa: ARG002
        pid_file = tmp_path / "test.pid"
        pid_file.write_text(str(os.getpid()))
        d = Daemon(pid_file=pid_file)

        with patch.object(Daemon, "_is_own_daemon", return_value=False):
            result = d.check_running()
        assert result is None
        assert not pid_file.exists()

    def test_check_running_stale(self, tmp_path):  # noqa: ARG002
        pid_file = tmp_path / "test.pid"
        pid_file.write_text(str(2**20))
        d = Daemon(pid_file=pid_file)

        result = d.check_running()
        assert result is None
        assert not pid_file.exists()

    def test_check_running_no_file(self, tmp_path):  # noqa: ARG002
        d = Daemon(pid_file=tmp_path / "missing.pid")
        assert d.check_running() is None

    def test_check_running_invalid_content(self, tmp_path):  # noqa: ARG002
        pid_file = tmp_path / "bad.pid"
        pid_file.write_text("not-a-number\n")
        d = Daemon(pid_file=pid_file)
        assert d.check_running() is None


class TestDaemonRun:
    def test_graceful_shutdown_on_signal(self, db, daemon):  # noqa: ARG002
        def fake_wait(**_):
            daemon._shutdown_event.set()
            return True

        with patch.object(daemon._shutdown_event, "wait", side_effect=fake_wait):
            daemon.run(foreground=True)

        assert not daemon._pid_file.exists()

    def test_writes_and_cleans_pid_file(self, db, daemon):  # noqa: ARG002
        def fake_wait(**_):
            # PID file should exist during run
            assert daemon._pid_file.exists()
            assert int(daemon._pid_file.read_text().strip()) == os.getpid()
            daemon._shutdown_event.set()
            return True

        with patch.object(daemon._shutdown_event, "wait", side_effect=fake_wait):
            daemon.run(foreground=True)

        assert not daemon._pid_file.exists()


class TestIngestWorker:
    def test_ingests_events_and_updates_mtime(self, db, tmp_path, lock_dir, setup):  # noqa: ARG002
        t, transcript_path = setup
        file_mtime = transcript_path.stat().st_mtime_ns

        ingest_worker(t.id, file_mtime, lock_dir)

        loaded = Transcript.get(t.id)
        assert loaded.cursor_offset > 0
        assert loaded.last_mtime == file_mtime

    def test_bails_when_lock_held(self, db, tmp_path, lock_dir, setup):  # noqa: ARG002
        t, transcript_path = setup
        file_mtime = transcript_path.stat().st_mtime_ns

        lock_path = lock_dir / f"transcript_{t.id}.lock"
        fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            ingest_worker(t.id, file_mtime, lock_dir)

            loaded = Transcript.get(t.id)
            assert loaded.cursor_offset == 0
            assert loaded.last_mtime is None
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def test_handles_missing_transcript(self, db, tmp_path, lock_dir):  # noqa: ARG002
        ingest_worker(9999, 1, lock_dir)

    def test_handles_missing_file(self, db, tmp_path, lock_dir, setup):  # noqa: ARG002
        t, transcript_path = setup
        file_mtime = transcript_path.stat().st_mtime_ns

        transcript_path.unlink()

        ingest_worker(t.id, file_mtime, lock_dir)

        loaded = Transcript.get(t.id)
        assert loaded.cursor_offset == 0
        assert loaded.last_mtime is None


class TestPollOnce:
    def test_spawns_worker_on_mtime_change(self, db, tmp_path, setup, daemon):  # noqa: ARG002
        t, transcript_path = setup

        t.last_mtime = 0
        with db.session() as s:
            t.save(s)

        with patch("observer.daemon.daemon.multiprocessing.Process") as mock_proc_cls:
            mock_proc = MagicMock()
            mock_proc_cls.return_value = mock_proc
            _run_one_poll(daemon)

        mock_proc_cls.assert_called_once()
        mock_proc.start.assert_called_once()

    def test_skips_when_mtime_unchanged(self, db, tmp_path, setup, daemon):  # noqa: ARG002
        t, transcript_path = setup
        file_mtime = transcript_path.stat().st_mtime_ns

        t.last_mtime = file_mtime
        with db.session() as s:
            t.save(s)

        with patch("observer.daemon.daemon.multiprocessing.Process") as mock_proc_cls:
            _run_one_poll(daemon)

        mock_proc_cls.assert_not_called()

    def test_sets_ended_at_when_file_deleted(self, db, tmp_path, setup, daemon):  # noqa: ARG002
        t, transcript_path = setup

        # Simulate a previously-tracked transcript (file was seen at least once)
        t.last_mtime = transcript_path.stat().st_mtime_ns
        with db.session() as s:
            t.save(s)

        transcript_path.unlink()

        with patch("observer.daemon.daemon.multiprocessing.Process") as mock_proc_cls:
            _run_one_poll(daemon)

        mock_proc_cls.assert_not_called()

        loaded = Transcript.get(t.id)
        assert loaded.ended_at is not None

    def test_grace_period_for_new_transcript(self, db, tmp_path, setup, daemon):  # noqa: ARG002
        """New transcripts (never seen on disk) get a grace period before deletion."""
        t, transcript_path = setup
        transcript_path.unlink()

        with patch("observer.daemon.daemon.multiprocessing.Process") as mock_proc_cls:
            _run_one_poll(daemon)

        mock_proc_cls.assert_not_called()

        loaded = Transcript.get(t.id)
        assert loaded.ended_at is None

    def test_spawns_on_first_poll_null_last_mtime(self, db, tmp_path, setup, daemon):  # noqa: ARG002
        t, transcript_path = setup

        with patch("observer.daemon.daemon.multiprocessing.Process") as mock_proc_cls:
            mock_proc = MagicMock()
            mock_proc_cls.return_value = mock_proc
            _run_one_poll(daemon)

        mock_proc_cls.assert_called_once()
        mock_proc.start.assert_called_once()

    def test_does_not_spawn_for_ended_transcripts(self, db, tmp_path, daemon):  # noqa: ARG002
        transcript_path = tmp_path / "ended.jsonl"
        _write_jsonl(transcript_path, [_make_event()])

        with db.session() as s:
            p = Project(name="proj", repo_path="/repo").save(s)
            Transcript(
                project_id=p.id,
                session_id="ended",
                path=str(transcript_path),
                started_at=NOW,
                ended_at=NOW,
            ).save(s)

        with patch("observer.daemon.daemon.multiprocessing.Process") as mock_proc_cls:
            _run_one_poll(daemon)

        mock_proc_cls.assert_not_called()

    def test_multiple_transcripts_mixed(self, db, tmp_path, daemon):  # noqa: ARG002
        path1 = tmp_path / "t1.jsonl"
        _write_jsonl(path1, [_make_event(uuid="u-1")])

        path2 = tmp_path / "t2.jsonl"
        _write_jsonl(path2, [_make_event(uuid="u-2")])
        mtime2 = path2.stat().st_mtime_ns

        path3 = tmp_path / "t3.jsonl"

        with db.session() as s:
            p = Project(name="proj", repo_path="/repo").save(s)
            Transcript(
                project_id=p.id,
                session_id="s1",
                path=str(path1),
                started_at=NOW,
                last_mtime=0,
            ).save(s)
            Transcript(
                project_id=p.id,
                session_id="s2",
                path=str(path2),
                started_at=NOW,
                last_mtime=mtime2,
            ).save(s)
            t3 = Transcript(
                project_id=p.id,
                session_id="s3",
                path=str(path3),
                started_at=NOW,
                last_mtime=1,
            ).save(s)

        with patch("observer.daemon.daemon.multiprocessing.Process") as mock_proc_cls:
            mock_proc = MagicMock()
            mock_proc_cls.return_value = mock_proc
            _run_one_poll(daemon)

        assert mock_proc_cls.call_count == 1
        mock_proc.start.assert_called_once()

        loaded = Transcript.get(t3.id)
        assert loaded.ended_at is not None


class TestRefineWorker:
    def test_calls_refine_batch(self, db, tmp_path, lock_dir):  # noqa: ARG002
        with patch("observer.daemon.workers.EventRefiner.refine_batch") as mock_batch:
            refine_worker(lock_dir)
            mock_batch.assert_called_once()

    def test_bails_when_lock_held(self, db, tmp_path, lock_dir):  # noqa: ARG002
        lock_path = lock_dir / "refining.lock"
        fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            with patch("observer.daemon.workers.EventRefiner.refine_batch") as mock_batch:
                refine_worker(lock_dir)
                mock_batch.assert_not_called()
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def test_handles_refining_error(self, db, tmp_path, lock_dir):  # noqa: ARG002
        with patch("observer.daemon.workers.EventRefiner.refine_batch", side_effect=RuntimeError("boom")):
            refine_worker(lock_dir)


class TestProcessWorker:
    def test_calls_process_batch(self, db, tmp_path, lock_dir):  # noqa: ARG002
        with patch("observer.daemon.workers.WorkItemExtractor.extract_batch") as mock_batch:
            process_worker(lock_dir)
            mock_batch.assert_called_once()

    def test_bails_when_lock_held(self, db, tmp_path, lock_dir):  # noqa: ARG002
        lock_path = lock_dir / "processing.lock"
        fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            with patch("observer.daemon.workers.WorkItemExtractor.extract_batch") as mock_batch:
                process_worker(lock_dir)
                mock_batch.assert_not_called()
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def test_handles_processing_error(self, db, tmp_path, lock_dir):  # noqa: ARG002
        with patch("observer.daemon.workers.WorkItemExtractor.extract_batch", side_effect=RuntimeError("boom")):
            process_worker(lock_dir)


class TestIndexWorker:
    def test_calls_index_batch(self, db, tmp_path, lock_dir):  # noqa: ARG002
        with patch("observer.daemon.workers.SearchIndexer.index_batch") as mock_batch:
            index_worker(lock_dir)
            mock_batch.assert_called_once()

    def test_bails_when_lock_held(self, db, tmp_path, lock_dir):  # noqa: ARG002
        lock_path = lock_dir / "indexing.lock"
        fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            with patch("observer.daemon.workers.SearchIndexer.index_batch") as mock_batch:
                index_worker(lock_dir)
                mock_batch.assert_not_called()
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def test_handles_indexing_error(self, db, tmp_path, lock_dir):  # noqa: ARG002
        with patch("observer.daemon.workers.SearchIndexer.index_batch", side_effect=RuntimeError("boom")):
            index_worker(lock_dir)


class TestScheduler:
    """Tests for the 4-tier priority scheduler in _poll_loop.

    The scheduler picks one stage per tick based on priority:
        indexing (15s) > processing (6s) > refining (4s) > ingest (fills remaining)

    Time is simulated by patching time.monotonic to return incrementing
    values (0.0, 1.0, 2.0, ...). _poll_once is mocked since ingest
    behavior is tested separately in TestPollOnce.
    """

    def test_refine_fires_after_interval(self, db, daemon):  # noqa: ARG002
        """Refining spawns once REFINE_INTERVAL (4s) has elapsed."""
        tick = 0

        def fake_wait(**_):
            nonlocal tick
            tick += 1
            if tick >= 5:
                daemon._shutdown_event.set()
                return True
            return False

        clock = iter(float(i) for i in range(5))

        with (
            patch.object(daemon._shutdown_event, "wait", side_effect=fake_wait),
            patch("observer.daemon.daemon.time.monotonic", side_effect=lambda: next(clock)),
            patch("observer.daemon.daemon.EventGrouper.has_pending", return_value=True),
            patch("observer.daemon.daemon.WorkItemRefiner.has_pending", return_value=False),
            patch("observer.daemon.daemon.WorkItem.has_by_processed", return_value=False),
            patch("observer.daemon.daemon.SearchIndexer.has_pending", return_value=False),
            patch("observer.daemon.daemon.multiprocessing.Process") as mock_proc_cls,
            patch.object(daemon, "_poll_once", return_value=0),
        ):
            mock_proc = MagicMock()
            mock_proc_cls.return_value = mock_proc
            daemon.run(foreground=True)

        # t=4: refine interval elapsed (4-0 >= 4)
        all_targets = [c.kwargs.get("target") for c in mock_proc_cls.call_args_list]
        assert refine_worker in all_targets

    def test_ingest_fills_remaining_ticks(self, db, daemon):  # noqa: ARG002
        """Ticks before any interval fires go to ingest."""
        tick = 0

        def fake_wait(**_):
            nonlocal tick
            tick += 1
            if tick >= 3:
                daemon._shutdown_event.set()
                return True
            return False

        clock = iter(float(i) for i in range(3))

        with (
            patch.object(daemon._shutdown_event, "wait", side_effect=fake_wait),
            patch("observer.daemon.daemon.time.monotonic", side_effect=lambda: next(clock)),
            patch("observer.daemon.daemon.multiprocessing.Process") as mock_proc_cls,
            patch.object(daemon, "_poll_once", return_value=0) as mock_poll,
        ):
            mock_proc = MagicMock()
            mock_proc_cls.return_value = mock_proc
            daemon.run(foreground=True)

        # t=0..2: all below refine interval (4s), so all go to ingest
        assert mock_poll.call_count == 3
        assert mock_proc_cls.call_count == 0

    def test_processing_fires_after_interval(self, db, daemon):  # noqa: ARG002
        """Processing spawns once PROCESS_INTERVAL (6s) has elapsed."""
        tick = 0

        def fake_wait(**_):
            nonlocal tick
            tick += 1
            if tick >= 7:
                daemon._shutdown_event.set()
                return True
            return False

        clock = iter(float(i) for i in range(7))

        with (
            patch.object(daemon._shutdown_event, "wait", side_effect=fake_wait),
            patch("observer.daemon.daemon.time.monotonic", side_effect=lambda: next(clock)),
            patch("observer.daemon.daemon.EventGrouper.has_pending", return_value=True),
            patch("observer.daemon.daemon.WorkItemRefiner.has_pending", return_value=False),
            patch("observer.daemon.daemon.WorkItem.has_by_processed", return_value=True),
            patch("observer.daemon.daemon.SearchIndexer.has_pending", return_value=False),
            patch("observer.daemon.daemon.multiprocessing.Process") as mock_proc_cls,
            patch.object(daemon, "_poll_once", return_value=0),
        ):
            mock_proc = MagicMock()
            mock_proc_cls.return_value = mock_proc
            daemon.run(foreground=True)

        # t=6: process interval elapsed (6-0 >= 6)
        all_targets = [c.kwargs.get("target") for c in mock_proc_cls.call_args_list]
        assert process_worker in all_targets

    def test_indexing_fires_after_interval(self, db, daemon):  # noqa: ARG002
        """Indexing spawns once INDEX_INTERVAL (15s) has elapsed."""
        tick = 0

        def fake_wait(**_):
            nonlocal tick
            tick += 1
            if tick >= 16:
                daemon._shutdown_event.set()
                return True
            return False

        clock = iter(float(i) for i in range(16))

        with (
            patch.object(daemon._shutdown_event, "wait", side_effect=fake_wait),
            patch("observer.daemon.daemon.time.monotonic", side_effect=lambda: next(clock)),
            patch("observer.daemon.daemon.EventGrouper.has_pending", return_value=True),
            patch("observer.daemon.daemon.WorkItemRefiner.has_pending", return_value=False),
            patch("observer.daemon.daemon.WorkItem.has_by_processed", return_value=True),
            patch("observer.daemon.daemon.SearchIndexer.has_pending", return_value=True),
            patch("observer.daemon.daemon.multiprocessing.Process") as mock_proc_cls,
            patch.object(daemon, "_poll_once", return_value=0),
        ):
            mock_proc = MagicMock()
            mock_proc_cls.return_value = mock_proc
            daemon.run(foreground=True)

        # t=15: index interval elapsed (15-0 >= 15)
        all_targets = [c.kwargs.get("target") for c in mock_proc_cls.call_args_list]
        assert index_worker in all_targets

    def test_indexing_skipped_when_nothing_pending(self, db, daemon):  # noqa: ARG002
        """Indexing tick updates timestamp but spawns no worker when nothing pending."""
        tick = 0

        def fake_wait(**_):
            nonlocal tick
            tick += 1
            if tick >= 16:
                daemon._shutdown_event.set()
                return True
            return False

        clock = iter(float(i) for i in range(16))

        with (
            patch.object(daemon._shutdown_event, "wait", side_effect=fake_wait),
            patch("observer.daemon.daemon.time.monotonic", side_effect=lambda: next(clock)),
            patch("observer.daemon.daemon.EventGrouper.has_pending", return_value=False),
            patch("observer.daemon.daemon.WorkItemRefiner.has_pending", return_value=False),
            patch("observer.daemon.daemon.WorkItem.has_by_processed", return_value=False),
            patch("observer.daemon.daemon.SearchIndexer.has_pending", return_value=False),
            patch("observer.daemon.daemon.multiprocessing.Process") as mock_proc_cls,
            patch.object(daemon, "_poll_once", return_value=0),
        ):
            mock_proc = MagicMock()
            mock_proc_cls.return_value = mock_proc
            daemon.run(foreground=True)

        all_targets = [c.kwargs.get("target") for c in mock_proc_cls.call_args_list]
        assert index_worker not in all_targets

    def test_indexing_has_priority_over_processing(self, db, daemon):  # noqa: ARG002
        """When both intervals are due on the same tick, indexing wins."""

        def fake_wait(**_):
            daemon._shutdown_event.set()
            return True

        # At t=20, all intervals are exceeded
        with (
            patch.object(daemon._shutdown_event, "wait", side_effect=fake_wait),
            patch("observer.daemon.daemon.time.monotonic", return_value=20.0),
            patch("observer.daemon.daemon.SearchIndexer.has_pending", return_value=True),
            patch("observer.daemon.daemon.WorkItem.has_by_processed", return_value=True),
            patch("observer.daemon.daemon.multiprocessing.Process") as mock_proc_cls,
        ):
            mock_proc = MagicMock()
            mock_proc_cls.return_value = mock_proc
            daemon.run(foreground=True)

        all_targets = [c.kwargs.get("target") for c in mock_proc_cls.call_args_list]
        assert index_worker in all_targets
        assert process_worker not in all_targets
