# Søjlediagram — Opdateringer og rettelser

## Problemet

Når en bruger bad om et søjlediagram over f.eks. "Arbejdsbeskæftigelsen i USA", fik de enten:
- **Et enkelt aggregeret bjælke** på ~155.000 i stedet for 50+ månedlige stænger
- **Forkert skala** — PAYEMS-serien fra FRED returnerer det samlede antal lønmodtagere (niveau ~155.000 tusinde = 155 mio.), ikke den månedlige ændring

---

## Hvad vi rettede

### 1. `transform: "diff"` — niveau → månedlig ændring (`macro.py`)
PAYEMS uden transformation viser niveauet (~155.000). Vi tilføjede understøttelse af feltet `"transform": "diff"` i seriespecifikationen, som konverterer FRED-niveau-serien til periode-over-periode-ændring via `.diff()`. Resultatet er den faktiske månedlige jobvækst (+100 til +400 tusinde) — præcis hvad søjlediagrammet skal vise.

### 2. Tidsserier-tilstand for type B (`renderers/charts.py`)
Den eksisterende søjlediagram-renderer (type B) antog altid et enkelt øjebliksbillede (ét datapunkt per enhed). Vi tilføjede en dedikeret **tidsserier-tilstand**: når DataFrame-indekset er `DatetimeIndex` og der kun er én kolonne, renderes alle datapunkter som separate månedsstænger over tid — ligesom i det originale Maj Invest newsletter.

**Visuelle valg der matcher newsletteren:**
- Alle stænger er teal (`#11716c`) — ingen rød/grøn forskel for negative værdier
- De **2 seneste stænger er amber** (`#d4843e`) for at markere foreløbige data
- **Årsgrupper på x-aksen**: årstal er centreret under hver årsgruppe (ingen rotation)
- Ingen værdilabels direkte på stængerne
- Vandret nul-linje samt kun vandrette gitterlinjer

### 3. Orchestrator-prompt opdateret (`orchestrator.py`)
Tilføjede eksplicit dokumentation:
- PAYEMS kræver `transform: "diff"` — uden det vises niveauet ~155.000, IKKE månedlig ændring
- Type B i tidsserier-tilstand kræver `period_days >= 1460` (4+ år) for at undgå kun 3 stænger
- KRITISK advarsel: bland aldrig PAYEMS (tusinder) og UNRATE (%) i samme type G-diagram

### 4. Reviewer-prompt opdateret (`reviewer.py`)
Reviewer flaggede type B tidsseriesøjler som "forkert diagramtype for tidsdata". Vi opdaterede beskrivelsen til at anerkende begge gyldige type B-tilstande.

### 5. Routing-regel tilføjet (`routing.py`)
Tilføjede en keyword-regel der fanger danske og engelske beskæftigelses-forespørgsler (`beskæftigelse`, `jobvækst`, `payroll`, `nonfarm` osv.) og automatisk instruerer LLM'en i at bruge `PAYEMS` med `transform: "diff"`, `period_days: 1825` og type B — så brugerens anmodning konsekvent producerer det rigtige diagram.

---

## Resultat

En forespørgsel om "Søjlediagram med arbejdsbeskæftigelsen i USA" returnerer nu:
- ~60 månedlige stænger for de seneste 5 år
- Værdier i hundredvis (månedlig jobvækst), ikke 155.000 (niveauet)
- Visuelt identisk med Maj Invest newsletter-stilen
