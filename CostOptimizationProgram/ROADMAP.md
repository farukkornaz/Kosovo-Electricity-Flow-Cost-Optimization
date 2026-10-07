# CostOptimizationProgram — Yol Haritası

Sınır ötesi elektrik ithalat/ihracat maliyet optimizasyonu.
Çekirdek mantık: `../or-tools-examples/Flows/minimum-cost-flow-2.py` (süper kaynak + min cost flow).

Gerçek veri henüz yok; tüm fiyat ve miktarlar yapay. Veri katmanı ayrı tutulduğu için
ileride gerçek veriye geçişte model/solver kodu değişmeyecek.

---

## Hedef klasör yapısı

```
CostOptimizationProgram/
├── ROADMAP.md
├── requirements.txt
├── main.py                        # uçtan uca çalıştırma: veri → model → çöz → görselleştir
├── data/
│   └── sample_network.json        # yapay ülkeler, hatlar, fiyat eğrileri
├── costopt/
│   ├── __init__.py
│   ├── price_curve.py             # PriceCurve: kademeli (artan) fiyat-miktar eğrisi + max fiyat
│   ├── model.py                   # NetworkModel: node, supply, demand, arc tanımları
│   ├── data_loader.py             # JSON/CSV → NetworkModel
│   ├── map.py                     # modelin görselleştirilmesi (kontrol amaçlı)
│   ├── min_cost_route_solver.py   # modeli OR-Tools'a çevirir, çözer, SolutionResult döner
│   ├── solution.py                # SolutionResult: akışlar, yollar, maliyet kırılımı
│   └── solution_map.py            # çözümün harita üzerinde gösterimi
└── tests/
```

> Not: Python'da modül adında `-` kullanılamaz (import edilemez), bu yüzden
> `minimum-cost-route-solver` → `min_cost_route_solver.py`.

---

## Aşama 0 — Kurulum
- [x] `CostOptimizationProgram/` klasörü
- [x] `requirements.txt` (ortools, numpy, networkx, matplotlib; ileride folium/plotly)
- [x] Paket iskeleti (`costopt/`)

## Aşama 1 — Arc fiyat eğrisi (`price_curve.py`) ✅
Her arc (hat kapasitesi ihalesi) için **bizim alım miktarımıza bağlı takas fiyatı** `P(q)`:

- Diğer katılımcıların teklifleriyle ihalede doğal olarak oluşacak bir fiyat var (`p0`).
- Biz malı kesin almak için yüksek fiyatla teklif veririz (teklif stratejisi, modelin konusu değil).
- Teklif ettiğimiz miktar `q` talebi sağa kaydırır; miktar yeterince büyükse takas fiyatı yükselir.
  Yani arc'ın birim maliyeti `P(q)`, `q` ile artar.
- **Ödeme kuralı: pay-as-clear (JAO gibi).** Takas fiyatı tüm miktara uygulanır.
  - Toplam maliyet `q · P(q)` olur. Marjinal maliyet takas fiyatından yüksektir,
    solver'a verilecek kademe maliyetleri buna göre hesaplanır.
  - `P(q)` sürekli/doğrusal kabul edilirse maliyet konvekstir ve arc, artan marjinal maliyetli
    **paralel alt-arc'lara** bölünür. Model saf min cost flow olarak kalır.
  - `P(q)` basamaklı alınırsa (fiyat sadece eşik aşılınca sıçrar) maliyet konveks olmaz,
    bu da MIP/CP-SAT gerektirir. Bu, ileride "kesin model" olarak eklenebilir.
- Yapay eğri üreticisi: `p0`, eğim, hat kapasitesi.
- OR-Tools tamsayı ister: fiyatlar ölçeklenir (örn. €/MWh × 100), sonuçta geri çevrilir.

**Supply node maliyeti sabittir** (birim fiyat × miktar), eğri yoktur.

## Aşama 2 — Model (`model.py`, `data_loader.py`) ✅
- `Node` (ülke/bölge: id, ad, koordinat), `SupplyNode` (max arz + sabit birim fiyat),
  `DemandNode` (sabit talep), `Arc` (hat: from, to, kapasite, fiyat eğrisi).
- `NetworkModel`: ekleme/doğrulama metodları (tek talep noktası, eksik node, negatif kapasite vb.).
- Yapay örnek ağ: ülke düğümleri (örn. TR, BG, GR, RO, GE, ...), aralarında hatlar.
- Veri JSON'dan okunur; model kodu veriden bağımsız.

