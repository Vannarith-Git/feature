import logging

# Never write Telegram Bot API request URLs (which contain the bot token) to logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Runtime patches. The final today-only gate is loaded last so every source is
# subject to the same strict publication-date rule.
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
    import khdiamond_rss_patch  # noqa: F401
except Exception:
    pass

try:
    import today_only_patch  # noqa: F401
except Exception:
    pass
