import re
import json
import html
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse
import html
import requests
from bs4 import BeautifulSoup

from parser.storage import is_seen_link, is_blocked_link

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ============================================================
# Базові функції
# ============================================================

def normalize_url(url: str) -> str:
    url = html.unescape((url or "").strip())
    parsed = urlparse(url)
    return parsed._replace(fragment="").geturl()


def clean_text(text: str) -> str:
    if not text:
        return ""

    text = html.unescape(str(text))
    text = text.replace("*", " ")
    text = " ".join(text.split())

    return text.strip()


def get_first_src_from_srcset(srcset: str) -> str:
    if not srcset:
        return ""

    first = srcset.split(",")[0].strip()
    return first.split(" ")[0].strip()


def unique_list(items: list[str]) -> list[str]:
    result = []

    for item in items:
        if item and item not in result:
            result.append(item)

    return result


def fetch_html(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def remove_query_from_url(url: str) -> str:
    parsed = urlparse(url)

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            "",
            "",
            "",
        )
    )


def set_page_number(url: str, page_number: int) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    query["p"] = [str(page_number)]

    new_query = urlencode(query, doseq=True)

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment,
        )
    )


def get_page_size_from_url(url: str) -> int:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    try:
        return int(query.get("n", ["24"])[0])
    except Exception:
        return 24


def extract_prices_from_text(text: str) -> dict:
    text = clean_text(text)

    prices = re.findall(r"€\s?\d+[.,]\d{2}", text)
    prices = [price.replace("€ ", "€") for price in prices]

    new_price = ""
    old_price = ""

    if len(prices) >= 2:
        new_price = prices[0]
        old_price = prices[1]
    elif len(prices) == 1:
        new_price = prices[0]

    discount = ""

    discount_match = re.search(r"[-−]?\s?(\d+)\s?%", text)
    if discount_match:
        discount = f"-{discount_match.group(1)}%"

    return {
        "new_price": new_price,
        "old_price": old_price,
        "discount": discount,
    }


# ============================================================
# Колір з HTML Fundis
# ============================================================

def parse_selected_color_name_from_html(html_text: str) -> str:
    """
    Дістаємо вибраний колір із HTML Fundis.

    Працює з:
    - color
    - colour
    - Farbe
    - selected value після двокрапки: Farbe: chalk violet
    - checked input
    - перший доступний НЕ disabled input
    """

    html_text = html.unescape(html_text)
    soup = BeautifulSoup(html_text, "html.parser")

    color_group_names = [
        "color",
        "colour",
        "farbe",
    ]

    for group in soup.select(".product--configurator .variant--group"):
        group_name_tag = group.select_one(".variant--name strong")

        if not group_name_tag:
            continue

        group_name = clean_text(group_name_tag.get_text(" ")).lower()

        if group_name not in color_group_names:
            continue

        variant_name_tag = group.select_one(".variant--name")

        # 1. Найкраще: беремо вибране значення з тексту групи
        # Наприклад:
        # Farbe: chalk violet
        # color: charcoal/grey
        if variant_name_tag:
            variant_text = clean_text(variant_name_tag.get_text(" "))

            if ":" in variant_text:
                selected_color = clean_text(variant_text.split(":", 1)[1])

                if selected_color:
                    print("Колір знайдено через variant--name:", selected_color)
                    return selected_color

        # 2. Якщо є checked input — беремо його
        checked_input = group.select_one("input.option--input[checked]")

        if checked_input and checked_input.get("title"):
            selected_color = clean_text(checked_input.get("title"))

            if selected_color:
                print("Колір знайдено через checked input:", selected_color)
                return selected_color

        # 3. Якщо checked немає — беремо перший НЕ disabled input
        for input_tag in group.select("input.option--input"):
            if input_tag.has_attr("disabled"):
                continue

            title = clean_text(input_tag.get("title", ""))

            if title:
                print("Колір знайдено через перший доступний input:", title)
                return title

        # 4. Запасний варіант — перший НЕ disabled label
        for option in group.select(".variant--option"):
            option_classes = option.get("class", [])
            label_tag = option.select_one(".option--label")

            if "is--disabled" in option_classes:
                continue

            if option.select_one("input[disabled]"):
                continue

            if label_tag:
                label_text = clean_text(label_tag.get_text(" "))

                if label_text:
                    print("Колір знайдено через доступний label:", label_text)
                    return label_text

    print("Колір у HTML не знайдено")
    return ""


