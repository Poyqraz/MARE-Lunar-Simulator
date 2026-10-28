import math

import pytest

from mars_rover.drive import Calibration, CommandState, wheels_from_twist, validate_wheels, wire_command


def test_forward_reverse_and_turns_follow_upstream_wire_sign():
    c = Calibration()
    forward = wheels_from_twist(0.2, 0, c)
    assert forward == dict.fromkeys(("FL", "FR", "BL", "BR"), 0.2)
    assert wire_command(forward, c)["FL"] == pytest.approx(-0.364)
    reverse = wheels_from_twist(-0.2, 0, c)
    assert all(v < 0 for v in reverse.values())
    turn = wheels_from_twist(0, 0.2, c)
    assert turn["FL"] == turn["BL"] < 0 < turn["FR"] == turn["BR"]


def test_four_motors_remain_independent():
    speeds = {"FL": 0.1, "FR": 0.2, "BL": -0.1, "BR": -0.2}
    wire = wire_command(validate_wheels(speeds, Calibration()), Calibration())
    for name, value in speeds.items():
        assert wire[name] == pytest.approx(-value * 1.82)
    assert wire["headlights_on"] is False
    assert wire["headlights_intensity"] == 0.0


def test_saturation_preserves_wheel_ratios():
    c = Calibration(max_wheel_speed_m_s=0.5)
    speeds = validate_wheels({"FL": 2, "FR": 1, "BL": -2, "BR": -1}, c)
    assert speeds == {"FL": 0.5, "FR": 0.25, "BL": -0.5, "BR": -0.25}


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, True, "0.1"])
def test_invalid_motor_values_are_rejected(value):
    with pytest.raises(ValueError):
        validate_wheels({"FL": value, "FR": 0, "BL": 0, "BR": 0}, Calibration())


def test_missing_motor_cannot_silently_keep_a_previous_speed():
    with pytest.raises(ValueError):
        validate_wheels({"FL": 0.1, "FR": 0.1, "BL": 0.1}, Calibration())


def test_watchdog_and_reconnection_cannot_replay_old_commands():
    state = CommandState(Calibration(), timeout_s=0.3)
    with pytest.raises(ConnectionError):
        state.submit_wheels(dict.fromkeys(("FL", "FR", "BL", "BR"), 0.2), now=1)
    state.connect()
    state.submit_wheels(dict.fromkeys(("FL", "FR", "BL", "BR"), 0.2), now=1)
    assert state.sample(now=1.1)["FL"] != 0
    assert state.sample(now=1.301)["FL"] == 0
    state.disconnect()
    state.connect()
    assert state.sample(now=1.1)["FL"] == 0


def test_invalid_request_stops_instead_of_leaving_previous_command_active():
    state = CommandState(Calibration())
    state.connect()
    state.submit_twist(0.2, 0, now=0)
    with pytest.raises(ValueError):
        state.submit_twist(math.nan, 0, now=0.1)
    assert state.sample(now=0.11)["FL"] == 0
