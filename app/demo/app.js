"use strict";

const byId = (id) => document.getElementById(id);
const state = {
  recommendation: null,
  traces: [],
  actionKey: null,
  actionPayload: null,
  actionRecord: null,
};

const errorMessages = {
  exception_not_found: "The selected business exception no longer exists. Check the case identifier and try again.",
  missing_evidence: "A linked ERP or logistics record is unavailable, so the agent stopped instead of guessing.",
  connector_bad_response: "An enterprise system returned data that did not match the agreed contract.",
  invalid_provider_output: "The reasoning result failed local schema or evidence validation.",
  provider_refusal: "The reasoning provider declined to analyse this case.",
  incomplete_provider_output: "The reasoning provider returned an incomplete response.",
  connector_unavailable: "An enterprise connector is temporarily unavailable. The request can be retried safely.",
  connector_circuit_open: "A connector circuit is temporarily open after repeated upstream failures. Try again later.",
  provider_unavailable: "The configured reasoning provider is temporarily unavailable.",
  provider_configuration_error: "The selected reasoning provider is not configured for this environment.",
  connector_timeout: "An enterprise connector exceeded its timeout. The request can be retried safely.",
  provider_timeout: "The reasoning provider exceeded its timeout. No fallback result was substituted.",
  corrupt_local_data: "The local demonstration data could not be validated.",
  internal_error: "The application could not complete the request safely.",
};

const eventDescriptions = {
  evidence_collected: ["Evidence catalogue built", "The retrieved records were validated and converted into stable evidence."],
  model_invoked: ["Reasoner invoked", "The selected provider received the canonical context snapshot."],
  model_completed: ["Reasoning completed", "A structured recommendation was returned for local validation."],
  output_validated: ["Output validated", "Required fields, confidence, and evidence references passed application checks."],
  recommendation_created: ["Recommendation created", "The validated recommendation became available to operations."],
  resolution_completed: ["Analysis completed", "The correlated run reached a successful terminal state."],
  action_intent_recorded: ["Action intent recorded", "One immutable record was committed to the local action journal."],
  action_intent_replayed: ["Idempotent replay confirmed", "The existing action record was returned without creating a duplicate."],
};

function announce(message) {
  byId("live-status").textContent = message;
}

function humanize(value) {
  if (value === null || value === undefined) return "Not available";
  return String(value)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatDate(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, options);
  let payload = null;
  try {
    payload = await response.json();
  } catch (_) {
    payload = null;
  }
  if (!response.ok) {
    const detail = payload && payload.detail ? payload.detail : {};
    const error = new Error(detail.message || `Request failed with HTTP ${response.status}.`);
    error.code = detail.code || `http_${response.status}`;
    error.runId = detail.run_id || response.headers.get("X-Run-ID");
    error.status = response.status;
    throw error;
  }
  return { payload, response };
}

function createBadge(label, neutral = false) {
  const badge = document.createElement("span");
  badge.className = neutral ? "badge badge-neutral" : "badge";
  badge.textContent = label;
  return badge;
}

async function loadSystemStatus() {
  const container = byId("system-badges");
  try {
    const { payload } = await fetchJson("/demo/status");
    const connectorLabel = payload.connector_mode === "fixture"
      ? "Synthetic fixture data"
      : payload.connector_mode === "http"
        ? "HTTP enterprise connectors"
        : "Injected test connectors";
    container.replaceChildren(
      createBadge(connectorLabel),
      createBadge(`${humanize(payload.reasoner_provider)} reasoner`),
      createBadge("Record-only actions", true),
      createBadge(`v${payload.version}`, true),
    );
  } catch (_) {
    container.replaceChildren(createBadge("Status unavailable", true));
  }
}

function selectTab(selectedTab, moveFocus = true) {
  const tabs = [byId("workflow-tab"), byId("architecture-tab")];
  for (const tab of tabs) {
    const selected = tab === selectedTab;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    byId(tab.getAttribute("aria-controls")).hidden = !selected;
  }
  if (moveFocus) selectedTab.focus();
}

function configureTabs() {
  const tabs = [byId("workflow-tab"), byId("architecture-tab")];
  for (const tab of tabs) {
    tab.addEventListener("click", () => selectTab(tab));
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      let index = tabs.indexOf(tab);
      if (event.key === "ArrowLeft") index = (index - 1 + tabs.length) % tabs.length;
      if (event.key === "ArrowRight") index = (index + 1) % tabs.length;
      if (event.key === "Home") index = 0;
      if (event.key === "End") index = tabs.length - 1;
      selectTab(tabs[index]);
    });
  }
}

