"use strict";

const STARTING_CREDITS = 1000;
const MAX_STAKE = 500;
const LOAN_CREDITS = 1000;
const TOTAL_ROUNDS = 12;
const SESSION_KEY = "field-notes-study-session-v1";
const CSV_COLUMNS = [
  "participant_id",
  "condition",
  "round_number",
  "phase",
  "team_a",
  "team_b",
  "team_a_score",
  "team_b_score",
  "week_games",
  "odds_a",
  "odds_b",
  "probability_a",
  "selection",
  "selected_odds",
  "stake",
  "stake_share",
  "winner",
  "bet_result",
  "profit",
  "balance_before",
  "balance_after",
  "debt_before",
  "debt_after",
  "loan_amount",
  "forced"
];
const TEAMS = [
  "Cedar City Foxes",
  "Northbank Owls",
  "Copperfield Comets",
  "Lakeview Lynx",
  "Redstone Rooks",
  "Westmere Wolves",
  "Pinecrest Pilots",
  "Harborlight Hawks",
  "Silvervale Sparks",
  "Easton Evergreens",
  "Stonebridge Storm",
  "Goldenfield Giants"
];

function createSchedule() {
  let rotation = [...TEAMS];
  const firstLeg = [];
  for (let week = 0; week < TEAMS.length - 1; week += 1) {
    const fixtures = [];
    for (let game = 0; game < TEAMS.length / 2; game += 1) {
      let teamA = rotation[game];
      let teamB = rotation[rotation.length - 1 - game];
      if ((week + game) % 2) {
        [teamA, teamB] = [teamB, teamA];
      }
      fixtures.push({ team_a: teamA, team_b: teamB });
    }
    firstLeg.push(fixtures);
    const movingTeams = rotation.slice(1);
    movingTeams.unshift(movingTeams.pop());
    rotation = [rotation[0], ...movingTeams];
  }

  const returnLeg = firstLeg[0].map(({ team_a, team_b }) => ({
    team_a: team_b,
    team_b: team_a
  }));
  return [...firstLeg, returnLeg];
}

const WEEKLY_SCHEDULE = createSchedule();
const apiBaseUrl = (window.STUDY_CONFIG?.apiBaseUrl ?? "").replace(/\/+$/, "");
const intro = document.querySelector("#intro");
const studyLayout = document.querySelector("#study-layout");
const gamePanel = document.querySelector("#game");
const completePanel = document.querySelector("#complete");
const consentInput = document.querySelector("#consent");
const beginButton = document.querySelector("#begin-button");
const serverStatus = document.querySelector("#server-status");
const errorMessage = document.querySelector("#error-message");

let serverReady = false;
let uploadInProgress = false;
let state = loadSession();

function showError(message) {
  errorMessage.textContent = message;
  errorMessage.hidden = false;
}

function clearError() {
  errorMessage.hidden = true;
  errorMessage.textContent = "";
}

function setServerStatus(message, kind = "") {
  serverStatus.textContent = message;
  serverStatus.className = `server-status ${kind}`.trim();
}

function isLoopbackHost(hostname) {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}

