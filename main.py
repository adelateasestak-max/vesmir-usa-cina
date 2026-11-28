#!/usr/bin/env python3
"""Prototyp: USA vs Čína ve vesmíru. Použití: python main.py update|report|refresh|serve [--force] [--port 8000]"""
import argparse, json, os, re, sys, time, datetime as dt, http.server, socketserver, functools
from collections import Counter, defaultdict
import requests, pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE, DATA, OUT = (os.path.join(BASE, d) for d in ("cache", "data", "output"))
OUT = os.path.join(BASE, os.environ.get("SPACE_OUT", "docs"))  # GitHub Pages: SPACE_OUT=docs
HTML_NAME = os.environ.get("SPACE_HTML", "index.html")       # GitHub Pages: SPACE_HTML=index.html
LIVE_SAMPLE = {"Starlink": 550, "Kuiper": 100, "USA ostatní": 350, "Čína konstelace": 200, "Čína ostatní": 298}  # + ISS a Tiangong = 1500
UA = {"User-Agent": "space-usa-cina-prototype/0.1 (research)"}
SOURCES = {
    "gcat_launch.tsv": "https://planet4589.org/space/gcat/tsv/launch/launch.tsv",
    "gcat_orgs.tsv": "https://planet4589.org/space/gcat/tsv/tables/orgs.tsv",
    "satcat.csv": "https://celestrak.org/pub/satcat.csv",
    "gp_active.json": "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=json",
    "ll2_upcoming.json": "https://ll.thespacedevs.com/2.2.0/launch/upcoming/?limit=100&mode=normal",
}
MAX_AGE_H = {"ll2_upcoming.json": 6, "gp_active.json": 2}  # LL2 má limit 15 požadavků/h -> šetříme; CelesTrak GP se mění po 2 h
MIN_RETRY_H = {"celestrak.org": 2.0}  # CelesTrak: nejvýš 1 pokus za 2 h (i po chybě / s --force), jinak hrozí 403/blokace
ORBIT_SAMPLE = {"USA_starlink": 1200, "USA_ostatni": 1500, "Čína": 2000}  # vzorek pro 3D mapu (výkon prohlížeče)
LL2_CHECK_YEAR = 2025
LL2_CHECK = {  # křížová kontrola počtů startů (LL2 vs GCAT)
    "SpaceX": "SpaceX",
    "CASC": "China Aerospace Science and Technology Corporation",
}
COUNTRY = {"US": "USA", "CN": "Čína"}
ROCKETLAB_AS_US = True  # Rocket Lab (sídlo v USA) startuje Electron z NZ; GCAT ho vede jako NZ


def p(*a):
    print(*a, flush=True)


def fetch(name, url, force=False):
    path = os.path.join(CACHE, name)
    if os.path.exists(path) and not force:
        age_h = (time.time() - os.path.getmtime(path)) / 3600
        if age_h < MAX_AGE_H.get(name, 24):
            p(f"  cache OK  {name} ({age_h:.1f} h)"); return True
    att_path = os.path.join(CACHE, "attempts.json"); att = load_json(att_path, {})
    host = re.sub(r"^https?://([^/]+).*", r"\1", url)
    lim = MIN_RETRY_H.get(host)
    if lim and name in att and (time.time() - att[name]) / 3600 < lim:
        p(f"  odloženo  {name}: poslední pokus před {(time.time()-att[name])/3600:.1f} h (< {lim} h limit {host}) -> cache"); return os.path.exists(path)
    att[name] = time.time(); save_json(att_path, att)
    try:
        r = requests.get(url, headers=UA, timeout=120)
        r.raise_for_status()
        if name.endswith(".json"): r.json()  # validace
        with open(path + ".tmp", "wb") as f: f.write(r.content)
        os.replace(path + ".tmp", path)
        p(f"  staženo   {name} ({len(r.content)/1e6:.1f} MB)"); return True
    except Exception as e:
        p(f"  CHYBA     {name}: {e} -> používám starou cache" if os.path.exists(path) else f"  CHYBA     {name}: {e}")
        return os.path.exists(path)


