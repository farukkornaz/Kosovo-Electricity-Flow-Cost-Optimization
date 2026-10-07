---
name: market-data-db
description: >
  Piyasa veritabanının (PostgreSQL, Docker) şeması ve analizi: ihale sonuçları (results), teklifler (bids),
  spot fiyatlar (spot_prices); kolonların JAO / SEECAO / MANUAL kaynağına göre anlamı,
  CET/UTC ve saat numaraları, hazır SQL ve pandas sorguları (bir saatin teklif eğrisi,
  takas fiyatı ve kapasite serileri, congestion income, spot farkı ile ihale fiyatı
  karşılaştırması). Use this whenever the user asks what is in the data, wants analysis,
  statistics, charts or exports from auction, bid or spot data, writes SQL against
  the market database (Postgres), prepares data for slope calibration, or asks about columns such as
  clearing_price, offered_capacity, awarded_quantity, participants — "veride ne var",
  "teklifleri analiz et", "son bir yılın fiyatları", "hangi sınır pahalı".
---

# Piyasa veritabanı (PostgreSQL)

Docker'daki PostgreSQL 18, veritabanı `market_data` (`docker compose up -d db`; veri
`kosovoflowopt_pgdata` volume'ünde, yeniden üretilebilir ama uzun sürer). Şemanın kaynağı
`market_data/db.py`, şu anki sürüm **3** (`schema_version` tablosu; 1 ve 2 eski SQLite
dosyalarıydı). Veri çekmek için `market-data-crawl`, elle veri eklemek için `add-border-data`
skill'ine bak.

## Bağlanma

Adresi `db.database_url()` verir: `DATABASE_URL` ortam değişkeni ya da kökteki `.env`'deki
`POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` (git'te yok; şifreyi koda yazma). Analizde salt
okunur bağlan; `db.connect()` boş bir veritabanında şemayı kurar, okuma için gerekmez:

```python
import sys; sys.path.insert(0, "market_data")
import db, psycopg, pandas as pd
from sqlalchemy import create_engine

conn = psycopg.connect(db.database_url(), options="-c default_transaction_read_only=on")
rows = conn.execute("SELECT border, count(*) FROM results_v GROUP BY 1").fetchall()

# pandas bir SQLAlchemy engine'i ister (psycopg bağlantısıyla da çalışır ama uyarı basar)
engine = create_engine(db.database_url().replace("postgresql://", "postgresql+psycopg://", 1),
                       connect_args={"options": "-c default_transaction_read_only=on"})
df = pd.read_sql_query("SELECT * FROM results_v WHERE border = %(b)s", engine, params={"b": "MK-XK"})
```

- Parametre yer tutucusu `%s` / `%(ad)s`'dir (SQLite'taki `?` değil).
- Elle sorgu: `docker compose exec db psql -U kosovo market_data`.
- Kök dizindeki `market_data.db` eski SQLite dosyasıdır (yalnız 2026-09-01), kullanılmıyor.

Analiz için neredeyse her zaman **view'ları** kullan: `results_v` ve `bids_v` tabloları
düz satırlara geri birleştirir. Ham tablolara sadece yazarken ya da performans gerektiğinde in.

## Tablolar

| Tablo | Satır | Anahtar | İçerik |
|---|---|---|---|
| `auctions` | ihale başına 1 | `id`; `(source, auction_id)` tekil | source, auction_id, corridor, out_area, in_area, `border` (üretilen kolon: `out-in`, indeksli), delivery_date |
| `results` | ihale-saat başına 1 | `(auction_ref, hour)` | timetable, delivery_start_utc, offered/requested/allocated_capacity_mw, clearing_price_eur_mwh, participants, awarded_participants, comment, cancelled |
| `bids` | teklif başına 1 | `(auction_ref, hour, seq)` | quantity_mw, price_eur_mwh, awarded_quantity_mw; `seq` 1 = o saatin en yüksek fiyatı |
| `spot_prices` | kaynak-zon-saat başına 1 | `(source, zone, delivery_start_utc)` | delivery_date, hour, timetable, price_eur_mwh (15 dk fiyatlarının saatlik ortalaması) |

- Tipler: `delivery_date` `DATE`, `delivery_start_utc` `TIMESTAMPTZ`, miktar/fiyatlar
  `DOUBLE PRECISION`, `cancelled` `BOOLEAN`, `hour` `SMALLINT`. Python'a `date`, `datetime`
  (UTC), `float`, `bool` olarak gelir; tarih parametresini `date` nesnesi ya da `'2026-09-01'` ver.
- `results_v` = results + auctions kolonları + `congestion_income_eur` (allocated × price, her iki platform için).
- `bids_v` = bids + auctions kolonları + o saatin `timetable` / `delivery_start_utc` değeri.

## Kaynaklar ve kolon anlamları

