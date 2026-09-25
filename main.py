"""
Sınırlar arası ithalat: kapasite ihalesinin fiyat etkisini hesaba katan
iki aşamalı stokastik model (OR-Tools / SCIP, MIP)

1. aşama (ihale, spot bilinmeden): her sınırda kaç MW kapasite alınacak?
2. aşama (her senaryo için, spot belli olduktan sonra): alınan kapasite
   içinde enerji hangi rotalardan, hangi ülkelerden alınacak?

Varsayım: kapasite ihalesi birörnek (marjinal) fiyatlı; biz tavan fiyattan
teklif veriyoruz, yani istediğimiz miktarı kesin alıyoruz ama takas fiyatı
bizim miktarımıza göre yükseliyor. Tüm veriler ÖRNEK/UYDURMADIR.
"""
from ortools.linear_solver import pywraplp

HEDEF = "A"
TALEP = 500        # MWh (1 saatlik teslimat)
MAKS_SINIR = 6     # bir rotanın geçebileceği en fazla sınır sayısı
ADIM = 5          # kapasite karar adımı (MW); küçüldükçe hassasiyet artar
TAVAN = 250.0      # bizim ihale teklif fiyatımız (€/MWh)

# Spot likidite kademeleri (baz): [(hacim MWh, fiyat €/MWh), ...] artan fiyatlı
ARZ = {
    "B": [(150, 95.0), (200, 100.0)],
    "C": [(200, 72.0), (150, 78.0)],
    "D": [(200, 80.0), (150, 85.0)],
    "E": [(150, 76.0), (100, 82.0)],
}

# Yönlü sınırlar: (çıkış, varış): (ATC MW, diğer katılımcıların tahmini
# teklif eğrisi [(fiyat €/MWh, miktar MW), ...])
SINIRLAR = {
    ("B", "A"): (450, [(15, 100), (9, 150), (7, 150), (4, 100)]),
    ("C", "A"): (250, [(120, 40), (70, 110), (6, 50), (5, 90), (3, 60)]),
    ("D", "B"): (300, [(8, 100), (4, 150), (2, 100)]),
    ("D", "C"): (100, [(5, 50), (2, 80)]),
    ("E", "D"): (250, [(10, 80), (5, 120), (3, 100)]),
    ("E", "C"): (120, [(12, 60), (8, 50), (4, 40)]),
}

# Senaryolar: rakip teklif fiyat/hacim çarpanı, spot kayması, A'nın yerel fiyatı
# (yerel: ithalat yerine A'nın kendi piyasasından alım; ithalatı zorunlu
#  kılmak için çok yüksek bir değer yazın)
SENARYOLAR = {
# spot_d: ülke bazında baz fiyata eklenecek kayma (€/MWh)
    "düşük rekabet": dict(olasilik=0.25, fiyat_c=0.7, hacim_c=0.8, yerel=110,
                          spot_d={"B": -8, "C": -2, "D": -4, "E": -3}),
    "baz":           dict(olasilik=0.50, fiyat_c=1.0, hacim_c=1.0, yerel=120,
                          spot_d={"B": 0, "C": 0, "D": 0, "E": 0}),
    "yüksek rekabet": dict(olasilik=0.25, fiyat_c=1.4, hacim_c=1.2, yerel=135,
                          spot_d={"B": 12, "C": 4, "D": 10, "E": 3}),
}


def takas_fiyati(teklifler, atc, bizim):
    """Birörnek fiyatlı ihale: fiyat = kabul edilen en düşük teklif.
    Talep kapasiteyi aşmıyorsa fiyat 0. Tüm kapasiteyi biz alırsak
    en düşük kabul edilen teklif bizimki olur ve TAVAN'ı öderiz."""
    if bizim + sum(v for _, v in teklifler) <= atc:
        return 0.0
    kalan = atc - bizim
    if kalan <= 1e-9:
        return TAVAN
    for fiyat, hacim in sorted(teklifler, reverse=True):
        kalan -= hacim
        if kalan <= 1e-9:
            return fiyat
    return 0.0


def senaryo_teklifleri(e, s):
    sc = SENARYOLAR[s]
    return [(p * sc["fiyat_c"], v * sc["hacim_c"]) for p, v in SINIRLAR[e][1]]


def rotalari_bul():
    rotalar = []

    def dfs(yol):
        if yol[-1] == HEDEF:
            rotalar.append(tuple(yol))
            return
        if len(yol) - 1 >= MAKS_SINIR:
            return
        for (u, v) in SINIRLAR:
            if u == yol[-1] and v not in yol:
                dfs(yol + [v])

    for k in ARZ:
        dfs([k])
    return rotalar


def kenarlar(r):
    return list(zip(r[:-1], r[1:]))


