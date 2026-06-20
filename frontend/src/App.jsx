import { useEffect, useRef, useState } from "react";
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

const STATUS_META = {
  match: { label: "Match", cls: "st-match" },
  partial: { label: "Partial", cls: "st-partial" },
  mismatch: { label: "Mismatch", cls: "st-mismatch" },
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
          const meta = STATUS_META[f.status];
          const reviewable =
            f.status === "mismatch" || f.status === "false_positive";
          const marked = f.status === "false_positive";
          const diff =
            f.status === "mismatch"
              ? diffSegments(f.expected, f.found || "")
              : null;
          return (
            <tr key={f.field}>
              <td className="serial">{f.serial}</td>
              <td>{f.label}</td>
              <td>
                <DiffCell segments={diff?.expected} fallback={f.expected} />
              </td>
              <td className="found">
                <DiffCell segments={diff?.found} fallback={f.found || "—"} />
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

function BatchMode() {
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState("");
  const [data, setData] = useState(null);
  const [overridesByForm, setOverridesByForm] = useState({});
  const [filter, setFilter] = useState("all"); // all | matched | unmatched

  const formKey = (imName, box) => `${imName}-${box}`;
  const makeSetOverrides = (key) => (updater) =>
    setOverridesByForm((all) => {
      const cur = all[key] || {};
      const next = typeof updater === "function" ? updater(cur) : updater;
      return { ...all, [key]: next };
    });

  function onFiles(e) {
    setFiles(Array.from(e.target.files || []));
    setData(null);
    setOverridesByForm({});
  }

  async function onRun(e) {
    e.preventDefault();
    setError("");
    setData(null);
    if (!files.length) return setError("Upload one or more images.");
    setLoading(true);
    setData(null);
    try {
      const images = [];
      let elapsed = 0;
      for (let i = 0; i < files.length; i += BATCH_CHUNK) {
        const group = files.slice(i, i + BATCH_CHUNK);
        setProgress({ done: i, total: files.length });
        const body = new FormData();
        group.forEach((f) => body.append("images", f));
        const res = await fetch(`${API}/validate-batch`, {
          method: "POST",
          body,
        });
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
        setProgress({ done: Math.min(i + BATCH_CHUNK, files.length), total: files.length });
      }
      setData({
        image_count: images.length,
        forms_detected: images.reduce((a, im) => a + (im.forms_detected || 0), 0),
        images,
        elapsed_seconds: Math.round(elapsed * 10) / 10,
        generated_at: new Date().toISOString(),
      });
      setOverridesByForm({});
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setProgress(null);
    }
  }

  const allResults = data?.images.flatMap((im) => im.results) || [];
  const matched = allResults.filter((r) => r.matched);
  const unmatchedCount = allResults.length - matched.length;
  const passed = matched.filter((r) => r.verdict === "PASS").length;

  const passFilter = (f) =>
    filter === "all" ? true : filter === "matched" ? f.matched : !f.matched;

  // Reports for the currently shown (filtered) forms. Empty / unmapped forms are
  // included too (with their image and OCR text), so "Download all" really is all.
  const shownReports = () => {
    const out = [];
    (data?.images || []).forEach((im) =>
      im.results.forEach((f) => {
        if (!passFilter(f)) return;
        out.push(
          f.matched
            ? applyOverrides(f, overridesByForm[formKey(im.image_name, f.box)])
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
          <label>Sheet image(s) — you can select several</label>
          <input type="file" accept="image/*" multiple onChange={onFiles} />
          {files.length > 0 && (
            <p className="hint">{files.length} image(s) selected.</p>
          )}
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
          Every form in every image is detected and matched to its record
          automatically by the record number printed on it.
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
                  {data.forms_detected} form(s) in {data.image_count} image(s)
                </h2>
                <p className="sub">
                  {matched.length} matched · {passed} passed
                  {data.elapsed_seconds != null &&
                    ` · ran in ${data.elapsed_seconds}s`}
                </p>
              </div>
              {allResults.length > 0 && (
                <button
                  className="primary"
                  onClick={() => downloadAllReports(shownReports())}
                >
                  {filter === "all"
                    ? "Download all reports (PDF)"
                    : `Download ${shownReports().length} shown (PDF)`}
                </button>
              )}
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
            {data.images.map((im) => {
              const shown = im.results.filter(passFilter);
              if (!shown.length) return null;
              return (
                <div key={im.image_name} className="batch-image-group">
                  <h3 className="batch-image-title">
                    {im.image_name}
                    <span className="batch-image-meta">
                      {im.error ? im.error : `${shown.length} form(s)`}
                    </span>
                  </h3>
                  <div className="batch-list">
                    {shown.map((f) => (
                      <BatchFormCard
                        key={formKey(im.image_name, f.box)}
                        form={f}
                        overrides={
                          overridesByForm[formKey(im.image_name, f.box)] || {}
                        }
                        setOverrides={makeSetOverrides(
                          formKey(im.image_name, f.box)
                        )}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
          </>
        )}
      </section>
    </div>
  );
}

function OcrToExcelMode() {
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(null); // { filename, formCount, imageCount, url, partialForms }

  // Clean up Blob URLs to prevent memory leaks when done changes or unmounts
  useEffect(() => {
    return () => {
      if (done && done.url) {
        URL.revokeObjectURL(done.url);
      }
    };
  }, [done]);

  function onFiles(e) {
    if (done && done.url) {
      URL.revokeObjectURL(done.url);
    }
    setFiles(Array.from(e.target.files || []));
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
    try {
      const body = new FormData();
      files.forEach((f) => body.append("images", f));
      const res = await fetch(`${API}/ocr-to-excel`, { method: "POST", body });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Server error ${res.status}`);
      }
      const cd = res.headers.get("content-disposition") || "";
      const nameMatch = cd.match(/filename="([^"]+)"/);
      const filename = nameMatch ? nameMatch[1] : "ocr_extract.xlsx";
      const formCount = parseInt(res.headers.get("x-form-count") || "0", 10);
      const imageCount = parseInt(res.headers.get("x-image-count") || "0", 10);
      const partials = res.headers.get("x-partial-forms") || "";

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);

      setDone({
        filename,
        formCount,
        imageCount,
        url,
        partialForms: partials ? partials.split(",").map((s) => s.trim()).filter(Boolean) : []
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="layout">
      <section className="card">
        <h2>OCR → Excel</h2>
        <form onSubmit={onRun}>
          <label>Form image(s) — select one or more scanned sheets</label>
          <input type="file" accept="image/*" multiple onChange={onFiles} />
          {files.length > 0 && (
            <p className="hint">{files.length} image(s) selected.</p>
          )}
          <button type="submit" disabled={loading} id="ocr-excel-submit">
            {loading ? "Extracting…" : "⬇ Extract & Download Excel"}
          </button>
          {error && <p className="error">{error}</p>}
        </form>
        <p className="hint">
          Each detected form box is OCR-read and written as one row. Columns
          match the full CRM field order (Record No → Card Holder Name). Green
          rows = record matched; amber rows = record not found.
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
            <p className="excel-filename">{done.filename}</p>
            <a href={done.url} download={done.filename} className="btn-excel-download">
              📥 Download Excel Again
            </a>
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
                    {uploadFile ? uploadFile.name : "Choose .json file…"}
                  </span>
                  <input
                    id="upload-data-input"
                    type="file"
                    accept=".json,application/json"
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