function loadSession() {
  try {
    const saved = sessionStorage.getItem(SESSION_KEY);
    if (!saved) {
      return null;
    }

    const restored = JSON.parse(saved);
    let updated = false;
    if (!Number.isFinite(restored.debt) || restored.debt < 0) {
      restored.debt = 0;
      updated = true;
    }
    if (![0, LOAN_CREDITS].includes(restored.current_loan)) {
      restored.current_loan = 0;
      updated = true;
    }
    for (const round of restored.rounds ?? []) {
      if (!Number.isInteger(round.team_a_score) || !Number.isInteger(round.team_b_score)) {
        Object.assign(round, createScoreline(round.probability_a, round.winner));
        updated = true;
      }
      if (!Array.isArray(round.week_games)) {
        round.week_games = [gameRecordForRound(round)];
        updated = true;
      }
      if (!Number.isFinite(round.debt_before)) {
        round.debt_before = 0;
        updated = true;
      }
      if (!Number.isFinite(round.debt_after)) {
        round.debt_after = 0;
        updated = true;
      }
      if (!Number.isInteger(round.loan_amount)) {
        round.loan_amount = 0;
        updated = true;
      }
    }
    if (restored.last_result && !Number.isInteger(restored.last_result.team_a_score)) {
      const savedRound = restored.rounds.find(
        (round) => round.round_number === restored.last_result.round_number
      );
      if (savedRound) {
        restored.last_result.team_a_score = savedRound.team_a_score;
        restored.last_result.team_b_score = savedRound.team_b_score;
        updated = true;
      }
    }
    const previousBetTeam = lastBetTeam(restored.rounds);
    if (!restored.current_week && restored.current_event && !restored.finished) {
      const repeatsPreviousBet = [restored.current_event.team_a, restored.current_event.team_b]
        .includes(previousBetTeam);
      restored.current_week = createWeek(
        restored.rounds.length + 1,
        repeatsPreviousBet ? null : restored.current_event,
        previousBetTeam
      );
      if (repeatsPreviousBet) {
        restored.selected_team = null;
      }
      updated = true;
    } else if (restored.current_week && !restored.last_result && !restored.finished) {
      const nextFeaturedIndex = featuredIndexWithoutTeam(
        restored.current_week.games,
        restored.current_week.featured_index,
        previousBetTeam
      );
      if (nextFeaturedIndex !== restored.current_week.featured_index) {
        restored.current_week.featured_index = nextFeaturedIndex;
        restored.current_week.games.forEach((game, index) => {
          game.featured = index === nextFeaturedIndex;
        });
        restored.selected_team = null;
        updated = true;
      }
      restored.current_event = restored.current_week.games[nextFeaturedIndex] ?? null;
    }
    if (updated) {
      sessionStorage.setItem(SESSION_KEY, JSON.stringify(restored));
    }
    return restored;
  } catch (error) {
    showError(`This browser could not restore the saved study session: ${error.message}`);
    return null;
  }
}

function saveSession() {
  try {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(state));
  } catch (error) {
    showError(`Progress could not be saved in this browser: ${error.message}. Keep this tab open until the upload finishes.`);
  }
}

function createEvent(teamA, teamB) {
  const probabilityA = 0.3 + Math.random() * 0.4;
  const margin = 1.05;
  const oddsA = round2(1 / (probabilityA * margin));
  const oddsB = round2(1 / ((1 - probabilityA) * margin));
  const impliedA = 1 / oddsA;
  const impliedB = 1 / oddsB;
  return {
    team_a: teamA,
    team_b: teamB,
    probability_a: impliedA / (impliedA + impliedB),
    odds_a: oddsA,
    odds_b: oddsB
  };
}

function featuredIndexWithoutTeam(games, preferredIndex, excludedTeam) {
  if (!excludedTeam) {
    return preferredIndex;
  }
  for (let offset = 0; offset < games.length; offset += 1) {
    const index = (preferredIndex + offset) % games.length;
    const game = games[index];
    if (game.team_a !== excludedTeam && game.team_b !== excludedTeam) {
      return index;
    }
  }
  return preferredIndex;
}

