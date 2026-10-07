---
name: add-border-data
description: >
  Crawler'ların çekemediği veriyi elle ya da başka bir kaynaktan DB'ye ekleyip senaryoya
  yansıtma: kapalı ya da eksik bir sınırın (ör. BA-RS, RS-XK, AL-XK, BG-GR) kapasite ve
  takas fiyatı, o sınırın teklifleri, API'de olmayan zonların (BA, TR) spot fiyatları;
  network.py'ye yeni sınır ya da ülke ekleme. Use this whenever the user says a border is
  missing or closed in the scenario, wants to add capacity/price data from an Excel file,
  a TSO website or another source, asks "sınır verisi nasıl eklerim", "bu sınırı aç",
  "manuel veri", "özel script ile ekle", complains about placeholder spot prices for BA
  or TR, or wants to add a country or interconnector to the model.
---

# Sınır ve spot verisini elle eklemek

Kullanıcı bu akışı "çok önemli" olarak tanımladı. Adımları atlamadan ve neden yapıldığını
anlatarak uygula.

## İlkeler

- **Senaryo JSON'u elle düzenlenmez.** Veri DB'ye girer, senaryo `build_scenario.py` ile
  üretilir. Böylece her saat, her gün aynı kurallarla yeniden üretilebilir.
- **`market_data/network.py` tek listedir.** Ülkeler (`COUNTRIES`) ve her fiziksel sınır
  (`BORDERS`) orada durur. Listede olmayan bir sınırın verisi DB'de görünürse `build_scenario`
  hata verir; bu bilinçli bir tercih, hiçbir sınır habersizce modele girmesin diye.
- **Kural:** listedeki bir sınır yönü, DB'de o saat için verisi varsa açık olur; yoksa
  kapasitesi 0 olur (kapalı).
- **Elle toplanan veri `market_data/manual/*.csv` olarak saklanır ve commit edilir.** DB
  (Docker'daki PostgreSQL) git'te yok; crawl ve `import_manual.py` ile yeniden kurulur. Bu CSV'ler o verinin tek kopyası.
- **Platform verisi `MANUAL` verinin önüne geçer.** Aynı yön ve saat için ikisi de varsa
  platform kullanılır ve raporda `MANUAL ignored, platform data used` yazar.

## Hangi durum?

1. **Sınır `BORDERS`'ta var, veri dosyadan ya da elle geliyor** → aşağıdaki CSV akışı.
2. **Kaynağın API'si ya da düzenli yayını var** → yeni crawler (`market-data-crawl` skill'i,
   "Yeni bir ihale platformu eklemek").
3. **Sınır `BORDERS`'ta yok** → önce `network.py`'ye ekle (aşağıda), sonra 1 ya da 2.
4. **Yeni ülke** → `COUNTRIES` + sınırları + spot zonu (aşağıda).
5. **Bir zonun spot fiyatı yok (BA, TR)** → spot CSV'si. Bu yapılmazsa senaryo 200-300 €/MWh
   arası rastgele bir yer tutucu fiyat kullanır ve uyarı basar.

## CSV akışı

### 1. Dosyayı hazırla: `market_data/manual/<anlamlı_ad>.csv`

Dosyanın türünü başlık satırı belirler; kolon sırası serbest, bir dosyada tek tür olur.
`[...]` içindekiler isteğe bağlı.

```
results: border,delivery_date,timetable,offered_capacity_mw,clearing_price_eur_mwh
         [,requested_capacity_mw,allocated_capacity_mw,participants,awarded_participants]
bids:    border,delivery_date,timetable,quantity_mw,price_eur_mwh
spot:    zone,delivery_date,timetable,price_eur_mwh
```

Örnek (`manual/ba_rs_2026-09.csv`):

```csv
border,delivery_date,timetable,offered_capacity_mw,clearing_price_eur_mwh
BA-RS,2026-09-01,*,300,4.50
RS-BA,2026-09-01,*,250,1.20
```

- `border` **yönlüdür**: `BA-RS` = BA'dan RS'ye. Ters yön kendi satırını ister. Sınır
  `BORDERS`'ta herhangi bir yönüyle bulunmalıdır.
- `timetable` CET/CEST `'HH:00-HH:00'` biçimindedir; `*` o günün bütün saatleri demektir
  (günlük sabit kapasite gibi veriler için).
- Teklifler (`bids`) isteğe bağlıdır ama her teklif saatinin bir `results` satırı olmalıdır.
  Teklif yoksa senaryo o yönü **düz eğri** (slope 0) ile açar: aldığımız miktar fiyatı
  artırmaz, bu da o hattı olduğundan ucuz gösterebilir. Kullanıcıya bunu söyle; teklif
  verisi varsa ekle.
