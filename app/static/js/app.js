// Single-label review UI.
// Responsibilities: file intake (drop/pick), form serialization, calling the
// API, rendering the LabelReview into the result template.

(() => {
  const form = document.getElementById("review-form");
  const drop = document.getElementById("drop");
  const fileInput = document.getElementById("file");
  const preview = document.getElementById("preview");
  const previewImg = document.getElementById("preview-img");
  const previewClear = document.getElementById("preview-clear");
  const submit = document.getElementById("submit");
  const resultSlot = document.getElementById("result-slot");

  let selectedFile = null;
  let selectedPreviewUrl = null;

  // --- File intake ---

  function setFile(file) {
    if (selectedPreviewUrl) URL.revokeObjectURL(selectedPreviewUrl);
    selectedFile = file || null;
    if (!file) {
      preview.hidden = true;
      submit.disabled = true;
      previewImg.src = "";
      return;
    }
    selectedPreviewUrl = URL.createObjectURL(file);
    previewImg.src = selectedPreviewUrl;
    preview.hidden = false;
    submit.disabled = false;
  }

  drop.addEventListener("click", () => fileInput.click());
  drop.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); }
  });
  fileInput.addEventListener("change", (e) => {
    const file = e.target.files?.[0];
    if (file) setFile(file);
  });
  previewClear.addEventListener("click", (e) => {
    e.stopPropagation();
    fileInput.value = "";
    setFile(null);
  });

  ["dragenter", "dragover"].forEach((evt) =>
    drop.addEventListener(evt, (e) => { e.preventDefault(); drop.classList.add("is-dragging"); })
  );
  ["dragleave", "drop"].forEach((evt) =>
    drop.addEventListener(evt, (e) => { e.preventDefault(); drop.classList.remove("is-dragging"); })
  );
  drop.addEventListener("drop", (e) => {
    const file = e.dataTransfer?.files?.[0];
    if (file) setFile(file);
  });

  // --- Application form → JSON ---

  function serializeApplication() {
    const fd = new FormData(form);
    const record = {};
    for (const [key, value] of fd.entries()) {
      if (key === "label") continue;
      const v = value.toString().trim();
      if (!v) continue;
      record[key] = key === "alcohol_pct" ? Number(v) : v;
    }
    return record;
  }

  // --- Submit ---

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!selectedFile) return;
    await runReview(selectedFile, serializeApplication());
  });

  // --- Samples ---

  document.querySelectorAll(".sample").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.dataset.sampleId;
      await runSample(id, btn);
    });
  });

  async function runSample(sampleId, triggerEl) {
    showLoading("Running sample");
    try {
      const res = await fetch(`/api/sample/${encodeURIComponent(sampleId)}`, { method: "POST" });
      if (!res.ok) throw new Error(await res.text());
      const review = await res.json();
      renderResult(review, `/static/samples/${sampleImageFor(sampleId)}`);
    } catch (err) {
      showError(err);
    }
  }

  function sampleImageFor(sampleId) {
    const map = {
      "bourbon-clean": "bourbon-clean.png",
      "stones-throw": "stones-throw.png",
      "wine-warning-issue": "riverbend-cellars.png",
      "abv-mismatch": "northgate-rye.png",
    };
    return map[sampleId] || "";
  }

  // --- Analyze the uploaded file ---

  async function runReview(file, application) {
    showLoading("Preprocessing image");
    updateLoadingSub("Sending to reviewer");
    const fd = new FormData();
    fd.append("label", file);
    if (Object.keys(application).length) {
      fd.append("application", JSON.stringify(application));
    }
    try {
      const res = await fetch("/api/analyze", { method: "POST", body: fd });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `Server returned ${res.status}`);
      }
      const review = await res.json();
      renderResult(review, selectedPreviewUrl);
    } catch (err) {
      showError(err);
    }
  }

  // --- Rendering ---

  function showLoading(subtext) {
    const tpl = document.getElementById("loading-tpl");
    resultSlot.innerHTML = "";
    resultSlot.appendChild(tpl.content.cloneNode(true));
    resultSlot.hidden = false;
    updateLoadingSub(subtext);
    resultSlot.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function updateLoadingSub(text) {
    const sub = document.getElementById("loading-sub");
    if (sub && text) sub.textContent = text;
  }

  function showError(err) {
    resultSlot.innerHTML = `
      <div class="result" data-verdict="fail">
        <header class="result__head">
          <div>
            <div class="result__eyebrow">Something went wrong</div>
            <h2 class="result__summary">${escapeHtml(err.message || String(err))}</h2>
          </div>
        </header>
      </div>`;
    resultSlot.hidden = false;
  }

  function renderResult(review, previewUrl) {
    const tpl = document.getElementById("result-tpl");
    const node = tpl.content.cloneNode(true);
    const root = node.querySelector(".result");
    root.dataset.verdict = review.overall;

    node.querySelector(".result__summary").textContent = review.summary;

    const timing = node.querySelector(".pill--timing");
    timing.textContent = `${(review.processing_ms / 1000).toFixed(1)} s`;
    if (review.processing_ms > 5000) {
      timing.style.color = "var(--review)";
    }

    const fname = node.querySelector(".pill--filename");
    if (review.filename) {
      fname.textContent = review.filename;
    } else {
      fname.hidden = true;
    }

    const img = node.querySelector(".result__label-img");
    if (previewUrl) img.src = previewUrl;
    else img.hidden = true;

    const stampText = node.querySelector(".stamp__text");
    stampText.textContent = stampLabel(review.overall);

    const tbody = node.querySelector(".checks tbody");
    for (const check of review.checks) {
      const row = document.createElement("tr");
      row.className = "check-row";
      row.innerHTML = `
        <td class="field-cell">${escapeHtml(check.field)}</td>
        <td class="value-cell ${check.label_value ? "" : "is-missing"}">${
          escapeHtml(check.label_value || "—")
        }</td>
        <td class="value-cell ${check.application_value ? "" : "is-missing"}">${
          escapeHtml(check.application_value || "—")
        }</td>
        <td><span class="verdict-tag ${check.verdict}">${verdictWord(check.verdict)}</span></td>
      `;
      tbody.appendChild(row);

      const reason = document.createElement("tr");
      reason.className = `reason-row ${check.verdict}`;
      reason.innerHTML = `<td colspan="4">${escapeHtml(check.reason)}${
        check.similarity != null
          ? ` <span style="color: var(--ink-soft); font-family: var(--mono); font-size: 12px;">(similarity ${(check.similarity * 100).toFixed(0)}%)</span>`
          : ""
      }</td>`;
      tbody.appendChild(reason);
    }

    resultSlot.innerHTML = "";
    resultSlot.appendChild(node);
    resultSlot.hidden = false;
    resultSlot.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function stampLabel(verdict) {
    if (verdict === "pass") return "Approved";
    if (verdict === "review") return "Needs review";
    return "Rejected";
  }
  function verdictWord(verdict) {
    if (verdict === "pass") return "Pass";
    if (verdict === "review") return "Review";
    return "Fail";
  }
  function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }
})();
