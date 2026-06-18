import os
import re
import html
import time
import requests

from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse

from parser.storage import is_seen_link, is_blocked_link

BASE_URL = "https://www.fundis-equestrian.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
}


# ============================================================
# BASIC HELPERS
# ============================================================

def clean_text(value: str) -> str:
    if value is None:
        return ""

    value = html.unescape(str(value))
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def normalize_url(url: str) -> str:
    if not url:
        return ""

    url = html.unescape(url.strip())

    if url.startswith("//"):
        return "https:" + url

    if url.startswith("/"):
        return urljoin(BASE_URL, url)

    return url


def remove_query_from_url(url: str) -> str:
    parsed_url = urlparse(url)

    return urlunparse(
        (
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            "",
            "",
            "",
        )
    )


def unique_list(values: list[str]) -> list[str]:
    result = []
    seen = set()

    for value in values:
        if not value:
            continue

        if value not in seen:
            seen.add(value)
            result.append(value)

    return result


def get_first_url_from_srcset(srcset: str) -> str:
    if not srcset:
        return ""

    first_part = srcset.split(",")[0].strip()
    first_url = first_part.split(" ")[0].strip()

    return normalize_url(first_url)


def image_to_large_url(image_url: str) -> str:
    """
    Пробуємо замінити маленькі thumbnail-фото на більші.
    """

    if not image_url:
        return ""

    image_url = normalize_url(image_url)

    replacements = [
        "_200x200@2x",
        "_200x200",
        "_600x600@2x",
        "_600x600",
    ]

    for replacement in replacements:
        if replacement in image_url:
            image_url = image_url.replace(replacement, "_1280x1280")

    image_url = image_url.replace("?class=thumbnail", "")

    return image_url


def extract_image_from_tag(tag) -> str:
    if not tag:
        return ""

    for attr in [
        "data-img-large",
        "data-img-original",
        "data-img-small",
        "href",
        "src",
        "data-src",
    ]:
        value = tag.get(attr)

        if not value:
            continue

        image_url = normalize_url(value)

        if image_url and not image_url.startswith("data:image"):
            return image_to_large_url(image_url)

    for attr in [
        "srcset",
        "data-srcset",
    ]:
        value = tag.get(attr)

        if not value:
            continue

        image_url = get_first_url_from_srcset(value)

        if image_url and not image_url.startswith("data:image"):
            return image_to_large_url(image_url)

    img_tag = tag.select_one("img")

    if img_tag:
        return extract_image_from_tag(img_tag)

    return ""


def extract_first_image(container) -> str:
    if not container:
        return ""

    image_element = container.select_one("[data-img-large], [data-img-original]")

    if image_element:
        image_url = extract_image_from_tag(image_element)

        if image_url:
            return image_url

    image_tag = container.select_one("img")

    if image_tag:
        image_url = extract_image_from_tag(image_tag)

        if image_url:
            return image_url

    return ""


def clean_price(value: str) -> str:
    value = clean_text(value)
    value = html.unescape(value)

    remove_words = [
        "Originally:",
        "Ursprünglich:",
        "RRP:",
        "inkl. MwSt.",
        "incl. VAT",
        "*",
    ]

    for word in remove_words:
        value = value.replace(word, "")

    value = value.replace("€ ", "€")
    value = value.replace("€&nbsp;", "€")
    value = value.replace("&nbsp;", " ")

    value = re.sub(r"\s+", " ", value)

    return value.strip()


def fetch_html(url: str) -> str:
    url = normalize_url(url)

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    if response.status_code == 404:
        raise Exception("404")

    response.raise_for_status()

    return response.text