def update(force=False):
    os.makedirs(CACHE, exist_ok=True)
    meta = load_json(os.path.join(CACHE, "meta.json"), {})
    for n, u in SOURCES.items():
        if fetch(n, u, force) and os.path.exists(os.path.join(CACHE, n)):
            meta[n] = {"url": u, "stazeno": dt.datetime.fromtimestamp(os.path.getmtime(os.path.join(CACHE, n))).isoformat(timespec="minutes")}
    # LL2 křížová kontrola (2 požadavky, cache 7 dní)
    chk_path = os.path.join(CACHE, "ll2_check.json")
    chk = load_json(chk_path, {})
    if force or not chk or time.time() - os.path.getmtime(chk_path) > 7 * 86400:
        for k, lsp in LL2_CHECK.items():
            try:
                r = requests.get("https://ll.thespacedevs.com/2.2.0/launch/", headers=UA, timeout=60, params={
                    "net__gte": f"{LL2_CHECK_YEAR}-01-01T00:00:00Z", "net__lt": f"{LL2_CHECK_YEAR+1}-01-01T00:00:00Z",
                    "lsp__name": lsp, "limit": 1, "mode": "list"})
                r.raise_for_status(); chk[k] = r.json()["count"]
            except Exception as e:
                p(f"  LL2 kontrola {k} selhala: {e}")
        save_json(chk_path, chk)
    # LL2 doplněk: starty po posledním datu v GCAT (1 dotaz/100 záznamů, cache 6 h)
    sup = ll2_supplement_fetch(force)
    if sup: meta["ll2_supplement.json"] = sup
    save_json(os.path.join(CACHE, "meta.json"), meta)
    p("Hotovo. Další krok: python main.py report")


def gdate(s):
    """GCAT/LL2 datum ('2026 Oct  1 1510:06') -> datetime.date (UTC den)."""
    return pd.to_datetime(s.str.extract(r"^(\d{4} \w{3}\s+\d+)")[0], format="%Y %b %d", errors="coerce").dt.date


def gcat_last_date():
    try:
        d = read_gcat("gcat_launch.tsv")
        d = d[d["LaunchCode"].str.startswith("O", na=False)]
        return pd.to_datetime(d["Launch_Date"].str.extract(r"^(\d{4} \w{3}\s+\d+)")[0], format="%Y %b %d", errors="coerce").max().date()
    except Exception: return None


def ll2_supplement_fetch(force=False):
    """Stáhne z LL2 starty od dne po posledním startu v GCAT do zítřka (stránkuje po 100, max LL2_SUP_MAX_PAGES dotazů)."""
    path = os.path.join(CACHE, "ll2_supplement.json")
    last = gcat_last_date()
    if not last: return None
    od = last + dt.timedelta(days=1); do = dt.date.today() + dt.timedelta(days=1)
    old = load_json(path, {})
    if old and not force and old.get("od", "9999") <= od.isoformat() and time.time() - os.path.getmtime(path) < 6 * 3600:
        p(f"  cache OK  ll2_supplement.json"); return old.get("meta")
    url = "https://ll.thespacedevs.com/2.2.0/launch/"
    params = {"net__gte": f"{od}T00:00:00Z", "net__lt": f"{do}T00:00:00Z", "limit": 100, "mode": "detailed", "ordering": "net"}
    res, nxt, pages, complete = [], None, 0, False
    try:
        r = requests.get(url, headers=UA, timeout=120, params=params)
        while True:
            r.raise_for_status(); j = r.json(); pages += 1; res += j["results"]; nxt = j.get("next")
            if not nxt: complete = True; break
            if pages >= LL2_SUP_MAX_PAGES: break
            time.sleep(5); r = requests.get(nxt, headers=UA, timeout=120)
    except Exception as e:
        p(f"  CHYBA     ll2_supplement: {e}")
        if not res: return old.get("meta") if old else None
    meta = {"url": url + " (net %s .. %s)" % (od, do), "stazeno": dt.datetime.now().isoformat(timespec="minutes"),
            "zaznamu": len(res), "kompletni": complete, "dalsi_stranka": nxt if not complete else None}
    save_json(path, {"od": od.isoformat(), "do": do.isoformat(), "meta": meta, "results": res})
    p(f"  staženo   ll2_supplement.json ({len(res)} startů od {od}, kompletní: {complete})")
    return meta


