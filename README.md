# 🚀 USA vs 🇨🇳 Čína ve vesmíru – online dashboard

Statický dashboard (GitHub Pages) s automatickou aktualizací dat (GitHub Actions) a **živými polohami družic** počítanými přímo v prohlížeči.

- `docs/index.html` – dashboard (jediný soubor, data jsou vložená uvnitř; knihovny Plotly a satellite.js z CDN)
- `docs/databaze.xlsx` – databáze ke stažení (starty, družice, konstelace, rakety, scénáře, vysvětlivky…)
- `docs/data/gp_sample.json` – vzorek ~1 500 drah (TLE) pro živý režim, obnovuje se při každém refreshi
- `main.py` (update | report | refresh | serve), `predict.py` (scénáře), `export_xlsx.py`, `facts.json`, `explain.json`, `template.html`
- `.github/workflows/refresh.yml` – každé 3 h: stáhne data, přegeneruje `docs/`, commitne změny a nasadí Pages
- `.github/workflows/pages.yml` – nasazení Pages při tvém ručním pushi do `docs/`

Žádné API klíče ani tajné údaje nejsou potřeba (všechny zdroje jsou veřejné).

## Nasazení krok za krokem

1. **Vytvoř nový repozitář** na GitHubu (např. `space-usa-cina`), *bez* README/licence (prázdný). Veřejný repozitář = GitHub Pages zdarma.
2. **Nahraj tuto složku** (v terminálu ve složce `space_usa_cina_site`):
   ```bash
   git init -b main
   git add .
   git commit -m "Dashboard USA vs Čína"
   git remote add origin https://github.com/TVOJE_JMENO/space-usa-cina.git
   git push -u origin main
   ```
   (`cache/` a `logs/` se nenahrají – jsou v `.gitignore`.)
3. **Povol zápis pro Actions:** *Settings → Actions → General → Workflow permissions →* **Read and write permissions** → Save.
4. **Zapni Pages:** *Settings → Pages → Build and deployment → Source:* **GitHub Actions**.
5. **První spuštění:** záložka *Actions →* „Aktualizace dat a nasazení“ → **Run workflow**. Po ~2–5 min bude web na
   `https://TVOJE_JMENO.github.io/space-usa-cina/` (odkaz je i v detailu běhu, krok *deploy*).
6. Dál se vše děje samo každé 3 hodiny (cron `17 */3 * * *` je v UTC). Ruční spuštění kdykoli přes *Run workflow*.

## Jak aktualizace respektuje limity zdrojů
- `cache/` se mezi běhy přenáší přes `actions/cache` (včetně `cache/attempts.json` s časem posledních pokusů).
- **CelesTrak** (aktivní družice): nejvýš 1 pokus za 2 h, i po chybě; SATCAT a GCAT 1× za 24 h.
- **Launch Library 2** (limit 15 dotazů/h): nadcházející starty a doplněk posledních startů 1× za 6 h, kontrolní počty 1× za 7 dní → jeden běh max. ~6 dotazů.
- Když zdroj selže, použije se poslední stažená data a běh pokračuje.

## Živé pozice družic
V sekci *Mapa orbit* tlačítko **● Živě** spočítá polohy vzorku ~1 500 družic USA a Číny (Starlink, Kuiper, ostatní, Guowang/Qianfan…) + **ISS a Tiangong** (žluté kosočtverce) každou sekundu pomocí [satellite.js](https://github.com/shashwatak/satellite-js) (model SGP4). **⏸ Pauza** zastaví animaci.
Dráhy se berou z `docs/data/gp_sample.json` (vložené i přímo v `index.html`), ne z CelesTraku při každé návštěvě – CelesTrak sice CORS povoluje (`Access-Control-Allow-Origin: *`, ověřeno 3. 11. 2026), ale stahování od každého návštěvníka by porušovalo jeho limity. Přesnost poloh klesá se stářím dat (proto refresh každé 3 h).

## Lokální spuštění
```bash
pip install -r requirements.txt
python main.py refresh          # update + report + export do docs/
cd docs && python -m http.server 8000   # http://localhost:8000/
```

## Omezení
- Každý automatický commit přidá do historie ~2,5 MB (`index.html` + `databaze.xlsx`), tj. ~20 MB/den. Pokud by repo rostlo moc, zřeď cron (např. `17 */6 * * *`) nebo `docs/databaze.xlsx` přidej do `.gitignore` (Pages ho dostanou i tak z artefaktu nasazení).
- GitHub může naplánované workflow ve veřejném repu pozastavit po 60 dnech bez aktivity – pak stačí v *Actions* workflow znovu povolit.
- Grafy i živý režim potřebují internet (CDN). Predikce jsou modelový odhad, ne fakt (viz metodika v dashboardu).


## Podpora a licence

Na webu je formulář k bezplatnému odběru novinek a patička se zdroji dat a licencemi.

- **GCAT** (J. McDowell): [CC BY](https://creativecommons.org/licenses/by/4.0/), komerční použití s uvedením zdroje je povoleno. https://planet4589.org/space/gcat/
- **CelesTrak** (T.S. Kelso): volně ke stažení, bez formální licence k redistribuci; platí [Usage Policy](https://celestrak.org/usage-policy.php) (GP nejvýš 1× za 2 h). Komerční přeposílání surových dat je vhodné nejdřív konzultovat s CelesTrakem.
- **Launch Library 2** (The Space Devs): data lze použít a výstupy sdílet, bez přeposílání bez přidané hodnoty; uvedení zdroje je vítané. [Podmínky](https://github.com/TheSpaceDevs/Tutorials/blob/main/faqs/faq_TSD.md).