def build_page_url(category_url: str, page_number: int) -> str:
    """
    FUNDIS не всегда удобно парсить через кнопку next.
    Поэтому вручную меняем только p=1, p=2, p=3...
    Все фильтры сохраняются:
    o=1, n=24, s=176|192|...
    """

    parsed_url = urlparse(category_url)
    query_params = parse_qs(parsed_url.query)

    query_params["p"] = [str(page_number)]

    new_query = urlencode(query_params, doseq=True)

    new_url = urlunparse(
        (
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            parsed_url.params,
            new_query,
            parsed_url.fragment,
        )
    )

    return new_url


# ============================================================
# CATEGORY PARSER
# ============================================================

def parse_product_title_and_brand(product_box) -> dict:
    title_tag = product_box.select_one(".product--title")

    if not title_tag:
        return {
            "brand": "",
            "title": "",
        }

    brand = ""

    brand_tag = title_tag.select_one("span")

    if brand_tag:
        brand = clean_text(brand_tag.get_text(" "))

    title_attr = clean_text(title_tag.get("title", ""))

    full_text = clean_text(title_tag.get_text(" "))

    if brand:
        title = full_text.replace(brand, "", 1).strip()
    else:
        title = full_text

    if not title and title_attr:
        title = title_attr

        if brand:
            title = title.replace(brand, "", 1).strip()

    return {
        "brand": brand,
        "title": title,
    }


def parse_product_box(product_box, category_type: str) -> dict:
    title_tag = product_box.select_one(".product--title")

    if not title_tag:
        return {}

    product_url = normalize_url(title_tag.get("href", ""))

    if not product_url:
        image_link = product_box.select_one("a.product--image")

        if image_link:
            product_url = normalize_url(image_link.get("href", ""))

    if not product_url:
        return {}

    title_brand = parse_product_title_and_brand(product_box)

    title = title_brand["title"]
    brand = title_brand["brand"]

    if not title:
        title = clean_text(title_tag.get("title", ""))

    article = clean_text(product_box.get("data-ordernumber", ""))

    image_url = ""

    image_container = product_box.select_one(".product--image, .fundis-product-box-img")

    if image_container:
        image_url = extract_first_image(image_container)

    if not image_url:
        image_url = extract_first_image(product_box)

    new_price = ""
    old_price = ""

    new_price_tag = product_box.select_one(".price--default")

    if new_price_tag:
        new_price = clean_price(new_price_tag.get_text(" "))

    old_price_tag = product_box.select_one(".price--pseudo .price--discount")

    if old_price_tag:
        old_price = clean_price(old_price_tag.get_text(" "))

    discount = ""

    discount_tag = product_box.select_one(".badge--discount, .product--badge.badge--discount")

    if discount_tag:
        discount = clean_text(discount_tag.get_text(" "))

    product = {
        "title": title,
        "brand": brand,
        "article": article,
        "url": product_url,
        "category_type": category_type,
        "old_price": old_price,
        "new_price": new_price,
        "discount": discount,
        "images": [image_url] if image_url else [],
        "colors": [],
        "color_details": [],
        "telegram_text": "",
        "detail_parsed": False,
        "sent": False,
        "telegram_sent": False,
        "deleted": False,
        "status": "active",
    }

    return product


