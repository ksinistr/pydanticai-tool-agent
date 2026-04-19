from __future__ import annotations

import pytest

from app.plugins.get_time.models import TimeRequest
from app.plugins.get_time.service import GetTimeService


def test_get_current_time_uses_requested_timezone() -> None:
    service = GetTimeService()
    response = service.get_current_time(TimeRequest(timezone_name="UTC"))

    assert response.timezone_name == "UTC"
    assert response.iso_datetime.endswith("+00:00")


def test_get_current_time_rejects_unknown_timezone() -> None:
    service = GetTimeService()

    with pytest.raises(ValueError, match="Unknown timezone: Mars/Olympus"):
        service.get_current_time(TimeRequest(timezone_name="Mars/Olympus"))

