# Sports Betting Decisions Study

A browser-based, no-real-money betting simulation with a Python API for centralized response collection.

## Study flow

Each participant makes one featured-game bet per week across a 12-week fictional season:

1. Weeks 1–4 establish baseline choices.
2. Featured-game outcomes in weeks 5–8 are assigned to create a winning or losing streak.
3. Weeks 9–12 measure follow-up choices.

All 12 teams play once each week: the first 11 weeks form a round robin, followed by a rematch week. Each week has six games; one rotating featured game is available to bet on, while the other five games also affect the session standings. Featured outcomes outside weeks 5–8 and all non-featured outcomes are simulated using displayed odds.

Participants are independently assigned at random to one of two conditions in their browser. The starting balance is 1,000 credits; each stake is an integer capped at 10% of the current balance. Decimal odds are shown for both teams. The study records the bet, odds, result, phase, balance, and all six weekly scorelines.

Before participation, users are told that some details about result determination will be explained after the simulation. The assigned featured-game sequence is explained in the end-of-study debrief. Obtain any required ethics/IRB approval, and add your approved researcher contact, consent, privacy, withdrawal, and data-retention details before recruiting participants.

Participants see a live win-loss table and completed scorelines from all games in their session. Score margins are influenced by displayed odds, while the featured-game winners in weeks 5–8 are assigned by condition. These are study stimuli and may affect later decisions; document them in the approved protocol and preregistration.

## Run locally

Use Python 3.10 or later.

1. Install the API dependencies: `python -m pip install -r requirements.txt`
2. Start the API from PowerShell:

   ```powershell
   $env:ADMIN_TOKEN = "replace-with-a-private-token"
   $env:ALLOWED_ORIGINS = "http://localhost:5500,http://127.0.0.1:5500"
   uvicorn server:app --reload
   ```

3. In a second terminal, serve the participant website: `python -m http.server 5500 --directory docs`
4. Open `http://localhost:5500`.

The API stores study responses in `study.sqlite3`. To export all rounds while the API is running, use the same token:

```powershell
curl.exe -H "Authorization: Bearer YOUR_ADMIN_TOKEN" http://127.0.0.1:8000/api/export.csv -o study-data.csv
```

Tests use the standard library:

```powershell
python -m unittest discover -s tests
```

## Analyze the study data

Install the analysis dependency with `python -m pip install -r requirements-analysis.txt`, then download the complete dataset from the API or pass multiple participant CSVs:

```powershell
python analyze.py study-data.csv --summary-output participant-summary.csv
```

The script computes each participant's mean stake as a proportion of balance during baseline and follow-up, then compares the within-participant change between conditions with a two-sided Welch t-test. It also writes one row per participant to the summary CSV. Treat the test as an initial descriptive analysis; choose and preregister the final statistical model and exclusions with your research advisor.

## Public deployment

The participant site is a static site for GitHub Pages. Central collection requires the separate API service; GitHub Pages by itself cannot receive or store responses.

1. In GitHub, set Pages to deploy branch `main` from the `/docs` folder.
2. Create a PostgreSQL database with Neon, then copy its connection string. Keep it private.
3. In Render, create a Blueprint from the repository. The included `render.yaml` configures a free web service; provide the Neon connection string as `DATABASE_URL` and set `ALLOWED_ORIGINS` to the exact GitHub Pages origin, such as `https://your-account.github.io` (no path). Render generates an admin token; keep it private and retrieve it from the service environment settings.
4. Set `apiBaseUrl` in `docs/config.js` to the HTTPS URL of the deployed API, then commit and push that change so Pages redeploys.
5. Confirm that the public site reports “Study server connected” before distributing its link.

The API uses SQLite locally and PostgreSQL when `DATABASE_URL` is set. Free hosting plans can sleep or have usage and retention limits; verify current provider limits and your study's data-retention requirements before collecting participant responses.

The browser sends one participant record when all rounds are complete. A random participant ID is generated in the browser; the app does not ask for names or contact details. Hosting providers may still keep technical request logs. The participant can download their own CSV, while the study owner can export the complete dataset using the private admin token. A failed submission stays in the current browser tab until it is retried or downloaded.

The API accepts anonymous submissions, so its URL is public by design. CORS limits which browser origins can read responses; it is not participant authentication. Do not use this endpoint to collect identifying or sensitive information.
