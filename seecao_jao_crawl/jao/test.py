import json
import urllib.request
from pathlib import Path

API_URL = "https://www.jao.eu/api/v1/auction/calls/getbids"
AUCTION_ID = "HU-RS-D-DAILYPRODU-261001-01"
OUTPUT_DIR = Path(__file__).parent / "outputs"

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Content-Type": "application/json",
    "Origin": "https://www.jao.eu",
    "Referer": "https://www.jao.eu/auctions",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
    ),
}


def fetch_bids(auction_id: str) -> list:
    body = json.dumps({"auctionid": auction_id}).encode("utf-8")
    request = urllib.request.Request(API_URL, data=body, headers=HEADERS, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> None:
    data = fetch_bids(AUCTION_ID)

    OUTPUT_DIR.mkdir(exist_ok=True)
    output_path = OUTPUT_DIR / f"{AUCTION_ID}.json"
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Saved {output_path}")


if __name__ == "__main__":
    main()
