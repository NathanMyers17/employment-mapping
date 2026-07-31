# Project: Job Market Map — Interactive Employment Dashboard

## Goal
An interactive, map-based dashboard showing employment data by metro area
(MSA) and by job function/field (e.g., IT, Finance, Sales). The core value:
help someone (e.g., a student or job-seeker) figure out where opportunities
in a given field are concentrated and growing, ideally with demographic/
livability context layered in. This is not just a technical showcase — it
should actually be useful to look at.

## Author background (for context, not to re-explain each session)
- Data Science major (UVA), comfortable with Python (pandas, numpy,
  seaborn, scikit-learn) and R; new to SQL — explain SQL concepts as we go,
  don't assume prior familiarity.
- Has built prior clustering/analysis projects (basketball stats vs.
  salary, NCAA tournament predictive metric) but not a deployed, interactive
  app before — this is the first project meant to be a real, hosted,
  portfolio-ready web app rather than a notebook.
- Timeline: aiming to get a working version built in the next ~3 weeks.

## Planned stack
- **Data**: BLS OEWS (Occupational Employment and Wage Statistics) —
  employment/wages by detailed occupation, at the metro-area (MSA) level.
  Chosen over QCEW/county-level data specifically to keep OEWS's more
  detailed job-function categories. Possibly layered with Census ACS
  demographic data (income, population) for livability context. Prefer
  pre-aggregated public data over scraping or raw microdata — the goal is
  build time, not data-wrangling time.
- **Database**: SQLite to start (simple, file-based, still real SQL —
  joins, indexes, aggregation queries). Could migrate to Postgres later.
- **Backend/app**: Streamlit or Flask — TBD based on how interactive the
  map needs to be.
- **Map**: Leaflet or Plotly/Mapbox for the interactive map view, at the
  metro-area (MSA) level — this is meant to be the centerpiece of the
  dashboard, not an afterthought.
- **Dev environment**: VS Code + Claude Code. Repo hosted on GitHub.

## Decided
- "Department/field" = job function/occupation (e.g., IT, Finance, Sales),
  not industry sector.
- Geographic grain = metro area (MSA), not county — this was a deliberate
  tradeoff to keep OEWS's detailed occupation categories rather than
  dropping to coarser Census ACS occupation groupings at the county level.
  This choice was revisited once (user pictured clicking on a "county") and
  reconfirmed: the clickable map unit is the metro area, not the county.
- Core interaction: the map is color-coded (choropleth) by metro area for
  at-a-glance scanning, and clicking a metro area opens an info panel with
  details about it — starting with things like top job fields in that area
  and land area, with room to add more (population, cost of living, etc.)
  later without re-architecting the data model.

## Working style
- Explain SQL and any new concepts as they come up — don't assume prior
  familiarity.
- Be direct about what's a weak approach or won't fit the timeline; give
  encouragement when things are genuinely working.
- Prefer getting to a working end-to-end version early (even ugly), then
  improving polish/interactivity, over polishing one piece before the
  pipeline works end-to-end.
