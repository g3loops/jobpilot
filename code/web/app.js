"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const S = {
  options: null,
  fields: { roles: [], skills: [], locations: [], dealbreakers: ["US only", "No contract/temp"], resume_text: "", base: null },
  weights: null, learner: null, excluded: [], metrics: null, total: 0,
  jobMap: {}, feedbackLog: [],
};

async function api(path, body) {
  const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  return r.json();
}

// ---------- chips ----------
function renderChips(containerId, key, opts) {
  const c = $(containerId), vals = S.fields[key], dl = key + "-dl";
  c.innerHTML =
    vals.map((v, i) => `<span class="chip">${esc(v)} <span class="x" data-key="${key}" data-i="${i}">×</span></span>`).join("") +
    `<span class="chip-add"><input list="${dl}" placeholder="+ add" data-addkey="${key}"></span>` +
    `<datalist id="${dl}">${(opts || []).map(o => `<option value="${esc(o)}">`).join("")}</datalist>`;
}
function renderAllChips() {
  renderChips("rolesChips", "roles", S.options.roles);
  renderChips("skillsChips", "skills", S.options.skills);
  renderChips("locationsChips", "locations", S.options.locations);
  renderChips("dealbreakersChips", "dealbreakers", S.options.dealbreakers);
}
document.addEventListener("click", (e) => {
  if (e.target.classList.contains("x")) {
    const k = e.target.dataset.key, i = +e.target.dataset.i;
    S.fields[k].splice(i, 1); renderAllChips();
  }
});
document.addEventListener("keydown", (e) => {
  if (e.target.dataset && e.target.dataset.addkey && e.key === "Enter") {
    e.preventDefault(); addChip(e.target);
  }
});
document.addEventListener("change", (e) => {            // datalist pick
  if (e.target.dataset && e.target.dataset.addkey) addChip(e.target);
});
function addChip(input) {
  const k = input.dataset.addkey, v = input.value.trim();
  if (v && !S.fields[k].includes(v)) { S.fields[k].push(v); renderAllChips(); }
  else input.value = "";
}

// ---------- profile ----------
function buildProfile() {
  const b = S.fields.base;
  return {
    name: b ? b.name : "You",
    resume_text: S.fields.resume_text || (b ? b.resume_text : ""),
    roles: S.fields.roles, skills: S.fields.skills, locations: S.fields.locations,
    dealbreakers: S.fields.dealbreakers, min_salary: +$("salary").value || 0,
    max_years_required: b ? b.max_years_required : null,
    education: b ? b.education : [], experience: b ? b.experience : [], contact: b ? b.contact : "",
    projects: b ? (b.projects || []) : [], publications: b ? (b.publications || []) : [],
    education_first: b ? !!b.education_first : false,
    emphasis: b ? (b.emphasis || []) : [], skills_first: b ? !!b.skills_first : false,
    preferred_locations: b ? (b.preferred_locations || []) : [],
    base_weights: b ? (b.base_weights || null) : null,
  };
}