def coz(mod="etkili", sabit_kap=None, yazdir=True):
    """mod='etkili': fiyat etkisi hesaba katılır (MIP).
    mod='naif': kapasite fiyatı, bizim alımımızdan bağımsız sanılır (LP).
    sabit_kap verilirse kapasite kararı sabitlenir, yalnızca 2. aşama çözülür."""
    rotalar = rotalari_bul()
    s = pywraplp.Solver.CreateSolver("SCIP")
    maliyet = 0

    # --- 1. aşama: kapasite kararı ---
    kap = {}
    if sabit_kap is not None:
        kap = dict(sabit_kap)
    elif mod == "etkili":
        y = {}
        for e, (atc, _) in SINIRLAR.items():
            seviyeler = list(range(0, atc + 1, ADIM))
            y[e] = {l: s.BoolVar(f"y_{e}_{l}") for l in seviyeler}
            s.Add(sum(y[e].values()) == 1)
            kap[e] = sum(l * v for l, v in y[e].items())
            for sn, sc in SENARYOLAR.items():
                tk = senaryo_teklifleri(e, sn)
                maliyet += sc["olasilik"] * sum(
                    l * takas_fiyati(tk, atc, l) * v for l, v in y[e].items())
    else:  # naif
        for e, (atc, _) in SINIRLAR.items():
            kap[e] = s.NumVar(0, atc, f"kap_{e}")
            for sn, sc in SENARYOLAR.items():
                p0 = takas_fiyati(senaryo_teklifleri(e, sn), atc, 0)
                maliyet += sc["olasilik"] * p0 * kap[e]

    # --- 2. aşama: her senaryoda enerji alımı ve rotalama ---
    x, yerel = {}, {}
    for sn, sc in SENARYOLAR.items():
        x[sn] = {r: s.NumVar(0, s.infinity(), "") for r in rotalar}
        yerel[sn] = s.NumVar(0, s.infinity(), "")
        s.Add(sum(x[sn].values()) + yerel[sn] == TALEP)
        for c, kd in ARZ.items():
            q = [s.NumVar(0, h, "") for h, _ in kd]
            s.Add(sum(x[sn][r] for r in rotalar if r[0] == c) == sum(q))
            maliyet += sc["olasilik"] * sum(
                qi * (p + sc["spot_d"][c]) for qi, (_, p) in zip(q, kd))
        for e in SINIRLAR:
            s.Add(sum(x[sn][r] for r in rotalar if e in kenarlar(r)) <= kap[e])
        maliyet += sc["olasilik"] * sc["yerel"] * yerel[sn]

    s.Minimize(maliyet)
    if s.Solve() != pywraplp.Solver.OPTIMAL:
        raise RuntimeError("Optimum çözüm bulunamadı")

    kap_deger = {e: (v if isinstance(v, (int, float)) else v.solution_value())
                 for e, v in kap.items()}
    # Gerçek (fiyat etkili) beklenen kapasite maliyeti
    kap_maliyet = sum(sc["olasilik"] * m * takas_fiyati(senaryo_teklifleri(e, sn), SINIRLAR[e][0], m)
                      for e, m in kap_deger.items() for sn, sc in SENARYOLAR.items())
    if yazdir:
        print("Kapasite kararları (ihaleye girilecek miktarlar):")
        for e, m in kap_deger.items():
            if m > 1e-6:
                fiyatlar = " / ".join(
                    f"{takas_fiyati(senaryo_teklifleri(e, sn), SINIRLAR[e][0], m):.1f}"
                    for sn in SENARYOLAR)
                print(f"  {e[0]}->{e[1]}: {m:5.0f} / {SINIRLAR[e][0]} MW   "
                      f"takas fiyatı (düşük/baz/yüksek): {fiyatlar} €/MWh")
        bloklar = {}  # aynı sonucu veren senaryoları birlikte yazdır
        for sn in SENARYOLAR:
            satirlar = [f"  {' -> '.join(r):<16} {x[sn][r].solution_value():6.1f} MWh"
                        for r in sorted(rotalar, key=lambda r: -x[sn][r].solution_value())
                        if x[sn][r].solution_value() > 1e-6]
            if yerel[sn].solution_value() > 1e-6:
                satirlar.append(f"  A yerel piyasa   {yerel[sn].solution_value():6.1f} MWh")
            bloklar.setdefault("\n".join(satirlar), []).append(sn)
        for blok, adlar in bloklar.items():
            print(f"\nEnerji rotaları [{', '.join(adlar)}]:\n{blok}")
    return kap_deger, s.Objective().Value(), kap_maliyet


def egri_yazdir(e, adim=20):
    """Bir sınırda alım miktarına göre takas fiyatı ve maliyet (baz senaryo)."""
    atc = SINIRLAR[e][0]
    print(f"\n{e[0]}->{e[1]} fiyat etkisi eğrisi (baz senaryo):")
    print("   MW   takas €/MWh   toplam €   son adımın marjinal maliyeti €/MWh")
    onceki = 0.0
    for m in range(adim, atc + 1, adim):
        f = takas_fiyati(senaryo_teklifleri(e, "baz"), atc, m)
        top = m * f
        print(f"  {m:4d}   {f:10.1f}   {top:9,.0f}   {(top - onceki) / adim:10.1f}")
        onceki = top


if __name__ == "__main__":
    print("=== FİYAT ETKİSİNİ HESABA KATAN MODEL ===")
    kap, amac, kap_m = coz("etkili")
    print(f"\nBeklenen toplam maliyet: {amac:,.0f} €  (kapasite: {kap_m:,.0f} €)")

    print("\n=== KARŞILAŞTIRMA: FİYAT ETKİSİNİ YOK SAYAN (NAİF) MODEL ===")
    naif_kap, _, _ = coz("naif", yazdir=False)
    naif_kap = {e: round(m) for e, m in naif_kap.items()}
    print("Naif modelin ihale miktarları: " +
          ", ".join(f"{e[0]}->{e[1]} {m} MW" for e, m in naif_kap.items() if m))
    _, enerji_naif, kap_naif = coz(sabit_kap=naif_kap, yazdir=False)
    print(f"Naif kararın GERÇEK beklenen maliyeti: {enerji_naif + kap_naif:,.0f} €  "
          f"(kapasite: {kap_naif:,.0f} €)")
    print(f"Fiyat etkisini modellemenin kazancı: {enerji_naif + kap_naif - amac:,.0f} €")
    egri_yazdir(("C", "A"))