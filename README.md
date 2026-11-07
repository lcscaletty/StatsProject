# Sports Betting Decisions Study

A browser-based, no-real-money betting simulation with a Python API for centralized response collection.

## Study flow

Each participant makes 12 bets with fictional teams and study credits:

1. Four baseline rounds with simulated outcomes.
2. Three assigned outcomes that create a winning or losing streak.
3. Five follow-up rounds with simulated outcomes.

Participants are independently assigned at random to one of the two conditions in their browser. The starting balance is 1,000 credits; each stake is an integer capped at 10% of the current balance. Decimal odds are shown for both teams. The study records the stake in credits and as a fraction of the current balance, along with odds, result, phase, and balance.

The outcome-sequence manipulation is disclosed before participation, and the particular assigned sequence is explained at the end. The outcome phase is intentionally controlled rather than generated from the displayed odds. Obtain any required ethics/IRB approval, and add your approved researcher contact, consent, privacy, withdrawal, and data-retention details before recruiting participants.

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

1. Put these files in a GitHub repository and deploy the `docs` folder with GitHub Pages.
2. Deploy `server.py`, `requirements.txt`, and `render.yaml` as a Render web service. The blueprint provisions persistent storage for SQLite and generates an admin token. Keep that token private; retrieve it from the service environment settings.
3. Set the API service's `ALLOWED_ORIGINS` to the exact GitHub Pages origin, such as `https://your-account.github.io` (no path).
4. Set `apiBaseUrl` in `docs/config.js` to the HTTPS URL of the deployed API, then redeploy the Pages site.
5. Confirm that the public site reports “Study server connected” before distributing its link.

The browser sends one participant record when all rounds are complete. A random participant ID is generated in the browser; the app does not ask for names or contact details. Hosting providers may still keep technical request logs. The participant can download their own CSV, while the study owner can export the complete dataset using the private admin token. A failed submission stays in the current browser tab until it is retried or downloaded.

The API accepts anonymous submissions, so its URL is public by design. CORS limits which browser origins can read responses; it is not participant authentication. Do not use this endpoint to collect identifying or sensitive information.