LL2_SUP_MAX_PAGES = 3
LL2_ROCKET = {r"^Long March ": "CZ ", r"^Falcon 9.*": "Falcon 9", r"^Zhuque-2E.*": "Zhuque-2E", r"^Ceres-1S?$": "Gushenxing 1",
              r"^Ceres-2$": "Gushenxing-2", r"^Kinetica 1$": "Lijian-1", r"^Kinetica 2$": "Lijian-2", r"^Gravity-1$": "Yinli-1",
              r"^Kuaizhou-": "Kuaizhou-", r"^Tianlong-3$": "Tianlong-3", r"^Starship.*": "Starship V3"}
LL2_AGENCY = {"SpaceX": "SPX", "Rocket Lab": "RLABN", "China Aerospace Science and Technology Corporation": "CASC",
              "LandSpace": "LANDSP", "Galactic Energy": "XIDO", "CAS Space": "ZKYT", "Blue Origin": "BLOR",
              "United Launch Alliance": "ULAL", "Firefly Aerospace": "FFLY", "Northrop Grumman Space Systems": "NGIS",
              "Space Pioneer": "TIANB", "Orienspace": "DFK", "iSpace": "XJRY", "China Rocket Co. Ltd.": "CZHJ", "ExPace": "EXPACE"}


def ll2_launches():
    """LL2 doplněk ve formátu sloupců GCAT; jen orbitální (orbita != Sub) z USA/Číny (+ Rocket Lab NZ jako USA)."""
    sup = load_json(os.path.join(CACHE, "ll2_supplement.json"), {}).get("results", [])
    rows = []
    for x in sup:
        st_ = x["status"]["abbrev"]
        if st_ not in ("Success", "Failure", "Partial Failure"): continue
        orb = ((x.get("mission") or {}).get("orbit") or {}).get("abbrev")
        if orb == "Sub": continue
        cc = x["pad"]["location"].get("country_code"); lsp = (x.get("launch_service_provider") or {}).get("name", "")
        state = {"USA": "US", "CHN": "CN"}.get(cc) or ("US" if cc == "NZL" and lsp == "Rocket Lab" and ROCKETLAB_AS_US else None)
        if not state: continue
        rk = x["rocket"]["configuration"]["name"]
        for rx, rep in LL2_ROCKET.items(): rk = re.sub(rx, rep, rk)
        t = dt.datetime.fromisoformat(x["net"].replace("Z", "+00:00"))
        stg = (x["rocket"].get("launcher_stage") or [])
        fid = ".".join(str(v) for v in [stg[0]["launcher"]["serial_number"], stg[0]["launcher_flight_number"]]) if stg and stg[0].get("launcher") else ""
        rows.append({"LaunchCode": "OS" if st_ == "Success" else "OF", "Launch_Date": t.strftime("%Y %b %d %H%M"),
                     "LV_Type": rk, "Mission": x.get("mission", {}).get("name") if x.get("mission") else x["name"],
                     "Agency": LL2_AGENCY.get(lsp, lsp), "Launch_Site": x["pad"]["name"], "Flight_ID": fid,
                     "state_ll2": state, "zdroj": "LL2 (doplněk)", "ll2_id": x["id"], "ll2_status": st_})
    return pd.DataFrame(rows)


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f: return json.load(f)
    except Exception: return default


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f: json.dump(obj, f, ensure_ascii=False, indent=1, default=str)


# ---------------------------------------------------------------- analýza
def read_gcat(name):
    d = pd.read_csv(os.path.join(CACHE, name), sep="\t", skiprows=[1], dtype=str, quoting=3)
    d.columns = [c.strip("#").strip() for c in d.columns]
    return d.apply(lambda s: s.str.strip())