function setProgress(step, allComplete = false) {
  for (const item of document.querySelectorAll(".progress-steps li")) {
    const itemStep = Number(item.dataset.step);
    item.classList.toggle("complete", allComplete || itemStep < step);
    item.classList.toggle("active", !allComplete && itemStep === step);
  }
}

function resetWorkflow() {
  state.recommendation = null;
  state.traces = [];
  state.actionKey = generateIdempotencyKey();
  state.actionPayload = null;
  state.actionRecord = null;
  byId("results").hidden = true;
  byId("error-panel").hidden = true;
  byId("processing-panel").hidden = true;
  byId("start-panel").hidden = false;
  byId("action-result").hidden = true;
  unlockActionForm();
  setProgress(1);
}

function showError(error) {
  byId("processing-panel").hidden = true;
  byId("start-panel").hidden = false;
  byId("error-panel").hidden = false;
  byId("error-title").textContent = `Analysis stopped safely${error.status ? ` (HTTP ${error.status})` : ""}`;
  byId("error-message").textContent = errorMessages[error.code] || error.message || errorMessages.internal_error;
  byId("error-run").textContent = error.runId ? `Run reference: ${error.runId}` : "No run reference was returned.";
  byId("analyse-button").disabled = false;
  setProgress(1);
  announce("The analysis stopped safely. Review the error message or try again.");
}

function sourceTitle(source) {
  if (source === "ERP") return "ERP order";
  if (source === "Logistics") return "Shipment status";
  if (source === "Carrier note") return "Carrier communication";
  return source;
}

function displayFields(record, source) {
  const preferred = source === "ERP"
    ? ["order_id", "customer", "material", "quantity", "requested_delivery_date", "incoterm", "order_status"]
    : source === "Logistics"
      ? ["shipment_id", "carrier", "status", "current_eta", "last_event"]
      : ["note_id", "shipment_id", "text"];
  const keys = [...preferred.filter((key) => Object.hasOwn(record, key))];
  for (const key of Object.keys(record).sort()) {
    if (!keys.includes(key)) keys.push(key);
  }
  return keys;
}

function renderEvidence(recommendation) {
  const container = byId("evidence-grid");
  const cards = [];
  for (const evidence of recommendation.evidence) {
    const card = document.createElement("article");
    card.className = "evidence-card";
    const cause = recommendation.cause_evidence_ids.includes(evidence.evidence_id);
    const action = recommendation.action_evidence_ids.includes(evidence.evidence_id);
    if (cause) card.classList.add("cited-cause");
    if (action) card.classList.add("cited-action");

    const sourceRow = document.createElement("div");
    sourceRow.className = "evidence-source";
    const title = document.createElement("strong");
    title.textContent = sourceTitle(evidence.source);
    const icon = document.createElement("span");
    icon.className = "source-icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = evidence.source.slice(0, 1).toUpperCase();
    sourceRow.append(title, icon);

    const id = document.createElement("p");
    id.className = "evidence-id";
    id.textContent = evidence.evidence_id;

    let record;
    try {
      record = JSON.parse(evidence.fact);
    } catch (_) {
      record = { fact: evidence.fact };
    }
    if (!record || typeof record !== "object" || Array.isArray(record)) record = { fact: String(record) };

    const facts = document.createElement("dl");
    facts.className = "evidence-facts";
    for (const key of displayFields(record, evidence.source)) {
      const row = document.createElement("div");
      const term = document.createElement("dt");
      const value = document.createElement("dd");
      term.textContent = humanize(key);
      value.textContent = typeof record[key] === "object" ? JSON.stringify(record[key]) : String(record[key]);
      row.append(term, value);
      facts.append(row);
    }

    const tags = document.createElement("div");
    tags.className = "citation-tags";
    if (cause) {
      const tag = document.createElement("span");
      tag.className = "citation-tag citation-cause";
      tag.textContent = "Supports cause";
      tags.append(tag);
    }
    if (action) {
      const tag = document.createElement("span");
      tag.className = "citation-tag citation-action";
      tag.textContent = "Supports action";
      tags.append(tag);
    }
    card.append(sourceRow, id, facts, tags);
    cards.push(card);
  }
  container.replaceChildren(...cards);
}

