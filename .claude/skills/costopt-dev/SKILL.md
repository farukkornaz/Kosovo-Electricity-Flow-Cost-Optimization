---
name: costopt-dev
description: >
  CostOptimizationProgram/costopt paketinin içyapısı ve geliştirilmesi: NetworkModel,
  PriceCurve / LinearPriceCurve, pay-as-clear maliyet ve fiyat eğrisi segmentleri, OR-Tools
  SimpleMinCostFlow çevirisi, SolutionResult ve yol ayrıştırma, model/çözüm haritaları,
  JSON model formatı ve testler. Use this whenever the user wants to change or extend the
  optimization code — a new curve type, stepwise (basamaklı) prices, transmission losses,
  fixed costs, several demand nodes, an hourly/time dimension, switching to LP/MIP/CP-SAT,
  solver behavior, map or plot changes — or debug a failing costopt test: "modeli
  değiştir", "yeni kısıt ekle", "solver", "kademeli fiyat", "kayıp ekle".
---

# costopt geliştirme

Paket `CostOptimizationProgram/costopt/`. Gerçek senaryo üretmek ve çözmek bu skill'in değil,
`xk-scenario`'nun işi. Yol haritası ve ileride yapılacaklar
`CostOptimizationProgram/ROADMAP.md`'de (Türkçe). Çıkış noktası
`or-tools-examples/Flows/minimum-cost-flow-2.py`.

## Katmanlar

| Modül | Görev | Bilmediği |
|---|---|---|
| `price_curve.py` | `PriceCurve`: `clearing_price(q)`, `total_cost = q·P(q)`, `segments(n)`; `LinearPriceCurve` | model, solver |
| `model.py` | `Node`, `SupplyNode`, `DemandNode`, `Arc`, `NetworkModel` (ekleme + `validate`) | OR-Tools |
| `data_loader.py` | JSON ↔ `NetworkModel`; `NODE_TYPES`, `CURVE_TYPES` kayıtları | solver |
| `min_cost_route_solver.py` | modeli `SimpleMinCostFlow`'a çevirir, çözer | çizim |
| `solution.py` | solver'dan bağımsız `SolutionResult`, gerçek maliyetler, yol ayrıştırma | OR-Tools |
| `map.py`, `solution_map.py` | matplotlib + networkx çizimleri | solver |
| `main.py` | uçtan uca çalıştırma: yükle → çiz → çöz → çiz → JSON | – |

