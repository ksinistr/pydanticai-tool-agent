from __future__ import annotations

from pydantic_ai import Agent

from app.agent.factory import build_model
from app.config import AppConfig
from app.morning_report.context import MorningReportContextBuilder
from app.morning_report.models import MorningReportSettings, MorningReportSetup
from app.morning_report.service import MorningReportService
from app.plugins.intervals_icu.client import IntervalsIcuClient
from app.plugins.open_meteo.client import OpenMeteoClient

INSTRUCTIONS = """
You write one concise morning cycling note for Telegram.
Use only the supplied context. Do not invent data.
Write in the requested language.
Keep it personal, varied, and compact.
Avoid headings, bullets, canned phrasing, and repetitive templates.
Make the note useful for today: readiness, best weather window, specific session choice, and one caution.
If weather data is missing, say that weather confidence is limited.
Assume weekdays are constrained workdays and weekends have fuller availability.
""".strip()


def build_morning_report_service(config: AppConfig) -> MorningReportService:
    setup = _build_setup(config)
    intervals_client = _build_intervals_client(config)
    context_builder = MorningReportContextBuilder(intervals_client, OpenMeteoClient())
    agent = Agent(build_model(config), instructions=INSTRUCTIONS)
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
            timezone=str(config.morning_report_timezone),
            language=str(config.morning_report_language),
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
