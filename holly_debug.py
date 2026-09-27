import logging

import app as core
import holly_fallback

log = logging.getLogger('movie-bot')
_original_holly = core.Scraper.holly


async def holly_with_preview_debug(self):
    try:
        return await _original_holly(self)
    except Exception:
        try:
            soup = await self.soup(holly_fallback.TELEGRAM_PREVIEW)
            messages = soup.select('.tgme_widget_message_wrap, .tgme_widget_message')
            samples = []
            for message in messages[:5]:
                text_node = message.select_one('.tgme_widget_message_text')
                text = text_node.get_text(' | ', strip=True) if text_node else core.node_text(message)
                links = [str(a.get('href') or '') for a in message.find_all('a', href=True)][:8]
                samples.append({'text': text[:220], 'links': links})
            log.info('Holly official Telegram preview: messages=%s samples=%s', len(messages), samples)
        except Exception as debug_error:
            log.info('Holly Telegram preview debug failed: %s', type(debug_error).__name__)
        raise


core.Scraper.holly = holly_with_preview_debug