`source`: `JAO`, `SEECAO` (platformlar), `ENTSOE` (yerel fiyat API'si), `MANUAL` (elle import).

- `corridor`: platformun kendi kodu. JAO'da `border`'dan farklı olabilir (`IF1-FR-GB`); filtrelemek için `border` / `out_area` / `in_area` kullan.
- `comment` sadece JAO'da dolu. `awarded_quantity_mw` sadece JAO'da var; SEECAO'da NULL.
- SEECAO teklifleri kümülatif eğriden türetilir; satır sayısı, sitenin yayınladığı teklif sayısına eşit.
- JAO'da 0 MW teklif satırları atılır.
- Veriyle doğrulandı (2026-09-01): `requested_capacity_mw` = o saatin teklif toplamı;
  JAO'da `allocated_capacity_mw` = `awarded_quantity_mw` toplamı.
- Talep arzın altında kaldığında (`requested < offered`) takas fiyatı 0'dır (130 saatin
  hepsinde). Talep yeterli olsa da teklifler 0 fiyatlıysa fiyat yine 0 olabilir.
- İptal edilen bir ihale aynı gün yeniden açılabilir (JAO HR-RS / RS-HR, 2026-08-17: `-01`
  iptal, `-02` geçerli). İkisi de saklanır; analizde `WHERE NOT cancelled` kullan. Senaryo
  kurucu iptal edilmemiş olanı seçer.
- `MANUAL` satırlarda genellikle teklif yoktur, `requested`/`allocated`/`participants` boş olabilir.
- Yalnızca modellenen 12 ülke arasındaki ihaleler saklanıyor. 2026-09-01'in tüm JAO
  koridorlarını içeren eski veri `market_data.db.v1.bak` dosyasında (SQLite, eski şema).

Aynı yön ve saat için hem platform hem `MANUAL` verisi olabilir. Senaryo kurucu platformu
seçer; analizde de bilinçli seç (genelde `WHERE source != 'MANUAL'`).

## Zaman

- `delivery_date`: CET/CEST teslim günü. `hour`: gün içinde 1'den başlayan ürün saati.
  `timetable`: `'14:00-15:00'` gibi; son saat `'23:00-24:00'`.
- `delivery_start_utc` tek anlamlıdır. Yaz/kış saati geçişinde gün 23 ya da 25 saat sürer
  ve 25 saatlik günde `'02:00-03:00'` iki kez geçer. Tabloları birleştirirken ya da
  zaman serisi kurarken `delivery_start_utc` (ya da `delivery_date` + `hour`) kullan, `timetable` değil.

## Hazır sorgular

Bir ihale-saatin teklif eğrisi (fiyat azalan, birikimli miktar):

```sql
SELECT seq, quantity_mw, price_eur_mwh,
       sum(quantity_mw) OVER (ORDER BY seq) AS cumulative_mw
FROM bids_v
WHERE border = 'MK-XK' AND delivery_date = '2026-09-01' AND timetable = '14:00-15:00'
ORDER BY seq;
```

Bir sınırın saatlik fiyat ve kapasite serisi:

```sql
SELECT delivery_start_utc, offered_capacity_mw, allocated_capacity_mw,
       clearing_price_eur_mwh, congestion_income_eur, participants
FROM results_v WHERE border = 'MK-XK' AND source != 'MANUAL' ORDER BY delivery_start_utc;
```

Spot fiyat farkı ile ihale fiyatını karşılaştırma (iki uçtaki spot fiyat farkı, kapasitenin
"değeri"dir; ihale fiyatı bunun ne kadarını yakalıyor):

```sql
SELECT r.border, r.delivery_start_utc, r.clearing_price_eur_mwh AS auction_price,
       si.price_eur_mwh - so.price_eur_mwh AS spot_spread
FROM results_v r
JOIN spot_prices so ON so.zone = r.out_area AND so.delivery_start_utc = r.delivery_start_utc AND so.source = 'ENTSOE'
JOIN spot_prices si ON si.zone = r.in_area  AND si.delivery_start_utc = r.delivery_start_utc AND si.source = 'ENTSOE'
WHERE r.delivery_date = '2026-09-01';
```

Genel durum:

```sql
SELECT delivery_date, source, count(*) AS auctions FROM auctions GROUP BY 1, 2 ORDER BY 1, 2;
SELECT zone, source, count(*), min(delivery_date), max(delivery_date) FROM spot_prices GROUP BY 1, 2;
```

## Senaryodaki eğim (slope) ile ilişkisi

`market_data/build_scenario.py` içindeki `fit_linear_curve` bir saatin tekliflerinden doğrusal
`P(q) = base_price + slope·q` eğrisi çıkarır. Biz q MW'ı kazanacak fiyattan aldığımızda kalan
`kapasite - q`'yu diğer teklif verenler paylaşır; takas fiyatı, onların birikimli talebinin bu
değere ulaştığı teklifin fiyatıdır. `slope` bu basamaklı eğriye en küçük kareler uyumudur,
0'ın altına düşmez. Kullanıcının planı, slope'u yaklaşık son bir yılın tekliflerinden kalibre
etmek (henüz başlamadı). Bu iş için veriyi `bids_v`'den ihale-saat bazında çek.

Grafik çizerken `dataviz` skill'ini kullan.
