# KosovoFlowOpt

Kosova'ya (XK) elektrik ithalatının en ucuz yolunu bulan proje: JAO/SEECAO günlük
sınır ötesi kapasite (CBC) ihaleleri + saatlik spot fiyatlar → tek saatlik senaryo →
OR-Tools min cost flow.

## Dil
- Kullanıcıyla Türkçe konuş. Kod, yorumlar, docstring'ler ve commit mesajları İngilizce.
- `CostOptimizationProgram/ROADMAP.md` Türkçe; ileride yapılacakların listesi orada.

## Yapı
```
docker-compose.yml          db: PostgreSQL 18 (pgdata volume) · app: Python ortamı (isteğe bağlı)
Dockerfile, docker/initdb/  app imajı; test veritabanını (market_data_test) kuran init script'i
market_data/                veri katmanı → PostgreSQL (market_data veritabanı)
  main.py                   JAO + SEECAO + spot fiyat crawler'ı (--from/--to)
  import_manual.py          manual/*.csv → DB (source = MANUAL)
  build_scenario.py         DB → tek saatlik senaryo JSON (data/)
  network.py                modellenen ülkeler ve sınırlar: TEK liste
  db.py                     şema (v3, Postgres), kayıt fonksiyonları, results_v / bids_v view'ları
  jao/ seecao/              platform crawler'ları; spot_prices.py: yerel fiyat API istemcisi
  manual/                   elle toplanan CSV'ler (commit edilir, DB'nin tek kaynağı)
  seecao_jao_samples/       platformların Excel export'ları (git'te yok)
CostOptimizationProgram/    optimizasyon: costopt/ paketi, main.py, data/ (sentetik), output/ (git'te yok)
or-tools-examples/          OR-Tools'u ilk denerken yazılan örnekler (min cost flow çıkış noktası)
```

## Çalıştırma
Veritabanı Docker'da çalışır; önce onu başlat (`docker compose ps` ile kontrol et):
```bash
docker compose up -d db
```
Kod iki yoldan da çalışır, ikisi de aynı veritabanına (`localhost:5432`) bağlanır.
Kök dizinden, kökteki `.venv` ile (Python 3.14):
```bash
.venv/bin/python market_data/main.py --from 2026-09-01 [--to 2026-09-30]
.venv/bin/python market_data/build_scenario.py --date 2026-09-01 --timetable 14:00-15:00
.venv/bin/python CostOptimizationProgram/main.py market_data/data/scenario_xk_demand_20260901_1400.json
.venv/bin/python -m pytest -q market_data          # test veritabanı gerekir
.venv/bin/python -m pytest -q CostOptimizationProgram
```
ya da container içinde: `docker compose run --rm app python market_data/main.py ...` (aynı komutlar,
`.venv/bin/python` yerine `python`). Bağımlılık değişince `docker compose build app`.

- Kullanıcı adı/şifre kökteki `.env`'de (git'te yok, şablon `.env.example`). Compose da
  `db.database_url()` de onu okur; `DATABASE_URL` ortam değişkeni varsa o geçerli. Şifreyi koda
  ya da compose dosyasına yazma. Testler `market_data_test` veritabanında, her test kendi şemasında.
- `psql`: `docker compose exec db psql -U kosovo market_data`. Python'da `db.connect()` ya da pandas.
- Veri `kosovoflowopt_pgdata` volume'ünde. `docker compose down -v` veritabanını **siler**.
- Kökteki `market_data.db` eski SQLite dosyası (sadece 2026-09-01); artık kullanılmıyor.

Spot fiyatlar bu projenin dışındaki yerel API'den gelir (ENTSO-E arkada):
`cd ~/lab/south-europe-energy-prices && .venv/bin/python api.py` → http://127.0.0.1:8000 (`/health`, `/docs`).
Taşınmayacak; ayrı proje olarak kalıyor.

## Kurallar
- Senaryo JSON'unu elle düzenleme. Veri DB'ye girer (crawler ya da `import_manual.py`), senaryo `build_scenario.py` ile üretilir.
- Sınır/ülke eklemek = `market_data/network.py`. DB'de verisi olmayan sınır yönü kapasite 0 (kapalı) olur.
- Veritabanı yeniden üretilebilir (crawl + import_manual) ama uzun sürer (gün başına ~2 dk); `manual/` CSV'leri üretilemez, kaybetme.
- Elle yazılmış `CostOptimizationProgram/data/*.json` sentetik test verisidir (uydurma slope'lar); testler onlara dayanır.
- `README.md` kullanıcının komut başvurusudur (Türkçe). Bir komut, seçenek ya da akış değişince onu da güncelle.
- Push'u kullanıcı yapar; commit'i sadece istendiğinde at.

## Skill'ler (`.claude/skills/`)
- `market-data-crawl`: veri çekme, backfill, fiyat API'si, yeni platform crawler'ı
- `market-data-db`: şema, kolon anlamları, analiz sorguları
- `add-border-data`: eksik sınır/spot verisini elle ekleme, yeni sınır/ülke
- `xk-scenario`: senaryo kurma, çözme, sonucu yorumlama
- `costopt-dev`: optimizasyon kodunu değiştirme/genişletme