def launches():
    d, orgs = read_gcat("gcat_launch.tsv"), read_gcat("gcat_orgs.tsv")
    state = dict(zip(orgs["Code"], orgs["StateCode"]))
    d = d[d["LaunchCode"].str.startswith("O", na=False)].copy()  # jen orbitální pokusy
    d["agency1"] = d["Agency"].str.split("/").str[0]
    d["state"] = d["agency1"].map(state)
    if ROCKETLAB_AS_US: d.loc[d["agency1"] == "RLABN", "state"] = "US"
    d = d[d["state"].isin(COUNTRY)].copy()
    d["zdroj"] = "GCAT"
    x = ll2_launches()
    if len(x):
        x["agency1"] = x["Agency"]; x["state"] = x.pop("state_ll2")
        norm = lambda s: s.str.replace(r"^Chang Zheng", "CZ", regex=True).str.lower().str.replace(r"[^a-z0-9]", "", regex=True)
        key = lambda df: gdate(df["Launch_Date"]).astype(str) + "|" + norm(df["LV_Type"])
        x = x[~key(x).isin(set(key(d)))]  # bez duplicit: datum (UTC den) + raketa
        d = pd.concat([d, x], ignore_index=True)
    d["zeme"] = d["state"].map(COUNTRY)
    d["rok"] = d["Launch_Date"].str[:4].astype(int)
    d["uspech"] = d["LaunchCode"].str[1] == "S"
    d["raketa"] = d["LV_Type"].str.replace(r"^Chang Zheng", "CZ", regex=True)
    return d


def orbit_class(per, apo, peri):
    try: per, apo, peri = float(per), float(apo), float(peri)
    except Exception: return "neznámá"
    if apo < 2000: return "LEO"
    if 1300 < per < 1600 and abs(apo - peri) < 2000: return "GEO/GSO"
    if apo - peri > 10000: return "HEO (eliptická)"
    if apo < 35000: return "MEO"
    return "jiná"


def sat_category(name):
    n = name.upper()
    rules = [("Starlink", r"^STARLINK"), ("Kuiper", r"^KUIPER"), ("Qianfan", r"^QIANFAN"),
             ("Guowang", r"^HULIANWANG"), ("Navigace", r"^(NAVSTAR|BEIDOU|GPS)"),
             ("Vojenské/zpravodajské", r"^(USA |USA-|YAOGAN|TJS|SDA|PRAETORIAN|SHIYAN|SHIJIAN|NROL)"),
             ("Pozorování Země", r"^(FLOCK|GAOFEN|JILIN|SKYSAT|LANDSAT|FENGYUN|NOAA|GOES|WORLDVIEW|PIESAT|TIANHUI|YUNHAI|HAIYANG|ZIYUAN|LEMUR|SENTINEL)"),
             ("Kosmické stanice", r"^(ISS|CSS|TIANHE|WENTIAN|MENGTIAN)")]
    for cat, rx in rules:
        if re.match(rx, n): return cat
    return "Ostatní"


def satellites():
    s = pd.read_csv(os.path.join(CACHE, "satcat.csv"), dtype=str)
    gp = load_json(os.path.join(CACHE, "gp_active.json"), [])
    active_ids = {str(int(x["NORAD_CAT_ID"])) for x in gp}
    s["NORAD_CAT_ID"] = s["NORAD_CAT_ID"].astype(str).str.lstrip("0")
    a = s[s["NORAD_CAT_ID"].isin(active_ids) & s["OWNER"].isin(["US", "PRC"])].copy()
    a["zeme"] = a["OWNER"].map({"US": "USA", "PRC": "Čína"})
    a["orbita"] = [orbit_class(*x) for x in zip(a["PERIOD"], a["APOGEE"], a["PERIGEE"])]
    a["kategorie"] = a["OBJECT_NAME"].fillna("").map(sat_category)
    return a, len(active_ids)


