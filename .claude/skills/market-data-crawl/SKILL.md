---
name: market-data-crawl
description: >
  JAO ve SEECAO günlük kapasite ihalelerini (sonuçlar + teklifler) ve saatlik spot
  fiyatları PostgreSQL piyasa veritabanına çekme: tek gün, tarih aralığı / backfill, yarıda kalan
  çekimi sürdürme, yerel fiyat API'sini başlatma, crawler hatalarını çözme, yeni bir
  ihale platformu için crawler yazma. Use this whenever the user wants to crawl, fetch,
  download, refresh or backfill auction or spot price data ("veri çek", "geçmiş veri",
  "bir yıllık veri", "eksik günleri tamamla"), mentions JAO, SEECAO, getauctions/getbids,
  the price API on 127.0.0.1:8000, ENTSO-E prices, or a crawl that failed — even if
  they never say "crawl".
---

# Piyasa verisi çekme (market_data/main.py)

`market_data/main.py` bir tarih aralığındaki günlük ihaleleri (JAO + SEECAO) ve saatlik
spot fiyatları Docker'daki PostgreSQL veritabanına (`DATABASE_URL`, `--db`) yazar. Şema ve sorgular için `market-data-db`,
crawler'ın çekemediği veri için `add-border-data` skill'ine bak.

## Ön koşul: veritabanı

```bash
docker compose ps                 # db "healthy" olmalı
docker compose up -d db           # değilse başlat
```

## Ön koşul: fiyat API'si

Spot fiyatlar bu projenin dışındaki yerel bir servisten gelir (ENTSO-E arkada):

```bash
curl -s http://127.0.0.1:8000/health          # {"status":"ok"} bekleniyor
cd ~/lab/south-europe-energy-prices && .venv/bin/python api.py   # kapalıysa başlat
```

Kapalıysa crawl yine çalışır: ihaleler çekilir, spot için uyarı basılır. API açıldıktan
sonra aynı komutu tekrar çalıştırmak yalnızca eksik spot günlerini çeker. Kullanıcıya
"API kapalı, başlatayım mı / sen mi başlatırsın" diye sor; API'yi arka planda başlatmak
uzun ömürlü bir süreç bırakır. API projesi buraya taşınmayacak (kullanıcı kararı).
Adres `PRICE_API_URL` ortam değişkeni ya da `--price-api` ile değişir.

## Komutlar (kök dizinden)

