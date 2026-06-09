import os
import json
import requests
from dotenv import load_dotenv


load_dotenv()


TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")


def get_telegram_api_url(method_name: str) -> str:
    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method_name}"


def check_telegram_settings():
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("Не знайдено TELEGRAM_BOT_TOKEN у файлі .env")

    if not TELEGRAM_CHANNEL_ID:
        raise ValueError("Не знайдено TELEGRAM_CHANNEL_ID у файлі .env")


def send_telegram_message(text: str) -> dict:
    check_telegram_settings()

    response = requests.post(
        get_telegram_api_url("sendMessage"),
        json={
            "chat_id": TELEGRAM_CHANNEL_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )

    result = response.json()

    if not result.get("ok"):
        raise Exception(f"Telegram sendMessage error: {result}")

    return result


def send_telegram_photo(photo_url: str) -> dict:
    check_telegram_settings()

    response = requests.post(
        get_telegram_api_url("sendPhoto"),
        json={
            "chat_id": TELEGRAM_CHANNEL_ID,
            "photo": photo_url,
        },
        timeout=30,
    )

    result = response.json()

    if not result.get("ok"):
        raise Exception(f"Telegram sendPhoto error: {result}")

    return result


def send_telegram_media_group(photo_urls: list[str]) -> dict:
    check_telegram_settings()

    media = []

    for photo_url in photo_urls[:10]:
        media.append(
            {
                "type": "photo",
                "media": photo_url,
            }
        )

    if not media:
        return {}

    response = requests.post(
        get_telegram_api_url("sendMediaGroup"),
        data={
            "chat_id": TELEGRAM_CHANNEL_ID,
            "media": json.dumps(media),
        },
        timeout=30,
    )

    result = response.json()

    if not result.get("ok"):
        raise Exception(f"Telegram sendMediaGroup error: {result}")

    return result


def send_product_to_telegram(product: dict) -> dict:
    """
    Відправка товару в Telegram:
    1. фото товару;
    2. текст товару.
    """

    text = product.get("telegram_text", "")
    photo_urls = product.get("images", [])

    photo_urls = [
        photo_url.strip()
        for photo_url in photo_urls
        if photo_url and photo_url.strip()
    ]

    sent_photos_result = None

    if len(photo_urls) == 1:
        sent_photos_result = send_telegram_photo(photo_urls[0])
    elif len(photo_urls) >= 2:
        sent_photos_result = send_telegram_media_group(photo_urls[:10])

    sent_message_result = send_telegram_message(text)

    return {
        "photos": sent_photos_result,
        "message": sent_message_result,
    }


def send_custom_post_to_telegram(text: str, photo_urls: list[str]) -> dict:
    """
    Відправка ручного поста:
    1. фото за посиланнями;
    2. текст поста.
    """

    photo_urls = [
        photo_url.strip()
        for photo_url in photo_urls
        if photo_url and photo_url.strip()
    ]

    sent_photos_result = None

    if len(photo_urls) == 1:
        sent_photos_result = send_telegram_photo(photo_urls[0])
    elif len(photo_urls) >= 2:
        sent_photos_result = send_telegram_media_group(photo_urls[:10])

    sent_message_result = send_telegram_message(text)

    return {
        "photos": sent_photos_result,
        "message": sent_message_result,
    }