def parse_category(category_url: str, category_type: str, on_page_products=None) -> dict:
    page_number = 1

    products_found = 0
    new_count = 0
    skipped_count = 0
    pages_parsed = 0

    previous_page_urls = set()
    max_pages = 300

    while page_number <= max_pages:
        page_url = build_page_url(category_url, page_number)

        print("=" * 60)
        print("Парсимо сторінку:", page_number)
        print("URL:", page_url)

        try:
            html_text = fetch_html(page_url)
        except Exception as error:
            print("Не вдалося завантажити сторінку:", error)
            print("Зупиняємо парсинг.")
            break

        soup = BeautifulSoup(html_text, "html.parser")

        product_boxes = soup.select(".product--box")

        print("Знайдено блоків товарів:", len(product_boxes))

        if not product_boxes:
            print("Товарів на сторінці немає. Зупиняємо парсинг.")
            break

        current_page_urls = set()
        page_products = []

        for product_box in product_boxes:
            product = parse_product_box(product_box, category_type)

            if not product:
                continue

            product_url = product.get("url", "")

            if product_url:
                current_page_urls.add(product_url)

            if is_seen_link(product_url) or is_blocked_link(product_url):
                skipped_count += 1
                continue

            page_products.append(product)
            new_count += 1

        products_found += len(product_boxes)
        pages_parsed += 1

        print("Нових товарів на сторінці:", len(page_products))
        print("Пропущено на сторінці:", len(product_boxes) - len(page_products))

        if page_number > 1 and current_page_urls and current_page_urls == previous_page_urls:
            print("Наступна сторінка повторює попередню. Зупиняємо парсинг.")
            break

        previous_page_urls = current_page_urls

        if page_products and on_page_products:
            on_page_products(page_number, page_url, page_products)

        page_number += 1

        time.sleep(0.4)

    return {
        "pages_parsed": pages_parsed,
        "products_found": products_found,
        "new_count": new_count,
        "skipped_count": skipped_count,
    }


# ============================================================
# DETAIL PARSER HELPERS
# ============================================================

def normalize_variant_group_name(group_name: str) -> str:
    group_name_clean = clean_text(group_name)
    group_name_lower = group_name_clean.lower()

    translations = {
        "größe": "size",
        "groesse": "size",
        "size": "size",
        "color": "color",
        "colour": "color",
        "farbe": "color",
        "lenght": "lenght",
        "length": "length",
        "width": "width",
        "height": "height",
        "form": "form",
    }

    return translations.get(group_name_lower, group_name_clean)


def parse_selected_color_name_from_html(html_text: str) -> str:
    """
    Дістаємо вибраний колір із HTML FUNDIS.

    Працює з:
    - color
    - colour
    - Farbe
    - selected value після двокрапки: Farbe: chalk violet
    - checked input
    - перший доступний НЕ disabled input
    """

    html_text = html.unescape(html_text or "")
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

        if variant_name_tag:
            variant_text = clean_text(variant_name_tag.get_text(" "))

            if ":" in variant_text:
                selected_color = clean_text(variant_text.split(":", 1)[1])

                if selected_color:
                    print("Колір знайдено через variant--name:", selected_color)
                    return selected_color

        checked_input = group.select_one("input.option--input[checked]")

        if checked_input and checked_input.get("title"):
            selected_color = clean_text(checked_input.get("title"))

            if selected_color:
                print("Колір знайдено через checked input:", selected_color)
                return selected_color

        for input_tag in group.select("input.option--input"):
            if input_tag.has_attr("disabled"):
                continue

            title = clean_text(input_tag.get("title", ""))

            if title:
                print("Колір знайдено через перший доступний input:", title)
                return title

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
    FUNDIS іноді по sale-посиланню ?c=193 віддає HTML,
    де configurator є, але колір може бути неочевидний.

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

        with open("debug_detail_page.html", "w", encoding="utf-8") as file:
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

        print("На цій сторінці не знайдено configurator. Пробуємо наступний URL...")

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


def parse_detail_title(soup, base_product=None) -> str:
    title_tag = soup.select_one(".product--title, h1[itemprop='name'], h1")

    if title_tag:
        return clean_text(title_tag.get_text(" "))

    if base_product:
        return clean_text(base_product.get("title", ""))

    return ""


def parse_detail_brand(soup, base_product=None) -> str:
    brand_meta = soup.select_one("[itemprop='brand'] meta[itemprop='name']")

    if brand_meta and brand_meta.get("content"):
        return clean_text(brand_meta.get("content"))

    supplier_img = soup.select_one(".product--supplier img")

    if supplier_img and supplier_img.get("alt"):
        return clean_text(supplier_img.get("alt"))

    if base_product:
        return clean_text(base_product.get("brand", ""))

    return ""


