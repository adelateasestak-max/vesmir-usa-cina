"""Scénáře vývoje 2026–2035 (MODELOVÝ ODHAD, ne fakt). Vstup: reálná historická data z GCAT/CelesTrak v databázi.
Metodika (transparentně):
  1) Starty: kotva = rok 2026 přepočtený na celý rok podle tempa do posledního dne v datech.
     Základní růst g0 = CAGR (průměrný roční růst) 2021 -> 2026e pro každou zemi.
     Ve scénáři: růst v roce t = g0 * m_zeme * 0.8^(t-2026)  (m = násobek trendu; útlum 0.8 = růst se zpomaluje),
     plus případný jednorázový šok (pokles v %) v daném roce.
  2) Aktivní družice = mega-konstelace + ostatní. Konstelace míří po S-křivce od dnešního stavu k cíli v roce 2035
     (cíl = podíl veřejně oznámeného plánu). Ostatní aktivní družice rostou o r_ostatni ročně (historicky viz katalog).
  3) Objekty v LEO (všechny státy, katalog CelesTrak): úlomky rostou o r_odpad ročně + jednorázové fragmentace
     (velikost ~3 000 sledovaných úlomků = čínský test ASAT 2007); družice v LEO = dnešní stav + přírůstek modelovaných družic USA/Číny.
  4) Pravděpodobnosti scénářů jsou EXPERTNÍ ODHAD autora prototypu (součet 100 %), ne statistický výpočet.
"""
import math, datetime as dt
import pandas as pd

ROKY = list(range(2026, 2036))
PLAN = {  # veřejně oznámené plány (zdroj: Wikipedie, stav 11/2026)
    "Starlink": {"plan": 12000, "plan_max": 42000, "zdroj": "https://en.wikipedia.org/wiki/Starlink", "pozn": "téměř 12 000 plánováno, možné rozšíření na 42 000"},
    "Kuiper": {"plan": 3236, "zdroj": "https://en.wikipedia.org/wiki/Amazon_Leo", "pozn": "povolení FCC 2020 na 3 236 družic (Amazon Leo)"},
    "Guowang": {"plan": 13000, "zdroj": "https://en.wikipedia.org/wiki/Guowang", "pozn": "plán přes 13 000 družic"},
    "Qianfan": {"plan": 15000, "zdroj": "https://en.wikipedia.org/wiki/Qianfan", "pozn": "plán přes 15 000, 1. fáze 1 296"},
}
SCEN = [
    {"id": "S1", "nazev": "Nejhorší: konflikt + řetězové srážky (Kessler)", "pst": 5, "barva": "#8b0000",
     "popis": "Ozbrojený konflikt nebo test protidružicových zbraní vytvoří velká pole úlomků (2028 a 2031). Pojištění a provoz v LEO se prudce zdraží, starty klesnou, část družic je ztracena nebo se nedoplňuje.",
     "m": {"USA": -0.25, "Čína": -0.25}, "sok": {2028: -0.35}, "r_ostatni": -0.03, "r_odpad": 0.06, "fragmentace": {2028: 3000, 2031: 3000},
     "konst": {"Starlink": 9000, "Kuiper": 0.25, "Guowang": 0.04, "Qianfan": 0.03}},
    {"id": "S2", "nazev": "Špatný: napětí, sankce, technické neúspěchy", "pst": 20, "barva": "#e3b341",
     "popis": "Obchodní a technologické sankce, zdržení nových raket (Starship, New Glenn, čínské znovupoužitelné rakety), finanční potíže konstelací. Růst se zastaví na zhruba dnešní úrovni.",
     "m": {"USA": 0.1, "Čína": 0.2}, "sok": {}, "r_ostatni": 0.02, "r_odpad": 0.04, "fragmentace": {2030: 1000},
     "konst": {"Starlink": 12000, "Kuiper": 0.6, "Guowang": 0.15, "Qianfan": 0.1}},
    {"id": "S3", "nazev": "Nominální: trend se postupně zpomaluje", "pst": 45, "barva": "#8b949e",
     "popis": "Pokračuje dnešní vývoj s přirozeným zpomalením růstu. Starlink udržuje a mírně rozšiřuje síť, Amazon Leo dokončí povolenou sestavu, čínské sítě rostou, ale pomaleji než plány.",
     "m": {"USA": 0.5, "Čína": 0.8}, "sok": {}, "r_ostatni": 0.05, "r_odpad": 0.03, "fragmentace": {},
     "konst": {"Starlink": 15000, "Kuiper": 1.0, "Guowang": 0.35, "Qianfan": 0.25}},
    {"id": "S4", "nazev": "Dobrý: Starship v provozu + čínská znovupoužitelnost", "pst": 22, "barva": "#3fb950",
     "popis": "Plně znovupoužitelné rakety (Starship, čínské Zhuque-3, CZ-12A aj.) výrazně zlevní starty, konstelace se rozšiřují rychleji. Lepší pravidla pro odklízení družic brzdí růst odpadu.",
     "m": {"USA": 0.8, "Čína": 1.4}, "sok": {}, "r_ostatni": 0.08, "r_odpad": 0.02, "fragmentace": {},
     "konst": {"Starlink": 25000, "Kuiper": 1.0, "Guowang": 0.7, "Qianfan": 0.5}},
    {"id": "S5", "nazev": "Nejlepší: technologický průlom", "pst": 8, "barva": "#58a6ff",
     "popis": "Masově levný přístup do vesmíru, plány všech konstelací se plní, aktivní odklízení odpadu funguje. Spíše horní mez možností než očekávání.",
     "m": {"USA": 1.0, "Čína": 1.8}, "sok": {}, "r_ostatni": 0.12, "r_odpad": 0.01, "fragmentace": {},
     "konst": {"Starlink": 35000, "Kuiper": 1.0, "Guowang": 1.0, "Qianfan": 1.0}},
]
assert sum(s["pst"] for s in SCEN) == 100


