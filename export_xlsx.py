#!/usr/bin/env python3
"""Export databáze do <OUT>/databaze.xlsx (OUT = env SPACE_OUT, výchozí output). Použití: python3 export_xlsx.py [cesta_k_předchozímu_stats.json]"""
import sys, os, json, datetime as dt
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import main as M

L = M.launches(); A, n_tot = M.satellites()
st = json.load(open(os.path.join(M.DATA, "stats.json"), encoding="utf-8"))
meta = st["meta"]
starty = L[["rok", "zeme", "raketa", "LaunchCode", "uspech", "Launch_Date", "Mission", "Agency", "Launch_Site", "Flight_ID", "zdroj"]].copy()
starty["vysledek"] = starty["uspech"].map({True: "úspěch", False: "neúspěch"})
starty["datum"] = starty["Launch_Date"].str.extract(r"^(\d{4} \w{3}\s+\d+)")[0].pipe(lambda s: pd.to_datetime(s, format="%Y %b %d", errors="coerce")).dt.date
starty = starty[["rok", "datum", "zeme", "raketa", "vysledek", "zdroj", "Mission", "Agency", "Launch_Site", "Flight_ID", "LaunchCode", "Launch_Date"]].rename(columns={
    "Mission": "mise", "Agency": "provozovatel_GCAT", "Launch_Site": "kosmodrom", "Flight_ID": "id_letu", "LaunchCode": "kod_GCAT", "Launch_Date": "datum_cas_UTC_GCAT"}).sort_values(["datum", "datum_cas_UTC_GCAT"], ascending=False)
roky = pd.DataFrame({"rok": st["roky"]})
for z in st["starty"]:
    roky[f"starty_{z}"] = st["starty"][z]; roky[f"uspesne_{z}"] = st["uspesne"][z]; roky[f"uspesnost_%_{z}"] = st["uspesnost_pct"][z]
dr = A.groupby(["zeme", "kategorie", "orbita"]).size().reset_index(name="pocet").sort_values(["zeme", "pocet"], ascending=[True, False])
dr_list = A[["zeme", "OBJECT_NAME", "NORAD_CAT_ID", "OBJECT_ID", "kategorie", "orbita", "LAUNCH_DATE", "LAUNCH_SITE", "PERIOD", "INCLINATION", "APOGEE", "PERIGEE"]].rename(columns={"OBJECT_NAME": "nazev", "NORAD_CAT_ID": "norad_id", "OBJECT_ID": "cospar_id", "LAUNCH_DATE": "datum_startu", "LAUNCH_SITE": "kosmodrom", "PERIOD": "perioda_min", "INCLINATION": "sklon_deg", "APOGEE": "apogeum_km", "PERIGEE": "perigeum_km"})
konst = pd.DataFrame([{"konstelace": k, "zeme": "USA" if k in ("Starlink", "Kuiper") else "Čína", "aktivni_druzice": v["aktivni"], "prvni_start": v["prvni_start"]} for k, v in st["konstelace"].items()])
orb = A[A.kategorie.isin(konst.konstelace)].groupby(["kategorie", "orbita"]).size().unstack(fill_value=0)
konst = konst.merge(orb, left_on="konstelace", right_index=True, how="left")
prog = pd.DataFrame(st["fakta"]).rename(columns={"usa_zdroj": "zdroj_USA", "cina_zdroj": "zdroj_Čína", "usa": "USA", "cina": "Čína"})
fr = pd.DataFrame([{"rok": int(y), **v} for y, v in st["falcon_reuse"].items()])
up = pd.DataFrame(st["nadchazejici"])
zdroje = pd.DataFrame([{"soubor": k, "url": v["url"], "stazeno_Praha": v["stazeno"]} for k, v in meta.items()])
zdroje = pd.concat([zdroje, pd.DataFrame([
    {"soubor": "ll2_check.json", "url": "https://ll.thespacedevs.com/2.2.0/launch/ (count, rok 2025)", "stazeno_Praha": dt.datetime.fromtimestamp(os.path.getmtime(os.path.join(M.CACHE, "ll2_check.json"))).isoformat(timespec="minutes")},
    {"soubor": "databaze.xlsx", "url": "export ze stats.json", "stazeno_Praha": dt.datetime.now().isoformat(timespec="minutes")},
    {"soubor": "poznámka", "url": f"Poslední start v GCAT: {st['posledni_start_gcat']}, v datech celkem: {st['posledni_start_v_datech']}. Starty po posledním dni GCAT doplněny z Launch Library 2 (sloupec zdroj = 'LL2 (doplněk)', bez duplicit podle dne UTC + rakety). Rocket Lab počítán za USA. Typ družic odhadnut podle názvu. Aktivní = CelesTrak GP 'active'.", "stazeno_Praha": ""},
    {"soubor": "kontrola GCAT vs LL2 2025", "url": json.dumps(st["kontrola"], ensure_ascii=False), "stazeno_Praha": ""},
    {"soubor": "varování sanity", "url": "; ".join(st["varovani"]) or "žádná", "stazeno_Praha": ""}])])
