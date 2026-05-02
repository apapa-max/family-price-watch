import requests
from bs4 import BeautifulSoup


def search_costco_products(keyword):
    url = f"https://www.costco.co.jp/search?text={keyword}"

    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # デバッグ: aタグを確認
    all_links = soup.find_all("a", href=True)

    print("\n=== DEBUG LINKS ===")
    for link in all_links[:30]:
        text = link.get_text(strip=True)
        href = link.get("href")
        print(text, "=>", href)
    print("=== END DEBUG ===\n")

    return []
