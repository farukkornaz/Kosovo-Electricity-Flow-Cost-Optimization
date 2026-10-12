# KosovoFlowOpt

Kosova'ya (XK) elektrik ithalatının en ucuz yolunu bulur. JAO, SEECAO ve NOSBiH'in (BA-RS) günlük
sınır ötesi kapasite (CBC) ihaleleri ile saatlik spot fiyatlar PostgreSQL'e çekilir; seçilen bir
gün ve saat için senaryo kurulur ve OR-Tools min cost flow ile çözülür.

```
JAO + SEECAO + NOSBiH ──┐
Spot fiyat API'si ──────┼─→ PostgreSQL ─→ build_scenario.py ─→ senaryo JSON ─→ CostOptimizationProgram/main.py ─→ rota, maliyet, haritalar
manual/*.csv ───────────┘
```

Bütün komutlar **proje kök dizininden** çalıştırılır.

---

## Hızlı başvuru

| Ne | Komut |
|---|---|
| Veritabanı çalışıyor mu? | `docker compose ps` |
| Veritabanını başlat | `docker compose up -d db` |
| Fiyat API'sini başlat (ayrı terminal) | `cd ~/lab/south-europe-energy-prices && .venv/bin/python api.py` |
| Bir günü çek | `.venv/bin/python market_data/main.py --from 2026-10-01` |
| Tarih aralığı çek | `.venv/bin/python market_data/main.py --from 2026-10-01 --to 2026-10-31` |
| Sadece bir platformu çek | `.venv/bin/python market_data/main.py --from 2026-10-01 --source NOSBIH` |
| Senaryo kur | `.venv/bin/python market_data/build_scenario.py --date 2026-08-01 --timetable 14:00-15:00 -o CostOptimizationProgram/output/scenarios/xk_20260801_1400.json` |
| Senaryoyu çöz | `.venv/bin/python CostOptimizationProgram/main.py CostOptimizationProgram/output/scenarios/xk_20260801_1400.json` |
| Elle veri ekle | `.venv/bin/python market_data/import_manual.py` |
| Yedek al | `docker compose exec -T db pg_dump -U kosovo -Fc market_data > backups/market_data_$(date +%F).dump` |
| psql | `docker compose exec db psql -U kosovo market_data` |
| Testler | `.venv/bin/python -m pytest -q market_data` ve `.venv/bin/python -m pytest -q CostOptimizationProgram` |

Her Python komutu Docker içinde de çalışır: `.venv/bin/python` yerine
`docker compose run --rm app python` yaz. İkisi de aynı veritabanını kullanır.

---

## 1. İlk kurulum (yeni makine ya da sıfırdan)

Bu makinede hepsi yapıldı; yeniden kurulum gerekirse:

