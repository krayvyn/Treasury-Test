/* TTB Label Check — client script.
   Handles single/batch mode, drag-and-drop, submission, and result rendering. */

(function () {
  const form = document.getElementById("reviewForm");
  const fileInput = document.getElementById("image");
  const dropZone = document.getElementById("dropZone");
  const dropLabel = document.getElementById("dropLabel");
  const dropHint = document.getElementById("dropHint");
  const thumbs = document.getElementById("thumbs");
  const submitBtn = document.getElementById("submitBtn");
  const resetBtn = document.getElementById("resetBtn");
  const resultEmpty = document.getElementById("resultEmpty");
  const resultBody = document.getElementById("resultBody");
  const tabs = document.querySelectorAll(".tab");

  let mode = "single";

  // --- mode toggle ---
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => {
        t.classList.remove("active");
        t.setAttribute("aria-selected", "false");
      });
      tab.classList.add("active");
      tab.setAttribute("aria-selected", "true");
      mode = tab.dataset.mode;
      applyMode();
    });
  });

  function applyMode() {
    if (mode === "batch") {
      fileInput.setAttribute("multiple", "multiple");
      fileInput.setAttribute("name", "images");
      dropLabel.textContent = "Label images (up to 25)";
      dropHint.textContent = "Drag & drop many, or click to select. Each label is checked against the same application below.";
      submitBtn.textContent = "Run batch review";
    } else {
      fileInput.removeAttribute("multiple");
      fileInput.setAttribute("name", "image");
      dropLabel.textContent = "Label image";
      dropHint.textContent = "Drag & drop, or click to select. JPG / PNG / WebP, up to 8 MB.";
      submitBtn.textContent = "Run review";
    }
    thumbs.innerHTML = "";
    fileInput.value = "";
  }

  // --- drag & drop ---
  ["dragenter", "dragover"].forEach((ev) =>
    dropZone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropZone.classList.add("drag");
    })
  );
  ["dragleave", "drop"].forEach((ev) =>
    dropZone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropZone.classList.remove("drag");
    })
  );
  dropZone.addEventListener("drop", (e) => {
    const dt = e.dataTransfer;
    if (!dt || !dt.files.length) return;
    fileInput.files = dt.files;
    renderThumbs();
  });
  fileInput.addEventListener("change", renderThumbs);

  function renderThumbs() {
    thumbs.innerHTML = "";
    const files = Array.from(fileInput.files || []);
    files.slice(0, 25).forEach((f) => {
      const img = document.createElement("img");
      img.alt = f.name;
      img.title = f.name;
      const reader = new FileReader();
      reader.onload = (e) => (img.src = e.target.result);
      reader.readAsDataURL(f);
      thumbs.appendChild(img);
    });
    if (files.length > 25) {
      const more = document.createElement("div");
      more.textContent = `+${files.length - 25} more`;
      more.style.fontFamily = "var(--mono)";
      more.style.fontSize = "12px";
      more.style.color = "var(--fail)";
      thumbs.appendChild(more);
    }
  }

  // --- submit ---
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!fileInput.files.length) return;

    submitBtn.disabled = true;
    submitBtn.textContent = "Reviewing…";
    resultEmpty.hidden = true;
    resultBody.hidden = false;
    resultBody.innerHTML = `
      <div class="loading">
        <div class="spinner"></div>
        <span>Extracting fields and comparing to application…</span>
      </div>`;
    resultBody.scrollIntoView({ behavior: "smooth", block: "start" });

    const fd = new FormData(form);
    // FormData picks up whatever the current input name is (image or images).
    const endpoint = mode === "batch" ? "/api/batch" : "/api/review";

    try {
      const resp = await fetch(endpoint, { method: "POST", body: fd });
      const data = await resp.json();
      if (!resp.ok) {
        throw new Error(data.detail || `Request failed (${resp.status})`);
      }
      if (mode === "batch") {
        renderBatch(data.results || []);
      } else {
        renderSingle(data);
      }
    } catch (err) {
      resultBody.innerHTML = `
        <div class="verdict-card error">
          <span class="verdict-stamp">Error</span>
          <div>
            <h3 class="verdict-headline">Review could not be completed</h3>
            <div class="verdict-meta">${escapeHtml(err.message)}</div>
          </div>
        </div>`;
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = mode === "batch" ? "Run batch review" : "Run review";
    }
  });

  resetBtn.addEventListener("click", () => {
    thumbs.innerHTML = "";
    resultBody.innerHTML = "";
    resultBody.hidden = true;
    resultEmpty.hidden = false;
  });

  // --- rendering ---
  const verdictHeadlines = {
    pass: "Cleared for approval",
    review: "Needs agent review",
    fail: "Rejected — see findings",
  };

  function renderSingle(result) {
    const verdict = result.verdict;
    let html = `
      <div class="verdict-card ${verdict}">
        <span class="verdict-stamp">${verdict}</span>
        <div>
          <h3 class="verdict-headline">${verdictHeadlines[verdict] || verdict}</h3>
          <div class="verdict-meta">${result.filename || "label"} · ${result.elapsed_ms || 0} ms</div>
        </div>
      </div>`;

    const q = result.extraction && result.extraction.image_quality_notes;
    if (q) {
      html += `<div class="quality-note"><strong>Image quality note:</strong> ${escapeHtml(q)}</div>`;
    }

    html += `<div class="checks">`;
    (result.checks || []).forEach((c) => {
      html += renderCheck(c);
    });
    html += `</div>`;

    resultBody.innerHTML = html;
  }

  function renderCheck(c) {
    const label = c.field.replace(/_/g, " ");
    const showValues = c.expected != null || c.found != null;
    return `
      <div class="check-row">
        <div class="check-icon ${c.status}" aria-label="${c.status}"></div>
        <div>
          <div class="check-field">${escapeHtml(label)}</div>
          <div class="check-detail">${escapeHtml(c.detail)}</div>
          ${showValues ? `
            <dl class="check-values">
              <dt>Application</dt><dd>${escapeHtml(c.expected || "—")}</dd>
              <dt>Label</dt><dd>${escapeHtml(c.found || "—")}</dd>
            </dl>` : ""}
        </div>
      </div>`;
  }

  function renderBatch(results) {
    const counts = { pass: 0, review: 0, fail: 0, error: 0 };
    results.forEach((r) => {
      counts[r.verdict] = (counts[r.verdict] || 0) + 1;
    });

    let html = `
      <div class="batch-summary">
        <span><strong style="color:var(--pass)">${counts.pass || 0}</strong>Passed</span>
        <span><strong style="color:var(--review)">${counts.review || 0}</strong>Needs review</span>
        <span><strong style="color:var(--fail)">${counts.fail || 0}</strong>Failed</span>
        ${counts.error ? `<span><strong style="color:var(--rule-strong)">${counts.error}</strong>Errors</span>` : ""}
      </div>
      <table class="batch-table">
        <thead>
          <tr>
            <th>Verdict</th>
            <th>File</th>
            <th>Notes</th>
            <th style="text-align:right">Time</th>
          </tr>
        </thead>
        <tbody>`;
    results.forEach((r) => {
      const notes = (r.checks || [])
        .filter((c) => c.status !== "match" && c.status !== "not_applicable")
        .map((c) => `${c.field.replace(/_/g, " ")}: ${c.status}`)
        .join("; ") || (r.error ? r.error : "All checks passed");
      html += `
        <tr>
          <td><span class="pill ${r.verdict}">${r.verdict}</span></td>
          <td class="file">${escapeHtml(r.filename || "—")}</td>
          <td>${escapeHtml(notes)}</td>
          <td style="text-align:right; font-family: var(--mono); font-size: 12px;">${r.elapsed_ms ? r.elapsed_ms + " ms" : "—"}</td>
        </tr>`;
    });
    html += `</tbody></table>`;
    resultBody.innerHTML = html;
  }

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }
})();
