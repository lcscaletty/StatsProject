"use strict";

const STARTING_CREDITS = 1000;
const TOTAL_ROUNDS = 12;
const SESSION_KEY = "field-notes-study-session-v1";
const CSV_COLUMNS = [
  "participant_id",
  "condition",
  "round_number",
  "phase",
  "team_a",
  "team_b",
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

const apiBaseUrl = (window.STUDY_CONFIG?.apiBaseUrl ?? "").replace(/\/+$/, "");
const intro = document.querySelector("#intro");
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
    return saved ? JSON.parse(saved) : null;
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

function randomItem(items) {
  return items[Math.floor(Math.random() * items.length)];
}

function createEvent() {
  const teamA = randomItem(TEAMS);
  let teamB = randomItem(TEAMS);
  while (teamB === teamA) {
    teamB = randomItem(TEAMS);
  }

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

function round2(value) {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

function createSession() {
  return {
    participant_id: crypto.randomUUID(),
    condition: Math.random() < 0.5 ? "winning" : "losing",
    balance: STARTING_CREDITS,
    rounds: [],
    current_event: null,
    selected_team: null,
    finished: false,
    uploaded: false
  };
}

function phaseForRound(roundNumber) {
  if (roundNumber <= 4) {
    return "baseline";
  }
  if (roundNumber <= 7) {
    return "streak";
  }
  return "post";
}

function phaseLabel(phase) {
  if (phase === "baseline") {
    return "BASELINE";
  }
  if (phase === "streak") {
    return "OUTCOME SEQUENCE";
  }
  return "FOLLOW-UP";
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
  gamePanel.hidden = !state || state.finished;
  completePanel.hidden = !state || !state.finished;

  if (!state) {
    updateBeginButton();
    return;
  }
  if (state.finished) {
    renderCompletion();
    return;
  }
  renderRound();
}

function renderRound() {
  const roundNumber = state.rounds.length + 1;
  const phase = phaseForRound(roundNumber);
  const progress = Math.round((state.rounds.length / TOTAL_ROUNDS) * 100);
  const progressBar = document.querySelector(".progress-track");

  document.querySelector("#phase-label").textContent = phaseLabel(phase);
  document.querySelector("#round-heading").textContent = `Round ${roundNumber} of ${TOTAL_ROUNDS}`;
  document.querySelector("#balance-value").textContent = formatCredits(state.balance);
  document.querySelector("#progress-value").style.width = `${progress}%`;
  progressBar.setAttribute("aria-valuenow", String(state.rounds.length));

  const isShowingResult = Boolean(state.last_result);
  document.querySelector("#wager-row").hidden = isShowingResult;
  document.querySelector("#round-feedback").hidden = !isShowingResult;
  if (isShowingResult) {
    renderLastResult();
    return;
  }

  if (!state.current_event) {
    state.current_event = createEvent();
    state.selected_team = null;
    saveSession();
  }
  renderTeamOptions();

  const maxStake = Math.floor(state.balance * 0.1);
  const stakeInput = document.querySelector("#stake-input");
  stakeInput.max = String(maxStake);
  stakeInput.value = String(Math.min(25, maxStake));
  document.querySelector("#stake-help").textContent = `Choose 1 to ${formatCredits(maxStake)} credits (maximum 10% of your current balance).`;
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
  const maxStake = Math.floor(state.balance * 0.1);
  document.querySelector("#place-bet-button").disabled =
    !state.selected_team ||
    !Number.isInteger(stake) ||
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
  const maxStake = Math.floor(balanceBefore * 0.1);

  if (!event || !["A", "B"].includes(state.selected_team) || !Number.isInteger(stake) || stake < 1 || stake > maxStake) {
    showError("Choose a team and a whole-number stake within the displayed limit.");
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
  const profit = round2(betResult === "win" ? stake * (selectedOdds - 1) : -stake);
  const balanceAfter = round2(balanceBefore + profit);

  const record = {
    round_number: roundNumber,
    phase,
    team_a: event.team_a,
    team_b: event.team_b,
    odds_a: event.odds_a,
    odds_b: event.odds_b,
    probability_a: event.probability_a,
    selection: state.selected_team,
    selected_odds: selectedOdds,
    stake,
    stake_share: stake / balanceBefore,
    winner,
    bet_result: betResult,
    profit,
    balance_before: balanceBefore,
    balance_after: balanceAfter,
    forced
  };

  state.rounds.push(record);
  state.balance = balanceAfter;
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
  const winnerName = result.winner === "A" ? result.team_a : result.team_b;
  const won = result.bet_result === "win";
  document.querySelector("#result-heading").textContent = `Winner: ${winnerName}`;
  document.querySelector("#result-copy").textContent = won
    ? `Your bet won ${formatCredits(result.profit)} credits. Your balance is now ${formatCredits(result.balance_after)}.`
    : `Your bet lost ${formatCredits(result.stake)} credits. Your balance is now ${formatCredits(result.balance_after)}.`;
}

function continueSimulation() {
  state.last_result = null;
  state.current_event = null;
  saveSession();
  render();
}

function meanStakeShare(phase) {
  const rows = state.rounds.filter((round) => round.phase === phase);
  const mean = rows.reduce((total, round) => total + round.stake_share, 0) / rows.length;
  return `${(mean * 100).toFixed(1)}% of balance`;
}

function renderCompletion() {
  document.querySelector("#baseline-summary").textContent = meanStakeShare("baseline");
  document.querySelector("#follow-up-summary").textContent = meanStakeShare("post");
  const conditionLabel = state.condition === "winning" ? "Win sequence" : "Loss sequence";
  document.querySelector("#condition-summary").textContent = conditionLabel;
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
    const row = { participant_id: state.participant_id, condition: state.condition, ...round };
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
  state.current_event = createEvent();
  saveSession();
  render();
});
document.querySelector("#place-bet-button").addEventListener("click", placeBet);
document.querySelector("#continue-button").addEventListener("click", continueSimulation);
document.querySelector("#download-button").addEventListener("click", downloadCsv);
document.querySelector("#retry-upload-button").addEventListener("click", submitSession);
document.querySelector("#new-participant-button").addEventListener("click", startNewParticipant);

render();
checkServer();

if (state?.finished && !state.uploaded) {
  submitSession();
}