1. **Docker** (WSL Ubuntu içinde Docker Engine). Kullanıcıyı `docker` grubuna ekle ve WSL'i
   yeniden başlat (PowerShell'de `wsl --shutdown`), yoksa `permission denied ... docker.sock` alırsın:
   ```bash
   sudo usermod -aG docker $USER
   ```
2. **Veritabanı şifresi:** `.env` dosyası git'te yok. Şablondan oluştur ve
   `POSTGRES_PASSWORD`'u değiştir:
   ```bash
   cp .env.example .env
   ```
   Şifre, veritabanı ilk kez oluşturulurken geçerli olur. Sonradan değiştirmek için `.env`'i
   değiştirmek yetmez, veritabanında da `ALTER USER kosovo PASSWORD '...'` gerekir.
3. **Veritabanını başlat:** ilk çalıştırmada `market_data` ve testler için `market_data_test`
   oluşturulur, tablolar ilk veri çekiminde kurulur.
   ```bash
   docker compose up -d db
   ```
4. **Python ortamı** (Python 3.14). İkisinden biri, ya da ikisi:
   ```bash
   python3.14 -m venv .venv && .venv/bin/pip install -r requirements.txt   # yerel
   docker compose build app                                               # Docker imajı
   ```
5. **Fiyat API'si** ayrı bir projedir (`~/lab/south-europe-energy-prices`, ENTSO-E arkada);
   bu repoya taşınmaz.

## 2. Her gün çalışmaya başlarken

- Docker WSL ile birlikte açılır, veritabanı container'ı da kendiliğinden başlar
  (`restart: unless-stopped`). Kontrol: `docker compose ps` → `db` satırında `healthy`.
- **Fiyat API'si kendiliğinden başlamaz.** Veri çekeceksen ayrı bir terminalde başlat:
  ```bash
  cd ~/lab/south-europe-energy-prices && .venv/bin/python api.py
  curl -s http://127.0.0.1:8000/health          # {"status":"ok"}
  ```
  Sadece senaryo kurup çözeceksen API gerekmez; veri veritabanında.

## 3. Veritabanına veri çekmek

```bash
.venv/bin/python market_data/main.py --from 2026-10-01                  # tek gün
.venv/bin/python market_data/main.py --from 2026-10-01 --to 2026-10-31  # aralık (iki uç dahil)
.venv/bin/python market_data/main.py --from 2026-10-01 --refresh        # kayıtlı olanı da yeniden indir
.venv/bin/python market_data/main.py --from 2026-10-01 --source NOSBIH  # sadece bu platform (tekrarlanabilir: --source JAO --source SEECAO)
```

- Önce aralığın bütün spot fiyatları, sonra gün gün ihaleler çekilir. Her gün için bir satır
  yazar: `2026-10-01: JAO 12, SEECAO 16, NOSBIH 2`. Normal bir günde 12 JAO + 16 SEECAO + 2 NOSBiH
  ihalesi var.
- `--source` sadece seçilen ihale platformlarını çeker (varsayılan: hepsi); spot fiyatlar yine
  kontrol edilir. Tek bir platformu geriye doğru doldururken ya da JAO erişimi kestiğinde işe yarar.
- **NOSBiH** (Bosna ISO'su) BA-RS sınırının ihalesini kendisi yapar, JAO/SEECAO'da yok. Sadece
  sonuçları yayınlıyor, **teklif yok**; bu yüzden BA↔RS senaryoda takas fiyatında düz eğriyle
  açılır. `participants` boş, `awarded_participants` = kapasite alan trader sayısı. Gün başına ~1 sn.
- **Kaldığı yerden devam eder:** kayıtlı ihaleler ve spot fiyatı olan günler atlanır. Yarıda
  kesilen bir çekimi aynı komutla yeniden başlatman yeterli.
- Yalnızca modellenen 12 ülke arasındaki ihaleler saklanır (`market_data/network.py`).
- Fiyat API'si kapalıysa ihaleler yine çekilir, spot fiyatlar için uyarı basılır. API'yi açıp
  aynı komutu tekrar çalıştırınca eksik spot günleri tamamlanır.
- Süre: gün başına 30 sn – 2 dk. Ağustos–Eylül 2026 (61 gün) yaklaşık 30 dakika sürdü.

### Uzun çekimler (bir ay ve üstü)

Ayrı bir container'da başlat; terminal ya da VS Code kapansa da sürer:

```bash
docker compose run -d --name kfo-crawl app python market_data/main.py --from 2025-10-01 --to 2025-10-31
docker logs -f kfo-crawl     # ilerlemeyi izle (Ctrl+C sadece izlemeyi bırakır)
docker rm kfo-crawl          # bittikten sonra, aynı isimle yenisini başlatmadan önce
```

- **JAO çok istekte erişimi kesebilir.** Ağustos–Eylül çekiminin sonunda (~30 dakikada ~1.700
  istek) `ConnectionResetError` gelmeye başladı ve `www.jao.eu` bir saat kadar açılmadı. Böyle
  olursa bekle, `curl -I https://www.jao.eu/` açılınca aynı komutla devam et. Bir yıllık
  çekimi **aylık parçalara böl**, parçalar arasında ara ver.

### Ne çekildiğini kontrol et

```bash
.venv/bin/python - <<'EOF'
import sys; sys.path.insert(0, "market_data"); import db
conn = db.connect(create=False)
print(conn.execute("SELECT min(delivery_date), max(delivery_date), count(DISTINCT delivery_date) FROM auctions").fetchone())
print(conn.execute("""SELECT delivery_date, source, count(*) FROM auctions GROUP BY 1, 2
                      HAVING count(*) NOT IN (2, 12, 16) ORDER BY 1""").fetchall())   # alışılmadık günler
EOF
```

Şu an veritabanında: **2026-08-01 – 2026-10-08** (69 gün, 2.072 ihale, ~1,64 milyon teklif).
Bilinen boşluk: 2026-09-14'te AL spot fiyatı yok.

## 4. Elle veri eklemek (crawler'ın çekemediği sınırlar)

Kapalı sınırlar (RS-XK, AL-XK, BG-GR...) ve API'de olmayan spot fiyatları (BA, TR)
için. Dosyayı `market_data/manual/<anlamlı_ad>.csv` olarak kaydet; bu CSV'ler commit edilir,
verinin tek kopyası onlardır. Dosya türünü başlık satırı belirler:

```
results: border,delivery_date,timetable,offered_capacity_mw,clearing_price_eur_mwh
bids:    border,delivery_date,timetable,quantity_mw,price_eur_mwh
spot:    zone,delivery_date,timetable,price_eur_mwh
```

```csv
border,delivery_date,timetable,offered_capacity_mw,clearing_price_eur_mwh
BG-GR,2026-09-01,*,300,4.50
GR-BG,2026-09-01,*,250,1.20
```

- `border` yönlüdür (`BG-GR` = BG'den GR'ye), ters yön ayrı satırdır.
- `timetable` CET saatidir (`14:00-15:00`); `*` o günün bütün saatleri demektir.
- Teklif (`bids`) yoksa o hat düz eğriyle açılır (slope 0); hat olduğundan ucuz görünebilir.

```bash
.venv/bin/python market_data/import_manual.py                                   # manual/ altındaki her şey
.venv/bin/python market_data/import_manual.py market_data/manual/bg_gr_2026-09.csv
```

Aynı yön ve saat için platform verisi varsa elle girilen yok sayılır. Yeni sınır ya da ülke
eklemek: önce `market_data/network.py`. Ayrıntılar: `.claude/skills/add-border-data/SKILL.md`.

## 5. Senaryo kurmak ve çözmek

İki adım. Veritabanı açık olmalı, fiyat API'si gerekmez.

**1. Senaryoyu kur:** o saatin kapasitelerini, takas fiyatlarını, tekliflerden eğimi (slope)
ve spot fiyatları okur, senaryo JSON'unu yazar.

```bash
.venv/bin/python market_data/build_scenario.py --date 2026-08-01 --timetable 14:00-15:00 \
    -o CostOptimizationProgram/output/scenarios/xk_20260801_1400.json
```

| Seçenek | Anlamı |
|---|---|
| `--date` | Teslim günü, `YYYY-MM-DD` |
| `--timetable` | CET saati, `HH:00-HH:00`; son saat `23:00-24:00` |
| `--demand` | Kosova talebi, MW (varsayılan 400) |
| `--seed` | Spot fiyatı olmayan zonlara (BA, TR) verilen rastgele yer tutucu fiyatın tohumu |
| `-o` | Çıktı dosyası. **Manuel testlerde kullan:** verilmezse `market_data/data/` altına yazar ve o klasör git'e girer |

Kurulumdan sonra basılan rapor:

| Satır | Anlamı |
|---|---|
| `Open: MK->XK SEECAO` | Hat açık, eğri o saatin tekliflerinden çıkarıldı |
| `Open with flat curve (no bids)` | Açık ama teklif yok (slope 0), olduğundan ucuz görünebilir (BA↔RS NOSBIH hep böyle) |
| `Closed, 0 MW offered` | İhale yapıldı ama o saat 0 MW sunuldu → kapasite 0 (ör. MK↔XK, 2026-10-03'ten beri) |
| `Closed, no daily auction known` | Bu sınırın bilinen bir günlük ihalesi yok → kapasite 0 |
| `WARNING closed, expected data missing` | Veri bekleniyordu ama yok: o günü çek |
| `WARNING random placeholder spot price` | Spot fiyatı yok, 200-300 €/MWh arası rastgele değer kullanıldı (BA, TR) |
| `WARNING infeasible: only 156 MW can flow into XK, demand 400 MW` | XK'ye giren hatların toplam kapasitesi talebin altında: çözüm kesin infeasible. Toplam yetse bile daha uzaktaki hatlar yetmeyebilir; onu çözücü söyler |

**2. Çöz:**

```bash
.venv/bin/python CostOptimizationProgram/main.py CostOptimizationProgram/output/scenarios/xk_20260801_1400.json
```

Seçenekler: `--segments 20` (hat maliyet eğrisi kaç parçaya bölünsün, varsayılan 10),
`-o KLASÖR`, `--show` (grafikleri pencerede aç; Docker'da çalışmaz).

Konsolda: durum, teslim edilen / talep, **Total cost** ve ortalama €/MWh, ülke ülke alımlar,
hat hat akışlar, rotalar (`BG→MK→XK 139 MW ...`). Dosyalar
`CostOptimizationProgram/output/<senaryo adı>/` altında: `solution.json`, `model_map.png`,
`arc_curves.png`, `solution_map.png`, `solution_paths.png`, `path_costs.png`.

Sonucu okurken:
- Gerçek maliyet `Total cost`'tur. `Solver objective` parçalı bir yaklaşımdır, biraz yüksek çıkar.
- Durum `infeasible` ise talep karşılanamadı; teslim edilebilen en fazla miktar gösterilir.
- İhale ödemesi pay-as-clear: bir hattan çok almak o hattın fiyatını bütün miktar için
  yükseltir. Bu yüzden solver akışı birkaç rotaya böler.
- Spot fiyat negatif olabilir (öğle saatlerinde güneş fazlası). Model bunu kabul eder ama
  iletim pahalıysa yine o ülkeden almaz.
- Ülkelerin `max_supply` değerleri (`market_data/network.py`) **yer tutucudur**, gerçek veri değil.

### Birçok saati karşılaştırmak

Haritasız, hızlı: bir günün 24 saati birkaç saniye sürer.

```bash
.venv/bin/python - <<'EOF'
import sys; sys.path[:0] = ["market_data", "CostOptimizationProgram"]
from datetime import date
import db
from common import day_hours
from build_scenario import build_scenario
from costopt.data_loader import model_from_dict
from costopt.min_cost_route_solver import MinCostRouteSolver

conn = db.connect(create=False)
day = date(2026, 8, 1)
for hour in day_hours(day):
    scenario, report = build_scenario(conn, day, hour["timetable"], demand=400, seed=42)
    result = MinCostRouteSolver().solve(model_from_dict(scenario))
    print(hour["timetable"], result.status.value, f"{result.unit_cost:7.2f} €/MWh", [p.label for p in result.paths])
EOF
```

Kış saatine geçiş gününde (ör. 2026-10-25) `02:00-03:00` iki kez geçer; o saat için senaryo
kurulamaz.

## 6. Veritabanına bakmak

**Grafik araçla** (DBeaver, pgAdmin, VS Code "PostgreSQL" eklentisi): yeni PostgreSQL bağlantısı.

| Alan | Değer |
|---|---|
| Host / Port | `localhost` / `5432` |
| Database | `market_data` |
| User | `kosovo` |
| Password | `.env` içindeki `POSTGRES_PASSWORD` |

**Terminalden:** `docker compose exec db psql -U kosovo market_data`

**Python / pandas:**

```python
import sys; sys.path.insert(0, "market_data")
import db, pandas as pd
from sqlalchemy import create_engine

engine = create_engine(db.database_url().replace("postgresql://", "postgresql+psycopg://", 1))
df = pd.read_sql_query("SELECT * FROM results_v WHERE border = 'MK-XK' AND NOT cancelled", engine)
```

| Tablo / view | İçerik |
|---|---|
| `results_v` | İhale-saat başına bir satır: sınır, kapasite, takas fiyatı, katılımcı, congestion income |
| `bids_v` | Teklif başına bir satır: miktar, fiyat (`seq` 1 = o saatin en yüksek teklifi) |
| `spot_prices` | Zon-saat başına spot fiyat |
| `auctions`, `results`, `bids` | Ham tablolar; analizde view'ları kullan |

- `delivery_date` ve `timetable` CET, `delivery_start_utc` UTC. Zaman serisinde
  `delivery_start_utc` kullan.
- İptal edilen bir ihale aynı gün yeniden açılabilir (2026-08-17, HR↔RS); analizde
  `WHERE NOT cancelled`.
- Kolonların ayrıntılı anlamı: `.claude/skills/market-data-db/SKILL.md`.

## 7. Yedekleme ve geri yükleme

Veri yeniden çekilebilir ama uzun sürer. Büyük bir çekimden sonra yedek al (iki ay ~6 MB, ~2 sn):

```bash
mkdir -p backups
docker compose exec -T db pg_dump -U kosovo -Fc market_data > backups/market_data_$(date +%F).dump
```

Geri yükleme (mevcut tabloların **yerine** yazar):

```bash
docker compose exec -T db pg_restore -U kosovo -d market_data --no-owner --clean --if-exists < backups/market_data_2026-10-07.dump
```

`backups/` git'te yok. Önemli bir yedeği WSL dışına da kopyala (ör. `/mnt/c/Users/...`).

## 8. Docker: durdurmak, silmek, güncellemek

| Komut | Ne yapar |
|---|---|
| `docker compose stop` | Veritabanını durdurur, veri kalır |
| `docker compose up -d db` | Yeniden başlatır |
| `docker compose down` | Container'ı siler, **veri kalır** (`kosovoflowopt_pgdata` volume'ü) |
| `docker compose down -v` | **Veritabanını tamamen siler.** Önce yedek al |
| `docker compose build app` | Requirements değişince app imajını yeniden kurar |
| `.venv/bin/pip install -r requirements.txt` | Aynısı, yerel ortam için |

Kod değişikliği için yeniden build gerekmez: proje klasörü container'a bağlı.

## 9. Testler

```bash
.venv/bin/python -m pytest -q market_data               # veritabanı açık olmalı (market_data_test kullanır)
.venv/bin/python -m pytest -q CostOptimizationProgram
```

İki klasörü ayrı ayrı çalıştır; tek komutta birlikte çalışmazlar. Testler asıl veritabanına
dokunmaz, her test `market_data_test` içinde kendi geçici şemasında çalışır.

## 10. Sık karşılaşılan hatalar

| Hata | Çözüm |
|---|---|
| `permission denied ... /var/run/docker.sock` | Kullanıcı `docker` grubunda değil ya da WSL yeniden başlatılmadı (bkz. kurulum 1) |
| `connection refused` / `test database unreachable` | `docker compose up -d db` |
| `POSTGRES_PASSWORD not set: copy .env.example to .env` | `.env` yok: `cp .env.example .env` |
| `WARNING: price API at ... is down` | Fiyat API'sini başlat, aynı çekim komutunu tekrar çalıştır |
| `ConnectionResetError` (JAO) | JAO erişimi kesti; bekle, aynı komutla devam et (bkz. bölüm 3) |
| `has no market schema: crawl first` | Veritabanı boş; önce veri çek |
| `schema version X, expected 4` | Veritabanında başka bir şemanın tabloları var; silmeden önce yedek al (sürüm 3 kendiliğinden 4'e yükseltilir) |
| `... has data but is not in network.BORDERS` | Yeni bir sınırın verisi geldi; `network.py`'ye ekle |
| `matches hours [...] (clock change day)` | Kış saatine geçiş günü `02:00-03:00`; başka saat seç |
| `Ignoring fixed y limits ...` (matplotlib) | Zararsız uyarı |

## 11. Proje yapısı

```
docker-compose.yml, Dockerfile     PostgreSQL (db) ve Python ortamı (app)
.env / .env.example                veritabanı kullanıcı adı ve şifresi (.env git'te yok)
docker/initdb/                     test veritabanını kuran init script'i
requirements.txt                   bütün bağımlılıklar (market_data + CostOptimizationProgram)
market_data/                       veri katmanı
  main.py                          JAO + SEECAO + NOSBiH + spot fiyat crawler'ı
  import_manual.py                 manual/*.csv → veritabanı
  build_scenario.py                veritabanı → tek saatlik senaryo JSON
  network.py                       modellenen ülkeler ve sınırlar (tek liste)
  db.py                            şema, bağlantı, kayıt fonksiyonları
  jao/, seecao/, nosbih/          ihale platformu crawler'ları
  spot_prices.py                   fiyat API istemcisi
  manual/                          elle toplanan CSV'ler (commit edilir)
  data/                            commit edilen örnek senaryo
CostOptimizationProgram/           optimizasyon
  costopt/                         model, fiyat eğrisi, solver, çözüm, haritalar
  main.py                          senaryoyu çöz + çiz
  data/                            elle yazılmış sentetik test verisi (testler buna dayanır)
  output/                          çözüm çıktıları (git'te yok)
  ROADMAP.md                       yol haritası ve bekleyen işler
or-tools-examples/                 OR-Tools ilk denemeleri
backups/                           veritabanı yedekleri (git'te yok)
market_data.db                     eski SQLite dosyası, kullanılmıyor (git'te yok)
```

Bekleyen işler (auction_analysis, slope kalibrasyonu, kapalı sınırlar, BA/TR spot
fiyatları, `max_supply`): `CostOptimizationProgram/ROADMAP.md`.

Claude Code ile çalışırken `.claude/skills/` altındaki skill'ler bu adımların ayrıntılı
hallerini içerir; "1 Ağustos saat 14'ü çöz" ya da "Ekim'i çek" gibi yazman yeter.
