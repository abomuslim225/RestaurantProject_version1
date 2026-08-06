# apps/utils.py
import httpx
from django.conf import settings

def set_webhook(bot, raw_token: str, request) -> bool:
    try:
        domain = getattr(settings, 'WEBHOOK_BASE_URL', None) or request.build_absolute_uri('/').rstrip('/')
        webhook_url = f"{domain}/api/v1/telegram/webhook/{bot.id}/"
        resp = httpx.post(
            f"https://api.telegram.org/bot{raw_token}/setWebhook",
            json={"url": webhook_url},
            timeout=8,
        )
        ok = resp.json().get('ok', False)
        bot.webhook_set = ok
        bot.save(update_fields=['webhook_set'])
        return ok
    except Exception:
        return False