def parse_detail_article(soup, base_product=None) -> str:
    sku_tag = soup.select_one("[itemprop='sku']")

    if sku_tag:
        return clean_text(sku_tag.get_text(" "))

    sku_meta = soup.select_one("meta[itemprop='sku'], meta[itemprop='productID']")

    if sku_meta and sku_meta.get("content"):
        return clean_text(sku_meta.get("content"))

    if base_product:
        return clean_text(base_product.get("article", ""))

    return ""


def get_clean_price_text_from_tag(tag) -> str:
    """
    Дістаємо тільки нову ціну.
    Видаляємо вкладені блоки старої ціни, знижки, іконки.
    """

    if not tag:
        return ""

    tag_copy = BeautifulSoup(str(tag), "html.parser")

    for bad_tag in tag_copy.select(
            ".content--discount, "
            ".price--line-through, "
            ".price--discount-percentage, "
            ".price--pseudo, "
            ".price--discount-icon, "
            "meta, "
            "i"
    ):
        bad_tag.decompose()

    return clean_price(tag_copy.get_text(" "))


def parse_detail_prices(soup, base_product=None) -> dict:
    new_price = ""
    old_price = ""
    discount = ""

    # НОВА ЦІНА
    new_price_tag = soup.select_one(".price--content.content--default")

    if not new_price_tag:
        new_price_tag = soup.select_one(".product--price .price--content")

    if new_price_tag:
        new_price = get_clean_price_text_from_tag(new_price_tag)

    if not new_price:
        price_meta = soup.select_one("meta[itemprop='price']")

        if price_meta and price_meta.get("content"):
            new_price = "€" + clean_text(price_meta.get("content"))

    # СТАРА ЦІНА
    old_price_tag = soup.select_one(".price--line-through")

    if not old_price_tag:
        old_price_tag = soup.select_one(".price--pseudo .price--discount")

    if old_price_tag:
        old_price = clean_price(old_price_tag.get_text(" "))

    # ЗНИЖКА
    discount_tag = soup.select_one(".price--discount-percentage")

    if discount_tag:
        discount = clean_text(discount_tag.get_text(" "))
        discount = discount.replace("(", "")
        discount = discount.replace(")", "")
        discount = discount.replace("gespart", "Saved")
        discount = clean_text(discount)

    if not discount:
        badge_discount = soup.select_one(".badge--discount, .product--badge.badge--discount")

        if badge_discount:
            discount = clean_text(badge_discount.get_text(" "))

    if base_product:
        if not new_price:
            new_price = clean_text(base_product.get("new_price", ""))

        if not old_price:
            old_price = clean_text(base_product.get("old_price", ""))

        if not discount:
            discount = clean_text(base_product.get("discount", ""))

    return {
        "new_price": new_price,
        "old_price": old_price,
        "discount": discount,
    }


def parse_stock(soup) -> str:
    stock_tag = soup.select_one(".delivery--information, .product--delivery")

    if stock_tag:
        return clean_text(stock_tag.get_text(" "))

    availability = soup.select_one("[itemprop='availability']")

    if availability and availability.get("href"):
        return clean_text(availability.get("href"))

    return ""


def extract_color_image_from_option(option) -> str:
    """
    Беремо фото тільки з кнопки кольору.
    Наприклад:
    .variant--option.is--image .image--media img[srcset]
    """

    if not option:
        return ""

    img_tag = option.select_one(".image--media img")

    if not img_tag:
        return ""

    srcset = img_tag.get("srcset", "")

    if srcset:
        image_url = get_first_url_from_srcset(srcset)

        if image_url:
            return normalize_url(image_url)

    src = img_tag.get("src", "")

    if src:
        return normalize_url(src)

    return ""