def report():
    L = launches()
    A, n_active_total = satellites()
    meta = load_json(os.path.join(CACHE, "meta.json"), {})
    years = list(range(2010, int(L["rok"].max()) + 1))
    st = {"meta": meta, "vygenerovano": dt.datetime.now().isoformat(timespec="minutes"), "roky": years}
    st["posledni_start_v_datech"] = str(max(gdate(L["Launch_Date"])))  # pozor: řetězcové max by řadilo "Oct" < "Sep"
    st["posledni_start_gcat"] = str(max(gdate(L[L.zdroj == "GCAT"]["Launch_Date"])))
    st["doplneno_ll2"] = L[L.zdroj != "GCAT"][["Launch_Date", "zeme", "raketa", "Mission"]].to_dict("records")
    st["starty"] = {z: [int(((L.zeme == z) & (L.rok == y)).sum()) for y in years] for z in COUNTRY.values()}
    st["uspesne"] = {z: [int(((L.zeme == z) & (L.rok == y) & L.uspech).sum()) for y in years] for z in COUNTRY.values()}
    st["uspesnost_pct"] = {z: [round(100 * s / n, 1) if n else None for s, n in zip(st["uspesne"][z], st["starty"][z])] for z in COUNTRY.values()}
    rec = L[L.rok >= years[-1] - 5]
    st["obdobi_raket"] = f"{years[-1]-5}–{years[-1]}"
    st["rakety"] = {z: rec[rec.zeme == z]["raketa"].value_counts().head(10).to_dict() for z in COUNTRY.values()}
    st["selhani_posledni"] = L[~L.uspech & (L.rok >= years[-1] - 1)][["Launch_Date", "zeme", "raketa", "Mission"]].sort_values("Launch_Date", key=gdate, ascending=False).head(20).to_dict("records")
    st["rocketlab_nz_starty"] = int(((L.agency1 == "RLABN") & (L.rok == years[-1])).sum())
    # znovupoužitelnost Falconu (z Flight_ID, např. B1093.18)
    f = L[L.raketa.isin(["Falcon 9", "Falcon Heavy"])].copy()
    f["let_boosteru"] = f["Flight_ID"].str.extract(r"B1\d{3}\.(\d+)")[0].astype(float)
    reuse = {}
    for y in years:
        fy = f[f.rok == y]
        if len(fy): reuse[y] = {"lety": int(len(fy)), "reuse": int((fy.let_boosteru > 1).sum()), "max_let": int(fy.let_boosteru.max()) if fy.let_boosteru.notna().any() else None}
    st["falcon_reuse"] = reuse
    # satelity
    st["aktivni_celkem_celestrak"] = n_active_total
    st["aktivni"] = A["zeme"].value_counts().to_dict()
    st["orbity"] = {z: A[A.zeme == z]["orbita"].value_counts().to_dict() for z in COUNTRY.values()}
    st["kategorie"] = {z: A[A.zeme == z]["kategorie"].value_counts().to_dict() for z in COUNTRY.values()}
    konst = {}
    for k in ["Starlink", "Kuiper", "Qianfan", "Guowang"]:
        sub = A[A.kategorie == k]
        konst[k] = {"aktivni": int(len(sub)), "prvni_start": sub["LAUNCH_DATE"].min() if len(sub) else None}
    st["konstelace"] = konst
    # LL2 nadcházející
    up = load_json(os.path.join(CACHE, "ll2_upcoming.json"), {}).get("results", [])
    cc = {"USA": "USA", "CHN": "Čína", "NZL": "USA" if ROCKETLAB_AS_US else None}
    st["nadchazejici"] = [{"net": r["net"], "nazev": r["name"], "zeme": cc.get(r["pad"]["location"].get("country_code")),
                          "poskytovatel": (r.get("launch_service_provider") or {}).get("name"), "status": r["status"]["abbrev"],
                          "pad": r["pad"]["name"]} for r in up if cc.get(r["pad"]["location"].get("country_code"))][:30]
    # křížová kontrola
    chk = load_json(os.path.join(CACHE, "ll2_check.json"), {})
    gy = L[L.rok == LL2_CHECK_YEAR]
    st["kontrola"] = {"rok": LL2_CHECK_YEAR,
        "SpaceX": {"GCAT": int((gy.agency1 == "SPX").sum()), "LL2": chk.get("SpaceX")},
        "CASC": {"GCAT": int(gy.agency1.isin(["CALT", "SAST", "CASC", "CGWIC"]).sum()), "LL2": chk.get("CASC")}}
    fk = load_json(os.path.join(BASE, "facts.json"), [])
    st["fakta"] = fk.get("programy", []) if isinstance(fk, dict) else fk
    st["rakety_param"] = fk.get("rakety", []) if isinstance(fk, dict) else []
    st["rakety_pozn"] = fk.get("rakety_pozn", "") if isinstance(fk, dict) else ""
    st["orbit_map"] = orbit_map(A)
    st["vysvetlivky"] = vysvetlivky(A)
    st["live"] = live_sample(A)
    try:
        import predict
        st["predikce"] = predict.build(st, os.path.join(CACHE, "satcat.csv"))
    except Exception as e:
        p(f"  (predikce selhala: {e})"); st["predikce"] = None
    st["varovani"] = sanity(st)
    os.makedirs(DATA, exist_ok=True); os.makedirs(OUT, exist_ok=True)
    save_json(os.path.join(DATA, "stats.json"), st)
    with open(os.path.join(OUT, HTML_NAME), "w", encoding="utf-8") as fh:
        fh.write(render_html(st))
    print_summary(st)
    p(f"\nDashboard: {os.path.join(OUT, HTML_NAME)}")


