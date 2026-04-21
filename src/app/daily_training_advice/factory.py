from __future__ import annotations

from pydantic_ai import Agent

from app.agent.factory import build_model
from app.config import AppConfig
from app.daily_training_advice.context import DailyTrainingAdviceContextBuilder
from app.daily_training_advice.models import (
    DailyTrainingAdviceSettings,
    DailyTrainingAdviceSetup,
    DailyTrainingAdviceStructuredOutput,
)
from app.daily_training_advice.service import DailyTrainingAdviceService
from app.plugins.caldav.client import CaldavClient
from app.plugins.caldav.models import CaldavSettings
from app.plugins.intervals_icu.client import IntervalsIcuClient
from app.plugins.open_meteo.client import OpenMeteoClient

INSTRUCTIONS = """
You generate deterministic cycling advice for the remaining part of the current local day.
Use only the supplied context. Do not invent data.
Write in the requested language.
Return structured output that fills every section in the schema.
Keep every line compact, specific, and decision-oriented.
Classify readiness as green, yellow, or red.
If today_summary.count is 0, recommend the best remaining training option for today.
If today_summary.count is greater than 0, account for the completed work and focus on what still makes sense today.
Do not prescribe the same load twice after it has already been completed today.
If the day is already late or little useful weather remains, prefer recovery, fueling, and sleep preparation.
If day_type is holiday, vacation, holiday_and_vacation, or weekend, regular workday constraints do not apply.
If workday_constraints_apply is true, keep the remaining day realistic for a workday.
If calendar data is missing, say availability fell back to weekday or weekend assumptions.
If weather data is missing, say forecast confidence is limited.
If remaining_weather_hours is empty, do not suggest a later outdoor window today.
Weather can move or downgrade an outdoor session, but it does not change physiological readiness by itself.
""".strip()


def build_daily_training_advice_service(config: AppConfig) -> DailyTrainingAdviceService:
    setup = _build_setup(config)
    intervals_client = _build_intervals_client(config)
    caldav_client = _build_caldav_client(config)
    context_builder = DailyTrainingAdviceContextBuilder(
        intervals_client=intervals_client,
        weather_client=OpenMeteoClient(),
        caldav_client=caldav_client,
        calendar_setup_error=_calendar_setup_error(config),
    )
    agent = Agent(
        build_model(config),
        output_type=DailyTrainingAdviceStructuredOutput,
        instructions=INSTRUCTIONS,
    )
    return DailyTrainingAdviceService(
        agent=agent,
        context_builder=context_builder,
        setup=setup,
        default_language=config.morning_report_language,
    )


def _build_setup(config: AppConfig) -> DailyTrainingAdviceSetup:
    missing = list(config.missing_morning_report_settings())
    if not config.intervals_icu_api_key:
        missing.append("INTERVALS_ICU_API_KEY")
    if not config.intervals_icu_athlete_id:
        missing.append("INTERVALS_ICU_ATHLETE_ID")

    settings = None
    if not config.missing_morning_report_settings():
        settings = DailyTrainingAdviceSettings(
            latitude=float(config.morning_report_latitude),
            longitude=float(config.morning_report_longitude),
            timezone=str(config.user_timezone),
            language=str(config.morning_report_language),
            holidays_calendar_id=config.morning_report_holidays_calendar_id,
            vacation_calendar_id=config.morning_report_vacation_calendar_id,
        )

    return DailyTrainingAdviceSetup(settings=settings, missing_variables=tuple(missing))


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