def parse_detail_images(soup) -> list[str]:
    """
    Беремо фото тільки з головного блоку фотографій товару.

    Тільки звідси:
    div.image--box.image-slider--item
    """

    images = []

    gallery_boxes = soup.select("div.image--box.image-slider--item")

    for box in gallery_boxes:
        image_element = box.select_one(".image--element")

        image_url = ""

        if image_element:
            for attr in [
                "data-img-large",
                "data-img-original",
                "data-img-small",
            ]:
                value = image_element.get(attr)

                if value:
                    image_url = normalize_url(value)
                    break

        if not image_url:
            img_tag = box.select_one(".image--media img")

            if img_tag:
                srcset = img_tag.get("srcset", "")

                if srcset:
                    image_url = get_first_url_from_srcset(srcset)

                if not image_url:
                    image_url = img_tag.get("src", "")

                image_url = normalize_url(image_url)

        if image_url and not image_url.startswith("data:image"):
            images.append(image_url)

    return unique_list(images)


def is_disabled_option(option, input_tag=None, label_tag=None) -> bool:
    option_classes = option.get("class", []) if option else []
    label_classes = label_tag.get("class", []) if label_tag else []

    return (
            "is--disabled" in option_classes
            or "variant--option--disabled" in option_classes
            or "is--disabled" in label_classes
            or option.select_one(".variant-badge--notAvailable") is not None
            or option.select_one(".variant-badge--notavailable") is not None
            or option.select_one(".variant-badge--not-available") is not None
            or (input_tag is not None and input_tag.has_attr("disabled"))
    )


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
                    r"sale|notAvailable|not available",
                    "",
                    label_text,
                    flags=re.IGNORECASE
                )
                option_name = clean_text(label_text)

            if not option_name:
                continue

            disabled = is_disabled_option(option, input_tag, label_tag)

            item = {
                "name": option_name,
                "available": not disabled,
            }

            all_values.append(item)

            if not disabled:
                available_values.append(option_name)

        groups.append(
            {
                "name": normalize_variant_group_name(group_name),
                "available_values": available_values,
                "all_values": all_values,
            }
        )

    return groups


def parse_color_options(soup, selected_color_name: str, fallback_main_image: str) -> list[dict]:
    color_group_names = [
        "color",
        "colour",
        "farbe",
    ]

    price_data = parse_detail_prices(soup)
    option_groups = parse_available_options_for_selected_color(soup)

    color_details = []

    for group in soup.select(".product--configurator .variant--group"):
        group_name_tag = group.select_one(".variant--name strong")

        if not group_name_tag:
            continue

        group_name = clean_text(group_name_tag.get_text(" ")).lower()

        if group_name not in color_group_names:
            continue

        for option in group.select(".variant--option"):
            input_tag = option.select_one(".option--input")
            label_tag = option.select_one(".option--label")

            color_name = ""

            if input_tag and input_tag.get("title"):
                color_name = clean_text(input_tag.get("title"))
            elif label_tag:
                color_name = clean_text(label_tag.get_text(" "))

            if not color_name:
                continue

            disabled = is_disabled_option(option, input_tag, label_tag)

            if disabled:
                continue

            color_image = extract_color_image_from_option(option)

            if not color_image and color_name == selected_color_name:
                color_image = fallback_main_image
            if not color_image:
                color_image = fallback_main_image
            color_details.append(
                {
                    "name": color_name,
                    "main_image": color_image,
                    "new_price": price_data["new_price"],
                    "old_price": price_data["old_price"],
                    "discount": price_data["discount"],
                    "option_groups": option_groups,
                    "available": True,
                }
            )

    if not color_details:
        final_color_name = selected_color_name if selected_color_name else "Колір не вказано"

        color_details.append(
            {
                "name": final_color_name,
                "main_image": fallback_main_image,
                "new_price": price_data["new_price"],
                "old_price": price_data["old_price"],
                "discount": price_data["discount"],
                "option_groups": option_groups,
                "available": True,
            }
        )

    return color_details


# ============================================================
# TELEGRAM TEXT
# ============================================================