def fetch_detail_html_with_fallback(product_url: str) -> dict:
    """
    Fundis іноді по sale-посиланню ?c=193 віддає HTML,
    де configurator є, але вибраний color не видно.

    Тому НЕ зупиняємося, якщо configurator є без color.
    Пробуємо:
    1. оригінальне посилання;
    2. посилання без query-параметрів.
    """

    product_url = normalize_url(product_url)

    urls_to_try = [
        product_url,
        remove_query_from_url(product_url),
    ]

    checked_urls = []
    fallback_result = None

    for url in urls_to_try:
        if not url or url in checked_urls:
            continue

        checked_urls.append(url)

        print("Пробуємо завантажити детальну сторінку:", url)

        html_text = fetch_html(url)

        with open("debug_last_tried_detail_page.html", "w", encoding="utf-8") as file:
            file.write(html_text)

        color_name = parse_selected_color_name_from_html(html_text)

        if color_name:
            print("Сторінка містить колір:", color_name)

            return {
                "url": url,
                "html": html_text,
                "color_name": color_name,
            }

        if "product--configurator" in html_text:
            print("Конфігуратор є, але color не знайдено. Пробуємо наступний URL...")

            if fallback_result is None:
                fallback_result = {
                    "url": url,
                    "html": html_text,
                    "color_name": "",
                }

            continue

        print("На цій сторінці не знайдено нормальний configurator. Пробуємо наступний URL...")

        if fallback_result is None:
            fallback_result = {
                "url": url,
                "html": html_text,
                "color_name": "",
            }

    if fallback_result:
        return fallback_result

    html_text = fetch_html(product_url)

    return {
        "url": product_url,
        "html": html_text,
        "color_name": "",
    }


# ============================================================
# Парсинг категорії
# ============================================================

def parse_variant_scripts(product_box) -> dict:
    variants = {}

    scripts = product_box.select("script")

    for script in scripts:
        script_text = script.get_text(" ", strip=True)

        matches = re.findall(
            r"mlvpProductData\['([^']+)'\]\s*=\s*(\{.*?\});",
            script_text,
            flags=re.DOTALL,
        )

        for order_number, json_text in matches:
            try:
                data = json.loads(json_text)
                variants[order_number] = data
            except Exception:
                continue

    return variants


def parse_product_box(product_box, base_url: str, category_type: str) -> dict | None:
    title_link = product_box.select_one("a.product--title")

    if not title_link:
        return None

    url = normalize_url(urljoin(base_url, title_link.get("href", "")))

    brand_tag = title_link.select_one("span")
    brand = clean_text(brand_tag.get_text()) if brand_tag else ""

    full_title = clean_text(title_link.get("title") or title_link.get_text(" "))
    title = full_title

    article = product_box.get("data-ordernumber", "")

    price_area = product_box.select_one(".product--price-info") or product_box
    price_data = extract_prices_from_text(price_area.get_text(" "))

    new_price = price_data["new_price"]
    old_price = price_data["old_price"]

    discount_tag = product_box.select_one(".badge--discount")
    discount = clean_text(discount_tag.get_text()) if discount_tag else price_data["discount"]

    image_tag = product_box.select_one(".product--image img")
    main_image = ""

    if image_tag:
        main_image = (
                image_tag.get("srcset")
                or image_tag.get("data-srcset")
                or image_tag.get("src")
                or ""
        )

        main_image = get_first_src_from_srcset(main_image)

    colors = []
    images = []

    variant_data = parse_variant_scripts(product_box)
    variant_buttons = product_box.select("a.variant-button")

    for button in variant_buttons:
        color_name = clean_text(button.get("title") or "")

        order_number = button.get("data-ordernumber", "")
        variant_url = normalize_url(urljoin(base_url, button.get("href", "")))

        img = button.select_one("img")
        color_image = ""

        if img:
            color_image = (
                    img.get("srcset")
                    or img.get("data-srcset")
                    or img.get("src")
                    or ""
            )

            color_image = get_first_src_from_srcset(color_image)

        script_data = variant_data.get(order_number, {})

        if script_data:
            color_name = clean_text(script_data.get("name", color_name))

            variant_url = normalize_url(
                urljoin(base_url, script_data.get("url", variant_url))
            )

        price = ""

        if script_data.get("price") is not None:
            try:
                price = f"€{float(script_data.get('price')):.2f}"
            except Exception:
                price = ""

        color_item = {
            "name": color_name,
            "article": order_number,
            "url": variant_url,
            "image": color_image,
            "price": price,
            "available": script_data.get("is_available", True),
            "sizes": [],
        }

        colors.append(color_item)

        if color_image and color_image not in images:
            images.append(color_image)

    if main_image and main_image not in images:
        images.insert(0, main_image)

    if not colors:
        colors.append(
            {
                "name": "",
                "article": article,
                "url": url,
                "image": main_image,
                "price": new_price,
                "available": True,
                "sizes": [],
            }
        )

    return {
        "url": url,
        "category_type": category_type,
        "title": title,
        "brand": brand,
        "article": article,
        "old_price": old_price,
        "new_price": new_price,
        "discount": discount,
        "colors": colors,
        "images": images,
        "status": "Чернетка",
        "sent": False,
        "telegram_message_id": None,
    }