function createWeek(weekNumber, preservedEvent = null, excludedTeam = null) {
  let fixtures = WEEKLY_SCHEDULE[weekNumber - 1].map((fixture) => ({ ...fixture }));
  if (
    preservedEvent &&
    [preservedEvent.team_a, preservedEvent.team_b].includes(excludedTeam)
  ) {
    preservedEvent = null;
  }
  let featuredIndex = featuredIndexWithoutTeam(
    fixtures,
    (weekNumber - 1) % fixtures.length,
    excludedTeam
  );

  if (preservedEvent) {
    const matchingFixture = fixtures.findIndex(
      (fixture) =>
        fixture.team_a === preservedEvent.team_a &&
        fixture.team_b === preservedEvent.team_b
    );
    if (matchingFixture >= 0) {
      featuredIndex = matchingFixture;
    } else {
      const remainingTeams = fixtures
        .flatMap((fixture) => [fixture.team_a, fixture.team_b])
        .filter((team) => team !== preservedEvent.team_a && team !== preservedEvent.team_b);
      let nextTeam = 0;
      fixtures = fixtures.map((fixture, index) => {
        if (index === featuredIndex) {
          return {
            team_a: preservedEvent.team_a,
            team_b: preservedEvent.team_b
          };
        }
        const replacement = {
          team_a: remainingTeams[nextTeam],
          team_b: remainingTeams[nextTeam + 1]
        };
        nextTeam += 2;
        return replacement;
      });
    }
  }

  const games = fixtures.map((fixture, index) => ({
    ...createEvent(fixture.team_a, fixture.team_b),
    featured: index === featuredIndex,
    bet_result: null
  }));
  if (preservedEvent) {
    games[featuredIndex] = {
      ...games[featuredIndex],
      ...preservedEvent,
      featured: true,
      bet_result: null
    };
  }

  return { week: weekNumber, featured_index: featuredIndex, games };
}

function round2(value) {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

function createScoreline(probabilityA, winner) {
  const winnerProbability = winner === "A" ? probabilityA : 1 - probabilityA;
  const confidence = Math.min(1, Math.max(0, (winnerProbability - 0.5) / 0.2));
  const maxMargin = 1 + Math.round(confidence * 3);
  const margin = 1 + Math.floor(Math.random() * maxMargin);
  const lowerScore = Math.floor(Math.random() * 6);
  const higherScore = lowerScore + margin;

  return winner === "A"
    ? { team_a_score: higherScore, team_b_score: lowerScore }
    : { team_a_score: lowerScore, team_b_score: higherScore };
}

function gameRecordForRound(round) {
  return {
    team_a: round.team_a,
    team_b: round.team_b,
    team_a_score: round.team_a_score,
    team_b_score: round.team_b_score,
    odds_a: round.odds_a,
    odds_b: round.odds_b,
    probability_a: round.probability_a,
    winner: round.winner,
    featured: true,
    bet_result: round.bet_result
  };
}

function lastBetTeam(rounds) {
  const previousRound = rounds[rounds.length - 1];
  if (!previousRound) {
    return null;
  }
  if (previousRound.selection === "A") {
    return previousRound.team_a;
  }
  if (previousRound.selection === "B") {
    return previousRound.team_b;
  }
  return null;
}

function createSession() {
  return {
    participant_id: crypto.randomUUID(),
    condition: Math.random() < 0.5 ? "winning" : "losing",
    balance: STARTING_CREDITS,
    debt: 0,
    current_loan: 0,
    rounds: [],
    current_event: null,
    current_week: null,
    selected_team: null,
    finished: false,
    uploaded: false
  };
}

function phaseForRound(roundNumber) {
  if (roundNumber <= 4) {
    return "baseline";
  }
  if (roundNumber <= 8) {
    return "streak";
  }
  return "post";
}

function phaseLabel(roundNumber) {
  return `WEEK ${String(roundNumber).padStart(2, "0")} · LEAGUE PLAY`;
}

function formatCredits(value) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
}

async function checkServer() {
  if (!apiBaseUrl) {
    setServerStatus("The study server URL is not configured. The study cannot be started yet.", "error");
    updateBeginButton();
    return;
  }

  let endpoint;
  try {
    endpoint = new URL(`${apiBaseUrl}/api/health`);
  } catch (error) {
    setServerStatus(`The configured study server URL is invalid: ${error.message}`, "error");
    updateBeginButton();
    return;
  }

  if (endpoint.protocol !== "https:" && !isLoopbackHost(window.location.hostname)) {
    setServerStatus("The public study site requires an HTTPS study server. Update docs/config.js before publishing.", "error");
    updateBeginButton();
    return;
  }
  if (isLoopbackHost(endpoint.hostname) && !isLoopbackHost(window.location.hostname)) {
    setServerStatus("The configured server is local to your computer and cannot receive public participant responses.", "error");
    updateBeginButton();
    return;
  }

  try {
    const response = await fetch(endpoint, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`server returned HTTP ${response.status}`);
    }
    const result = await response.json();
    if (result.status !== "ok") {
      throw new Error("server health check did not succeed");
    }
    serverReady = true;
    setServerStatus("Study server connected. Responses will be submitted when the simulation is complete.", "success");
  } catch (error) {
    serverReady = false;
    setServerStatus(`Could not connect to the study server: ${error.message}. Check its address and try reloading.`, "error");
  }
  updateBeginButton();
}

