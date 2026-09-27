import logging

# Prevent HTTP client request URLs from being written to application logs.
# Telegram Bot API URLs contain the bot token in the path, so INFO-level
# request logging is intentionally disabled.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