def orbit_map(A):
    """Poloha vzorku aktivních družic USA/Číny v čase vygenerování (SGP4 z CelesTrak GP/OMM), souřadnice ECEF v km."""
    try:
        from sgp4.api import Satrec, WGS72, jday
        from sgp4 import omm
    except ImportError:
        p("  (sgp4 není nainstalováno -> mapa orbit vynechána; pip install sgp4)"); return None
    import math, random
    gp = {str(int(x["NORAD_CAT_ID"])): x for x in load_json(os.path.join(CACHE, "gp_active.json"), [])}
    rnd = random.Random(42)
    groups = {"USA_starlink": A[(A.zeme == "USA") & (A.kategorie == "Starlink")], "USA_ostatni": A[(A.zeme == "USA") & (A.kategorie != "Starlink")], "Čína": A[A.zeme == "Čína"]}
    now = dt.datetime.now(dt.timezone.utc)
    jd, fr = jday(now.year, now.month, now.day, now.hour, now.minute, now.second)
    t = (jd - 2451545.0) + fr  # GMST (IAU 1982, přibližně) pro TEME -> ECEF
    gmst = math.radians((280.46061837 + 360.98564736629 * t) % 360)
    c, s_ = math.cos(gmst), math.sin(gmst)
    pts, pocty = [], {}
    for g, df in groups.items():
        ids = list(df["NORAD_CAT_ID"]); n_all = len(ids)
        if len(ids) > ORBIT_SAMPLE[g]: ids = rnd.sample(ids, ORBIT_SAMPLE[g])
        meta = df.set_index("NORAD_CAT_ID")
        ok = 0
        for i in ids:
            if i not in gp: continue
            sat = Satrec(); omm.initialize(sat, gp[i])
            e, r, v = sat.sgp4(jd, fr)
            if e != 0: continue
            x, y, z = r[0] * c + r[1] * s_, -r[0] * s_ + r[1] * c, r[2]
            rr = math.sqrt(x*x + y*y + z*z)
            pts.append({"g": g, "z": "USA" if g.startswith("USA") else "Čína", "x": round(x), "y": round(y), "zz": round(z),
                        "alt": round(rr - 6371), "lat": round(math.degrees(math.asin(z / rr)), 2), "lon": round(math.degrees(math.atan2(y, x)), 2),
                        "inc": round(float(gp[i]["INCLINATION"]), 2), "n": meta.at[i, "OBJECT_NAME"] if i in meta.index else i,
                        "k": meta.at[i, "kategorie"], "o": meta.at[i, "orbita"]}); ok += 1
        pocty[g] = {"celkem": n_all, "ve_vzorku": ok}
    return {"cas_utc": now.isoformat(timespec="seconds"), "pocty": pocty, "body": pts}