function updateBeginButton() {
  beginButton.disabled = !serverReady || !consentInput.checked || Boolean(state);
}

function render() {
  intro.hidden = Boolean(state);
  studyLayout.hidden = !state;
  gamePanel.hidden = !state || state.finished;
  completePanel.hidden = !state || !state.finished;

  if (!state) {
    updateBeginButton();
    return;
  }
  if (state.finished) {
    renderLeague();
    renderCompletion();
    return;
  }
  renderRound();
  renderLeague();
}

function renderRound() {
  const roundNumber = state.rounds.length + 1;
  const phase = phaseForRound(roundNumber);
  const progress = Math.round((state.rounds.length / TOTAL_ROUNDS) * 100);
  const progressBar = document.querySelector(".progress-track");

  document.querySelector("#phase-label").textContent = phaseLabel(roundNumber);
  document.querySelector("#round-heading").textContent = `Week ${roundNumber} of ${TOTAL_ROUNDS}`;
  document.querySelector("#balance-value").textContent = formatCredits(state.balance);
  document.querySelector("#debt-value").textContent = formatCredits(state.debt);
  const netValue = document.querySelector("#net-value");
  const netPosition = round2(state.balance - state.debt);
  netValue.textContent = formatCredits(netPosition);
  netValue.classList.toggle("is-debt", netPosition < 0);
  document.querySelector("#progress-value").style.width = `${progress}%`;
  progressBar.setAttribute("aria-valuenow", String(state.rounds.length));

  const isShowingResult = Boolean(state.last_result);
  document.querySelector("#wager-row").hidden = isShowingResult;
  document.querySelector("#loan-prompt").hidden = true;
  document.querySelector("#round-feedback").hidden = !isShowingResult;
  if (isShowingResult) {
    renderLastResult();
    return;
  }

  if (!state.current_week || state.current_week.week !== roundNumber) {
    state.current_week = createWeek(roundNumber, null, lastBetTeam(state.rounds));
    state.current_event = state.current_week.games[state.current_week.featured_index];
    state.selected_team = null;
    saveSession();
  } else {
    state.current_event =
      state.current_week.games[state.current_week.featured_index] ?? null;
  }
  const previousBet = lastBetTeam(state.rounds);
  document.querySelector("#odds-note").textContent = previousBet
    ? `You backed ${previousBet} last week, so this week's featured matchup offers two different teams. The other five games also affect the league standings.`
    : "Make one pick from the featured matchup. Five other games are also played this week and count toward the league standings.";
  renderTeamOptions();

  const maxStake = Math.min(MAX_STAKE, Math.floor(state.balance));
  const wagerRow = document.querySelector("#wager-row");
  const loanPrompt = document.querySelector("#loan-prompt");
  wagerRow.hidden = maxStake < 1;
  loanPrompt.hidden = maxStake >= 1;
  if (maxStake < 1) {
    return;
  }

  const stakeInput = document.querySelector("#stake-input");
  stakeInput.max = String(maxStake);
  stakeInput.value = "25";
  document.querySelector("#stake-help").textContent =
    `Choose 1 to ${formatCredits(maxStake)} credits (max 500 and no more than available credits).`;
  stakeInput.oninput = updateBetButton;
  updateBetButton();
}