def parse_products_from_html(html_text: str, page_url: str, category_type: str) -> list[dict]:
    soup = BeautifulSoup(html_text, "html.parser")
    product_boxes = soup.select(".product--box")

    products = []

    for product_box in product_boxes:
        product = parse_product_box(product_box, page_url, category_type)

        if product:
            products.append(product)

    return products


def parse_category(start_url: str, category_type: str, on_page_products=None) -> dict:
    start_url = normalize_url(start_url)

    all_new_products = []
    seen_urls_in_current_run = set()

    pages_parsed = 0
    products_found = 0
    skipped_count = 0

    max_pages = 300
    page_size = get_page_size_from_url(start_url)

    for page_number in range(1, max_pages + 1):
        page_url = set_page_number(start_url, page_number)

        print(f"Парсимо сторінку: {page_url}")

        try:
            html_text = fetch_html(page_url)
        except requests.HTTPError as error:
            if error.response is not None and error.response.status_code == 404:
                print("Сторінки закінчилися. Отримали 404, зупиняємо парсинг.")
                break

            raise error

        page_products = parse_products_from_html(html_text, page_url, category_type)

        print(f"Знайдено товарів на сторінці: {len(page_products)}")

        if not page_products:
            print("Товарів на сторінці немає. Зупиняємо парсинг.")
            break

        pages_parsed += 1
        products_found += len(page_products)

        page_new_products = []

        for product in page_products:
            product_url = product["url"]

            if product_url in seen_urls_in_current_run:
                continue

            seen_urls_in_current_run.add(product_url)

            if is_seen_link(product_url) or is_blocked_link(product_url):
                skipped_count += 1
                continue

            page_new_products.append(product)

        if page_new_products:
            all_new_products.extend(page_new_products)

            if on_page_products:
                on_page_products(page_number, page_url, page_new_products)

        print(f"Нових товарів на сторінці: {len(page_new_products)}")

        if len(page_products) < page_size:
            print("Це остання сторінка, бо товарів менше ніж розмір сторінки.")
            break

    return {
        "start_url": start_url,
        "category_type": category_type,
        "pages_parsed": pages_parsed,
        "products_found": products_found,
        "new_products": all_new_products,
        "new_count": len(all_new_products),
        "skipped_count": skipped_count,
    }


# ============================================================
# Детальний парсинг товару
# ============================================================