def satcat_history(satcat_path, y0=1990, y1=2025):
    s = pd.read_csv(satcat_path, dtype=str)
    s["ly"] = pd.to_datetime(s["LAUNCH_DATE"], errors="coerce").dt.year
    s["dy"] = pd.to_datetime(s["DECAY_DATE"], errors="coerce").dt.year
    s["apo"] = pd.to_numeric(s["APOGEE"], errors="coerce"); s["per"] = pd.to_numeric(s["PERIGEE"], errors="coerce")
    s["leo"] = s["apo"] < 2000
    # rok katalogizace (úlomky mají v katalogu datum startu "rodiče", vznikly ale později):
    # NORAD čísla se přidělují postupně -> rok = první rok, jehož nejvyšší NORAD číslo družice (PAY) je >= číslu objektu
    s["nid"] = pd.to_numeric(s["NORAD_CAT_ID"], errors="coerce")
    mn = s[(s.OBJECT_TYPE == "PAY") & (s.nid < 70000)].groupby("ly")["nid"].quantile(0.05).cummax()  # první čísla roku
    import numpy as np
    yrs, ids = mn.index.values, mn.values
    s["cy"] = [yrs[max(np.searchsorted(ids, v, side="right") - 1, 0)] if v == v else np.nan for v in s["nid"]]
    s.loc[s.nid >= 70000, "cy"] = np.nan  # analytická/nová čísla -> nelze určit, ponechá se rok startu
    s["ly"] = np.fmax(s["ly"], s["cy"])
    s = s[s["ORBIT_CENTER"].fillna("EA") == "EA"]
    hist = {"roky": list(range(y0, y1 + 1)), "pay_orbit": {}, "leo": {}}
    for own, z in [("US", "USA"), ("PRC", "Čína")]:
        o = s[(s.OWNER == own) & (s.OBJECT_TYPE == "PAY")]
        hist["pay_orbit"][z] = [int(((o.ly <= y) & (o.dy.isna() | (o.dy > y))).sum()) for y in hist["roky"]]
    for t in ["PAY", "R/B", "DEB"]:
        o = s[(s.OBJECT_TYPE == t) & s.leo]
        hist["leo"][t] = [int(((o.ly <= y) & (o.dy.isna() | (o.dy > y))).sum()) for y in hist["roky"]]
    # dnešní výškový profil LEO (všechny objekty na dráze), po 50 km
    now = s[s.dy.isna() & s.leo & s.per.notna()].copy()
    now["h"] = ((now.apo + now.per) / 2 // 50 * 50).astype(int)
    prof = now.groupby(["h", "OBJECT_TYPE"]).size().unstack(fill_value=0)
    prof = prof[(prof.index >= 150) & (prof.index < 2000)]
    hist["profil"] = {"h": [int(x) for x in prof.index], **{t: [int(v) for v in prof.get(t, pd.Series(0, index=prof.index))] for t in ["PAY", "R/B", "DEB"]}}
    hist["pozn"] = "Historie = objekty v katalogu CelesTrak SATCAT, které byly v daném roce na dráze (start/katalogizace <= rok, zánik po roce). Rok vzniku úlomků je odhadnut z pořadí katalogových čísel NORAD. Malé úlomky (< ~10 cm) katalog nezná."
    hist["na_orbite_dnes"] = {t: int((s.dy.isna() & (s.OBJECT_TYPE == t)).sum()) for t in ["PAY", "R/B", "DEB", "UNK"]}
    hist["na_orbite_dnes_zeme"] = {z: {t: int((s.dy.isna() & (s.OBJECT_TYPE == t) & (s.OWNER == own)).sum()) for t in ["PAY", "R/B", "DEB"]} for own, z in [("US", "USA"), ("PRC", "Čína")]}
    hist["leo_dnes"] = {t: int((s.dy.isna() & s.leo & (s.OBJECT_TYPE == t)).sum()) for t in ["PAY", "R/B", "DEB"]}
    return hist


def scurve(a, b, n_years, t):  # plynulý přechod z a do b za n_years (t = 0..n_years)
    x = min(max(t / n_years, 0), 1)
    return a + (b - a) * (3 * x * x - 2 * x * x * x)


def build(st, satcat_path):
    last_day = dt.date.fromisoformat(st["posledni_start_v_datech"])
    frac = (last_day - dt.date(last_day.year, 1, 1)).days + 1
    frac = frac / (366 if last_day.year % 4 == 0 else 365)
    roky_h = st["roky"]
    i26 = roky_h.index(2026) if 2026 in roky_h else None
    out = {"roky": ROKY, "metodika": __doc__, "scenare": [], "plany": PLAN}
    base = {}
    for z in ["USA", "Čína"]:
        ytd = st["starty"][z][i26]
        e26 = ytd / frac
        y21 = st["starty"][z][roky_h.index(2021)]
        g0 = (e26 / y21) ** (1 / 5) - 1
        base[z] = {"2026_do_data": ytd, "2026_odhad": round(e26, 1), "podil_roku": round(frac, 3), "cagr_2021_2026e": round(g0, 4)}
    out["zaklad"] = base
    act = st["aktivni"]; kon = {k: v["aktivni"] for k, v in st["konstelace"].items()}
    ost = {"USA": act["USA"] - kon["Starlink"] - kon["Kuiper"], "Čína": act["Čína"] - kon["Guowang"] - kon["Qianfan"]}
    hist = satcat_history(satcat_path)
    out["historie"] = hist
    leo0 = hist["leo_dnes"]
    for sc in SCEN:
        r = {k: sc[k] for k in ["id", "nazev", "pst", "barva", "popis", "r_ostatni", "r_odpad"]}
        r["predpoklady"] = {"m_trend": sc["m"], "sok": sc["sok"], "fragmentace": sc["fragmentace"], "konst_cil_2035": sc["konst"]}
        r["starty"] = {}
        for z in ["USA", "Čína"]:
            v = [base[z]["2026_odhad"]]
            for t in ROKY[1:]:
                g = base[z]["cagr_2021_2026e"] * sc["m"][z] * 0.8 ** (t - 2026)
                v.append(v[-1] * (1 + g) * (1 + sc["sok"].get(t, 0)))
            r["starty"][z] = [round(x) for x in v]
        r["konstelace"] = {}
        for k, cil in sc["konst"].items():
            target = cil if cil > 1.5 else cil * PLAN[k]["plan"]
            target = max(target, 0)
            r["konstelace"][k] = [round(scurve(kon[k], target, 9, t - 2026)) for t in ROKY]
        r["aktivni"] = {}
        for z, ks in [("USA", ["Starlink", "Kuiper"]), ("Čína", ["Guowang", "Qianfan"])]:
            r["aktivni"][z] = [round(ost[z] * (1 + sc["r_ostatni"]) ** (t - 2026) + sum(r["konstelace"][k][i] for k in ks)) for i, t in enumerate(ROKY)]
        deb, frag_acc = [], 0
        for t in ROKY:
            frag_acc += sc["fragmentace"].get(t, 0)
            deb.append(round(leo0["DEB"] * (1 + sc["r_odpad"]) ** (t - 2026) + frag_acc))
        d_act = [r["aktivni"]["USA"][i] + r["aktivni"]["Čína"][i] - act["USA"] - act["Čína"] for i in range(len(ROKY))]
        r["leo"] = {"DEB": deb, "R/B": [round(leo0["R/B"] * (1 + sc["r_odpad"] / 2) ** (t - 2026)) for t in ROKY],
                    "PAY": [max(0, round(leo0["PAY"] + d)) for d in d_act]}
        r["leo"]["celkem"] = [a + b + c for a, b, c in zip(r["leo"]["DEB"], r["leo"]["R/B"], r["leo"]["PAY"])]
        out["scenare"].append(r)
    # vážený průměr
    W = {"id": "VAZ", "nazev": "Vážený průměr (podle pravděpodobností)", "pst": None, "barva": "#ffffff"}
    def wavg(get):
        return [round(sum(s["pst"] / 100 * get(s)[i] for s in out["scenare"])) for i in range(len(ROKY))]
    W["starty"] = {z: wavg(lambda s, z=z: s["starty"][z]) for z in ["USA", "Čína"]}
    W["aktivni"] = {z: wavg(lambda s, z=z: s["aktivni"][z]) for z in ["USA", "Čína"]}
    W["konstelace"] = {k: wavg(lambda s, k=k: s["konstelace"][k]) for k in PLAN}
    W["leo"] = {k: wavg(lambda s, k=k: s["leo"][k]) for k in ["DEB", "R/B", "PAY", "celkem"]}
    out["vazeny"] = W
    out["dnes"] = {"aktivni": act, "konstelace": kon, "ostatni": ost}
    return out


def to_rows(P):
    rows = []
    for s in P["scenare"] + [P["vazeny"]]:
        for i, y in enumerate(P["roky"]):
            row = {"scénář": s["id"], "název": s["nazev"], "pravděpodobnost_%": s["pst"], "rok": y,
                   "starty_USA": s["starty"]["USA"][i], "starty_Čína": s["starty"]["Čína"][i],
                   "aktivní_USA": s["aktivni"]["USA"][i], "aktivní_Čína": s["aktivni"]["Čína"][i]}
            row.update({f"konst_{k}": s["konstelace"][k][i] for k in P["plany"]})
            row.update({"LEO_úlomky": s["leo"]["DEB"][i], "LEO_horní_stupně": s["leo"]["R/B"][i], "LEO_družice": s["leo"]["PAY"][i], "LEO_celkem": s["leo"]["celkem"][i]})
            rows.append(row)
    return rows
