# KosovoFlowOpt

Kosova'ya (XK) elektrik ithalatının en ucuz yolunu bulan proje: JAO/SEECAO günlük
sınır ötesi kapasite (CBC) ihaleleri + saatlik spot fiyatlar → tek saatlik senaryo →
OR-Tools min cost flow.

## Dil
- Kullanıcıyla Türkçe konuş. Kod, yorumlar, docstring'ler ve commit mesajları İngilizce.
- `CostOptimizationProgram/ROADMAP.md` Türkçe; ileride yapılacakların listesi orada.

## Yapı
```
market_data/                veri katmanı → market_data.db (kökte, git'te yok)
  main.py                   JAO + SEECAO + spot fiyat crawler'ı (--from/--to)
  import_manual.py          manual/*.csv → DB (source = MANUAL)
  build_scenario.py         DB → tek saatlik senaryo JSON (data/)
  network.py                modellenen ülkeler ve sınırlar: TEK liste
  db.py                     şema (v2), kayıt fonksiyonları, results_v / bids_v view'ları
  jao/ seecao/              platform crawler'ları; spot_prices.py: yerel fiyat API istemcisi
  manual/                   elle toplanan CSV'ler (commit edilir, DB'nin tek kaynağı)
  seecao_jao_samples/       platformların Excel export'ları (git'te yok)
CostOptimizationProgram/    optimizasyon: costopt/ paketi, main.py, data/ (sentetik), output/ (git'te yok)
or-tools-examples/          OR-Tools'u ilk denerken yazılan örnekler (min cost flow çıkış noktası)
```

## Çalıştırma
Hepsi kök dizinden, kökteki `.venv` ile (Python 3.14):
```bash
.venv/bin/python market_data/main.py --from 2026-09-01 [--to 2026-09-30]
.venv/bin/python market_data/build_scenario.py --date 2026-09-01 --timetable 14:00-15:00
.venv/bin/python CostOptimizationProgram/main.py market_data/data/scenario_xk_demand_20260901_1400.json
.venv/bin/python -m pytest -q market_data
.venv/bin/python -m pytest -q CostOptimizationProgram
```
`sqlite3` CLI kurulu değil; DB'yi Python/pandas ile oku.

Spot fiyatlar bu projenin dışındaki yerel API'den gelir (ENTSO-E arkada):
`cd ~/lab/south-europe-energy-prices && .venv/bin/python api.py` → http://127.0.0.1:8000 (`/health`, `/docs`).
Taşınmayacak; ayrı proje olarak kalıyor.

## Kurallar
- Senaryo JSON'unu elle düzenleme. Veri DB'ye girer (crawler ya da `import_manual.py`), senaryo `build_scenario.py` ile üretilir.
- Sınır/ülke eklemek = `market_data/network.py`. DB'de verisi olmayan sınır yönü kapasite 0 (kapalı) olur.
- `market_data.db` yeniden üretilebilir (crawl + import_manual); `manual/` CSV'leri üretilemez, kaybetme.
- Elle yazılmış `CostOptimizationProgram/data/*.json` sentetik test verisidir (uydurma slope'lar); testler onlara dayanır.
- Push'u kullanıcı yapar; commit'i sadece istendiğinde at.

## Skill'ler (`.claude/skills/`)
- `market-data-crawl`: veri çekme, backfill, fiyat API'si, yeni platform crawler'ı
- `market-data-db`: şema, kolon anlamları, analiz sorguları
- `add-border-data`: eksik sınır/spot verisini elle ekleme, yeni sınır/ülke
- `xk-scenario`: senaryo kurma, çözme, sonucu yorumlama
- `costopt-dev`: optimizasyon kodunu değiştirme/genişletme