def parse_detail_images(soup) -> list[str]:
    images = []

    for image_element in soup.select(".product--image-container .image--element"):
        for attr in ["data-img-large", "data-img-original", "data-img-small"]:
            image_url = image_element.get(attr)

            if image_url:
                images.append(image_url)

    for img in soup.select(".product--image-container img"):
        image_url = (
                img.get("srcset")
                or img.get("data-srcset")
                or img.get("src")
                or ""
        )

        image_url = get_first_src_from_srcset(image_url)

        if image_url and not image_url.startswith("data:image"):
            images.append(image_url)

    return unique_list(images)


def parse_detail_price(soup) -> dict:
    price_area = soup.select_one(".product--price")

    if price_area:
        price_text = price_area.get_text(" ")
    else:
        price_text = soup.get_text(" ")

    price_data = extract_prices_from_text(price_text)

    discount_tag = soup.select_one(".badge--discount")
    if discount_tag:
        price_data["discount"] = clean_text(discount_tag.get_text(" "))

    return price_data


def parse_detail_title_brand(soup) -> dict:
    title_tag = soup.select_one("h1.product--title")
    if not title_tag:
        title_tag = soup.select_one("[itemprop='name']")
    if not title_tag:
        title_tag = soup.select_one("h1")

    title = clean_text(title_tag.get_text(" ")) if title_tag else ""

    brand = ""

    brand_meta = soup.select_one('[itemprop="brand"] meta[itemprop="name"]')
    if brand_meta and brand_meta.get("content"):
        brand = clean_text(brand_meta.get("content"))

    if not brand:
        brand_img = soup.select_one(".product--supplier img")
        if brand_img and brand_img.get("alt"):
            brand = clean_text(brand_img.get("alt"))

    if not brand:
        brand_link = soup.select_one(".product--supplier a")
        if brand_link:
            brand = clean_text(brand_link.get("title") or brand_link.get_text(" "))

    return {
        "title": title,
        "brand": brand,
    }


def parse_detail_article(soup) -> str:
    s_add = soup.select_one('input[name="sAdd"]')

    if s_add and s_add.get("value"):
        return clean_text(s_add.get("value"))

    order_number_tag = soup.select_one(".entry--sku .entry--content")

    if order_number_tag:
        return clean_text(order_number_tag.get_text())

    return ""


def parse_detail_stock(soup) -> dict:
    quantity_input = soup.select_one("#sQuantity")
    buy_button = soup.select_one("#buyboxButton")

    max_quantity = ""

    if quantity_input:
        max_quantity = quantity_input.get("max", "")

    is_buyable = False

    if buy_button:
        classes = buy_button.get("class", [])
        disabled = buy_button.has_attr("disabled") or buy_button.get("aria-disabled") == "true"
        is_buyable = not disabled and "is--disabled" not in classes

    delivery_texts = []

    for delivery_tag in soup.select(".product--delivery .delivery--text"):
        text = clean_text(delivery_tag.get_text(" "))
        if text:
            delivery_texts.append(text)

    return {
        "is_buyable": is_buyable,
        "max_quantity": max_quantity,
        "delivery_text": " · ".join(delivery_texts),
    }


def parse_available_options_for_selected_color(soup) -> list[dict]:
    groups = []

    color_group_names = [
        "color",
        "colour",
        "farbe",
    ]

    for group in soup.select(".product--configurator .variant--group"):
        group_name_tag = group.select_one(".variant--name strong")
        group_name = clean_text(group_name_tag.get_text()) if group_name_tag else ""

        if not group_name:
            continue

        normalized_group_name = group_name.strip().lower()

        # Колір не додаємо в option_groups, бо він окремо в color.name
        if normalized_group_name in color_group_names:
            continue

        available_values = []
        all_values = []

        for option in group.select(".variant--option"):
            input_tag = option.select_one(".option--input")
            label_tag = option.select_one(".option--label")

            option_name = ""

            if input_tag and input_tag.get("title"):
                option_name = clean_text(input_tag.get("title"))
            elif label_tag:
                label_text = label_tag.get_text(" ")
                label_text = re.sub(
                    r"sale|notAvailable",
                    "",
                    label_text,
                    flags=re.IGNORECASE
                )
                option_name = clean_text(label_text)

            if not option_name:
                continue

            option_classes = option.get("class", [])
            label_classes = label_tag.get("class", []) if label_tag else []

            is_disabled = (
                    "is--disabled" in option_classes
                    or "variant--option--disabled" in option_classes
                    or "is--disabled" in label_classes
                    or option.select_one(".variant-badge--notAvailable") is not None
                    or (input_tag is not None and input_tag.has_attr("disabled"))
            )

            item = {
                "name": option_name,
                "available": not is_disabled,
            }

            all_values.append(item)

            if not is_disabled:
                available_values.append(option_name)

        groups.append(
            {
                "name": normalize_variant_group_name(group_name),
                "available_values": available_values,
                "all_values": all_values,
            }
        )

    return groups