## Aşama 3 — Model görselleştirme (`map.py`) ✅
- Girdi: `NetworkModel`. Çıktı: node/arc grafiği (networkx + matplotlib).
- Supply/demand node'lar farklı renk, arc üzerinde kapasite ve fiyat aralığı etiketi.
- Amaç: kurulan modelin doğru olduğunu gözle kontrol etmek.
- İleride: coğrafi harita (folium/plotly) üzerinde gerçek koordinatlarla.

## Aşama 4 — Solver (`min_cost_route_solver.py`, `solution.py`) ✅
- `NetworkModel` → süper kaynak + kademeli alt-arc'lar → `SimpleMinCostFlow`.
- Çıktı `SolutionResult`:
  - toplam maliyet (arz maliyeti + iletim maliyeti)
  - hangi supply node'dan ne kadar alındı, hangi kademeden
  - her arc'taki akış ve kullanılan kademeler
  - **yollar**: akış ayrıştırma ile "X'ten Y MW, A→B→C güzergâhından, Z € maliyetle" formatında
- Durumlar: optimal / infeasible (talep karşılanamıyor) / hatalı girdi.
- Opsiyon: karşılanamayan talep için yüksek cezalı "slack" arz, böylece çözüm her zaman
  döner ve eksik miktar raporlanır.

## Aşama 5 — Çözüm görselleştirme (`solution_map.py`) ✅
- Girdi: `NetworkModel` + `SolutionResult`.
- Kullanılan arc'lar akış miktarına göre kalınlıkta, kullanılmayanlar soluk.
- Supply node'larda alınan miktar/max; yolların ayrı ayrı vurgulanması.

## Aşama 6 — `main.py` ve testler ✅
- Uçtan uca akış tek komutla çalışır.
- Testler: elle doğrulanabilir küçük ağlar, kademe sırası, max fiyat kesmesi, infeasible durumu.

---

## Sonraki genişlemeler (çekirdek oturduktan sonra)
- **Zaman boyutu**: saatlik/günlük çözüm (24 saatlik talep, her saat farklı eğri).
- **İletim kayıpları**: arc üzerinde % kayıp. Saf min cost flow bunu desteklemez;
  LP'ye (OR-Tools `pywraplp`/GLOP) geçiş gerekir.
- **Sabit maliyetler** (hat/tedarikçi kullanım ücreti, minimum alım): MIP / CP-SAT.
- **Azalan fiyatlı eğriler** (hacim indirimi): konveks olmadığı için MIP gerekir.
- **Çift yönlü hatlar / ihracat senaryoları**, birden fazla talep noktası.
- **Gerçek veri**: ENTSO-E Transparency (fiyat, NTC), JAO (kapasite ihaleleri); `data_loader` genişletilir.
- Senaryo analizi ve raporlama (CSV/Excel çıktı).

---

## Proje geneli — bekleyen işler

Altyapı ayarları (Docker, PostgreSQL, 2026 Ağustos–Eylül verisi) bitmeden bunlara geçilmeyecek.

### `auction_analysis/` — ihale fiyatı tahmini (yeni klasör, kökte)
- Amaç: JAO/SEECAO günlük ihale takas fiyatlarını (`clearing_price_eur_mwh`) farklı modellerle
  tahmin etmek ve modelleri karşılaştırmak (benchmark).
- İlk aday model **LSTM**. Duruma göre başka modeller de denenecek; basit referans modeller
  (dünün/geçen haftanın aynı saati gibi) benchmark'ın tabanı olmalı.
- **Feature analizi önemli**, modelden önce yapılacak. Aday feature'lar: aynı sınırın gecikmeli
  fiyatları, sunulan kapasite, katılımcı sayısı, talep/kapasite oranı, iki uçtaki spot fiyat
  farkı, saat / haftanın günü / tatil, komşu sınırların fiyatları, teklif eğrisinin şekli.
- Veri PostgreSQL'den (`results_v`, `bids_v`, `spot_prices`). İki aylık veri başlangıç için;
  model eğitimi için daha uzun geçmiş gerekebilir.

### Diğer notlar
- **Slope kalibrasyonu:** fiyat eğrisinin eğimini yaklaşık bir yıllık tekliflerden kalibre etmek.
- **Kapalı sınırlar:** RS-XK, AL-XK, BA-RS, BG-GR vb. için elle ya da başka kaynaktan veri.
- **BA ve TR spot fiyatları:** API'de yok; şu an senaryoda yer tutucu fiyat kullanılıyor.
- **`max_supply`** değerleri (`market_data/network.py`) yer tutucu; gerçek veriyle değişmeli.