rk = pd.DataFrame(st.get("rakety_param", []))
if len(rk): rk["nejiste"] = rk["nejiste"].map({True: "ano", False: ""})
rk_cols = {"zeme": "země", "raketa": "raketa", "stav": "stav", "leo_kg": "LEO_kg", "leo_pozn": "LEO_pozn", "gto_kg": "GTO_nebo_TLI_kg", "gto_typ": "typ_dráhy",
           "cena_musd_min": "cena_mil_USD_min", "cena_musd_max": "cena_mil_USD_max", "cena_rok": "cena_rok_zdroj", "kg_pro_vypocet": "kg_pro_výpočet_USD_kg",
           "usd_za_kg_min": "USD_za_kg_min", "usd_za_kg_max": "USD_za_kg_max", "nejiste": "nejisté", "poznamka": "poznámka", "zdroj_nosnost": "zdroj_nosnost", "zdroj_cena": "zdroj_cena"}
rk = rk.rename(columns=rk_cols)[list(rk_cols.values())] if len(rk) else rk
if len(rk): rk = pd.concat([rk, pd.DataFrame([{"země": "POZNÁMKA", "raketa": st.get("rakety_pozn", "")}])], ignore_index=True)
om = st.get("orbit_map") or {}
orbm = pd.DataFrame(om.get("body", [])).rename(columns={"g": "skupina", "z": "země", "x": "x_km_ECEF", "y": "y_km_ECEF", "zz": "z_km_ECEF", "alt": "výška_km", "lat": "šířka", "lon": "délka", "inc": "sklon_deg", "n": "název", "k": "kategorie", "o": "orbita"})
if len(orbm): orbm.insert(0, "čas_UTC", om.get("cas_utc"))
import predict as _pr
P = st.get("predikce")
scen = pd.DataFrame(_pr.to_rows(P)) if P else pd.DataFrame()
if P:
    pred = pd.DataFrame([{"scénář": s["id"], "název": s["nazev"], "pravděpodobnost_%": s["pst"], "popis": s["popis"],
        "násobek_trendu_USA": s["predpoklady"]["m_trend"]["USA"], "násobek_trendu_Čína": s["predpoklady"]["m_trend"]["Čína"],
        "šok_startů": json.dumps(s["predpoklady"]["sok"]), "růst_ostatních_družic_%/rok": 100 * s["r_ostatni"], "růst_úlomků_%/rok": 100 * s["r_odpad"],
        "fragmentace_(rok:úlomky)": json.dumps(s["predpoklady"]["fragmentace"]), "cíl_konstelací_2035": json.dumps(s["predpoklady"]["konst_cil_2035"], ensure_ascii=False)} for s in P["scenare"]])
    pred = pd.concat([pred, pd.DataFrame([{"scénář": "METODIKA", "název": "MODELOVÝ ODHAD, ne fakt; pravděpodobnosti = expertní odhad", "popis": P["metodika"]},
        {"scénář": "ZÁKLAD", "popis": json.dumps(P["zaklad"], ensure_ascii=False)}])], ignore_index=True)
    H = P["historie"]
    hist = pd.DataFrame({"rok": H["roky"], "družice_na_dráze_USA": H["pay_orbit"]["USA"], "družice_na_dráze_Čína": H["pay_orbit"]["Čína"],
                         "LEO_družice": H["leo"]["PAY"], "LEO_horní_stupně": H["leo"]["R/B"], "LEO_úlomky": H["leo"]["DEB"]})