// ---------- matches ----------
function whyHtml(w) {
  const p = [];
  if (w.matched.length) p.push(`matched skills <b>${esc(w.matched.join(", "))}</b> (${w.overlap})`);
  if (w.title_ok) p.push(`title <b style="color:var(--good)">✓</b>`);
  if (w.salary_ok) p.push(`salary <b style="color:var(--good)">meets min ✓</b>`);
  p.push(`cosine sim <b>${w.similarity}</b>`);
  if (w.missing.length) p.push(`<span style="color:#b06a00">add: ${esc(w.missing.join(", "))}</span>`);
  return p.join(" · ");
}
function jobCard(j, rank) {
  const acc = S.feedbackLog.some(f => f.job_id === j.job_id && f.action === "accept");
  const badge = acc ? ` · <span class="accepted-badge">✓ ACCEPTED</span>` : "";
  const link = j.url.startsWith("http") ? ` · <a href="${esc(j.url)}" target="_blank">link</a>` : "";
  const cs = j.company_size === "large" ? ` <span class="cs cs-lg">Large co.</span>`
    : j.company_size === "small" ? ` <span class="cs cs-sm">Small co.</span>` : "";
  return `<article class="job" data-id="${j.job_id}">
    <div class="top"><div>
      <h3>${rank}. ${esc(j.title)}${badge}</h3>
      <div class="meta">${esc(j.company)}${cs} · ${esc(j.location)} · ${esc(j.salary)}${link}</div>
    </div><div class="score">${j.score.toFixed(2)}</div></div>
    <div class="explain"><b>Why this rank →</b> ${whyHtml(j.why)}</div>
    <div class="actions">
      <button class="accept" data-act="accept">✓ Accept</button>
      <button class="skip"   data-act="skip">↷ Skip</button>
      <button class="reject" data-act="reject">✕ Reject</button>
      <button class="gendoc" data-act="resume">Generate Resume</button>
      <button class="gendoc" data-act="cover">Generate Cover Letter</button>
    </div>
    <div class="docslot"></div>
  </article>`;
}
function setResults(data) {
  S.metrics = data.metrics; S.total = data.total; S.weights = data.weights || S.weights;
  S.jobMap = {}; data.jobs.forEach(j => S.jobMap[j.job_id] = j);
  $("countLine").innerHTML = `Showing top <b>${data.jobs.length}</b> of <b>${data.total.toLocaleString()}</b>`;
  $("metricLine").textContent = `Ranking quality — Precision@10 ${data.metrics.precision_at_k} · NDCG@10 ${data.metrics.ndcg_at_k}`;
  $("jobs").innerHTML = data.jobs.length
    ? data.jobs.map((j, i) => jobCard(j, i + 1)).join("")
    : `<div class="spin">No matches passed the filters. Try relaxing dealbreakers / salary / location.</div>`;
}
async function findMatches() {
  S.weights = null; S.learner = null; S.excluded = []; S.feedbackLog = [];
  $("jobs").innerHTML = `<div class="spin">Ranking matches…</div>`;
  setResults(await api("/api/match", { profile: buildProfile(), n: 10 }));
}
async function doFeedback(jobId, action) {
  const j = S.jobMap[jobId];
  const r = await api("/api/feedback", {
    profile: buildProfile(), learner: S.learner, excluded: S.excluded,
    job_id: jobId, action, breakdown: j.breakdown, n: 10,
  });
  S.learner = r.learner; S.excluded = r.excluded; S.weights = r.weights;
  S.feedbackLog.push({ job_id: jobId, title: j.title, action });
  setResults(r);
  if (!$("view-feedback").style.display || $("view-feedback").style.display !== "none") renderFeedback();
}
async function generate(jobId, kind, slot) {
  slot.innerHTML = `<div class="spin">Generating ${kind === "cover" ? "cover letter" : "résumé"} with Claude…</div>`;
  const r = await api("/api/generate", { profile: buildProfile(), job_id: jobId, kind });
  const base = kind === "cover" ? "CoverLetter" : "Resume";
  let ats = "";
  if (r.ats) ats = `<div class="atsline">ATS match <b>${r.ats.score}%</b> · covered: ${esc((r.ats.covered || []).slice(0, 8).join(", ")) || "—"}${r.ats.missing && r.ats.missing.length ? " · ➕ add: " + esc(r.ats.missing.slice(0, 6).join(", ")) : ""}</div>`;
  const tag = r.backend === "llm" ? ` · <span style="color:var(--good)">Claude-tailored</span>` : "";
  slot.innerHTML = `<div class="docbox">${ats}<pre>${esc(r.preview)}</pre>
    <div class="row"><span class="muted" style="font-size:11.5px">Download${tag}:</span>
      <button class="gendoc" data-dl="docx">⬇ Word (.docx)</button>
      <button class="gendoc" data-dl="pdf">⬇ PDF</button></div></div>`;
  slot.querySelector('[data-dl="docx"]').onclick = () => downloadB64(r.docx_b64, base + ".docx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
  slot.querySelector('[data-dl="pdf"]').onclick = () => downloadB64(r.pdf_b64, base + ".pdf", "application/pdf");
}
function downloadB64(b64, filename, mime) {
  const bin = atob(b64), arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  const url = URL.createObjectURL(new Blob([arr], { type: mime }));
  const a = document.createElement("a"); a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}
// job-card action delegation
$("jobs").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-act]"); if (!btn) return;
  const card = e.target.closest(".job"), jid = card.dataset.id, act = btn.dataset.act;
  if (act === "resume" || act === "cover") generate(jid, act, card.querySelector(".docslot"));
  else doFeedback(jid, act);
});