def live_sample(A):
    """Vzorek TLE (z CelesTrak GP/OMM) pro živé pozice v prohlížeči (satellite.js). Uloží i OUT/data/gp_sample.json."""
    try:
        from sgp4.api import Satrec
        from sgp4 import omm, exporter
    except ImportError:
        return None
    import random
    gp = {str(int(x["NORAD_CAT_ID"])): x for x in load_json(os.path.join(CACHE, "gp_active.json"), [])}
    rnd = random.Random(7)
    grp = {"Starlink": A[A.kategorie == "Starlink"], "Kuiper": A[A.kategorie == "Kuiper"],
           "USA ostatní": A[(A.zeme == "USA") & ~A.kategorie.isin(["Starlink", "Kuiper"])],
           "Čína konstelace": A[A.kategorie.isin(["Guowang", "Qianfan"])],
           "Čína ostatní": A[(A.zeme == "Čína") & ~A.kategorie.isin(["Guowang", "Qianfan"])]}
    out = []
    def add(i, g, z):
        x = gp.get(i)
        if not x: return
        try:
            s = Satrec(); omm.initialize(s, x); l1, l2 = exporter.export_tle(s)
        except Exception: return
        out.append({"g": g, "z": z, "n": x["OBJECT_NAME"], "id": int(i), "l1": l1, "l2": l2})
    for i, nm in [("25544", "ISS"), ("48274", "Tiangong (CSS)")]:
        add(i, "Stanice", "ISS (mezinárodní)" if i == "25544" else "Čína")
    for g, df in grp.items():
        ids = [i for i in df["NORAD_CAT_ID"] if i not in ("25544", "48274")]
        for i in rnd.sample(ids, min(LIVE_SAMPLE[g], len(ids))):
            add(i, g, "USA" if g in ("Starlink", "Kuiper", "USA ostatní") else "Čína")
    epoch = max((x["EPOCH"] for x in gp.values()), default=None)
    res = {"zdroj": "CelesTrak GP (active), převedeno na TLE knihovnou sgp4", "stazeno": (load_json(os.path.join(CACHE, "meta.json"), {}).get("gp_active.json") or {}).get("stazeno"),
           "pocet": len(out), "sats": out}
    os.makedirs(os.path.join(OUT, "data"), exist_ok=True)
    save_json(os.path.join(OUT, "data", "gp_sample.json"), res)
    return res


def vysvetlivky(A):
    """explain.json + živé počty: aktivní družice podle kategorie (GP) a objekty na dráze podle typu (SATCAT)."""
    ex = load_json(os.path.join(BASE, "explain.json"), {})
    if not ex: return None
    s = pd.read_csv(os.path.join(CACHE, "satcat.csv"), dtype=str)
    s = s[s["DECAY_DATE"].isna()]
    for t in ex.get("typy", []):
        if t.get("satcat"):
            t["pocet"] = {z: int(((s.OWNER == own) & (s.OBJECT_TYPE == t["satcat"])).sum()) for own, z in [("US", "USA"), ("PRC", "Čína")]}
            t["pocet_pozn"] = "objekty na dráze (katalog CelesTrak SATCAT)"
        elif t.get("kategorie"):
            t["pocet"] = {z: int(((A.zeme == z) & A.kategorie.isin(t["kategorie"])).sum()) for z in ["USA", "Čína"]}
            t["pocet_pozn"] = "aktivní družice (CelesTrak GP, typ odhadnut podle názvu)"
            if t["id"] == "stanice": t["pocet_pozn"] += "; ISS je v katalogu vedena jako mezinárodní, ne pod USA"
    ex["drahy_pocet"] = {z: A[A.zeme == z]["orbita"].value_counts().to_dict() for z in ["USA", "Čína"]}
    return ex