def parse_color_variants_from_listing_product(product: dict) -> list[dict]:
    color_variants = []

    for color in product.get("colors", []):
        color_url = color.get("url") or product.get("url")

        if not color_url:
            continue

        color_variants.append(
            {
                "name": clean_text(color.get("name", "")),
                "url": normalize_url(color_url),
                "preview_image": color.get("image", ""),
                "article": color.get("article", ""),
                "is_default": False,
            }
        )

    if not color_variants:
        first_image = ""

        if product.get("images") and len(product["images"]) > 0:
            first_image = product["images"][0]

        color_variants.append(
            {
                "name": "",
                "url": normalize_url(product.get("url", "")),
                "preview_image": first_image,
                "article": product.get("article", ""),
                "is_default": False,
            }
        )

    return color_variants


def parse_selected_color_detail(
        color_name: str,
        color_url: str,
        fallback_image: str = "",
        is_default: bool = False,
) -> dict:
    detail_page = fetch_detail_html_with_fallback(color_url)

    html_text = detail_page["html"]
    final_color_url = detail_page["url"]

    with open("debug_detail_page.html", "w", encoding="utf-8") as file:
        file.write(html_text)

    soup = BeautifulSoup(html_text, "html.parser")

    images = parse_detail_images(soup)
    prices = parse_detail_price(soup)
    article = parse_detail_article(soup)
    stock = parse_detail_stock(soup)

    real_color_name = clean_text(color_name)

    print("Колір із категорії:", real_color_name)

    if not real_color_name or real_color_name.lower() == "default":
        real_color_name = detail_page.get("color_name", "")

    if not real_color_name:
        real_color_name = parse_selected_color_name_from_html(html_text)

    if not real_color_name:
        real_color_name = "Колір не вказано"

    print("Фінальний колір:", real_color_name)

    if images:
        color_main_image = images[0]
    else:
        color_main_image = fallback_image

    option_groups = parse_available_options_for_selected_color(soup)

    return {
        "name": real_color_name,
        "url": final_color_url,
        "article": article,
        "main_image": color_main_image,
        "images": images,
        "old_price": prices["old_price"],
        "new_price": prices["new_price"],
        "discount": prices["discount"],
        "stock": stock,
        "option_groups": option_groups,
        "is_default": False,
    }


def parse_product_detail(product_url: str, category_type: str = "", base_product: dict | None = None) -> dict:
    product_url = normalize_url(product_url)

    detail_page = fetch_detail_html_with_fallback(product_url)

    html_text = detail_page["html"]
    product_url = detail_page["url"]

    with open("debug_product_main_page.html", "w", encoding="utf-8") as file:
        file.write(html_text)

    soup = BeautifulSoup(html_text, "html.parser")

    title_brand = parse_detail_title_brand(soup)
    prices = parse_detail_price(soup)
    images = parse_detail_images(soup)
    article = parse_detail_article(soup)
    stock = parse_detail_stock(soup)

    if base_product:
        color_variants = parse_color_variants_from_listing_product(base_product)
    else:
        color_variants = [
            {
                "name": detail_page.get("color_name", ""),
                "url": product_url,
                "preview_image": images[0] if images else "",
                "article": article,
                "is_default": False,
            }
        ]

    color_details = []

    for color in color_variants:
        print(f"Парсимо колір: {color.get('name', '')} — {color['url']}")

        try:
            color_detail = parse_selected_color_detail(
                color_name=color.get("name", ""),
                color_url=color["url"],
                fallback_image=color.get("preview_image", ""),
                is_default=color.get("is_default", False),
            )

            color_details.append(color_detail)

        except Exception as error:
            print(f"Не вдалося спарсити колір {color.get('name', '')}: {error}")

    gallery_images = []

    for color in color_details:
        if color.get("main_image"):
            gallery_images.append(color["main_image"])

    gallery_images = unique_list(gallery_images)

    telegram_text = build_telegram_text_by_colors(
        category_type=category_type,
        title=title_brand["title"],
        brand=title_brand["brand"],
        article=article,
        color_details=color_details,
        url=product_url,
    )

    return {
        "url": product_url,
        "category_type": category_type,
        "title": title_brand["title"],
        "brand": title_brand["brand"],
        "article": article,
        "old_price": prices["old_price"],
        "new_price": prices["new_price"],
        "discount": prices["discount"],
        "images": gallery_images,
        "stock": stock,
        "color_details": color_details,
        "telegram_text": telegram_text,
        "detail_parsed": True,
    }


