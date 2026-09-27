import logging

# Never write Telegram Bot API request URLs (which contain the bot token) to logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Runtime patches. Source adapters load first; the persistent incremental
# monitor loads last so every source uses the same dedupe/baseline rules.
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
    import incremental_patch  # noqa: F401
except Exception:
    pass