function renderTeamOptions() {
  const container = document.querySelector("#team-options");
  const event = state.current_event;
  container.replaceChildren();

  for (const team of [
    { key: "A", name: event.team_a, odds: event.odds_a },
    { key: "B", name: event.team_b, odds: event.odds_b }
  ]) {
    const label = document.createElement("label");
    label.className = `team-option${state.selected_team === team.key ? " selected" : ""}`;

    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "team";
    radio.value = team.key;
    radio.checked = state.selected_team === team.key;
    radio.addEventListener("change", () => {
      state.selected_team = team.key;
      saveSession();
      renderTeamOptions();
      updateBetButton();
    });

    const content = document.createElement("span");
    content.className = "team-option-content";
    const name = document.createElement("span");
    name.className = "team-name";
    name.textContent = team.name;
    const odds = document.createElement("span");
    odds.className = "team-odds";
    odds.textContent = `${team.odds.toFixed(2)}×`;
    content.append(name, odds);
    label.append(radio, content);
    container.append(label);
  }
}

function updateBetButton() {
  const stakeInput = document.querySelector("#stake-input");
  const stake = Number(stakeInput.value);
  const maxStake = Math.min(MAX_STAKE, Math.floor(state.balance));
  document.querySelector("#place-bet-button").disabled =
    !state.selected_team ||
    !Number.isSafeInteger(stake) ||
    stake < 1 ||
    stake > maxStake;
}

function placeBet() {
  clearError();
  const roundNumber = state.rounds.length + 1;
  const phase = phaseForRound(roundNumber);
  const event = state.current_event;
  const stake = Number(document.querySelector("#stake-input").value);
  const balanceBefore = round2(state.balance);
  const maxStake = Math.min(MAX_STAKE, Math.floor(balanceBefore));

  if (!event || !["A", "B"].includes(state.selected_team) || !Number.isSafeInteger(stake) || stake < 1 || stake > maxStake) {
    showError("Choose a team and a whole-credit stake within your available credits and the 500-credit round limit.");
    return;
  }

  const forced = phase === "streak";
  let winner;
  if (forced) {
    winner = state.condition === "winning"
      ? state.selected_team
      : state.selected_team === "A" ? "B" : "A";
  } else {
    winner = Math.random() < event.probability_a ? "A" : "B";
  }

  const betResult = winner === state.selected_team ? "win" : "loss";
  const selectedOdds = state.selected_team === "A" ? event.odds_a : event.odds_b;
  const scoreline = createScoreline(event.probability_a, winner);
  const profit = round2(betResult === "win" ? stake * (selectedOdds - 1) : -stake);
  const balanceAfter = round2(balanceBefore + profit);
  const completedGames = state.current_week.games.map((game, index) => {
    if (index === state.current_week.featured_index) {
      return {
        ...game,
        ...scoreline,
        winner,
        featured: true,
        bet_result: betResult
      };
    }
    const gameWinner = Math.random() < game.probability_a ? "A" : "B";
    return {
      ...game,
      ...createScoreline(game.probability_a, gameWinner),
      winner: gameWinner,
      featured: false,
      bet_result: null
    };
  });
  state.current_week.games = completedGames;
  const completedFeaturedGame = completedGames[state.current_week.featured_index];

  const record = {
    round_number: roundNumber,
    phase,
    team_a: completedFeaturedGame.team_a,
    team_b: completedFeaturedGame.team_b,
    team_a_score: completedFeaturedGame.team_a_score,
    team_b_score: completedFeaturedGame.team_b_score,
    week_games: completedGames,
    odds_a: completedFeaturedGame.odds_a,
    odds_b: completedFeaturedGame.odds_b,
    probability_a: completedFeaturedGame.probability_a,
    selection: state.selected_team,
    selected_odds: selectedOdds,
    stake,
    stake_share: stake / Math.max(balanceBefore, 1),
    winner,
    bet_result: betResult,
    profit,
    balance_before: balanceBefore,
    balance_after: balanceAfter,
    debt_before: state.debt - state.current_loan,
    debt_after: state.debt,
    loan_amount: state.current_loan,
    forced
  };

  state.rounds.push(record);
  state.balance = balanceAfter;
  state.current_loan = 0;
  state.current_event = null;
  state.selected_team = null;
  state.last_result = record;
  if (state.rounds.length === TOTAL_ROUNDS) {
    state.finished = true;
  }
  saveSession();
  render();
  if (state.finished) {
    submitSession();
  }
}