# ============================================================
# Telegram
# ============================================================

def build_telegram_text_by_colors(
    category_type: str,
    title: str,
    brand: str,
    article: str,
    color_details: list[dict],
    url: str,
) -> str:
    import os

    personal_username = os.getenv("TELEGRAM_PERSONAL_USERNAME", "")
    personal_username = personal_username.replace("@", "").strip()

    if personal_username:
        order_link = f"https://t.me/{personal_username}"
    else:
        order_link = url

    category_line = category_type.upper() if category_type else "SALE"

    max_discount = ""

    for color in color_details:
        if color.get("discount"):
            max_discount = color["discount"]
            break

    if max_discount:
        header = f"🔥 {category_line} {max_discount} 🔥"
    else:
        header = f"🔥 {category_line} 🔥"

    lines = [
        html.escape(header),
        "",
        html.escape(title),
        "",
    ]

    meta_parts = []

    if brand:
        meta_parts.append(f"🏷 {html.escape(brand)}")

    if meta_parts:
        lines.append(" · ".join(meta_parts))
        lines.append("")

    lines.append("✅ В наявності:")

    for color in color_details:
        color_name = clean_text(color.get("name", ""))

        if not color_name or color_name.lower() == "default":
            color_name = "Колір не вказано"

        option_parts = []

        for group in color.get("option_groups", []):
            group_name = clean_text(group.get("name", ""))

            available_values = [
                clean_text(value)
                for value in group.get("available_values", [])
                if clean_text(value)
            ]

            if available_values:
                escaped_values = [
                    html.escape(value)
                    for value in available_values
                ]

                option_parts.append(
                    f"{html.escape(group_name)}: {', '.join(escaped_values)}"
                )

        if option_parts:
            lines.append(
                f"• {html.escape(color_name)} — {'; '.join(option_parts)}"
            )
        else:
            lines.append(f"• {html.escape(color_name)}")

        price_parts = []

        old_price = clean_text(color.get("old_price", ""))
        new_price = clean_text(color.get("new_price", ""))
        discount = clean_text(color.get("discount", ""))

        if old_price:
            price_parts.append(f"стара: {html.escape(old_price)}")

        if new_price:
            price_parts.append(f"нова: {html.escape(new_price)}")

        if discount:
            price_parts.append(f"знижка: {html.escape(discount)}")

        if price_parts:
            lines.append(f"  💶 {' · '.join(price_parts)}")

    lines.extend(
        [
            "",
            f'<a href="{html.escape(order_link)}">🛒 Написати для замовлення</a>',
        ]
    )

    return "\n".join(lines)


def normalize_variant_group_name(group_name: str) -> str:
    group_name_clean = clean_text(group_name)
    group_name_lower = group_name_clean.lower()

    translations = {
        "größe": "size",
        "groesse": "size",
        "size": "size",
        "lenght": "lenght",
        "length": "length",
        "width": "width",
        "height": "height",
        "form": "form",
    }

    return translations.get(group_name_lower, group_name_clean)

def send_custom_post_to_telegram(text: str, photo_urls: list[str]) -> dict:
    """
    Відправка ручного поста:
    - фото посиланнями;
    - текст.
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