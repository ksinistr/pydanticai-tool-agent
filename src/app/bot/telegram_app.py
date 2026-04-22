from __future__ import annotations

import logging

from telegram.error import NetworkError
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from app.agent.factory import build_agent
from app.agent.service import AgentService, CurrentDayConversationStore
from app.bot.handlers import TelegramHandlers
from app.bot.uploads import PendingTelegramDocumentStore, TelegramDocumentStore
from app.config import AppConfig, project_root
from app.daily_training_advice import build_daily_training_advice_service
from app.morning_report import build_morning_report_service
from app.plugins.loader import load_plugins


def build_application(config: AppConfig) -> Application:
    agent = build_agent(config, load_plugins(config))
    service = AgentService(agent, CurrentDayConversationStore())
    morning_report_service = build_morning_report_service(config)
    daily_training_advice_service = build_daily_training_advice_service(config)
    handlers = TelegramHandlers(
        service,
        morning_report_service=morning_report_service,
        daily_training_advice_service=daily_training_advice_service,
        authorized_users=config.telegram_authorized_users,
        document_store=TelegramDocumentStore(project_root() / "output" / "telegram_uploads"),
        pending_documents=PendingTelegramDocumentStore(),
    )

    application = Application.builder().token(config.require_telegram_bot_token()).build()
    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("help", handlers.help))
    application.add_handler(CommandHandler("reset", handlers.reset))
    application.add_handler(CommandHandler("morning_report", handlers.morning_report))
    application.add_handler(CommandHandler("daily_training_advice", handlers.daily_training_advice))
    application.add_handler(MessageHandler(filters.Document.ALL, handlers.handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_text))
    return application


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        level=logging.INFO,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    try:
        config = AppConfig.from_env()
        application = build_application(config)
        application.run_polling()
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    except NetworkError as exc:
        raise SystemExit(
            "Failed to reach the Telegram API. Check network access, DNS, and TELEGRAM_BOT_TOKEN."
        ) from exc


if __name__ == "__main__":
    main()
