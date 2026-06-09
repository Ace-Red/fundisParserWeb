from parser.fundis_parser import fetch_html, parse_products_from_html

url = "https://www.fundis-equestrian.com/sale/?p=1&o=1&n=24&s=176%7C192"

print("Завантажуємо HTML...")
html = fetch_html(url)

print("Довжина HTML:", len(html))

with open("debug_fundis_page.html", "w", encoding="utf-8") as file:
    file.write(html)

print("HTML збережено у debug_fundis_page.html")

products = parse_products_from_html(html, url, "Sale")

print("Знайдено товарів:", len(products))

for product in products[:5]:
    print("-" * 40)
    print("Назва:", product["title"])
    print("Бренд:", product["brand"])
    print("Артикул:", product["article"])
    print("Стара ціна:", product["old_price"])
    print("Нова ціна:", product["new_price"])
    print("Знижка:", product["discount"])
    print("URL:", product["url"])
    print("Фото:", product["images"][:1])
    print("Кольори:", [color["name"] for color in product["colors"]])