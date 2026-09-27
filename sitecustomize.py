import logging

# Never write Telegram Bot API request URLs (which contain the bot token) to logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Load runtime patches in order: graceful source handling, Holly free cache,
# then Indonesian Horror as an additional source.
try:
    import free_mode  # noqa: F401
except Exception:
    pass

try:
    import cache_patch  # noqa: F401
except Exception:
    pass

try:
    import indonesia_patch  # noqa: F401
except Exception:
    pass