function renderLastResult() {
  const result = state.last_result;
  const won = result.bet_result === "win";
  const feedback = document.querySelector("#round-feedback");
  feedback.classList.toggle("is-loss", !won);
  feedback.classList.toggle("is-win", won);
  document.querySelector("#result-outcome").textContent = won ? "BET WON" : "BET LOST";
  document.querySelector("#result-heading").textContent = won ? "Your bet won" : "Your bet lost";
  document.querySelector("#result-delta").textContent = won
    ? `+${formatCredits(result.profit)} credits`
    : `-${formatCredits(result.stake)} credits`;
  document.querySelector("#result-copy").textContent =
    `Final score: ${result.team_a} ${result.team_a_score}-${result.team_b_score} ${result.team_b}. Your balance is now ${formatCredits(result.balance_after)} credits.`;
}

function renderLeague() {
  const standings = new Map(
    TEAMS.map((team) => [team, { team, wins: 0, losses: 0 }])
  );
  const completedGames = state.rounds.flatMap((round) => {
    const weekGames = round.week_games?.length
      ? round.week_games
      : [gameRecordForRound(round)];
    return weekGames.map((game) => ({ ...game, round_number: round.round_number }));
  });
  for (const game of completedGames) {
    const winnerTeam = game.winner === "A" ? game.team_a : game.team_b;
    const loserTeam = game.winner === "A" ? game.team_b : game.team_a;
    standings.get(winnerTeam).wins += 1;
    standings.get(loserTeam).losses += 1;
  }

  const orderedStandings = [...standings.values()].sort((first, second) => {
    const firstGames = first.wins + first.losses;
    const secondGames = second.wins + second.losses;
    const firstRate = firstGames ? first.wins / firstGames : 0;
    const secondRate = secondGames ? second.wins / secondGames : 0;
    return secondRate - firstRate || second.wins - first.wins || first.team.localeCompare(second.team);
  });

  const currentEvent = state.current_week?.games[state.current_week.featured_index];
  const currentTeams = new Set(currentEvent ? [currentEvent.team_a, currentEvent.team_b] : []);
  const standingsBody = document.querySelector("#standings-body");
  standingsBody.replaceChildren();
  for (const record of orderedStandings) {
    const row = document.createElement("tr");
    const games = record.wins + record.losses;
    if (games) {
      row.classList.add("is-played");
    }
    if (currentTeams.has(record.team)) {
      row.classList.add("is-current");
    }

    const teamCell = document.createElement("td");
    teamCell.textContent = record.team;
    const recordCell = document.createElement("td");
    recordCell.textContent = `${record.wins}-${record.losses}`;
    row.append(teamCell, recordCell);
    standingsBody.append(row);
  }

  const gamesPlayed = document.querySelector("#games-played");
  gamesPlayed.textContent = `${completedGames.length} / ${TOTAL_ROUNDS * 6} GAMES`;

  const weekLabel = document.querySelector("#week-label");
  const weekFixtures = document.querySelector("#week-fixtures");
  weekFixtures.replaceChildren();
  if (state.current_week) {
    weekLabel.textContent = `WEEK ${String(state.current_week.week).padStart(2, "0")}`;
    state.current_week.games.forEach((game, index) => {
      const item = document.createElement("li");
      item.className = `week-fixture${game.featured ? " is-featured" : ""}${game.winner ? " is-complete" : ""}`;

      const heading = document.createElement("div");
      heading.className = "fixture-heading";
      const gameNumber = document.createElement("span");
      gameNumber.textContent = `GAME ${String(index + 1).padStart(2, "0")}`;
      const gameTag = document.createElement("span");
      gameTag.className = "fixture-tag";
      gameTag.textContent = game.featured ? "YOUR PICK" : game.winner ? "FINAL" : "IN PLAY";
      heading.append(gameNumber, gameTag);

      const matchup = document.createElement("div");
      matchup.className = "fixture-matchup";
      const teamA = document.createElement("span");
      teamA.textContent = game.team_a;
      const score = document.createElement("strong");
      score.textContent = game.winner
        ? `${game.team_a_score} – ${game.team_b_score}`
        : "VS";
      const teamB = document.createElement("span");
      teamB.textContent = game.team_b;
      matchup.append(teamA, score, teamB);
      item.append(heading, matchup);
      weekFixtures.append(item);
    });
  } else {
    weekLabel.textContent = "SEASON";
  }

  const gameResults = document.querySelector("#past-games");
  gameResults.replaceChildren();
  document.querySelector("#empty-games").hidden = completedGames.length > 0;
  for (const game of [...completedGames].reverse()) {
    const item = document.createElement("li");
    item.className = `game-result${game.bet_result ? ` is-${game.bet_result}` : ""}`;

    const heading = document.createElement("div");
    heading.className = "game-result-topline";
    const weekNumber = document.createElement("span");
    weekNumber.textContent = `WEEK ${String(game.round_number).padStart(2, "0")}`;
    const betOutcome = document.createElement("span");
    betOutcome.className = "bet-outcome";
    betOutcome.textContent = game.bet_result
      ? game.bet_result === "win" ? "BET WON" : "BET LOST"
      : game.featured ? "FEATURED GAME" : "LEAGUE RESULT";
    heading.append(weekNumber, betOutcome);

    const scoreline = document.createElement("div");
    scoreline.className = "game-result-scoreline";
    const teamA = document.createElement("span");
    teamA.className = `game-result-team${game.winner === "A" ? " is-winner" : ""}`;
    const teamAName = document.createElement("span");
    teamAName.textContent = game.team_a;
    const teamAScore = document.createElement("strong");
    teamAScore.className = "game-result-score";
    teamAScore.textContent = String(game.team_a_score);
    teamA.append(teamAName, teamAScore);

    const teamB = document.createElement("span");
    teamB.className = `game-result-team${game.winner === "B" ? " is-winner" : ""}`;
    const teamBName = document.createElement("span");
    teamBName.textContent = game.team_b;
    const teamBScore = document.createElement("strong");
    teamBScore.className = "game-result-score";
    teamBScore.textContent = String(game.team_b_score);
    teamB.append(teamBName, teamBScore);

    const separator = document.createElement("span");
    separator.className = "score-separator";
    separator.textContent = "-";
    scoreline.append(teamA, separator, teamB);
    item.append(heading, scoreline);
    gameResults.append(item);
  }
}

