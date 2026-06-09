import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

PRODUCTS_FILE = DATA_DIR / "products.json"
SEEN_LINKS_FILE = DATA_DIR / "seen_links.json"
DELETED_LINKS_FILE = DATA_DIR / "deleted_links.json"
SENT_LINKS_FILE = DATA_DIR / "sent_links.json"
CUSTOM_POSTS_FILE = DATA_DIR / "custom_posts.json"


def ensure_data_files():
    DATA_DIR.mkdir(exist_ok=True)

    files = [
        PRODUCTS_FILE,
        SEEN_LINKS_FILE,
        DELETED_LINKS_FILE,
        SENT_LINKS_FILE,
        CUSTOM_POSTS_FILE,
    ]

    for file_path in files:
        if not file_path.exists():
            save_json(file_path, [])


def load_json(file_path, default_value):
    if not file_path.exists():
        return default_value

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            return json.load(file)
    except json.JSONDecodeError:
        return default_value


def save_json(file_path, data):
    DATA_DIR.mkdir(exist_ok=True)

    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)


def load_products():
    ensure_data_files()
    return load_json(PRODUCTS_FILE, [])


def save_products(products):
    ensure_data_files()
    save_json(PRODUCTS_FILE, products)


def load_seen_links():
    ensure_data_files()
    return load_json(SEEN_LINKS_FILE, [])


def save_seen_links(links):
    ensure_data_files()
    save_json(SEEN_LINKS_FILE, links)


def load_deleted_links():
    ensure_data_files()
    return load_json(DELETED_LINKS_FILE, [])


def save_deleted_links(links):
    ensure_data_files()
    save_json(DELETED_LINKS_FILE, links)


def load_sent_links():
    ensure_data_files()
    return load_json(SENT_LINKS_FILE, [])


def save_sent_links(links):
    ensure_data_files()
    save_json(SENT_LINKS_FILE, links)


def load_custom_posts():
    ensure_data_files()
    return load_json(CUSTOM_POSTS_FILE, [])


def save_custom_posts(posts):
    ensure_data_files()
    save_json(CUSTOM_POSTS_FILE, posts)


def is_seen_link(url):
    seen_links = load_seen_links()
    return url in seen_links


def mark_link_as_seen(url):
    if not url:
        return

    seen_links = load_seen_links()

    if url not in seen_links:
        seen_links.append(url)
        save_seen_links(seen_links)


def is_deleted_link(url):
    deleted_links = load_deleted_links()
    return url in deleted_links


def mark_link_as_deleted(url):
    if not url:
        return

    deleted_links = load_deleted_links()

    if url not in deleted_links:
        deleted_links.append(url)
        save_deleted_links(deleted_links)

    mark_link_as_seen(url)


def is_sent_link(url):
    sent_links = load_sent_links()
    return url in sent_links


def mark_link_as_sent(url):
    if not url:
        return

    sent_links = load_sent_links()

    if url not in sent_links:
        sent_links.append(url)
        save_sent_links(sent_links)

    mark_link_as_seen(url)


def is_blocked_link(url):
    """
    Якщо товар видалений або вже відправлений,
    його більше не потрібно додавати при парсингу.
    """
    return is_deleted_link(url) or is_sent_link(url)