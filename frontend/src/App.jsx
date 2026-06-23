import { useEffect, useRef, useState } from "react";
import * as XLSX from "xlsx";
import {
  applyOverrides,
  buildReportHtml,
  downloadReport,
  downloadAllReports,
  diffSegments,
} from "./report.js";

function DiffCell({ segments, fallback }) {
  if (!segments) return <>{fallback}</>;
  return (
    <>
      {segments.map((seg, i) =>
        seg.diff ? (
          <span key={i} className="diff">
            {seg.text}
          </span>
        ) : (
          <span key={i}>{seg.text}</span>
        )
      )}
    </>
  );
}

function fileToDataUrl(file) {
  return new Promise((resolve) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = () => resolve(null);
    r.readAsDataURL(file);
  });
}

const API = "/api";

const IMG_RE = /\.(jpe?g|png|bmp|tiff?)$/i;

// Relative path used for grouping: the browser sets webkitRelativePath for
// folder picks; dropped folders get it stamped on by the traversal below.
function relPathOf(f) {
  return f.webkitRelativePath || f._relPath || f.name;
}

// Group selected files by the folder that directly contains them. Files with no
// folder path (loose files / flat selection) fall into one "Selected files"
// group; everything else groups by its containing folder.
function groupByFolder(files) {
  const groups = new Map();
  for (const f of files) {
    const rel = relPathOf(f);
    const parts = rel.split("/");
    const dir = parts.length > 1 ? parts.slice(0, -1).join("/") : "";
    const key = dir || "(files)";
    const label = dir ? parts[parts.length - 2] : "Selected files";
    if (!groups.has(key)) groups.set(key, { key, label, files: [] });
    groups.get(key).files.push(f);
  }
  const arr = [...groups.values()];
  const byName = (a, b) =>
    a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
  arr.forEach((g) => g.files.sort((a, b) => byName(a.name, b.name)));
  arr.sort((a, b) => byName(a.label, b.label));
  return arr;
}

function stampRelPath(file, path) {
  try {
    Object.defineProperty(file, "webkitRelativePath", {
      value: path,
      configurable: true,
    });
  } catch {
    file._relPath = path; // fallback if the property can't be overridden
  }
  return file;
}

function readEntries(reader) {
  return new Promise((resolve, reject) => reader.readEntries(resolve, reject));
}

// Recursively collect image File objects from a dropped FileSystemEntry, tagging
// each with its relative path (so multiple dropped folders stay separable).
async function traverseEntry(entry, prefix, out) {
  if (!entry) return;
  if (entry.isFile) {
    const file = await new Promise((res, rej) => entry.file(res, rej));
    if (IMG_RE.test(file.name)) out.push(stampRelPath(file, prefix + file.name));
  } else if (entry.isDirectory) {
    const reader = entry.createReader();
    let batch;
    do {
      batch = await readEntries(reader);
      for (const child of batch) {
        await traverseEntry(child, prefix + entry.name + "/", out);
      }
    } while (batch.length);
  }
}

