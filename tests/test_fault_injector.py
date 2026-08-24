"""Unit tests for FaultInjector determinism, repeatability across seeds, and state updates."""

import pytest
from toy_service.fault_injector import FaultInjector
from toy_service.state import ServiceState


def test_fault_injector_determinism():
    """Verify same fault type and same seed yields identical telemetry."""
    for fault_type in FaultInjector.FAULT_TYPES:
        state_a = ServiceState()
        injector_a = FaultInjector(state_a)
        res_a = injector_a.inject(fault_type, seed=123)

        state_b = ServiceState()
        injector_b = FaultInjector(state_b)
        res_b = injector_b.inject(fault_type, seed=123)

        assert res_a["metrics"] == res_b["metrics"]
        assert res_a["fault_type"] == res_b["fault_type"]
        assert res_a["current_version"] == res_b["current_version"]


def test_fault_injector_different_seeds():
    """Verify different seeds produce different metric values."""
    state_a = ServiceState()
    injector_a = FaultInjector(state_a)
    res_a = injector_a.inject("high_latency", seed=42)

    state_b = ServiceState()
    injector_b = FaultInjector(state_b)
    res_b = injector_b.inject("high_latency", seed=999)

    assert res_a["metrics"]["p99_latency_ms"] != res_b["metrics"]["p99_latency_ms"]


def test_fault_injector_invalid_fault_type():
    """Verify unknown fault type raises ValueError."""
    state = ServiceState()
    injector = FaultInjector(state)
    with pytest.raises(ValueError, match="Unknown fault type"):
        injector.inject("non_existent_fault", seed=42)


def test_fault_injector_all_types_mutate_health():
    """Verify all 4 fault types flip is_healthy to False."""
    for fault_type in FaultInjector.FAULT_TYPES:
        state = ServiceState()
        injector = FaultInjector(state)
        injector.inject(fault_type, seed=50)
        assert state.is_healthy is False
        assert state.active_fault == fault_type