function renderRecommendation(recommendation) {
  byId("category").textContent = humanize(recommendation.category);
  byId("risk").textContent = `${humanize(recommendation.risk_level)} risk`;
  byId("risk").dataset.risk = recommendation.risk_level;
  byId("approval").textContent = recommendation.human_approval_required ? "Human review advised" : "No approval flag";
  byId("recommendation-summary").textContent = recommendation.summary;
  byId("recommended-action").textContent = recommendation.recommended_action;
  const confidence = Math.round(recommendation.confidence * 100);
  byId("confidence").textContent = `${confidence}%`;
  byId("confidence-ring").style.setProperty("--confidence", `${confidence * 3.6}deg`);
  byId("action-reason").value = recommendation.recommended_action.slice(0, 1000);
  byId("document-type").value = /invoice/i.test(recommendation.recommended_action)
    ? "commercial_invoice"
    : "other";
}

function connectorEventDescription(event) {
  if (event.event_type !== "connector_completed") return null;
  const labels = {
    get_erp_order: ["ERP order retrieved", "The linked sales order passed typed record validation."],
    get_logistics_status: ["Shipment status retrieved", "The carrier status and current ETA were collected."],
    get_shipment_note: ["Carrier note retrieved", "The untrusted note was collected as evidence, not as an instruction."],
  };
  return labels[event.details.tool] || ["Connector completed", "An enterprise record was retrieved successfully."];
}

function renderTimeline() {
  const timeline = byId("audit-timeline");
  const items = [];
  for (const event of state.traces) {
    const description = connectorEventDescription(event) || eventDescriptions[event.event_type];
    if (!description) continue;
    const item = document.createElement("li");
    const title = document.createElement("strong");
    const detail = document.createElement("p");
    const time = document.createElement("time");
    title.textContent = description[0];
    detail.textContent = description[1];
    time.dateTime = event.timestamp;
    time.textContent = formatDate(event.timestamp);
    item.append(title, detail, time);
    items.push(item);
  }
  timeline.replaceChildren(...items);
}

function renderTechnicalDetails() {
  if (!state.recommendation) return;
  const recommendation = state.recommendation;
  const meta = byId("technical-meta");
  const values = [
    `provider: ${recommendation.provider}`,
    `run: ${recommendation.run_id}`,
    `cause evidence: ${recommendation.cause_evidence_ids.join(", ")}`,
    `action evidence: ${recommendation.action_evidence_ids.join(", ")}`,
  ];
  meta.replaceChildren(...values.map((value) => {
    const item = document.createElement("span");
    item.textContent = value;
    return item;
  }));
  byId("technical-json").textContent = JSON.stringify({
    recommendation,
    trace_events: state.traces,
    action: state.actionRecord,
  }, null, 2);
}

async function loadTrace(exceptionId, runId, append = false) {
  if (!runId) return;
  try {
    const { payload } = await fetchJson(`/exceptions/${encodeURIComponent(exceptionId)}/audit?run_id=${encodeURIComponent(runId)}`);
    state.traces = append ? state.traces.concat(payload.events || []) : (payload.events || []);
    renderTimeline();
    renderTechnicalDetails();
  } catch (_) {
    // The recommendation remains usable if the development-only trace store is unavailable.
  }
}

async function analyseException() {
  resetWorkflow();
  const button = byId("analyse-button");
  button.disabled = true;
  byId("start-panel").hidden = true;
  byId("processing-panel").hidden = false;
  setProgress(2);
  announce("Analysis started. Waiting for the verified application response.");

  const messages = [
    "Waiting for the application to complete the analysis…",
    "The request is still processing safely…",
    "Preparing the validated result for display…",
  ];
  let messageIndex = 0;
  const timer = window.setInterval(() => {
    messageIndex = (messageIndex + 1) % messages.length;
    byId("processing-message").textContent = messages[messageIndex];
  }, 1100);

  try {
    const { payload } = await fetchJson("/exceptions/EX-001/resolve", { method: "POST" });
    state.recommendation = payload;
    renderEvidence(payload);
    renderRecommendation(payload);
    byId("processing-panel").hidden = true;
    byId("results").hidden = false;
    setProgress(4);
    await loadTrace(payload.exception_id, payload.run_id);
    renderTechnicalDetails();
    byId("results").scrollIntoView({ behavior: "smooth", block: "start" });
    announce("Analysis complete. Evidence, recommendation, action controls, and verified trace are now available.");
  } catch (error) {
    showError(error);
  } finally {
    window.clearInterval(timer);
    button.disabled = false;
  }
}