function continueSimulation() {
  state.last_result = null;
  state.current_event = null;
  state.current_week = null;
  state.current_loan = 0;
  state.selected_team = null;
  saveSession();
  render();
}

function takeLoan() {
  if (!state || state.finished || Math.floor(state.balance) >= 1 || state.current_loan) {
    return;
  }
  state.balance = round2(state.balance + LOAN_CREDITS);
  state.debt = round2(state.debt + LOAN_CREDITS);
  state.current_loan = LOAN_CREDITS;
  saveSession();
  render();
}

function meanStakeShare(phase) {
  const rows = state.rounds.filter((round) => round.phase === phase);
  const mean = rows.reduce((total, round) => total + round.stake_share, 0) / rows.length;
  return `${(mean * 100).toFixed(1)}% of available balance`;
}

function renderCompletion() {
  document.querySelector("#baseline-summary").textContent = meanStakeShare("baseline");
  document.querySelector("#follow-up-summary").textContent = meanStakeShare("post");
  document.querySelector("#ending-account").textContent =
    `${formatCredits(state.balance)} available · ${formatCredits(state.debt)} debt · ${formatCredits(round2(state.balance - state.debt))} net`;
  document.querySelector("#debrief-condition").textContent = state.condition === "winning" ? "winning" : "losing";
  document.querySelector("#completion-copy").textContent =
    `Your random study ID is ${state.participant_id}. The study server receives your betting choices and study condition, but not a name or contact detail.`;

  const retryButton = document.querySelector("#retry-upload-button");
  retryButton.hidden = state.uploaded;
  document.querySelector("#new-participant-button").disabled = uploadInProgress;
  const uploadStatus = document.querySelector("#upload-status");
  if (state.uploaded) {
    uploadStatus.textContent = "Your responses were received by the study server.";
    uploadStatus.className = "server-status success";
  } else if (state.upload_error) {
    uploadStatus.textContent = `Your responses have not reached the study server: ${state.upload_error}. Keep this page open, retry, or download the CSV and contact the researcher.`;
    uploadStatus.className = "server-status error";
  } else {
    uploadStatus.textContent = "Submitting your responses…";
    uploadStatus.className = "server-status";
  }
}

