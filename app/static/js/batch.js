// Batch review UI.
// Upload many, poll results, populate a filterable table.

(() => {
  const form = document.getElementById("batch-form");
  const drop = document.getElementById("drop");
  const filesInput = document.getElementById("files");
  const fileList = document.getElementById("file-list");
  const submit = document.getElementById("batch-submit");
  const progressWrap = document.getElementById("batch-progress");
  const progressBar = document.getElementById("progress-bar");
  const progressText = document.getElementById("progress-text");
  const resultsWrap = document.getElementById("batch-results");
  const tbody = document.getElementById("batch-body");

  let files = [];

  function refreshList() {
    if (!files.length) {
      fileList.hidden = true;
      fileList.innerHTML = "";
      submit.disabled = true;
      return;
    }
    submit.disabled = false;
    fileList.hidden = false;
    fileList.innerHTML = "";
    const ul = document.createElement("ul");
    ul.style.cssText = "list-style: none; padding: 0; margin: 0; display: contents;";
    for (const f of files) {
      const li = document.createElement("li");
      li.textContent = f.name;
      li.title = f.name;
      fileList.appendChild(li);
    }
  }

  drop.addEventListener("click", () => filesInput.click());
  drop.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); filesInput.click(); }
  });
  filesInput.addEventListener("change", (e) => {
    files = Array.from(e.target.files || []).slice(0, 50);
    refreshList();
  });
  ["dragenter", "dragover"].forEach((evt) =>
    drop.addEventListener(evt, (e) => { e.preventDefault(); drop.classList.add("is-dragging"); })
  );
  ["dragleave", "drop"].forEach((evt) =>
    drop.addEventListener(evt, (e) => { e.preventDefault(); drop.classList.remove("is-dragging"); })
  );
  drop.addEventListener("drop", (e) => {
    files = Array.from(e.dataTransfer?.files || []).slice(0, 50);
    refreshList();
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!files.length) return;
    await runBatch();
  });

  async function runBatch() {
    progressWrap.hidden = false;
    resultsWrap.hidden = true;
    setProgress(5, `Uploading ${files.length} label${files.length === 1 ? "" : "s"}…`);

    const fd = new FormData();
    for (const f of files) fd.append("labels", f);

    // The server processes files in parallel with a bounded concurrency, so we
    // can't stream true progress without SSE — approximate with a slow crawl
    // that finishes on response.
    const crawler = crawl(files.length);

    let payload;
    try {
      const res = await fetch("/api/batch", { method: "POST", body: fd });
      if (!res.ok) throw new Error(await res.text());
      payload = await res.json();
    } catch (err) {
      progressText.textContent = `Failed: ${err.message || err}`;
      clearInterval(crawler);
      return;
    }
    clearInterval(crawler);
    setProgress(100, "Done.");
    renderResults(payload);
  }

  function setProgress(pct, text) {
    progressBar.style.width = `${pct}%`;
    progressText.textContent = text;
  }

  function crawl(count) {
    const perLabelMs = 3500;
    const total = Math.max(perLabelMs, (count / 4) * perLabelMs); // matches server concurrency
    const start = performance.now();
    return setInterval(() => {
      const elapsed = performance.now() - start;
      const pct = Math.min(90, 5 + (elapsed / total) * 85);
      setProgress(pct, `Reviewing ${count} label${count === 1 ? "" : "s"}…`);
    }, 200);
  }

  // --- Results ---

  const counts = { all: 0, pass: 0, review: 0, fail: 0 };

  function renderResults(payload) {
    tbody.innerHTML = "";
    for (const key of Object.keys(counts)) counts[key] = 0;

    for (const item of payload) {
      if (item.error) {
        const row = document.createElement("tr");
        row.dataset.verdict = "fail";
        row.innerHTML = `
          <td><span class="verdict-tag fail">Error</span></td>
          <td class="filename">${escapeHtml(item.filename || "unknown")}</td>
          <td>—</td>
          <td class="summary">${escapeHtml(item.error)}</td>
          <td class="right">—</td>
        `;
        tbody.appendChild(row);
        counts.fail++;
        counts.all++;
        continue;
      }
      const brand = item.extracted?.brand_name || item.application?.brand_name || "—";
      const row = document.createElement("tr");
      row.dataset.verdict = item.overall;
      row.innerHTML = `
        <td><span class="verdict-tag ${item.overall}">${verdictWord(item.overall)}</span></td>
        <td class="filename">${escapeHtml(item.filename || "—")}</td>
        <td class="brand">${escapeHtml(brand)}</td>
        <td class="summary">${escapeHtml(item.summary)}</td>
        <td class="right">${(item.processing_ms / 1000).toFixed(1)}s</td>
      `;
      tbody.appendChild(row);
      counts[item.overall] = (counts[item.overall] || 0) + 1;
      counts.all++;
    }

    for (const key of Object.keys(counts)) {
      const el = document.querySelector(`[data-count="${key}"]`);
      if (el) el.textContent = counts[key];
    }

    resultsWrap.hidden = false;
    resultsWrap.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  document.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      document.querySelectorAll(".chip").forEach((c) => c.classList.remove("is-on"));
      chip.classList.add("is-on");
      const filter = chip.dataset.filter;
      tbody.querySelectorAll("tr").forEach((row) => {
        row.hidden = filter !== "all" && row.dataset.verdict !== filter;
      });
    });
  });

  function verdictWord(v) {
    return v === "pass" ? "Pass" : v === "review" ? "Review" : "Fail";
  }
  function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }
})();
