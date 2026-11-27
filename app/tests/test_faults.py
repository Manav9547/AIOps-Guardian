"""Fault switches: each turns on, shows its effect, and turns cleanly off."""

import time

import anyio
import pytest

from app import faults


def test_all_off_by_default():
    assert faults.state() == {"cpu_hog": False, "memory_leak": False, "slow_db": False}
    assert faults.slow_db_delay() == 0.0


def test_unknown_fault_raises():
    with pytest.raises(KeyError):
        faults.set_fault("disk_full", True)


def test_slow_db_adds_delay_only_while_on():
    faults.set_fault("slow_db", True)
    assert faults.slow_db_delay() == faults.SLOW_DB_SLEEP_S == 0.5
    faults.set_fault("slow_db", False)
    assert faults.slow_db_delay() == 0.0


def test_cpu_hog_runs_a_child_process_and_stops_it():
    faults.set_fault("cpu_hog", True)
    proc = faults._cpu_proc
    try:
        assert faults.state()["cpu_hog"] is True
        assert proc.pid is not None and proc.is_alive()
        faults.set_fault("cpu_hog", True)          # idempotent: no second child
        assert faults._cpu_proc is proc
    finally:
        faults.set_fault("cpu_hog", False)
    assert faults.state()["cpu_hog"] is False
    assert not proc.is_alive()


@pytest.mark.anyio
async def test_memory_leak_grows_then_frees(monkeypatch):
    monkeypatch.setattr(faults, "LEAK_CHUNK_BYTES", 1024)
    monkeypatch.setattr(faults, "LEAK_INTERVAL_S", 0.01)
    faults.set_fault("memory_leak", True)
    assert faults.state()["memory_leak"] is True
    await anyio.sleep(0.1)
    assert len(faults._leaked) >= 3
    assert all(len(chunk) == 1024 for chunk in faults._leaked)
    faults.set_fault("memory_leak", False)
    await anyio.sleep(0)                           # let the cancellation land
    assert faults.state()["memory_leak"] is False
    assert faults._leaked == []


@pytest.mark.anyio
async def test_stop_all_switches_everything_off():
    faults.set_fault("slow_db", True)
    faults.set_fault("memory_leak", True)
    faults.set_fault("cpu_hog", True)
    faults.stop_all()
    await anyio.sleep(0)
    assert faults.state() == {"cpu_hog": False, "memory_leak": False, "slow_db": False}


def test_fault_change_is_logged(caplog):
    with caplog.at_level("WARNING", logger="booking.faults"):
        faults.set_fault("slow_db", True)
    rec = caplog.records[-1]
    assert rec.event == "fault" and rec.fault == "slow_db" and rec.enabled is True


def test_cpu_hog_child_exits_when_off_quickly():
    faults.set_fault("cpu_hog", True)
    start = time.monotonic()
    faults.set_fault("cpu_hog", False)
    assert time.monotonic() - start < 3