`.venv/bin/python` yerine `docker compose run --rm app python` de olur (aynı DB ve API'ye bağlanır).

```bash
.venv/bin/python market_data/main.py --from 2026-09-01                  # tek gün (--date de olur)
.venv/bin/python market_data/main.py --from 2025-10-01 --to 2026-09-30  # aralık
.venv/bin/python market_data/main.py --from 2026-09-01 --refresh        # saklananı da yeniden indir
```

- DB'de olan ihale (source + auction_id) ve spot fiyatı olan gün **atlanır**, bu yüzden
  yarıda kesilen bir backfill aynı komutla kaldığı yerden devam eder. Her ihale kendi
  transaction'ında yazılır; yarım ihale kalmaz.
- Sadece iki ucu da `network.COUNTRIES` içinde olan ihaleler saklanır (JAO'nun FR-GB,
  CH-IT gibi koridorları atlanır). Yeni ülke eklemek → `add-border-data`.
- Çıktı her gün için tek satır: `2026-09-01: JAO 12, SEECAO 16` (atlananlar parantezde).

### Uzun backfill

Ölçüm: bir gün 30 sn – 2 dk (neredeyse tamamı ağ beklemesi), yani bir yıl 3-12 saat.
Uzun çekimi ayrı (detached) bir container'da başlat; oturum ya da VS Code kapansa da sürer:

```bash
docker compose run -d --name kfo-crawl app python market_data/main.py --from 2025-10-01 --to 2026-09-30
docker logs -f kfo-crawl        # ilerleme (gün başına bir satır)
docker wait kfo-crawl           # bitişi bekle (Bash'te run_in_background ile), sonra: docker rm kfo-crawl
```

Önce kısa bir aralıkla (2-3 gün) dene ve sonucu doğrula. Spot fiyatlar başta tek seferde
çekilir (API isteği başına en fazla 31 gün; API'nin üst sınırı 366 gün). API önbelleğinde
olmayan bir ay ENTSO-E'den zon zon sorulur ve ~75 sn sürer; bu yüzden istek zaman aşımı
600 sn (`spot_prices.REQUEST_TIMEOUT`). Spot çekimi başarısız olursa uyarı basılır, ihaleler
yine çekilir; aynı komutu tekrar çalıştırmak eksik spot günlerini tamamlar.

## Çekimden sonra doğrula

```python
import sys; sys.path.insert(0, "market_data")
import db, psycopg
conn = psycopg.connect(db.database_url())
print(conn.execute("""SELECT delivery_date, source, count(*) FROM auctions
                      GROUP BY 1, 2 ORDER BY 1, 2""").fetchall())
print(conn.execute("""SELECT delivery_date, count(DISTINCT zone) FROM spot_prices
                      GROUP BY 1 ORDER BY 1""").fetchall())
```

Normal bir günde ~12 JAO, ~16 SEECAO ihalesi ve 10 spot zonu var (BA ve TR API'de yok).
Bir sınırın verisinin beklenip gelmediğini en kolay `build_scenario.py` raporundaki
`WARNING closed, expected data missing` satırı gösterir.

## Platformlara özgü noktalar

Kod bunları zaten hallediyor; bir şey bozulduğunda nereye bakacağını bilmek için:

- **Saat:** iki platform da ürün saatlerini CET/CEST (Europe/Brussels) yayınlar. `hour`
  1'den başlar; yaz saatine geçiş günü 23, kışa geçiş günü 25 saattir.
- **JAO** (`jao/crawler.py`): `getauctions` UTC dönem başlangıcına göre filtreler; bu yüzden
  `fromdate = gün - 1` ile sorulur ve sonuç teslim gününe göre süzülür. Hiç ihale yoksa
  400 "No Data found" döner (boş liste sayılır). `corridorCode` önek taşıyabilir
  (`IF1-FR-GB`) → `areas()` son iki parçayı alır. `getbids` bir teklifin boş bıraktığı saatleri
  0 MW satır olarak döndürür; bunlar atılır. Para birimi EUR değilse hata verir.
- **SEECAO** (`seecao/crawler.py`): `/config` her yönü EIC kodlarıyla verir; ihaleler
  yön başına `/data/filter` ile bulunur. Teklifler kümülatif talep eğrisi olarak gelir
  (fiyat azalan, `capacity` birikimli toplam); ardışık noktaların farkı tek tek teklifleri
  verir. Sayılar string gelir, `'--'` = yok. `Authorization: Bearer false` başlığı sitenin
  kendi gönderdiği değerdir.
- **Hatalar:** ağ hataları (bağlantı kopması, zaman aşımı) ve 5xx üç kez, artan beklemeyle
  tekrar denenir (`common.fetch_json`). 4xx hemen yükselir.
- **JAO erişimi kesebilir:** 2026-10-07'de 2 aylık çekimin sonunda (~30 dk'da ~1.700 istek)
  `ConnectionResetError` gelmeye başladı ve `https://www.jao.eu/` bu makineden hiç açılmadı
  (SEECAO normaldi), büyük ihtimalle geçici bir IP engeli. Böyle olursa JAO'ya istek atmayı
  bırak, seyrek aralıkla (5 dk'da bir `curl`) erişimi kontrol et, açılınca aynı komutla devam
  et. Bir yıllık backfill'i aylık parçalara böl.
- `RuntimeError: ... schema version X, expected 3` → veritabanında başka bir şemanın tabloları
  var. Silmeden önce kullanıcıya sor; `docker compose down -v` bütün veriyi siler.
- `connection refused` → `docker compose up -d db`.
- Sitedeki tabloyla karşılaştırmak için platform Excel export'ları
  `market_data/seecao_jao_samples/` altında.

## Yeni bir ihale platformu eklemek

Kaynağın bir API'si ya da düzenli yayınlanan bir sayfası varsa crawler yaz; tek seferlik
ya da elle derlenen veri için `add-border-data`'daki CSV yolu daha basit.

1. `market_data/<platform>/crawler.py`: `SOURCE = "<PLATFORM>"`, gün için ihaleleri bulan bir
   fonksiyon, ihaleyi indiren bir fonksiyon ve `to_rows(...) -> (auction, results, bids)`.
   - `auction`: `common.auction_row(source, auction_id, corridor, out_area, in_area, period_start_utc)`
   - `results`: saat başına `{**common.hour_columns(start, hour, timetable), offered_capacity_mw,
     requested_capacity_mw, allocated_capacity_mw, clearing_price_eur_mwh, participants,
     awarded_participants, comment, cancelled}`
   - `bids`: `{hour, quantity_mw, price_eur_mwh, awarded_quantity_mw}`; sıra numarasını
     (`seq`) `db.save_auction` verir.
2. `main.py`'de `crawl_auctions` içine JAO/SEECAO'daki kalıpla ekle: `network.is_modeled`
   filtresi, `db.has_auction` ile atlama, `db.save_auction`.
3. `network.BORDERS`'ta ilgili sınırların beklenen kaynağını `"<PLATFORM>"` yap; böylece
   veri gelmezse senaryo raporu uyarır.
4. `market_data/tests/test_crawlers.py`'ye küçük sentetik bir payload ile `to_rows` testi ekle,
   sonra `.venv/bin/python -m pytest -q market_data`.