function generateIdempotencyKey() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return `demo-${window.crypto.randomUUID()}`;
  }
  return `demo-${Date.now()}-${Math.random().toString(36).slice(2, 14)}`;
}

function lockActionForm() {
  byId("document-type").disabled = true;
  byId("action-reason").disabled = true;
  byId("record-action-button").hidden = true;
  byId("replay-action-button").hidden = false;
  byId("replay-action-button").disabled = false;
  byId("new-action-button").hidden = false;
}

function unlockActionForm() {
  byId("document-type").disabled = false;
  byId("action-reason").disabled = false;
  byId("record-action-button").hidden = false;
  byId("record-action-button").disabled = false;
  byId("replay-action-button").hidden = true;
  byId("replay-action-button").disabled = false;
  byId("new-action-button").hidden = true;
}

function renderActionResult(record, replayed) {
  const container = byId("action-result");
  const title = document.createElement("h3");
  title.textContent = replayed ? "Existing action returned—no duplicate created" : "Action intent recorded safely";
  const explanation = document.createElement("p");
  explanation.textContent = replayed
    ? "The identical idempotency key and payload returned the original immutable record."
    : "The intent is durable in local SQLite, but no external message or ERP update was performed.";
  const facts = document.createElement("dl");
  const entries = [
    ["Action ID", record.action_id],
    ["Status", humanize(record.status)],
    ["Linked records", `${record.order_id} · ${record.shipment_id}`],
    ["Created", formatDate(record.created_at)],
  ];
  for (const [label, value] of entries) {
    const wrapper = document.createElement("div");
    const term = document.createElement("dt");
    const detail = document.createElement("dd");
    term.textContent = label;
    detail.textContent = value;
    wrapper.append(term, detail);
    facts.append(wrapper);
  }
  container.replaceChildren(title, explanation, facts);
  container.hidden = false;
}

function renderActionError(error) {
  const container = byId("action-result");
  const title = document.createElement("h3");
  const detail = document.createElement("p");
  title.textContent = "Action intent was not recorded";
  detail.textContent = errorMessages[error.code] || error.message || "The request could not be completed.";
  container.replaceChildren(title, detail);
  container.hidden = false;
}

async function submitAction(replay = false) {
  if (!state.recommendation) return;
  const recordButton = byId("record-action-button");
  const replayButton = byId("replay-action-button");
  recordButton.disabled = true;
  replayButton.disabled = true;

  if (!replay) {
    state.actionPayload = Object.freeze({
      exception_id: state.recommendation.exception_id,
      document_type: byId("document-type").value,
      reason: byId("action-reason").value,
    });
  }

  try {
    const { payload, response } = await fetchJson("/actions/request-document", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": state.actionKey,
      },
      body: JSON.stringify(state.actionPayload),
    });
    const replayed = response.headers.get("Idempotency-Replayed") === "true";
    state.actionRecord = payload;
    renderActionResult(payload, replayed);
    lockActionForm();
    setProgress(4, true);
    await loadTrace(payload.exception_id, response.headers.get("X-Run-ID"), true);
    renderTechnicalDetails();
    announce(replayed
      ? "Idempotent replay confirmed. The same action record was returned."
      : "Action intent recorded. No external side effect was performed.");
  } catch (error) {
    renderActionError(error);
    recordButton.disabled = false;
    replayButton.disabled = false;
    announce("The action intent was not recorded.");
  }
}

function startNewAction() {
  state.actionKey = generateIdempotencyKey();
  state.actionPayload = null;
  state.actionRecord = null;
  byId("action-result").hidden = true;
  unlockActionForm();
  setProgress(4);
  byId("document-type").focus();
  announce("A new action request can now be prepared with a new idempotency key.");
}

function configureActions() {
  byId("analyse-button").addEventListener("click", analyseException);
  byId("retry-button").addEventListener("click", analyseException);
  byId("action-form").addEventListener("submit", (event) => {
    event.preventDefault();
    submitAction(false);
  });
  byId("replay-action-button").addEventListener("click", () => submitAction(true));
  byId("new-action-button").addEventListener("click", startNewAction);
}

document.addEventListener("DOMContentLoaded", () => {
  configureTabs();
  configureActions();
  resetWorkflow();
  loadSystemStatus();
  if (new URLSearchParams(window.location.search).get("view") === "architecture") {
    selectTab(byId("architecture-tab"), false);
  }
});
