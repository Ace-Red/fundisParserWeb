from flask import Flask, render_template, request, redirect, url_for, flash

from parser.storage import (
    load_products,
    save_products,
    mark_link_as_seen,
    mark_link_as_deleted,
    mark_link_as_sent,
    load_custom_posts,
    save_custom_posts,
)

from parser.fundis_parser import (
    parse_category,
    parse_product_detail,
)

from parser.telegram_sender import (
    send_product_to_telegram,
    send_custom_post_to_telegram,
)


app = Flask(__name__)
app.secret_key = "fundis_parser_secret_key"


@app.route("/")
def index():
    products = load_products()

    active_products = [
        product for product in products
        if product.get("status") not in ["deleted", "sent"]
    ]

    latest_products = active_products[-3:][::-1]

    return render_template(
        "index.html",
        latest_products=latest_products
    )


@app.route("/parse", methods=["POST"])
def parse_category_route():
    category_type = request.form.get("category_type")
    category_url = request.form.get("category_url")

    if not category_type or not category_url:
        flash("Будь ласка, оберіть тип категорії та вставте посилання.", "error")
        return redirect(url_for("index"))

    try:
        print("=" * 60)
        print("СТАРТ ПАРСИНГУ")
        print("Категорія:", category_type)
        print("Посилання:", category_url)

        def save_products_batch(page_number, page_url, page_products):
            products = load_products()

            print("-" * 60)
            print(f"Зберігаємо пачку зі сторінки {page_number}")
            print(f"Посилання сторінки: {page_url}")
            print(f"Товарів у пачці: {len(page_products)}")
            print(f"Було товарів у products.json: {len(products)}")

            products.extend(page_products)
            save_products(products)

            for product in page_products:
                mark_link_as_seen(product["url"])

            products_after_save = load_products()

            print(f"Стало товарів у products.json: {len(products_after_save)}")
            print("-" * 60)

        result = parse_category(
            category_url,
            category_type,
            on_page_products=save_products_batch
        )

        print("Результат:")
        print("Сторінок:", result["pages_parsed"])
        print("Знайдено товарів:", result["products_found"])
        print("Нових товарів:", result["new_count"])
        print("Пропущено:", result["skipped_count"])
        print("=" * 60)

        flash(
            f"Готово! Сторінок перевірено: {result['pages_parsed']}. "
            f"Товарів знайдено: {result['products_found']}. "
            f"Нових товарів: {result['new_count']}. "
            f"Пропущено: {result['skipped_count']}.",
            "success"
        )

    except Exception as error:
        print("ПОМИЛКА ПАРСИНГУ:", error)
        flash(f"Помилка під час парсингу: {error}", "error")

    return redirect(url_for("products"))


@app.route("/product/<int:product_index>/delete", methods=["POST"])
def delete_product(product_index):
    products = load_products()

    if product_index < 0 or product_index >= len(products):
        flash("Товар не знайдено.", "error")
        return redirect(url_for("products"))

    product = products[product_index]

    product["status"] = "deleted"
    product["deleted"] = True
    product["sent"] = False

    products[product_index] = product
    save_products(products)

    mark_link_as_deleted(product.get("url", ""))

    flash("Товар видалено. Він більше не буде показуватися і не буде додаватися при парсингу.", "success")

    return redirect(url_for("products"))


@app.route("/products")
def products():
    products = load_products()

    indexed_products = []

    for index, product in enumerate(products):
        if product.get("status") in ["deleted", "sent"]:
            continue

        indexed_products.append(
            {
                "index": index,
                "product": product,
            }
        )

    indexed_products = indexed_products[::-1]

    return render_template(
        "products.html",
        indexed_products=indexed_products
    )


@app.route("/product/<int:product_index>")
def product_detail(product_index):
    products = load_products()

    if product_index < 0 or product_index >= len(products):
        flash("Товар не знайдено.", "error")
        return redirect(url_for("products"))

    product = products[product_index]

    try:
        print("=" * 60)
        print("СТАРТ ДЕТАЛЬНОГО ПАРСИНГУ")
        print("Індекс товару:", product_index)
        print("Назва:", product.get("title", ""))
        print("Посилання:", product.get("url", ""))

        detail = parse_product_detail(
            product_url=product["url"],
            category_type=product.get("category_type", ""),
            base_product=product
        )

        product.update(detail)
        products[product_index] = product
        save_products(products)

        print("Деталі товару збережено.")
        print("=" * 60)

    except Exception as error:
        print("ПОМИЛКА ДЕТАЛЬНОГО ПАРСИНГУ:", error)
        flash(f"Помилка під час детального парсингу товару: {error}", "error")

    return render_template(
        "product_detail.html",
        product=products[product_index],
        product_index=product_index
    )