def build_telegram_text_by_colors(
        category_type: str,
        title: str,
        brand: str,
        article: str,
        color_details: list[dict],
        url: str,
) -> str:
    personal_link = os.getenv("TELEGRAM_PERSONAL_LINK", "").strip()

    if personal_link:
        order_link = personal_link
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

    if article:
        meta_parts.append(f"📦 {html.escape(article)}")

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


# ============================================================
# PRODUCT DETAIL PARSER
# ============================================================

def parse_product_detail(product_url: str, category_type: str = "", base_product=None) -> dict:
    product_url = normalize_url(product_url)

    detail_page = fetch_detail_html_with_fallback(product_url)

    html_text = detail_page["html"]
    used_url = detail_page["url"]

    soup = BeautifulSoup(html_text, "html.parser")

    title = parse_detail_title(soup, base_product)
    brand = parse_detail_brand(soup, base_product)
    article = parse_detail_article(soup, base_product)

    price_data = parse_detail_prices(soup, base_product)
    stock = parse_stock(soup)

    selected_color_name = detail_page.get("color_name", "")

    if not selected_color_name:
        selected_color_name = parse_selected_color_name_from_html(html_text)

    all_detail_images = parse_detail_images(soup)

    fallback_main_image = ""

    if all_detail_images:
        fallback_main_image = all_detail_images[0]
    elif base_product and base_product.get("images"):
        fallback_main_image = base_product.get("images", [""])[0]

    print("Парсимо колір:", selected_color_name, "—", product_url)

    color_details = parse_color_options(
        soup=soup,
        selected_color_name=selected_color_name,
        fallback_main_image=fallback_main_image,
    )

    print("Колір із категорії:", "")
    print("Фінальний колір:", color_details[0]["name"] if color_details else "Колір не вказано")

    gallery_images = []

    # 1. Спочатку беремо головні фото доступних кольорів
    gallery_images = []

    for color in color_details:
        if color.get("main_image"):
            gallery_images.append(color["main_image"])

    gallery_images.extend(all_detail_images)

    gallery_images = unique_list(gallery_images)

    if not gallery_images and base_product and base_product.get("images"):
        gallery_images = unique_list(base_product.get("images", []))

    # 2. Фото, які вже були у JSON-об'єкті товару
    json_object_images = []

    if base_product and base_product.get("images"):
        json_object_images.extend(base_product.get("images", []))

    if base_product and base_product.get("all_detail_images"):
        json_object_images.extend(base_product.get("all_detail_images", []))

    # 3. Усі можливі fallback-фото
    fallback_images = []

    fallback_images.extend(gallery_images)
    fallback_images.extend(json_object_images)
    fallback_images.extend(all_detail_images)

    for color in color_details:
        if color.get("main_image"):
            fallback_images.append(color["main_image"])

    fallback_images = unique_list(fallback_images)

    # 4. Якщо фото кольорів не знайдені,
    # тоді показуємо фото з JSON-об'єкта
    if not gallery_images:
        gallery_images = unique_list(json_object_images)

    # 5. Якщо взагалі нічого немає — залишаємо порожній список

    option_groups = []

    if color_details:
        option_groups = color_details[0].get("option_groups", [])

    telegram_text = build_telegram_text_by_colors(
        category_type=category_type,
        title=title,
        brand=brand,
        article=article,
        color_details=color_details,
        url=used_url,
    )

    detail = {
        "title": title,
        "brand": brand,
        "article": article,
        "url": product_url,
        "detail_url": used_url,
        "category_type": category_type,
        "old_price": price_data["old_price"],
        "new_price": price_data["new_price"],
        "discount": price_data["discount"],
        "stock": stock,
        "images": gallery_images,
        "all_detail_images": all_detail_images,
        "color_details": color_details,
        "colors_detail": color_details,
        "available_colors": color_details,
        "variant_groups": option_groups,
        "telegram_text": telegram_text,
        "detail_parsed": True,
    }

    return detail