- Kaynakta veri aylık ya da sabit kapasite olarak geliyorsa, günlük satırlara (`*` ile)
  çeviren küçük bir dönüşümü kullanıcıyla birlikte yaz ve sonucu yine `manual/`'a koy.
  Ham kaynak dosyayı da yanında saklamayı öner.

### 2. Import et

```bash
.venv/bin/python market_data/import_manual.py                          # manual/ altındaki tüm CSV'ler
.venv/bin/python market_data/import_manual.py market_data/manual/ba_rs_2026-09.csv
```

- Script önce her şeyi doğrular, sonra yazar. Hatalar dosya ve satır numarasını gösterir
  (`ba_rs.csv:3: border 'AL-BG' is not in network.BORDERS`).
- Her yön ve gün bir `MANUAL` ihalesidir (`auction_id = MANUAL-<out>-<in>-<tarih>`);
  aynı yön-günü yeniden import etmek öncekinin yerine geçer.
- CSV'den bir satırı silmek DB'den silmez. Silmek için:

  ```python
  import sys; sys.path.insert(0, "market_data")
  import db
  conn = db.connect()   # ON DELETE CASCADE: results/bids de silinir
  conn.execute("DELETE FROM auctions WHERE source = 'MANUAL' AND auction_id = %s", ("MANUAL-BA-RS-2026-09-01",))
  ```

  Silmeden önce kullanıcıya hangi kaydın silineceğini göster ve onay al.

### 3. Doğrula

```python
import sys; sys.path.insert(0, "market_data")
import db, psycopg
conn = psycopg.connect(db.database_url())
print(conn.execute("""SELECT border, delivery_date, count(*), min(offered_capacity_mw), max(clearing_price_eur_mwh)
                      FROM results_v WHERE source = 'MANUAL' GROUP BY 1, 2""").fetchall())
```

### 4. Senaryoyu kur ve raporu oku

```bash
.venv/bin/python market_data/build_scenario.py --date 2026-09-01 --timetable 14:00-15:00
```

Raporda sınırın yeri değişmeli: `Closed, no daily auction known` satırından
`Open: BA->RS MANUAL` satırına ya da teklif yoksa `Open with flat curve (no bids)` satırına
geçer. Spot için `WARNING random placeholder spot price` satırından ilgili zon düşer.
Çözüm ve yorum için `xk-scenario` skill'ine bak.

## `network.py`'yi düzenlemek

```python
BORDERS = {
    ("BA", "RS"): None,   # no daily auction found on JAO/SEECAO
    ("MK", "XK"): "SEECAO",
}
```

- Anahtar alfabetik sıralı bir çifttir (`a < b`) ve iki yönü birden kapsar.
- Değer, günlük ihaleyi yayınlaması beklenen kaynaktır (`"JAO"`, `"SEECAO"`, yeni bir
  platform adı) ya da bilinen bir kaynak yoksa `None`.
  - Kaynak yazılıysa ve veri yoksa rapor `WARNING closed, expected data missing` der
    (ör. o gün crawl başarısız olmuş).
  - `None` ise sınır sessizce kapalı kalır; `MANUAL` veri gelirse açılır. Elle veri
    eklenen sınırlarda değeri `None` bırakmak doğrudur; `MANUAL` "beklenen kaynak" değildir.
- Satır sonuna kısa bir gerekçe yaz (`# not in operation`, `# market coupled` gibi).
  Gerekçeyi bilmiyorsan uydurma, kullanıcıya sor.

**Yeni ülke:** `COUNTRIES`'e `"ID": (ad, enlem, boylam, max_supply)` ekle (`max_supply`
şimdilik yer tutucudur, kullanıcıya sor). Sonra sınırlarını `BORDERS`'a ekle. Fiyat API'si o
zonu sunuyorsa (`curl -s 127.0.0.1:8000/zones`) `market_data/spot_prices.py` içindeki `ZONES`
listesine ekle; sunmuyorsa spot CSV'si gerekir.

Crawler yalnızca modellenen ülkeleri sakladığı için yeni ülkenin geçmiş verisi DB'de yoktur:
- **İhaleler:** aynı tarih aralığını `main.py` ile yeniden çalıştırmak yeterli. Saklanan
  ihaleler atlanır, yeni ülkeninkiler eklenir.
- **Spot:** zaten spot fiyatı olan günler zon fark etmeksizin atlanır. Yeni zonun geçmişi için
  `--refresh` gerekir; bu, o aralıktaki her şeyi yeniden indirir ve uzun sürer.

Her `network.py` değişikliğinden sonra: `.venv/bin/python -m pytest -q market_data`.

## Bilinen sınırlamalar

- Kış saatine geçiş gününde (25 saat) `'02:00-03:00'` iki saate karşılık gelir; import bu
  `timetable` için hata verir. `*` çalışır. Senaryo da o saat için hata verir.
- `CostOptimizationProgram/data/scenario_xk_demand.json` elle yazılmış sentetik bir dosyadır;
  bu akış onu değiştirmez.