def sanity(st):
    w = []
    last = st["roky"][-1]
    for z in st["starty"]:
        for y, n in zip(st["roky"], st["starty"][z]):
            if n > 400: w.append(f"{z} {y}: podezřele mnoho startů ({n})")
        if st["starty"][z][st["roky"].index(2024)] < 30: w.append(f"{z} 2024: podezřele málo startů")
    for k, v in st["kontrola"].items():
        if isinstance(v, dict) and v.get("LL2") and abs(v["GCAT"] - v["LL2"]) > 0.1 * v["LL2"]:
            w.append(f"Kontrola {k}: GCAT {v['GCAT']} vs LL2 {v['LL2']} se liší o >10 %")
    if st["aktivni"].get("USA", 0) < st["konstelace"]["Starlink"]["aktivni"]: w.append("Starlink > všechny US družice?!")
    if st["posledni_start_v_datech"][:4] != str(last): w.append("Poslední rok dat neodpovídá")
    return w


def print_summary(st):
    y = st["roky"]
    p("Starty (orbitální pokusy) posledních 5 let:")
    for z in st["starty"]:
        p(f"  {z:5}: " + ", ".join(f"{yy}={n} ({st['uspesnost_pct'][z][i]} %)" for i, (yy, n) in enumerate(zip(y, st["starty"][z])) if yy >= y[-1] - 4))
    p(f"Aktivní družice: {st['aktivni']} (CelesTrak celkem {st['aktivni_celkem_celestrak']})")
    p(f"Konstelace: {st['konstelace']}")
    p(f"Kontrola GCAT vs LL2 ({st['kontrola']['rok']}): {st['kontrola']}")
    p("Varování: " + ("; ".join(st["varovani"]) or "žádná"))


def render_html(st):
    with open(os.path.join(BASE, "template.html"), encoding="utf-8") as f: t = f.read()
    return t.replace("/*__DATA__*/null", json.dumps(st, ensure_ascii=False, default=str).replace("</", "<\\/"))


def refresh():
    """update + report + export s logem (pro cron). Respektuje cache, LL2 limit i 2h limit CelesTraku."""
    import shutil, subprocess, io, contextlib
    os.makedirs(os.path.join(BASE, "logs"), exist_ok=True)
    log = os.path.join(BASE, "logs", "refresh.log")
    buf = io.StringIO(); ok = True; t0 = time.time()
    class Tee(io.TextIOBase):
        def write(self, x): sys.__stdout__.write(x); buf.write(x); return len(x)
    with contextlib.redirect_stdout(Tee()):
        p(f"=== refresh {dt.datetime.now().isoformat(timespec='seconds')} ===")
        try:
            prev = os.path.join(DATA, "stats_prev.json")
            if os.path.exists(os.path.join(DATA, "stats.json")): shutil.copy2(os.path.join(DATA, "stats.json"), prev)
            update(False); report()
            r = subprocess.run([sys.executable, os.path.join(BASE, "export_xlsx.py")] + ([prev] if os.path.exists(prev) else []), capture_output=True, text=True)
            p(r.stdout.strip()); 
            if r.returncode: ok = False; p("CHYBA export: " + r.stderr.strip()[-800:])
        except Exception as e:
            import traceback; ok = False; p("CHYBA: " + "".join(traceback.format_exception(e))[-1500:])
        p(f"=== konec: {'OK' if ok else 'CHYBA'} za {time.time()-t0:.0f} s ===")
    with open(log, "a", encoding="utf-8") as f: f.write(buf.getvalue() + "\n")
    sys.exit(0 if ok else 1)


def serve(port):
    if not os.path.exists(os.path.join(OUT, HTML_NAME)): report()
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=OUT)
    with socketserver.TCPServer(("127.0.0.1", port), h) as srv:
        p(f"Dashboard běží na http://127.0.0.1:{port}/dashboard.html (Ctrl+C ukončí)")
        srv.serve_forever()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=["update", "report", "serve", "refresh"])
    ap.add_argument("--force", action="store_true", help="ignorovat cache")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    {"update": lambda: update(a.force), "report": report, "serve": lambda: serve(a.port), "refresh": refresh}[a.cmd]()
