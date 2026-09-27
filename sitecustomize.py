import logging

# Prevent HTTP client request URLs from being written to application logs.
# Telegram Bot API URLs contain the bot token in the path, so INFO-level
# request logging is intentionally disabled.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Keep known upstream cloud-block responses from being reported as bot errors.
try:
    import free_mode  # noqa: F401
except Exception:
    pass

# Read HollyMovieHD public listing metadata from the free GitHub cache refreshed
# by GitHub Actions. No paid proxy or database is required.
try:
    import cache_patch  # noqa: F401
except Exception:
    pass