async function submitSession() {
  if (!state?.finished || state.uploaded || uploadInProgress) {
    return;
  }
  uploadInProgress = true;
  const retryButton = document.querySelector("#retry-upload-button");
  retryButton.hidden = true;
  state.upload_error = null;
  saveSession();
  renderCompletion();

  try {
    const response = await fetch(`${apiBaseUrl}/api/submissions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        participant_id: state.participant_id,
        condition: state.condition,
        rounds: state.rounds
      })
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      const detail = body.detail;
      throw new Error(
        typeof detail === "string"
          ? detail
          : detail ? JSON.stringify(detail) : `server returned HTTP ${response.status}`
      );
    }
    state.uploaded = true;
    state.upload_error = null;
    try {
      sessionStorage.removeItem(SESSION_KEY);
    } catch (error) {
      showError(`Your response was received, but this browser could not clear its saved copy: ${error.message}`);
    }
    renderCompletion();
  } catch (error) {
    state.upload_error = error.message;
    saveSession();
    renderCompletion();
  } finally {
    uploadInProgress = false;
    renderCompletion();
  }
}

function csvEscape(value) {
  const text = String(value);
  return `"${text.replaceAll('"', '""')}"`;
}

function downloadCsv() {
  const lines = [CSV_COLUMNS.map(csvEscape).join(",")];
  for (const round of state.rounds) {
    const row = {
      participant_id: state.participant_id,
      condition: state.condition,
      ...round,
      week_games: JSON.stringify(round.week_games ?? [gameRecordForRound(round)])
    };
    lines.push(CSV_COLUMNS.map((column) => csvEscape(row[column])).join(","));
  }
  const blob = new Blob([`${lines.join("\r\n")}\r\n`], { type: "text/csv;charset=utf-8" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `study-${state.participant_id}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function startNewParticipant() {
  if (uploadInProgress) {
    return;
  }
  if (!state.uploaded && !window.confirm("The current responses have not been confirmed by the study server. Start a new participant session anyway?")) {
    return;
  }
  try {
    sessionStorage.removeItem(SESSION_KEY);
  } catch (error) {
    showError(`This browser could not clear the saved session: ${error.message}`);
    return;
  }
  state = null;
  consentInput.checked = false;
  render();
}

consentInput.addEventListener("change", updateBeginButton);
beginButton.addEventListener("click", () => {
  if (!serverReady || !consentInput.checked || state) {
    return;
  }
  clearError();
  state = createSession();
  saveSession();
  render();
});
document.querySelector("#place-bet-button").addEventListener("click", placeBet);
document.querySelector("#continue-button").addEventListener("click", continueSimulation);
document.querySelector("#loan-button").addEventListener("click", takeLoan);
document.querySelector("#download-button").addEventListener("click", downloadCsv);
document.querySelector("#retry-upload-button").addEventListener("click", submitSession);
document.querySelector("#new-participant-button").addEventListener("click", startNewParticipant);

render();
checkServer();

if (state?.finished && !state.uploaded) {
  submitSession();
}
