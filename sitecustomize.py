import logging

# Prevent HTTP client request URLs from being written to application logs.
# Telegram Bot API URLs contain the bot token in the path, so INFO-level
# request logging is intentionally disabled.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Apply the HollyMovieHD public-mirror fallback when the app runtime has all
# dependencies available. During build-time Python invocations this may not be
# importable yet, so failures are intentionally ignored.
try:
    import holly_fallback  # noqa: F401
except Exception:
    pass
