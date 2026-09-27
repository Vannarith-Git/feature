import logging

# Never write Telegram Bot API request URLs (which contain the bot token) to logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Load runtime patches in order: graceful source handling, Holly free cache,
# Indonesian Horror, Anime + Chinese sources, then the final strict date gate.
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

try:
    import extra_sources_patch  # noqa: F401
except Exception:
    pass

try:
    import today_only_patch  # noqa: F401
except Exception:
    pass