Bu ayrımı koru. Model OR-Tools'u bilmez ve veri katmanı ayrı kalır; böylece solver değişse de
model ve veri kodu değişmez (ROADMAP'in temel ilkesi).

## Matematik

- `P(q) = base_price + slope·q`, toplam maliyet `q·P(q)`, marjinal maliyet `base_price + 2·slope·q`.
  Takas fiyatı bütün miktara uygulandığı için marjinal maliyet takas fiyatının üstündedir.
- `segments(n)`: `[0, capacity]` aralığı tamsayı sınırlarla yaklaşık eşit parçalara bölünür.
  Her parçanın birim maliyeti, o parçadaki ortalama marjinal maliyettir: `(TC(end) - TC(start)) / width`.
  Böylece parçalı toplam maliyet her sınır noktasında tam doğrudur.
- Maliyet konveks olduğu için (marjinal maliyet artıyor) parçalar paralel alt-hatlar olarak
  verilir ve solver ucuz parçayı önce doldurur. Model saf min cost flow olarak kalır.
- **Çeviri:** sanal süper kaynak talep kadar arz üretir. Süper kaynaktan her arz düğümüne giden
  hattın kapasitesi `max_supply`, birim maliyeti `unit_price`'tır. Talep düğümünün arzı `-demand`'dir.
  Maliyetler tamsayı olmalı, bu yüzden €/MWh `cost_scale = 100` ile ölçeklenir (sent).
  Kapasiteler tamsayı MW'dır.
- Problem infeasible ise `solve_max_flow_with_min_cost` ile en fazla teslim edilebilecek miktar
  en düşük maliyetle bulunur (`SolveStatus.INFEASIBLE`).
- `SolutionResult` maliyetleri son akışlardan **gerçek** pay-as-clear ile hesaplar. `objective`
  ise segment yaklaşımıdır ve biraz yüksek olabilir. Yol maliyetleri her hattın maliyetini akışa
  oranla paylaştırır, yani yolların toplamı `total_cost`'a tam eşittir.
- `capacity == 0` kapalı hat demektir; `segments()` boş döner, haritada kesikli çizilir.
- Tek talep düğümü varsayımı `validate()` ve `demand_node` içinde kodlu.

## JSON model formatı

```json
{"name": "...",
 "nodes": [{"id": "XK", "name": "Kosovo", "lat": 42.6, "lon": 20.9, "type": "demand", "demand": 400},
           {"id": "RS", "name": "Serbia", "lat": 44.0, "lon": 21.6, "type": "supply", "max_supply": 700, "unit_price": 88.0},
           {"id": "X",  "name": "...", "lat": 0, "lon": 0, "type": "transit"}],
 "arcs":  [{"from": "RS", "to": "XK", "curve": {"type": "linear", "base_price": 8.0, "slope": 0.03, "capacity": 600}}]}
```

`_build` alanları sıkı kontrol eder: eksik ya da bilinmeyen alan hata verir. Yeni bir alan
ekliyorsan dataclass'a, JSON'a ve `market_data/build_scenario.py` çıktısına birlikte ekle.

## Genişletme rehberi

- **Yeni eğri tipi:** `PriceCurve`'den türet (`capacity` + `clearing_price`), frozen dataclass yap,
  `__post_init__` içinde doğrula, `CURVE_TYPES`'a kaydet. Marjinal maliyeti azalmayan
  (konveks) olmalı. Değilse segmentler yanlış sırayla dolar ve min cost flow yanlış sonuç verir.
- **Konveks olmayan maliyetler** (fiyatın eşikte sıçradığı basamaklı eğriler, hacim indirimi,
  sabit kullanım ücreti, minimum alım): MIP ya da CP-SAT gerekir (ROADMAP "kesin model").
  Ayrı bir solver modülü yaz ve aynı `build_solution`'ı besle; `SolutionResult`'ın solver'dan
  bağımsız olması bunun için var.
- **İletim kayıpları** (arc üzerinde %): saf min cost flow desteklemez; LP'ye (`pywraplp` / GLOP) geç.
- **Birden fazla talep düğümü:** `validate`/`demand_node`, süper havuz (sink) ile çeviri,
  `decompose_paths` ve `SolutionResult` alanları birlikte değişir.
- **Zaman boyutu:** önce saat başına bağımsız çözüm (`xk-scenario`'daki döngü). Saatler arası
  bağ gerekirse çok dönemli bir model kurulur.
- Kod ya da arayüz değiştiğinde `market_data/build_scenario.py`'nin ürettiği JSON'un hâlâ
  yüklendiğini kontrol et (`xk-scenario`'daki tek saatlik komut).

## Çizim kuralları

- Renkler `map.py`'nin başındaki sabitler (dataviz paletinin ilk kategorik renkleri + nötr
  mürekkep tonları): supply mavi, demand turuncu, transit gri. Yeni grafiklerde bu sabitleri
  kullan; yeni bir grafik türü için `dataviz` skill'ini oku.
- İki yönlü hatlar ters yönlere kavisli çizilir (`PAIRED_ARC_RAD`), etiketler hatlardan
  uzak bir yöne yerleşir. Ortak yardımcılar `draw_nodes`, `draw_arcs`, `finish_map` vb.
  `solution_map` ile paylaşılır.
- Konum lat/lon üzerinden kabaca eşdikdörtgen projeksiyonla hesaplanır (`_x_scale`).

## Testler ve CLI

```bash
.venv/bin/python -m pytest -q CostOptimizationProgram        # kök dizinden
cd CostOptimizationProgram && ../.venv/bin/python -m costopt.min_cost_route_solver data/sample_network.json --json output/sample.json
cd CostOptimizationProgram && ../.venv/bin/python -m costopt.map data/sample_network.json -o output
cd CostOptimizationProgram && ../.venv/bin/python -m costopt.solution_map data/sample_network.json -o output
```

- Test stili: elle doğrulanabilecek küçük ağlar; beklenen değer hesabı yorumda yazar
  (`# A: 50 + 10 transport = 60 ...`). Yeni davranış için aynı tarzda test ekle.
- `test_main.py` üç veri dosyasını uçtan uca çalıştırıp altı çıktı dosyasını kontrol eder;
  çizim testleri `matplotlib.use("Agg")` kullanır.
- `data/sample_network.json`, `scenario_gr_demand.json` ve `scenario_xk_demand.json` elle
  yazılmış sentetik dosyalardır (uydurma slope'lar). Testler bunlara dayandığı için değerlerini
  gelişigüzel değiştirme.
- `../.venv/bin/python` ile çalıştırınca çıkan `sys.prefix` RuntimeWarning'i zararsızdır;
  kök dizinden `.venv/bin/python` ile çalıştırırsan görünmez.
