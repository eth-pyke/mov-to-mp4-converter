"use strict";

const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("fileInput");
const fileList = document.getElementById("fileList");
const outdir = document.getElementById("outdir");
const convertBtn = document.getElementById("convertBtn");
const rowTemplate = document.getElementById("rowTemplate");

// Each queue entry: { file, li, nameEl, statusEl, fillEl, detailEl, done }
const queue = [];

const SUPPORTED_EXTS = [".mov", ".heic", ".heif"];

function isSupported(file) {
  const name = file.name.toLowerCase();
  return SUPPORTED_EXTS.some((ext) => name.endsWith(ext));
}

function addFiles(files) {
  let added = 0;
  for (const file of files) {
    if (!isSupported(file)) continue;
    // Skip obvious duplicates by name+size.
    if (queue.some((q) => q.file.name === file.name && q.file.size === file.size)) continue;

    const li = rowTemplate.content.firstElementChild.cloneNode(true);
    const entry = {
      file,
      li,
      nameEl: li.querySelector(".row-name"),
      statusEl: li.querySelector(".row-status"),
      fillEl: li.querySelector(".bar-fill"),
      detailEl: li.querySelector(".row-detail"),
      done: false,
    };
    entry.nameEl.textContent = file.name;
    entry.detailEl.textContent = humanSize(file.size);
    fileList.appendChild(li);
    queue.push(entry);
    added++;
  }
  if (added) convertBtn.disabled = false;
}

function humanSize(bytes) {
  const mb = bytes / (1024 * 1024);
  return mb >= 1024 ? (mb / 1024).toFixed(2) + " GB" : mb.toFixed(1) + " MB";
}

function setStatus(entry, text, cls) {
  entry.statusEl.textContent = text;
  entry.statusEl.className = "row-status" + (cls ? " " + cls : "");
  entry.li.className = "file-row" + (cls ? " " + cls : "");
}

async function convertOne(entry) {
  const dir = encodeURIComponent(outdir.value.trim() || "~/Downloads");
  const name = encodeURIComponent(entry.file.name);
  setStatus(entry, "uploading…");
  entry.fillEl.style.width = "3%";

  let job;
  try {
    const resp = await fetch(`/api/convert?name=${name}&outdir=${dir}`, {
      method: "POST",
      body: entry.file,
    });
    job = await resp.json();
  } catch (err) {
    setStatus(entry, "upload failed", "error");
    return;
  }

  if (job.error) {
    setStatus(entry, "error", "error");
    entry.detailEl.textContent = job.error;
    return;
  }

  if (job.source_desc) {
    entry.detailEl.textContent = `${job.source_desc} → ${job.action}`;
  }
  setStatus(entry, "converting…");

  // Poll for progress until done or error.
  await new Promise((resolve) => {
    const timer = setInterval(async () => {
      let s;
      try {
        s = await (await fetch(`/api/status?job=${job.id}`)).json();
      } catch (_) {
        return; // transient; try again next tick
      }
      entry.fillEl.style.width = Math.max(3, (s.progress || 0) * 100).toFixed(1) + "%";
      if (s.status === "done") {
        clearInterval(timer);
        entry.fillEl.style.width = "100%";
        entry.done = true;
        setStatus(entry, "done", "done");
        const savedTo = s.output_path || "";
        entry.detailEl.innerHTML = "";
        const where = document.createElement("span");
        where.textContent = "Saved to " + savedTo;
        const dl = document.createElement("a");
        dl.href = `/api/download?job=${job.id}`;
        dl.textContent = "Download";
        entry.detailEl.append(where, dl);
        resolve();
      } else if (s.status === "error") {
        clearInterval(timer);
        setStatus(entry, "error", "error");
        entry.detailEl.textContent = s.error || "conversion failed";
        resolve();
      }
    }, 400);
  });
}

async function convertAll() {
  convertBtn.disabled = true;
  const original = convertBtn.textContent;
  convertBtn.textContent = "Converting…";
  for (const entry of queue) {
    if (!entry.done) await convertOne(entry);
  }
  convertBtn.textContent = original;
  convertBtn.disabled = queue.every((q) => q.done);
}

// --- wiring ---------------------------------------------------------------
dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") fileInput.click();
});
fileInput.addEventListener("change", () => {
  addFiles(fileInput.files);
  fileInput.value = "";
});

["dragenter", "dragover"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => {
    e.preventDefault();
    dropzone.classList.add("drag");
  })
);
["dragleave", "drop"].forEach((ev) =>
  dropzone.addEventListener(ev, (e) => {
    e.preventDefault();
    dropzone.classList.remove("drag");
  })
);
dropzone.addEventListener("drop", (e) => {
  if (e.dataTransfer && e.dataTransfer.files) addFiles(e.dataTransfer.files);
});

// Prevent the browser from opening a file if dropped outside the zone.
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());

convertBtn.addEventListener("click", convertAll);