// A unified upload area: drag & drop one or more folders (or images), or click
// to browse files / a single folder. Grouping is detected automatically.
function DropZone({ files, onFiles, idPrefix }) {
  const [drag, setDrag] = useState(false);

  async function handleDrop(e) {
    e.preventDefault();
    setDrag(false);
    const items = e.dataTransfer?.items ? Array.from(e.dataTransfer.items) : [];
    const entries = items
      .map((it) => (it.webkitGetAsEntry ? it.webkitGetAsEntry() : null))
      .filter(Boolean);
    let collected = [];
    if (entries.length) {
      for (const entry of entries) await traverseEntry(entry, "", collected);
    } else {
      collected = Array.from(e.dataTransfer.files || []).filter((f) =>
        IMG_RE.test(f.name)
      );
    }
    if (collected.length) onFiles(collected);
  }

  function pickFiles(e) {
    onFiles(Array.from(e.target.files || []).filter((f) => IMG_RE.test(f.name)));
  }

  const groups = files.length ? groupByFolder(files) : [];
  const folderCount = groups.filter((g) => g.key !== "(files)").length;
  const looseCount = groups
    .filter((g) => g.key === "(files)")
    .reduce((a, g) => a + g.files.length, 0);
  let summary = "";
  if (files.length) {
    if (folderCount === 0) summary = `${files.length} image(s) — no folders`;
    else {
      summary = `${files.length} image(s) across ${folderCount} folder(s)`;
      if (looseCount) summary += ` (+ ${looseCount} loose)`;
    }
  }

  return (
    <div
      className={`dropzone ${drag ? "drag" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={handleDrop}
    >
      <div className="dropzone-icon">📁</div>
      <p className="dropzone-text">Drag &amp; drop folders or images here</p>
      <p className="dropzone-sub">
        Multiple folders supported — each folder is processed and downloaded
        separately.
      </p>
      <div className="dropzone-actions">
        <label className="dropzone-browse" htmlFor={`${idPrefix}-files`}>
          Browse files
        </label>
        <label className="dropzone-browse" htmlFor={`${idPrefix}-folder`}>
          Browse a folder
        </label>
      </div>
      <input
        id={`${idPrefix}-files`}
        type="file"
        accept="image/*"
        multiple
        hidden
        onChange={pickFiles}
      />
      <input
        id={`${idPrefix}-folder`}
        type="file"
        multiple
        hidden
        ref={(el) => {
          if (el) {
            el.setAttribute("webkitdirectory", "");
            el.setAttribute("directory", "");
          }
        }}
        onChange={pickFiles}
      />
      {summary && <p className="dropzone-summary">{summary}</p>}
    </div>
  );
}

const STATUS_META = {
  match: { label: "Match", cls: "st-match" },
  partial: { label: "Partial", cls: "st-partial" },
  mismatch: { label: "Mismatch", cls: "st-mismatch" },
  ocr_missed: { label: "OCR missed", cls: "st-missed" },
  not_on_form: { label: "Not on form", cls: "st-skipped" },
  calculated: { label: "Calculated", cls: "st-calc" },
  false_positive: { label: "False positive (scan error)", cls: "st-fp" },
};

function openImage(src, title) {
  const w = window.open("", "_blank");
  if (!w) return;
  w.document.write(
    `<title>${title || "form image"}</title>` +
      `<body style="margin:0;background:#111;display:flex;justify-content:center">` +
      `<img src="${src}" style="max-width:100%;height:auto"/></body>`
  );
  w.document.close();
}

function SearchableSelect({ records, value, onChange }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const needle = q.trim().toLowerCase();
  const filtered = records
    .filter((r) =>
      `${r.record_no} ${r.ph_name || ""} ${r.form_no || ""}`
        .toLowerCase()
        .includes(needle)
    )
    .slice(0, 60);

  return (
    <div className="combo">
      <input
        className="combo-input"
        value={open ? q : value}
        placeholder="Search by code, name or form…"
        onFocus={() => {
          setOpen(true);
          setQ("");
        }}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
        }}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
      />
      {open && (
        <ul className="combo-list">
          {filtered.length === 0 && <li className="combo-empty">No matches</li>}
          {filtered.map((r) => (
            <li
              key={r.record_no}
              className={r.record_no === value ? "active" : ""}
              onMouseDown={() => {
                onChange(r.record_no);
                setOpen(false);
              }}
            >
              <b>{r.record_no}</b> — {r.ph_name}
              <span className="combo-form">{r.form_no}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ReportTable({ result, overrides, onToggle, onNote }) {
  return (
    <table className="report">
      <thead>
        <tr>
          <th className="serial">#</th>
          <th>Field</th>
          <th>Entered (CRM)</th>
          <th>Found in image</th>
          <th>Score</th>
          <th>Status</th>
          <th>Review</th>
        </tr>
      </thead>
      <tbody>
        {result.fields.map((f) => {
          const meta = STATUS_META[f.status] || STATUS_META.mismatch;
          const reviewable =
            f.status === "mismatch" || f.status === "false_positive" || f.status === "ocr_missed";
          const marked = f.status === "false_positive";
          const diff =
            f.status === "mismatch"
              ? diffSegments(f.expected, f.found || "")
              : null;
          const foundDisplay =
            f.status === "ocr_missed"
              ? <span className="ocr-missed-label">— not found by OCR</span>
              : (f.found || "—");
          return (
            <tr key={f.field} className={f.status === "ocr_missed" ? "row-missed" : ""}>
              <td className="serial">{f.serial}</td>
              <td>{f.label}</td>
              <td className={f.status === "ocr_missed" ? "expected-missed" : ""}>
                <DiffCell segments={diff?.expected} fallback={f.expected} />
              </td>
              <td className="found">
                {diff
                  ? <DiffCell segments={diff.found} fallback={f.found || "—"} />
                  : foundDisplay
                }
              </td>
              <td className="score">{f.score == null ? "—" : f.score}</td>
              <td>
                <span className={`badge ${meta.cls}`}>{meta.label}</span>
              </td>
              <td className="review">
                {reviewable ? (
                  <div className="review-cell">
                    <label className="fp-toggle">
                      <input
                        type="checkbox"
                        checked={marked}
                        onChange={() => onToggle(f.field)}
                      />
                      Scan error
                    </label>
                    {marked && (
                      <input
                        className="fp-note"
                        type="text"
                        placeholder="note (optional)"
                        value={overrides[f.field] || ""}
                        onChange={(e) => onNote(f.field, e.target.value)}
                      />
                    )}
                  </div>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function SingleMode({ records }) {
  const [formNo, setFormNo] = useState("");
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const [overrides, setOverrides] = useState({});
  const [showReport, setShowReport] = useState(false);

  function onFile(e) {
    const f = e.target.files?.[0] || null;
    setFile(f);
    setPreview(f ? URL.createObjectURL(f) : null);
  }

  async function onValidate(e) {
    e.preventDefault();
    setError("");
    setResult(null);
    setOverrides({});
    setShowReport(false);
    if (!formNo.trim()) return setError("Select or type a record number.");
    if (!file) return setError("Upload the form image.");

    const body = new FormData();
    body.append("form_no", formNo.trim());
    body.append("image", file);
    setLoading(true);
    try {
      const res = await fetch(`${API}/validate`, { method: "POST", body });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Validation failed");
      data.image = await fileToDataUrl(file);
      setResult(data);
      setShowReport(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  function toggleFalsePositive(field) {
    setOverrides((o) => {
      const next = { ...o };
      if (next[field] !== undefined) delete next[field];
      else next[field] = "";
      return next;
    });
  }
  const setNote = (field, note) =>
    setOverrides((o) => ({ ...o, [field]: note }));

  const effective = applyOverrides(result, overrides);
  const verdictClass = effective
    ? effective.verdict === "PASS"
      ? "v-pass"
      : "v-fail"
    : "";

  function openReportTab() {
    const w = window.open("", "_blank");
    if (w) {
      w.document.write(buildReportHtml(effective));
      w.document.close();
    }
  }

  return (
    <div className="layout">
      <section className="card">
        <h2>Validate a record</h2>
        <form onSubmit={onValidate}>
          <label>Form / Record number</label>
          <SearchableSelect
            records={records}
            value={formNo}
            onChange={setFormNo}
          />
          <input
            value={formNo}
            onChange={(e) => setFormNo(e.target.value)}
            placeholder="…or type e.g. 61031 / L_I@61031"
          />

          <label>Form image</label>
          <input type="file" accept="image/*" onChange={onFile} />
          {preview && <img className="preview" src={preview} alt="form" />}

          <button type="submit" disabled={loading}>
            {loading ? "Reading form…" : "Validate"}
          </button>
          {error && <p className="error">{error}</p>}
        </form>
        <p className="hint">{records.length} record(s) loaded.</p>
      </section>

      <section className="card result">
        {!result && <p className="empty">Run a validation to see the report.</p>}
        {effective && (
          <>
            <div className="result-head">
              <div>
                <h2>{effective.record_no}</h2>
                <p className="sub">
                  {effective.ph_name} · {effective.form_no}
                  {effective.elapsed_seconds != null &&
                    ` · ran in ${effective.elapsed_seconds}s`}
                </p>
              </div>
              <div className={`verdict ${verdictClass}`}>
                {effective.verdict}
                <span>{effective.overall_score}%</span>
              </div>
            </div>

            {effective.image_mismatch && (
              <div className="warn-banner">
                This image doesn’t appear to be the form for{" "}
                <b>{effective.record_no}</b> — its record number wasn’t found in
                the scan. The results below are unreliable.
              </div>
            )}

            <div className="counts">
              <span>Checked {effective.summary.checked}</span>
              <span className="st-match">
                Matched {effective.summary.matched}
              </span>
              <span className="st-mismatch">
                Mismatched {effective.summary.mismatched}
              </span>
              {(effective.fields?.filter(f => f.status === "ocr_missed").length || 0) > 0 && (
                <span className="st-missed">
                  OCR missed {effective.fields.filter(f => f.status === "ocr_missed").length}
                </span>
              )}
              {effective.summary.false_positive > 0 && (
                <span className="st-fp">
                  False positives {effective.summary.false_positive}
                </span>
              )}
            </div>

            <div className="actions">
              <button onClick={() => setShowReport((s) => !s)}>
                {showReport ? "Hide report" : "View report"}
              </button>
              <button onClick={openReportTab}>Open in new tab</button>
              <button className="primary" onClick={() => downloadReport(effective)}>
                Download PDF
              </button>
            </div>

            <p className="hint">
              The scanned form is the source of truth. If a “Mismatch” is really a
              scan misread, tick “Scan error”, the score updates automatically.
            </p>

            {showReport && (
              <ReportTable
                result={effective}
                overrides={overrides}
                onToggle={toggleFalsePositive}
                onNote={setNote}
              />
            )}
          </>
        )}
      </section>
    </div>
  );
}

function BatchFormCard({ form, overrides, setOverrides }) {
  const [open, setOpen] = useState(false);

  if (!form.matched) {
    return (
      <div className="batch-card unmatched">
        <div className="batch-row">
          <span className="batch-box">Form #{form.box + 1}</span>
          <span className="batch-norec">No matching record found</span>
          {form.image && (
            <button
              className="link-btn"
              onClick={() => openImage(form.image, `form ${form.box + 1}`)}
            >
              View image
            </button>
          )}
        </div>
      </div>
    );
  }

  function toggle(field) {
    setOverrides((o) => {
      const next = { ...o };
      if (next[field] !== undefined) delete next[field];
      else next[field] = "";
      return next;
    });
  }
  const setNote = (field, note) =>
    setOverrides((o) => ({ ...o, [field]: note }));

  const eff = applyOverrides(form, overrides);
  const vClass = eff.verdict === "PASS" ? "v-pass" : "v-fail";

  return (
    <div className="batch-card">
      <div className="batch-row" onClick={() => setOpen((s) => !s)}>
        <span className="batch-box">Form #{form.box + 1}</span>
        <span className="batch-rec">{eff.record_no}</span>
        <span className="batch-name">{eff.ph_name}</span>
        {eff.image_mismatch && <span className="batch-warn">wrong image?</span>}
        <span className="batch-counts">
          {eff.summary.matched}/{eff.summary.checked}
        </span>
        <span className={`verdict mini ${vClass}`}>
          {eff.verdict} {eff.overall_score}%
        </span>
        {form.image && (
          <button
            className="link-btn"
            onClick={(e) => {
              e.stopPropagation();
              openImage(form.image, eff.record_no);
            }}
          >
            View image
          </button>
        )}
        <span className="batch-toggle">{open ? "▲" : "▼"}</span>
      </div>
      {open && (
        <div className="batch-detail">
          {form.image && (
            <>
              {eff.summary.mismatched > 0 && (
                <p className="crop-caption">
                  Red boxes mark the values that didn't match.
                </p>
              )}
              <img className="form-crop" src={form.image} alt="form crop" />
            </>
          )}
          <div className="actions">
            <button className="primary" onClick={() => downloadReport(eff)}>
              Download PDF
            </button>
          </div>
          <ReportTable
            result={eff}
            overrides={overrides}
            onToggle={toggle}
            onNote={setNote}
          />
        </div>
      )}
    </div>
  );
}

// Send at most this many images per request. A single request with many images
// produces a huge JSON response (each form embeds a base64 crop) that the dev
// proxy can truncate, causing "Unexpected end of JSON input". Chunking keeps
// each response small and lets us show progress.
const BATCH_CHUNK = 4;

// Run the chunked validate-batch pipeline for one folder's images. Each form box
// in each image is detected, matched to its record, and validated independently.
async function validateFolder(folderFiles, onProgress) {
  const images = [];
  let elapsed = 0;

  for (let i = 0; i < folderFiles.length; i += BATCH_CHUNK) {
    const group = folderFiles.slice(i, i + BATCH_CHUNK);
    const body = new FormData();
    group.forEach((f) => body.append("images", f));
    const res = await fetch(`${API}/validate-batch`, { method: "POST", body });
    const text = await res.text();
    let json;
    try {
      json = JSON.parse(text);
    } catch {
      if (!res.ok) throw new Error(`Validation failed (${res.status})`);
      throw new Error(
        "Server returned an incomplete response. Try fewer images at once."
      );
    }
    if (!res.ok) throw new Error(json.detail || "Batch validation failed");
    images.push(...json.images);
    elapsed += json.elapsed_seconds || 0;
    onProgress?.(Math.min(i + BATCH_CHUNK, folderFiles.length));
  }

  return {
    images,
    elapsed: Math.round(elapsed * 10) / 10,
    forms_detected: images.reduce((a, im) => a + (im.forms_detected || 0), 0),
  };
}

function BatchMode() {
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState("");
  const [data, setData] = useState(null); // { folders: [...], generated_at }
  const [overridesByForm, setOverridesByForm] = useState({});
  const [filter, setFilter] = useState("all"); // all | matched | unmatched

  const formKey = (folderKey, imName, box) => `${folderKey}::${imName}-${box}`;
  const makeSetOverrides = (key) => (updater) =>
    setOverridesByForm((all) => {
      const cur = all[key] || {};
      const next = typeof updater === "function" ? updater(cur) : updater;
      return { ...all, [key]: next };
    });

  function handleFiles(list) {
    setFiles(list);
    setData(null);
    setOverridesByForm({});
    setError("");
  }

  async function onRun(e) {
    e.preventDefault();
    setError("");
    setData(null);
    if (!files.length) return setError("Upload one or more images.");
    setLoading(true);
    try {
      const groups = groupByFolder(files);
      const folders = [];
      let processed = 0;
      for (const g of groups) {
        const { images, elapsed, forms_detected } = await validateFolder(
          g.files,
          (doneInFolder) =>
            setProgress({ done: processed + doneInFolder, total: files.length })
        );
        processed += g.files.length;
        setProgress({ done: processed, total: files.length });
        folders.push({ key: g.key, label: g.label, images, elapsed, forms_detected });
      }
      setData({ folders, generated_at: new Date().toISOString() });
      setOverridesByForm({});
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setProgress(null);
    }
  }

  const folders = data?.folders || [];
  const allResults = folders.flatMap((fd) => fd.images.flatMap((im) => im.results));
  const matched = allResults.filter((r) => r.matched);
  const unmatchedCount = allResults.length - matched.length;
  const passed = matched.filter((r) => r.verdict === "PASS").length;
  const totalForms = folders.reduce((a, fd) => a + (fd.forms_detected || 0), 0);
  const totalImages = folders.reduce((a, fd) => a + fd.images.length, 0);
  const multiFolder = folders.length > 1;

  const passFilter = (f) =>
    filter === "all" ? true : filter === "matched" ? f.matched : !f.matched;

  // Reports for the shown (filtered) forms of one folder. Empty / unmapped forms
  // are included too (with their image + OCR text) so the download is complete.
  const folderReports = (fd) => {
    const out = [];
    fd.images.forEach((im) =>
      im.results.forEach((f) => {
        if (!passFilter(f)) return;
        out.push(
          f.matched
            ? applyOverrides(f, overridesByForm[formKey(fd.key, im.image_name, f.box)])
            : f
        );
      })
    );
    return out;
  };

  return (
    <div className="layout">
      <section className="card">
        <h2>Validate multi-form sheets</h2>
        <form onSubmit={onRun}>
          <label>Sheet images — drop one or more folders, or pick files</label>
          <DropZone files={files} onFiles={handleFiles} idPrefix="batch" />
          <button type="submit" disabled={loading}>
            {loading ? "Reading forms…" : "Validate all forms"}
          </button>
          {loading && progress && (
            <p className="hint">
              Processed {progress.done} of {progress.total} image(s)…
            </p>
          )}
          {error && <p className="error">{error}</p>}
        </form>
        <p className="hint">
          Every form is detected and matched to its record automatically by the
          record number printed on it.
        </p>
      </section>

      <section className="card result">
        {!data && (
          <p className="empty">Upload image(s) and run to see every form.</p>
        )}
        {data && (
          <>
            <div className="result-head">
              <div>
                <h2>
                  {totalForms} form(s) in {totalImages} image(s)
                  {multiFolder && ` · ${folders.length} folder(s)`}
                </h2>
                <p className="sub">
                  {matched.length} matched · {passed} passed
                </p>
              </div>
            </div>
            <div className="batch-filter">
              <button
                className={filter === "all" ? "active" : ""}
                onClick={() => setFilter("all")}
              >
                All ({allResults.length})
              </button>
              <button
                className={filter === "matched" ? "active" : ""}
                onClick={() => setFilter("matched")}
              >
                Mapped ({matched.length})
              </button>
              <button
                className={filter === "unmatched" ? "active" : ""}
                onClick={() => setFilter("unmatched")}
              >
                Empty / not mapped ({unmatchedCount})
              </button>
            </div>

            {folders.map((fd) => {
              const reports = folderReports(fd);
              return (
                <div key={fd.key} className="folder-section">
                  <div className="folder-head">
                    <h3 className="folder-title">
                      📁 {fd.label}
                      <span className="folder-meta">
                        {fd.forms_detected} form(s) · {fd.images.length} image(s)
                        {fd.elapsed != null && ` · ${fd.elapsed}s`}
                      </span>
                    </h3>
                    {reports.length > 0 && (
                      <button
                        className="primary"
                        onClick={() => downloadAllReports(reports)}
                      >
                        ↓ Download {fd.label} reports (PDF)
                      </button>
                    )}
                  </div>
                  {fd.images.map((im) => {
                    const shown = im.results.filter(passFilter);
                    if (!shown.length) return null;
                    return (
                      <div key={im.image_name} className="batch-image-group">
                        <h4 className="batch-image-title">
                          {im.image_name}
                          <span className="batch-image-meta">
                            {im.error ? im.error : `${shown.length} form(s)`}
                          </span>
                        </h4>
                        <div className="batch-list">
                          {shown.map((f) => (
                            <BatchFormCard
                              key={formKey(fd.key, im.image_name, f.box)}
                              form={f}
                              overrides={
                                overridesByForm[
                                  formKey(fd.key, im.image_name, f.box)
                                ] || {}
                              }
                              setOverrides={makeSetOverrides(
                                formKey(fd.key, im.image_name, f.box)
                              )}
                            />
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </>
        )}
      </section>
    </div>
  );
}

// Run the chunked /extract pipeline for one folder's images, carrying open
// cross-page partials (`pending`) between chunks and across a final flush.
async function extractFolder(folderFiles, onProgress) {
  let pending = [];
  let rows = [];
  let header = null;
  let elapsed = 0;

  for (let i = 0; i < folderFiles.length; i += BATCH_CHUNK) {
    const group = folderFiles.slice(i, i + BATCH_CHUNK);
    const body = new FormData();
    group.forEach((f) => body.append("images", f));
    body.append("carry", JSON.stringify(pending));
    body.append("flush", "false");
    const res = await fetch(`${API}/extract`, { method: "POST", body });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || `Server error ${res.status}`);
    }
    const json = await res.json();
    if (!header && json.header) header = json.header;
    if (json.rows) rows.push(...json.rows);
    pending = json.pending || [];
    elapsed += json.elapsed_seconds || 0;
    onProgress?.(Math.min(i + BATCH_CHUNK, folderFiles.length));
  }

  if (pending.length > 0) {
    const body = new FormData();
    body.append("carry", JSON.stringify(pending));
    body.append("flush", "true");
    const res = await fetch(`${API}/extract`, { method: "POST", body });
    if (res.ok) {
      const json = await res.json();
      if (!header && json.header) header = json.header;
      if (json.rows) rows.push(...json.rows);
      elapsed += json.elapsed_seconds || 0;
    }
  }

  return { header: header || ["ID"], rows, elapsed: Math.round(elapsed * 10) / 10 };
}

// Build one worksheet from a header + rows, with a numeric (comma-free) ID
// column and auto-width columns.
function buildExcelSheet(header, rows) {
  const sheetData = [
    header,
    ...rows.map((row) => {
      const r = [...row];
      const num = Number(r[0]);
      if (!isNaN(num) && String(r[0]).trim() !== "") r[0] = num;
      return r;
    }),
  ];
  const ws = XLSX.utils.aoa_to_sheet(sheetData);
  const range = XLSX.utils.decode_range(ws["!ref"] || "A1");
  for (let R = 1; R <= range.e.r; R++) {
    const addr = XLSX.utils.encode_cell({ r: R, c: 0 });
    if (ws[addr] && ws[addr].t === "n") ws[addr].z = "0";
  }
  ws["!cols"] = header.map((h, i) => {
    let max = String(h).length;
    for (const row of rows) {
      const val = row[i] != null ? String(row[i]) : "";
      if (val.length > max) max = val.length;
    }
    return { wch: Math.min(max + 2, 42) };
  });
  return ws;
}

// Excel sheet names: <=31 chars, no : \ / ? * [ ], non-blank, unique.
function uniqueSheetName(label, used) {
  let name = String(label).replace(/[\\/?*[\]:]/g, " ").trim().slice(0, 31) || "Sheet";
  const base = name;
  let n = 2;
  while (used.has(name.toLowerCase())) {
    const suffix = ` (${n++})`;
    name = base.slice(0, 31 - suffix.length) + suffix;
  }
  used.add(name.toLowerCase());
  return name;
}

function OcrToExcelMode() {
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [progress, setProgress] = useState(null);
  const [done, setDone] = useState(null); // { filename, formCount, imageCount, url, folders, partialForms }

  // Clean up Blob URLs to prevent memory leaks when done changes or unmounts
  useEffect(() => {
    return () => {
      if (done && done.url) {
        URL.revokeObjectURL(done.url);
      }
    };
  }, [done]);

  function handleFiles(list) {
    if (done && done.url) {
      URL.revokeObjectURL(done.url);
    }
    setFiles(list);
    setDone(null);
    setError("");
  }

  async function onRun(e) {
    e.preventDefault();
    if (!files.length) return setError("Upload one or more images.");
    if (done && done.url) {
      URL.revokeObjectURL(done.url);
    }
    setLoading(true);
    setError("");
    setDone(null);
    setProgress({ done: 0, total: files.length });

    try {
      const groups = groupByFolder(files);
      const wb = XLSX.utils.book_new();
      const usedNames = new Set();
      const folderSummaries = [];
      let processed = 0;
      let totalElapsed = 0;
      let totalForms = 0;

      for (const g of groups) {
        const { header, rows, elapsed } = await extractFolder(g.files, (n) =>
          setProgress({ done: processed + n, total: files.length })
        );
        processed += g.files.length;
        setProgress({ done: processed, total: files.length });
        totalElapsed += elapsed;
        totalForms += rows.length;

        const sheet =
          groups.length > 1
            ? uniqueSheetName(g.label, usedNames)
            : "OCR Extract";
        XLSX.utils.book_append_sheet(wb, buildExcelSheet(header, rows), sheet);
        folderSummaries.push({
          label: g.label,
          sheet,
          formCount: rows.length,
          imageCount: g.files.length,
        });
      }

      if (!wb.SheetNames.length) {
        XLSX.utils.book_append_sheet(wb, buildExcelSheet(["ID"], []), "OCR Extract");
      }

      const wbout = XLSX.write(wb, { bookType: "xlsx", type: "array" });
      const blob = new Blob([wbout], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });

      const ts = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14);
      const filename = `ocr_extract_${ts}.xlsx`;

      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);

      setDone({
        filename,
        formCount: totalForms,
        imageCount: files.length,
        url,
        elapsed: Math.round(totalElapsed * 10) / 10,
        folders: folderSummaries,
        partialForms: []
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setProgress(null);
    }
  }

  return (
    <div className="layout">
      <section className="card">
        <h2>OCR → Excel</h2>
        <form onSubmit={onRun}>
          <label>Scanned sheets — drop one or more folders, or pick files</label>
          <DropZone files={files} onFiles={handleFiles} idPrefix="ocr-excel" />
          <button type="submit" disabled={loading} id="ocr-excel-submit">
            {loading ? "Extracting…" : "⬇ Extract & Download Excel"}
          </button>
          {error && <p className="error">{error}</p>}
        </form>
        <p className="hint">
          Each detected form box is OCR-read and written as one row. Columns
          match the full CRM field order (Record No → Card Holder Name). Upload
          multiple folders and each becomes its own sheet in the workbook.
        </p>
      </section>

      <section className="card result">
        {!done && !loading && (
          <div className="excel-placeholder">
            <div className="excel-icon-large">📊</div>
            <p className="empty">
              Upload images and click Extract — the spreadsheet downloads
              automatically.
            </p>
          </div>
        )}
        {loading && (
          <div className="excel-loading">
            <div className="excel-spinner" />
            <p className="excel-loading-text">
              Running OCR on {files.length} image(s)…
              {progress && (
                <><br/><span>Processed {progress.done} of {progress.total} image(s)...</span></>
              )}
              <br />
              <span>This may take a moment for large batches.</span>
            </p>
          </div>
        )}
        {done && (
          <div className="excel-done">
            <div className="excel-done-icon">✅</div>
            <h3>Excel downloaded!</h3>
            <p className="sub">
              {done.imageCount} image(s) · {done.formCount} form(s) extracted
            </p>
            <p className="sub" style={{ marginTop: '4px', fontSize: '0.9em', color: '#6b7280' }}>
              Extracted in {done.elapsed}s
            </p>
            <p className="excel-filename">{done.filename}</p>
            <a href={done.url} download={done.filename} className="btn-excel-download">
              📥 Download Excel Again
            </a>
            {done.folders && done.folders.length > 1 && (
              <div className="excel-folder-summary">
                <div className="excel-folder-summary-title">
                  {done.folders.length} sheet(s) in this workbook
                </div>
                <ul className="excel-folder-list">
                  {done.folders.map((fd) => (
                    <li key={fd.sheet}>
                      <span className="excel-folder-name">📁 {fd.label}</span>
                      <span className="excel-folder-meta">
                        → “{fd.sheet}” · {fd.formCount} form(s) · {fd.imageCount} image(s)
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <p className="hint" style={{ marginTop: "12px" }}>
              Check your downloads folder. Run again to refresh with new images.
            </p>

            {done.partialForms && done.partialForms.length > 0 && (
              <div className="excel-partial-warning">
                <div className="warning-title">⚠️ Partial / Cut-off Forms Skipped</div>
                <p className="warning-desc">
                  The following form IDs were found at the top or bottom edges of the page, detected as cut-off (partial), and skipped to prevent incomplete data rows:
                </p>
                <ul className="partial-list">
                  {done.partialForms.map((id, index) => (
                    <li key={index}>Form ID: <strong>{id}</strong></li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState("validate"); // "validate" | "excel"
  const [status, setStatus] = useState(null);
  const [scraping, setScraping] = useState(false);
  const [scrapeMsg, setScrapeMsg] = useState(null);
  const [scrapeUser, setScrapeUser] = useState("");
  const [scrapePass, setScrapePass] = useState("");
  const [uploadFile, setUploadFile] = useState(null);
  const [uploading, setUploading] = useState(false);

  function loadStatus() {
    fetch(`${API}/data-status`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setStatus)
      .catch(() => setStatus(null));
  }

  useEffect(() => {
    loadStatus();
  }, []);

  async function onScrape() {
    setScraping(true);
    setScrapeMsg(null);
    try {
      const body = new FormData();
      if (scrapeUser.trim()) body.append("username", scrapeUser.trim());
      if (scrapePass.trim()) body.append("password", scrapePass.trim());
      const res = await fetch(`${API}/scrape`, { method: "POST", body });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Scrape failed");
      setScrapeMsg({
        ok: true,
        text: `Scraped ${data.record_count} records. Now using the latest data.`,
      });
      loadStatus();
    } catch (e) {
      setScrapeMsg({ ok: false, text: e.message });
    } finally {
      setScraping(false);
    }
  }

  async function onUpload(e) {
    e.preventDefault();
    if (!uploadFile) return;
    setUploading(true);
    setScrapeMsg(null);
    try {
      const body = new FormData();
      body.append("file", uploadFile);
      const res = await fetch(`${API}/upload-data`, { method: "POST", body });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Upload failed");
      setScrapeMsg({
        ok: true,
        text: `Loaded ${data.record_count} records from ${uploadFile.name}.`,
      });
      setUploadFile(null);
      // reset file input
      const inp = document.getElementById("upload-data-input");
      if (inp) inp.value = "";
      loadStatus();
    } catch (e) {
      setScrapeMsg({ ok: false, text: e.message });
    } finally {
      setUploading(false);
    }
  }

  const lastScraped = status?.last_scraped_at
    ? new Date(status.last_scraped_at).toLocaleString()
    : null;

  return (
    <div className="page">
      <header>
        <div className="header-row">
          <div>
            <h1>Data Entry Validator</h1>
            <p>Check the data entered in the CRM against the scanned form.</p>
          </div>

          <div className="data-controls">
            {/* ── Scrape CRM ── */}
            <div className="ctrl-block">
              <span className="ctrl-label">Scrape CRM</span>
              <div className="ctrl-row">
                <input
                  id="scrape-username"
                  className="ctrl-field"
                  type="text"
                  placeholder="Username"
                  value={scrapeUser}
                  onChange={(e) => setScrapeUser(e.target.value)}
                  autoComplete="username"
                />
                <input
                  id="scrape-password"
                  className="ctrl-field"
                  type="password"
                  placeholder="Password"
                  value={scrapePass}
                  onChange={(e) => setScrapePass(e.target.value)}
                  autoComplete="current-password"
                />
                <button
                  id="scrape-btn"
                  className="ctrl-action-btn"
                  onClick={onScrape}
                  disabled={scraping}
                >
                  {scraping ? "Scraping…" : "Scrape"}
                </button>
              </div>
              <span className="ctrl-hint">
                Leave blank to use server credentials (.env)
              </span>
            </div>

            <div className="ctrl-divider" />

            {/* ── Upload pre-scraped JSON ── */}
            <div className="ctrl-block">
              <span className="ctrl-label">Upload data file</span>
              <div className="ctrl-row">
                <label className="file-pick-label" htmlFor="upload-data-input">
                  <span className="file-pick-icon">📎</span>
                  <span className="file-pick-name">
                    {uploadFile ? uploadFile.name : "Choose .json or .xlsx file…"}
                  </span>
                  <input
                    id="upload-data-input"
                    type="file"
                    accept=".json,application/json,.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,.xls"
                    onChange={(e) =>
                      setUploadFile(e.target.files?.[0] || null)
                    }
                  />
                </label>
                <button
                  id="upload-data-btn"
                  className="ctrl-action-btn"
                  onClick={onUpload}
                  disabled={uploading || !uploadFile}
                >
                  {uploading ? "Uploading…" : "Upload"}
                </button>
              </div>
            </div>

            {/* ── Footer: downloads + status ── */}
            <div className="ctrl-footer">
              <div className="ctrl-links">
                {status && (
                  <a
                    className="link-btn"
                    href={`${API}/download-csv`}
                    download
                  >
                    ↓ CSV
                  </a>
                )}
                {status && (
                  <a
                    className="link-btn"
                    href={`${API}/download-data`}
                    download
                  >
                    ↓ JSON
                  </a>
                )}
              </div>
              <span className="ctrl-status">
                {status
                  ? `${status.record_count} records · ${
                      status.last_scraped_at
                        ? "scraped " +
                          new Date(status.last_scraped_at).toLocaleString()
                        : "bundled data"
                    }`
                  : ""}
              </span>
            </div>
          </div>
        </div>

        {scrapeMsg && (
          <p className={`scrape-msg ${scrapeMsg.ok ? "ok" : "err"}`}>
            {scrapeMsg.text}
          </p>
        )}
      </header>

      <div className="tabs">
        <button
          id="tab-validate"
          className={tab === "validate" ? "active" : ""}
          onClick={() => setTab("validate")}
        >
          ✓ Validate Forms
        </button>
        <button
          id="tab-excel"
          className={tab === "excel" ? "active" : ""}
          onClick={() => setTab("excel")}
        >
          📊 OCR → Excel
        </button>
      </div>

      {tab === "validate" && <BatchMode />}
      {tab === "excel" && <OcrToExcelMode />}
    </div>
  );
}