@app.route("/product/<int:product_index>/refresh", methods=["POST"])
def refresh_product_detail(product_index):
    products = load_products()

    if product_index < 0 or product_index >= len(products):
        flash("Товар не знайдено.", "error")
        return redirect(url_for("products"))

    product = products[product_index]

    try:
        print("=" * 60)
        print("ОНОВЛЕННЯ ДЕТАЛЕЙ ТОВАРУ")
        print("Індекс товару:", product_index)
        print("Назва:", product.get("title", ""))
        print("Посилання:", product.get("url", ""))

        detail = parse_product_detail(
            product_url=product["url"],
            category_type=product.get("category_type", ""),
            base_product=product
        )

        product.update(detail)
        products[product_index] = product
        save_products(products)

        print("Деталі товару оновлено.")
        print("=" * 60)

        flash("Детальну інформацію товару оновлено.", "success")

    except Exception as error:
        print("ПОМИЛКА ПІД ЧАС ОНОВЛЕННЯ ТОВАРУ:", error)
        flash(f"Помилка під час оновлення товару: {error}", "error")

    return redirect(url_for("product_detail", product_index=product_index))


@app.route("/product/<int:product_index>/send-telegram", methods=["POST"])
def send_product_telegram(product_index):
    products = load_products()

    if product_index < 0 or product_index >= len(products):
        flash("Товар не знайдено.", "error")
        return redirect(url_for("products"))

    product = products[product_index]

    if not product.get("detail_parsed"):
        flash("Спочатку потрібно завантажити деталі товару.", "error")
        return redirect(url_for("product_detail", product_index=product_index))

    try:
        print("=" * 60)
        print("ВІДПРАВКА ТОВАРУ В TELEGRAM")
        print("Індекс товару:", product_index)
        print("Назва:", product.get("title", ""))

        result = send_product_to_telegram(product)

        product["status"] = "sent"
        product["sent"] = True
        product["telegram_sent"] = True
        product["telegram_result"] = result

        mark_link_as_sent(product.get("url", ""))

        products[product_index] = product
        save_products(products)

        print("Товар відправлено в Telegram.")
        print("=" * 60)

        flash("Товар успішно відправлено в Telegram.", "success")

    except Exception as error:
        print("ПОМИЛКА TELEGRAM:", error)
        flash(f"Помилка під час відправки в Telegram: {error}", "error")

    return redirect(url_for("product_detail", product_index=product_index))


@app.route("/telegram")
def telegram_page():
    products = load_products()
    custom_posts = load_custom_posts()

    sent_products = []

    for index, product in enumerate(products):
        if product.get("status") == "sent" or product.get("telegram_sent"):
            sent_products.append(
                {
                    "index": index,
                    "product": product,
                }
            )

    sent_products = sent_products[::-1]
    custom_posts = custom_posts[::-1]

    return render_template(
        "telegram.html",
        sent_products=sent_products,
        custom_posts=custom_posts
    )


@app.route("/telegram/custom-send", methods=["POST"])
def telegram_custom_send():
    text = request.form.get("post_text", "").strip()
    photo_urls_raw = request.form.get("photo_urls", "").strip()

    if not text:
        flash("Введіть текст поста.", "error")
        return redirect(url_for("telegram_page"))

    photo_urls = []

    if photo_urls_raw:
        photo_urls = [
            line.strip()
            for line in photo_urls_raw.splitlines()
            if line.strip()
        ]

    try:
        result = send_custom_post_to_telegram(
            text=text,
            photo_urls=photo_urls
        )

        custom_posts = load_custom_posts()

        custom_posts.append(
            {
                "text": text,
                "photo_urls": photo_urls,
                "telegram_result": result,
                "status": "sent",
            }
        )

        save_custom_posts(custom_posts)

        flash("Пост успішно відправлено в Telegram.", "success")

    except Exception as error:
        print("ПОМИЛКА РУЧНОГО TELEGRAM-ПОСТА:", error)
        flash(f"Помилка під час відправки поста: {error}", "error")

    return redirect(url_for("telegram_page"))


@app.route("/clear-data", methods=["POST"])
def clear_data():
    save_products([])

    with open("data/seen_links.json", "w", encoding="utf-8") as file:
        file.write("[]")

    flash("Дані очищено. Товари та список переглянутих посилань видалені.", "success")

    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True, port=5001)