// ---------- export ----------
document.querySelectorAll(".download-bar [data-fmt]").forEach(b => b.onclick = async () => {
  if (!S.metrics) return;
  const r = await api("/api/export", { profile: buildProfile(), weights: S.weights, excluded: S.excluded, n: 10, fmt: b.dataset.fmt });
  const mimes = { csv: "text/csv", excel: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", json: "application/json" };
  downloadB64(r.b64, r.filename, mimes[b.dataset.fmt]);
});

// ---------- tabs ----------
let analyticsLoaded = false;
document.querySelectorAll("#nav a").forEach(a => a.onclick = () => {
  document.querySelectorAll("#nav a").forEach(x => x.classList.remove("active"));
  a.classList.add("active");
  ["matches", "analytics", "feedback", "about"].forEach(t =>
    $("view-" + t).style.display = t === a.dataset.tab ? "" : "none");
  if (a.dataset.tab === "analytics") loadAnalytics();
  if (a.dataset.tab === "feedback") renderFeedback();
  if (a.dataset.tab === "about") renderAbout();
});

// ---------- analytics (Plotly 2x2 grid, orange theme) ----------
const ORANGE = "#e8612c", ORANGE2 = "#f3b49a";
const PLOT_FONT = { family: "Inter,-apple-system,sans-serif", size: 11, color: "#1d1c1a" };
const PCONF = { displayModeBar: false, responsive: true };
const baseLayout = (extra) => Object.assign({
  margin: { l: 150, r: 14, t: 8, b: 40 }, font: PLOT_FONT,
  paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", showlegend: false,
}, extra || {});

async function loadAnalytics() {
  analyticsLoaded = true;
  const d = await (await fetch("/api/analytics")).json();
  const s = d.summary;
  const stat = (n, l) => `<div class="stat"><div class="n">${n}</div><div class="l">${l}</div></div>`;
  $("analytics").innerHTML = `<h2>Analytics · job-market insights (${(s.total_jobs || 0).toLocaleString()} postings · Kaggle + live Adzuna)</h2>
    <div>${stat((s.total_jobs || 0).toLocaleString(), "Total postings")}${stat((s.companies || 0).toLocaleString(), "Companies")}
      ${stat(s.median_salary ? "$" + Math.round(s.median_salary).toLocaleString() : "—", "Median salary")}${stat((s.pct_with_salary || 0) + "%", "with salary")}</div>
    <div class="chart-grid">
      <div class="chart-card"><h3>Top skills in demand</h3><div class="plot" id="cSkills"></div></div>
      <div class="chart-card"><h3>Salary distribution (where listed)</h3><div class="plot" id="cSalary"></div></div>
      <div class="chart-card"><h3>Demand by location</h3><div class="plot" id="cLoc"></div></div>
      <div class="chart-card"><h3>Data source mix</h3><div class="plot" id="cSource"></div></div>
    </div>`;

  const sk = d.top_skills.slice().reverse();   // reverse -> largest bar on top
  Plotly.newPlot("cSkills", [{ type: "bar", orientation: "h", x: sk.map(r => r.count),
    y: sk.map(r => r.skill), marker: { color: ORANGE } }],
    baseLayout({ xaxis: { title: "count" } }), PCONF);

  Plotly.newPlot("cSalary", [{ type: "histogram", x: d.salary, nbinsx: 30, marker: { color: ORANGE } }],
    baseLayout({ margin: { l: 48, r: 14, t: 8, b: 40 }, xaxis: { title: "salary" }, yaxis: { title: "count" } }), PCONF);

  const lo = d.locations.slice().reverse();
  Plotly.newPlot("cLoc", [{ type: "bar", orientation: "h", x: lo.map(r => r.count),
    y: lo.map(r => r.location), marker: { color: ORANGE } }],
    baseLayout({ xaxis: { title: "count" } }), PCONF);

  Plotly.newPlot("cSource", [{ type: "pie", labels: d.sources.map(r => r.source),
    values: d.sources.map(r => r.count), sort: false, textinfo: "label+percent",
    marker: { colors: [ORANGE, ORANGE2, "#d9cfc2"] } }],
    baseLayout({ margin: { l: 10, r: 10, t: 10, b: 10 }, showlegend: true,
      legend: { font: { size: 11 } } }), PCONF);
}

// ---------- feedback log ----------
function renderFeedback() {
  const fl = S.feedbackLog;
  const c = { accept: 0, skip: 0, reject: 0 }; fl.forEach(f => c[f.action]++);
  const stat = (n, l) => `<div class="stat"><div class="n">${n}</div><div class="l">${l}</div></div>`;
  let w = "";
  if (S.weights) w = `<h3 style="margin-top:16px">Learned scoring weights</h3>` +
    Object.entries(S.weights).map(([k, v]) =>
      `<div class="bar-row"><div class="lbl">${k}</div><div class="bar" style="width:${Math.round(220 * v)}px"></div><div class="val">${Math.round(v * 100)}%</div></div>`).join("");
  $("feedback").innerHTML = `<h2>Feedback log &amp; adaptive learning</h2>
    ${stat(c.accept, "✓ Accepted")}${stat(c.skip, "↷ Skipped")}${stat(c.reject, "✕ Rejected")}${stat(S.excluded.length, "Removed")}
    ${w}
    <p class="muted" style="margin-top:14px;font-size:12.5px">✓ Accept = +1 reward (keeps the job) · ↷ Skip = −0.2 (removes it) · ✕ Reject = −1 (removes + teaches). Rewards update the scoring weights (incl. <b>company size</b>, so rejecting tiny startups deprioritises them) via an ε-greedy online learner; the list re-ranks instantly.</p>
    <h3 style="margin-top:18px">Learning benchmark — visible improvement (L8)</h3>
    <button class="ghost" id="lcBtn">▶ Run learning benchmark</button>
    <div class="muted" id="lcNote" style="font-size:12px;margin-top:6px">Simulates a user with hidden preferences over 6 rounds: the adaptive learner's acceptance rate climbs vs a no-learning random baseline.</div>
    <div id="lcPlot" style="height:300px;margin-top:8px"></div>`;
  $("lcBtn").onclick = async () => {
    $("lcBtn").disabled = true; $("lcNote").textContent = "Running 6-round simulation (adaptive learner vs random)…";
    try {
      const r = await api("/api/learning-curve", { profile: buildProfile() });
      $("lcNote").innerHTML = `Acceptance of surfaced jobs rose from <b>${Math.round(r.adaptive[0] * 100)}%</b> to <b>${Math.round(r.adaptive[r.adaptive.length - 1] * 100)}%</b> over ${r.rounds.length} rounds (<b>+${Math.round(r.lift * 100)} pts</b>) — the random baseline stays flat.`;
      Plotly.newPlot("lcPlot", [
        { x: r.rounds, y: r.adaptive.map(v => v * 100), name: "Adaptive (learns)", mode: "lines+markers", line: { color: ORANGE, width: 3 } },
        { x: r.rounds, y: r.static.map(v => v * 100), name: "Random baseline", mode: "lines+markers", line: { color: "#b9b2a6", width: 2, dash: "dot" } },
      ], { margin: { l: 46, r: 14, t: 8, b: 52 }, font: PLOT_FONT, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)", legend: { orientation: "h", y: -0.25 }, xaxis: { title: "round", dtick: 1 }, yaxis: { title: "acceptance %" } }, PCONF);
    } catch (e) { $("lcNote").textContent = "Benchmark failed — see console."; }
    $("lcBtn").disabled = false;
  };
}

// ---------- about ----------
function renderAbout() {
  $("about").innerHTML = `<h2>About · pipeline &amp; BAX-423 techniques</h2>
    <ul style="line-height:1.9;font-size:13px">
      <li><b>Ingestion + streaming (L3)</b> via Google <b>Pub/Sub</b> + <b>Bloom-filter dedup (L2)</b> — 50k Kaggle + live Adzuna.</li>
      <li><b>Random byte-offset sampling (L2)</b> — 50k drawn from a 47 GB dump without loading it.</li>
      <li><b>Embeddings &amp; vector retrieval (L5)</b> — 384-dim MiniLM + cosine k-NN.</li>
      <li><b>Multi-stage ranking (L7)</b> — candidate gen → hard filters → scoring → re-rank.</li>
      <li><b>RL rewards + ε-greedy (L8)</b> — feedback adapts the ranking weights.</li>
      <li><b>Count-Min Sketch (L2)</b> — approximate skill counts benchmarked vs exact.</li>
    </ul>
    <button id="psbtn">▶ Run live Pub/Sub streaming demo</button>
    <div id="psout" style="margin-top:12px"></div>`;
  $("psbtn").onclick = async () => {
    $("psout").innerHTML = `<div class="spin">Streaming through Pub/Sub…</div>`;
    const r = await api("/api/pubsub-demo", { n: 2000 });
    const stat = (n, l) => `<div class="stat"><div class="n">${n}</div><div class="l">${l}</div></div>`;
    $("psout").innerHTML = `${stat(r.produced.toLocaleString(), "Published → topic")}${stat(r.consumed.toLocaleString(), "Consumed")}
      ${stat(r.duplicates.toLocaleString(), "Duplicates removed")}${stat(r.false_positives, "Bloom false pos.")}
      <div class="muted" style="font-size:12px;margin-top:6px">backend: <b>${esc(r.backend)}</b> · ${r.rate.toLocaleString()} rec/s · ${r.bloom_kb} KB filter</div>`;
  };
}

// ---------- pdf upload ----------
$("upload").onclick = () => $("pdf").click();
$("pdf").onchange = async (e) => {
  const f = e.target.files[0]; if (!f) return;
  $("pdfStatus").textContent = "Reading…";
  const fd = new FormData(); fd.append("file", f);
  const r = await (await fetch("/api/upload-resume", { method: "POST", body: fd })).json();
  S.fields.resume_text = r.resume_text || "";
  (r.skills || []).forEach(s => { if (!S.fields.skills.includes(s)) S.fields.skills.push(s); });
  renderAllChips();
  $("pdfStatus").textContent = `✓ ${f.name} — ${(r.skills || []).length} skills detected`;
};

// ---------- init ----------
$("persona").onchange = () => {
  const name = $("persona").value;
  if (!name) { S.fields.base = null; return; }
  const p = S.options.personas[name];
  S.fields.base = p;
  S.fields.roles = [...p.roles]; S.fields.skills = [...p.skills];
  S.fields.locations = [...p.locations]; S.fields.dealbreakers = [...p.dealbreakers];
  S.fields.resume_text = p.resume_text;
  $("salary").value = p.min_salary;
  renderAllChips();
};
// ---------- live Adzuna refresh ----------
$("adzBtn").onclick = async () => {
  const btn = $("adzBtn"), st = $("adzStatus"), label = btn.textContent;
  btn.disabled = true; btn.textContent = "↻ Fetching…";
  st.textContent = "Fetching live postings from Adzuna…";
  try {
    const r = await api("/api/fetch-adzuna", { pages: 2 });
    if (r.available === false) st.textContent = "Adzuna API key not configured on the server.";
    else st.innerHTML = `✓ Added <b>${(r.added || 0).toLocaleString()}</b> live jobs` +
      (r.duplicates ? ` (${r.duplicates} dups skipped)` : "") + `. Corpus: <b>${(r.corpus_size || 0).toLocaleString()}</b>.`;
    if (r.corpus_size) {
      S.options.corpus_size = r.corpus_size;
      $("corpusInfo").innerHTML = `Corpus: ${r.corpus_size.toLocaleString()} job postings` +
        (r.added ? ` <span class="count-pill">+${r.added} live</span>` : "");
      $("footCorpus").textContent = `${r.corpus_size.toLocaleString()} active postings`;
    }
  } catch (e) { st.textContent = "Refresh failed — see console."; }
  btn.disabled = false; btn.textContent = label;
};

$("find").onclick = findMatches;
$("reset").onclick = () => {
  S.fields = { roles: [], skills: [], locations: [], dealbreakers: [], resume_text: "", base: null };
  $("persona").value = ""; $("salary").value = 90000; $("jobs").innerHTML = "";
  $("countLine").innerHTML = "Pick a persona or fill your profile, then <b>Find matches</b>.";
  $("metricLine").textContent = ""; S.feedbackLog = []; renderAllChips();
};

(async function init() {
  S.options = await (await fetch("/api/options")).json();
  Object.keys(S.options.personas).forEach(n => {
    const o = document.createElement("option"); o.value = n; o.textContent = n; $("persona").appendChild(o);
  });
  $("corpusInfo").textContent = `Corpus: ${S.options.corpus_size.toLocaleString()} job postings`;
  $("footCorpus").textContent = `${S.options.corpus_size.toLocaleString()} active postings`;
  renderAllChips();
  // Deep-link: ?tab=analytics opens that tab on load (handy for sharing / demo).
  const wantTab = new URLSearchParams(location.search).get("tab");
  if (wantTab) { const lnk = document.querySelector(`#nav a[data-tab="${wantTab}"]`); if (lnk) lnk.click(); }
})();
