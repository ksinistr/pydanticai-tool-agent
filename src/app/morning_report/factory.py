from __future__ import annotations

from pydantic_ai import Agent

from app.agent.factory import build_model
from app.config import AppConfig
from app.morning_report.context import MorningReportContextBuilder
from app.morning_report.models import (
    MorningReportSettings,
    MorningReportSetup,
    MorningReportStructuredOutput,
)
from app.morning_report.service import MorningReportService
from app.plugins.caldav.client import CaldavClient
from app.plugins.caldav.models import CaldavSettings
from app.plugins.intervals_icu.client import IntervalsIcuClient
from app.plugins.open_meteo.client import OpenMeteoClient

INSTRUCTIONS = """
You generate a deterministic morning cycling readiness brief.
Use only the supplied context. Do not invent data.
Write in the requested language.
Return structured output that fills every section in the schema.
Keep every line compact, specific, and decision-oriented.
Classify readiness as green, yellow, or red.
If day_type is holiday, vacation, holiday_and_vacation, or weekend, regular workday constraints do not apply.
If workday_constraints_apply is true, keep today realistic for a workday.
If calendar data is missing, say availability fell back to weekday or weekend assumptions.
If weather data is missing, say forecast confidence is limited.
Weather can move or downgrade an outdoor session, but it does not change physiological readiness by itself.
""".strip()


def build_morning_report_service(config: AppConfig) -> MorningReportService:
    setup = _build_setup(config)
    intervals_client = _build_intervals_client(config)
    caldav_client = _build_caldav_client(config)
    context_builder = MorningReportContextBuilder(
        intervals_client=intervals_client,
        weather_client=OpenMeteoClient(),
        caldav_client=caldav_client,
        calendar_setup_error=_calendar_setup_error(config),
    )
    agent = Agent(
        build_model(config),
        output_type=MorningReportStructuredOutput,
        instructions=INSTRUCTIONS,
    )
    return MorningReportService(
        agent=agent,
        context_builder=context_builder,
        setup=setup,
        default_language=config.morning_report_language,
    )


def _build_setup(config: AppConfig) -> MorningReportSetup:
    missing = list(config.missing_morning_report_settings())
    if not config.intervals_icu_api_key:
        missing.append("INTERVALS_ICU_API_KEY")
    if not config.intervals_icu_athlete_id:
        missing.append("INTERVALS_ICU_ATHLETE_ID")

    settings = None
    if not config.missing_morning_report_settings():
        settings = MorningReportSettings(
            latitude=float(config.morning_report_latitude),
            longitude=float(config.morning_report_longitude),
            timezone=str(config.user_timezone),
            language=str(config.morning_report_language),
            holidays_calendar_id=config.morning_report_holidays_calendar_id,
            vacation_calendar_id=config.morning_report_vacation_calendar_id,
        )

    return MorningReportSetup(settings=settings, missing_variables=tuple(missing))


def _build_intervals_client(config: AppConfig) -> IntervalsIcuClient | None:
    if not config.intervals_icu_api_key or not config.intervals_icu_athlete_id:
        return None
    return IntervalsIcuClient(
        athlete_id=config.intervals_icu_athlete_id,
        api_key=config.intervals_icu_api_key,
        base_url=config.intervals_icu_base_url,
    )


def _build_caldav_client(config: AppConfig) -> CaldavClient | None:
    if not config.caldav_server_url or not config.caldav_username:
        return None
    settings = CaldavSettings(
        server_url=config.caldav_server_url,
        username=config.caldav_username,
        password=config.caldav_password,
        insecure_skip_verify=config.caldav_insecure_skip_verify,
    )
    return CaldavClient(settings)


def _calendar_setup_error(config: AppConfig) -> str | None:
    missing: list[str] = []
    if not config.caldav_server_url:
        missing.append("CALDAV_SERVER_URL")
    if not config.caldav_username:
        missing.append("CALDAV_USERNAME")
    if missing:
        joined = ", ".join(missing)
        return f"CalDAV is not configured ({joined})."
    return None