else:
    pred = hist = pd.DataFrame()
EX = st.get("vysvetlivky") or {}
vysv = pd.DataFrame([{"typ": t["nazev"], "co_to_je": t["co"], "proč": t["proc"], "záměr_historie": t["zamer"], "USA": t["kdo_usa"], "Čína": t["kdo_cina"],
    "dráha": t["draha"], "počet_USA": (t.get("pocet") or {}).get("USA"), "počet_Čína": (t.get("pocet") or {}).get("Čína"), "počet_co": t.get("pocet_pozn"), "zdroje": " ; ".join(t["zdroje"])} for t in EX.get("typy", [])]
    + [{"typ": d["nazev"], "co_to_je": d["text"], "dráha": d["vyska"], "zdroje": d["zdroj"]} for d in EX.get("drahy", [])])
sheets = {"starty": starty, "starty_po_rocich": roky, "druzice_souhrn": dr, "druzice_seznam": dr_list, "konstelace": konst,
          "programy_technologie": prog, "rakety_nosnost_cena": rk, "orbity_vzorek_sgp4": orbm, "falcon_reuse": fr, "scenare": scen, "scenare_predpoklady": pred, "historie_orbit_satcat": hist, "vysvetlivky": vysv, "nadchazejici_starty": up, "zdroje_a_cas": zdroje}
if len(sys.argv) > 1:
    old = json.load(open(sys.argv[1], encoding="utf-8")); rows = []
    for z in st["starty"]:
        for i, y in enumerate(st["roky"]):
            o = old["starty"][z][old["roky"].index(y)] if y in old["roky"] else None
            rows.append({"ukazatel": f"starty {z} {y}", "predtim": o, "ted": st["starty"][z][i]})
    for z in st["aktivni"]: rows.append({"ukazatel": f"aktivní družice {z}", "predtim": old["aktivni"].get(z), "ted": st["aktivni"][z]})
    for k in st["konstelace"]: rows.append({"ukazatel": f"konstelace {k}", "predtim": old["konstelace"][k]["aktivni"], "ted": st["konstelace"][k]["aktivni"]})
    rows.append({"ukazatel": "poslední start v datech", "predtim": old["posledni_start_v_datech"], "ted": st["posledni_start_v_datech"]})
    rows.append({"ukazatel": "nadcházející starty (seznam)", "predtim": len(old["nadchazejici"]), "ted": len(st["nadchazejici"])})
    ch = pd.DataFrame(rows); ch["zmena"] = [("" if a == b else "ZMĚNA") for a, b in zip(ch.predtim, ch.ted)]
    ch.insert(0, "srovnani", f"{old['vygenerovano']} -> {st['vygenerovano']}")
    sheets["zmeny"] = ch
out = os.path.join(M.OUT, "databaze.xlsx")
with pd.ExcelWriter(out, engine="openpyxl") as w:
    for n, d in sheets.items():
        d.to_excel(w, sheet_name=n[:31], index=False)
        ws = w.sheets[n[:31]]; ws.freeze_panes = "A2"; ws.auto_filter.ref = ws.dimensions
        for col in ws.columns:
            ws.column_dimensions[col[0].column_letter].width = min(60, max(10, max(len(str(c.value or "")) for c in col[:200]) + 2))
print(out, {n: len(d) for n, d in sheets.items()})
