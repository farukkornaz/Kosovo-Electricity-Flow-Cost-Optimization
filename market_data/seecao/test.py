import json
import urllib.parse
import urllib.request
from pathlib import Path

API_URL = "https://api.seecao.com/api/data"
AUCTION_ID = "MKXK-DH-20260901-67851"
OUTPUT_DIR = Path(__file__).parent / "outputs"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Authorization": "Bearer false",
    "Origin": "https://seecao.com",
    "Referer": "https://seecao.com/auctions/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
    ),
}


def fetch_auction(auction_id: str) -> dict:
    query = urllib.parse.urlencode({"auctionIdentification": auction_id})
    request = urllib.request.Request(f"{API_URL}?{query}", headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> None:
    data = fetch_auction(AUCTION_ID)

    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = OUTPUT_DIR / f"{AUCTION_ID}.json"
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Saved {output_path}")


if __name__ == "__main__":
    main()
