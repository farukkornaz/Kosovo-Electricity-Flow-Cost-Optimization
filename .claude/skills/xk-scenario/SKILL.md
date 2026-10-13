---
name: xk-scenario
description: >
  Belirli bir gün ve saat için Kosova (XK) talep senaryosunu piyasa veritabanından kurma,
  OR-Tools min cost flow ile çözme ve sonucu yorumlama: build_scenario.py raporu,
  CostOptimizationProgram/main.py çıktıları (solution.json, haritalar, yol maliyetleri),
  birden fazla saati, günü ya da talep miktarını karşılaştırma. Use this whenever the user
  asks to build, run or solve a scenario ("1 Eylül saat 14 için çöz", "Kosova'ya 400 MW en
  ucuz nasıl gelir", "en ucuz rota", "24 saati karşılaştır"), asks why the solver picked a
  route, why a cost or €/MWh looks high, or what the scenario report warnings mean.
---

# Kosova senaryosu: kur, çöz, yorumla

Zincir: PostgreSQL (`docker compose up -d db`) → `market_data/build_scenario.py` → senaryo JSON →
`CostOptimizationProgram/main.py` → `CostOptimizationProgram/output/<senaryo adı>/`.

DB'de o gün yoksa önce `market-data-crawl`, bir sınır kapalı görünüyor ve açılması gerekiyorsa
`add-border-data`, optimizasyon kodunu değiştirmek için `costopt-dev` skill'ine bak.

## Tek saat

```bash
.venv/bin/python market_data/build_scenario.py --date 2026-09-01 --timetable 14:00-15:00 [--demand-node XK] [--demand 400] [--seed 42] [-o yol.json]
.venv/bin/python CostOptimizationProgram/main.py market_data/data/scenario_xk_demand_20260901_1400.json [--segments 10] [-o klasör]
```

- `--timetable` CET/CEST'tir, `'HH:00-HH:00'` biçiminde (son saat `'23:00-24:00'`).
- `--demand-node` talep ülkesi (varsayılan XK; ör. `MK`), diğer ülkeler arz olur. `--demand` onun
  talebi (MW, varsayılan 400). `--seed` yalnızca yer tutucu spot fiyatlarını etkiler; talep ülkesi
  BA ya da TR ise diğerinin yer tutucu fiyatı değişir (rng çekiş sırası kayar).
- Varsayılan çıktı `market_data/data/scenario_<ülke>_demand_<tarih>_<hhmm>.json` (ör. `scenario_xk_demand_...`). Bu klasör
  **commit ediliyor**; deneme amaçlı ya da toplu çalıştırmalarda `-o` ile scratchpad'e yaz.
- `main.py` çıktıları `CostOptimizationProgram/output/` altına gider (git'te yok).
  Matplotlib'in `Ignoring fixed y limits...` uyarıları zararsızdır.

## Senaryo raporunu oku

`build_scenario.py` senaryoyu kaydettikten sonra neyi nereden aldığını yazar:

| Satır | Anlamı | Yapılacak |
|---|---|---|
| `Open: MK->XK SEECAO` | Yön açık, eğri o saatin tekliflerinden çıkarıldı | – |
| `Open with flat curve (no bids)` | Yön açık ama teklif yok, slope 0 | Sonucu yorumlarken hattın olduğundan ucuz görünebileceğini söyle |
| `Closed, 0 MW offered` | İhale yapıldı ama o saat 0 MW sunuldu → kapasite 0 | Bilgi amaçlı; çözücü de `closed (ATC 0)` der |
| `Closed, no daily auction known` | `network.BORDERS`'ta kaynak `None`, veri yok → kapasite 0 | Açılması gerekiyorsa `add-border-data` |
| `WARNING closed, expected data missing` | Kaynak bekleniyordu ama o saat için veri yok (ya da iptal, kapasite/fiyat yok) | O günü crawl et; hâlâ yoksa kullanıcıya bildir |
| `MANUAL ignored, platform data used` | Aynı yön için hem platform hem MANUAL var | Bilgi amaçlı |
| `WARNING random placeholder spot price` | O zonun spot fiyatı yok → 200-300 €/MWh arası rastgele değer | Sonuçta bu zon kullanıldıysa vurgula; gerçek fiyat için spot CSV'si (`add-border-data`) |
| `WARNING infeasible: only N MW can flow into XK, demand D MW` | XK'ye giren hatların toplamı talebin altında → çözüm kesin infeasible | Talebi düşür ya da hangi XK hattının kapalı olduğunu (0 MW, eksik veri) kullanıcıya söyle |

Raporu kullanıcıya özetlemeden sonuç yorumlama: eksik veri sonucu sessizce değiştirir.

## Senaryodaki değerler nereden geliyor

- **Arz düğümleri:** XK dışındaki tüm ülkeler. `unit_price` o saatin spot fiyatıdır
  (ENTSOE, yoksa MANUAL, o da yoksa yer tutucu). `max_supply` `network.py`'deki
  **yer tutucu** sabitlerdir, gerçek veri değildir.
- **Hatlar:** her sınır iki yönlü hat olur. `capacity` = ihalede sunulan kapasite,
  `base_price` = yayınlanan takas fiyatı, `slope` = tekliflerden çıkarılan eğim
  (`fit_linear_curve`, ayrıntısı `market-data-db`'de). Kapalı yönlerde `capacity` 0'dır.
- **Ödeme kuralı pay-as-clear:** bir hattan q MW almanın maliyeti `q · P(q)`'dur; takas fiyatı
  bütün miktara uygulanır. Bu yüzden akışı paralel rotalara bölmek çoğu zaman daha ucuzdur.

## Çözüm çıktısı

Konsol özeti: durum, teslim edilen / talep, toplam maliyet (arz + iletim) ve ortalama €/MWh,
solver amaç değeri, arz tablosu, hat tablosu (akış / kapasite, kullanım, takas fiyatı, maliyet)
ve yollar (`BG→MK→XK 171 MW ...`).

- **Durumlar:** `optimal` (talep tam karşılandı), `infeasible` (karşılanamadı; en düşük
  maliyetle teslim edilebilecek en fazla miktar gösterilir), `error`.
- `Solver objective` doğrusal parçalı bir yaklaşımdır ve gerçek `Total cost`'tan biraz yüksek
  çıkabilir. Kullanıcıya gerçek maliyet olarak `Total cost`'u ver.
- Dosyalar: `solution.json` (supplies, arcs, paths, total_cost, unit_cost...), `model_map.png`,
  `arc_curves.png`, `solution_map.png`, `solution_paths.png`, `path_costs.png`. PNG'lere Read
  aracıyla bakabilirsin.

## Yorumlarken dikkat

- Yüksek bir €/MWh değeri genellikle pay-as-clear iletim maliyetinden (dik eğimli, düşük
  kapasiteli hatlar) ya da yer tutucu spot/`max_supply` değerlerinden gelir. Hangisi olduğunu
  arz ve hat tablolarından göster.
- Taban fiyatı 0 ve eğimi çok küçük hatlar (talebin az olduğu yönler) neredeyse bedavadır;
  rotalar bunları kullanır.
- Düz eğrili (teklifsiz) yönlerde gerçek maliyet olduğundan yüksek olabilir.
- Karşılaştırma için o saatin XK spot fiyatına bak (`spot_prices`, zon `XK`): ithalatın ortalama
  maliyeti yerel fiyatla kıyaslanabilir. Model ise talebin tamamının ithal edilmesini varsayar.

## Birden fazla saat, gün ya da talep

Toplu çalıştırmada figür çizmeden doğrudan Python ile çöz; hızlıdır ve `data/` klasörünü kirletmez:

```python
import sys; sys.path[:0] = ["market_data", "CostOptimizationProgram"]
from datetime import date
import db
from build_scenario import build_scenario
from costopt.data_loader import model_from_dict
from costopt.min_cost_route_solver import MinCostRouteSolver

conn = db.connect(create=False)
for h in range(24):
    timetable = f"{h:02d}:00-{h + 1:02d}:00"
    scenario, report = build_scenario(conn, date(2026, 9, 1), timetable, demand=400, seed=42)
    result = MinCostRouteSolver().solve(model_from_dict(scenario))
    print(timetable, result.status.value, f"{result.unit_cost:.2f} €/MWh", [p.label for p in result.paths])
```

Kök dizinden çalıştır. Sonuçları bir tabloya topla; her saat için `report.missing` ve
`report.placeholder_prices` listelerini de tabloya koy. Kış saatine geçiş gününde
`'02:00-03:00'` iki saate denk geldiği için `build_scenario` o saatte hata verir. Grafik
gerekiyorsa `dataviz` skill'ini kullan.
