const STATUS_COLORS = {
  match: "#1b7f3b",
  partial: "#b8860b",
  mismatch: "#c0392b",
  not_on_form: "#888",
  calculated: "#1b7f3b",
  false_positive: "#0e7490",
};

const STATUS_LABEL = {
  match: "Match",
  partial: "Partial",
  mismatch: "Mismatch",
  not_on_form: "Not on form",
  calculated: "Calculated",
  false_positive: "False positive (scan error)",
};

// Apply reviewer overrides (image is the source of truth, OCR can misread, so a
// Mismatch may be a false positive). Marked fields are treated as correct and
// every summary number, the score and the verdict are recomputed.
export function applyOverrides(result, overrides) {
  if (!result) return result;
  const ov = overrides || {};
  const fields = result.fields.map((f) =>
    ov[f.field] !== undefined && f.status === "mismatch"
      ? { ...f, status: "false_positive", note: ov[f.field] || "" }
      : f
  );

  let checked = 0;
  let matched = 0;
  let mismatched = 0;
  let falsePositive = 0;
  for (const f of fields) {
    if (["match", "mismatch", "false_positive"].includes(f.status)) checked += 1;
    if (f.status === "match") matched += 1;
    else if (f.status === "mismatch") mismatched += 1;
    else if (f.status === "false_positive") falsePositive += 1;
  }

  const correct = matched + falsePositive;
  const overall_score = checked ? Math.round((correct / checked) * 1000) / 10 : 0;
  const verdict = mismatched === 0 ? "PASS" : "FAIL";

  return {
    ...result,
    fields,
    overall_score,
    verdict,
    summary: {
      checked,
      matched,
      partial: 0,
      mismatched,
      false_positive: falsePositive,
    },
  };
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// Character-level diff that mirrors the backend comparison: whitespace, hyphens,
// commas and underscores are ignored, case is ignored, and the visually
// identical glyphs L/l/I/| and O/0 are folded. Returns, for each side, a list
// of {text, diff} segments so the differing characters can be highlighted.
const DIFF_SEP = (c) => /[\s\-,_]/.test(c);
function diffFold(c) {
  let u = c.toUpperCase();
  if (u === "L" || u === "|") u = "I";
  if (u === "O") u = "0";
  return u;
}

export function diffSegments(expected, found) {
  const a = [];
  const b = [];
  const sa = String(expected ?? "");
  const sb = String(found ?? "");
  for (let i = 0; i < sa.length; i++)
    if (!DIFF_SEP(sa[i])) a.push({ f: diffFold(sa[i]), idx: i });
  for (let i = 0; i < sb.length; i++)
    if (!DIFF_SEP(sb[i])) b.push({ f: diffFold(sb[i]), idx: i });

  const n = a.length;
  const m = b.length;
  const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i][j] =
        a[i].f === b[j].f
          ? dp[i + 1][j + 1] + 1
          : Math.max(dp[i + 1][j], dp[i][j + 1]);

  const keepA = new Set();
  const keepB = new Set();
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i].f === b[j].f) {
      keepA.add(a[i].idx);
      keepB.add(b[j].idx);
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) i++;
    else j++;
  }

  const toSegments = (s, keep) => {
    const segs = [];
    for (let k = 0; k < s.length; k++) {
      const diff = !DIFF_SEP(s[k]) && !keep.has(k);
      const last = segs[segs.length - 1];
      if (last && last.diff === diff) last.text += s[k];
      else segs.push({ text: s[k], diff });
    }
    return segs;
  };

  return { expected: toSegments(sa, keepA), found: toSegments(sb, keepB) };
}

function diffHtml(expected, found) {
  const { expected: ea, found: fa } = diffSegments(expected, found);
  const render = (segs) =>
    segs
      .map((seg) =>
        seg.diff
          ? `<span class="diff">${escapeHtml(seg.text)}</span>`
          : escapeHtml(seg.text)
      )
      .join("");
  return { expected: render(ea), found: render(fa) };
}

const REPORT_STYLE = `
  @page{margin:14mm;}
  body{font-family:Arial,Helvetica,sans-serif;color:#222;margin:32px;}
  h1{font-size:20px;margin:0 0 4px;}
  .meta{color:#555;font-size:13px;margin-bottom:16px;}
  .verdict{display:inline-block;padding:6px 14px;border-radius:6px;color:#fff;font-weight:700;font-size:15px;}
  .summary{margin:16px 0;font-size:14px;}
  .summary span{margin-right:18px;}
  table{border-collapse:collapse;width:100%;font-size:13px;}
  th,td{border:1px solid #ddd;padding:6px 8px;text-align:left;vertical-align:top;}
  th{background:#f4f4f6;}
  tr{break-inside:avoid;}
  thead{display:table-header-group;}
  .formimg{margin-top:20px;}
  .formimg img{max-width:100%;border:1px solid #ddd;border-radius:4px;}
  .ocr{margin-top:20px;}
  pre{background:#f7f7f9;border:1px solid #e3e3e6;padding:12px;white-space:pre-wrap;font-size:12px;}
  .report-section{page-break-after:always;}
  .report-section:last-child{page-break-after:auto;}
  .diff{background:#ffe08a;color:#b91c1c;font-weight:700;border-radius:2px;}`;

function unmatchedBody(form) {
  return `
  <div class="report-section">
    <h1>Data Entry Validation Report</h1>
    <div class="meta">
      Image: ${escapeHtml(form.image_name)} &nbsp;|&nbsp;
      Form #${(form.box ?? 0) + 1}
    </div>
    <div class="verdict" style="background:#b8860b">NOT MAPPED</div>
    <p style="margin:16px 0;font-size:14px">${escapeHtml(
      form.message ||
        "This form could not be matched to any CRM record (the record number could not be read or mapped)."
    )}</p>
    ${
      form.image
        ? `<div class="formimg"><h3>Form image</h3><img src="${form.image}"/></div>`
        : ""
    }
    ${
      form.ocr_text
        ? `<div class="ocr"><h3>Text read from the form</h3><pre>${escapeHtml(
            form.ocr_text
          )}</pre></div>`
        : ""
    }
  </div>`;
}

function reportBody(result) {
  if (result.matched === false || !result.fields) return unmatchedBody(result);
  const rows = result.fields
    .map((f) => {
      const d = f.status === "mismatch" ? diffHtml(f.expected, f.found) : null;
      const expectedCell = d ? d.expected : escapeHtml(f.expected);
      const foundCell = d ? d.found : escapeHtml(f.found || "-");
      return `
      <tr>
        <td style="text-align:right;color:#888">${escapeHtml(f.serial)}</td>
        <td>${escapeHtml(f.label)}</td>
        <td>${expectedCell}</td>
        <td>${foundCell}</td>
        <td style="text-align:right">${f.score == null ? "-" : f.score}</td>
        <td style="color:${STATUS_COLORS[f.status]};font-weight:600">${STATUS_LABEL[f.status]}${
        f.note
          ? `<div style="color:#555;font-weight:400;font-size:11px">${escapeHtml(
              f.note
            )}</div>`
          : ""
      }</td>
      </tr>`;
    })
    .join("");

  const s = result.summary;
  const verdictBg =
    result.verdict === "PASS"
      ? "#1b7f3b"
      : result.verdict === "REVIEW"
      ? "#b8860b"
      : "#c0392b";
  return `
  <div class="report-section">
    <h1>Data Entry Validation Report</h1>
    <div class="meta">
      Record: <b>${escapeHtml(result.record_no)}</b> &nbsp;|&nbsp;
      Form: ${escapeHtml(result.form_no)} &nbsp;|&nbsp;
      Holder: ${escapeHtml(result.ph_name)} &nbsp;|&nbsp;
      Image: ${escapeHtml(result.image_name)} &nbsp;|&nbsp;
      Generated: ${escapeHtml(result.generated_at)}
    </div>
    <div class="verdict" style="background:${verdictBg}">${escapeHtml(
    result.verdict
  )} &middot; ${result.overall_score}%</div>
    <div class="summary">
      <span>Checked: ${s.checked}</span>
      <span style="color:#1b7f3b">Matched: ${s.matched}</span>
      <span style="color:#c0392b">Mismatched: ${s.mismatched}</span>
      ${
        s.false_positive
          ? `<span style="color:#0e7490">False positives (scan error): ${s.false_positive}</span>`
          : ""
      }
    </div>
    <table>
      <thead><tr><th>#</th><th>Field</th><th>Entered (CRM)</th><th>Found in image</th><th>Score</th><th>Status</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    ${
      result.sources?.length
        ? `<div class="formimg"><h3>Form image${
            result.sources.length > 1 ? "s" : ""
          }</h3>${
            s.mismatched
              ? '<p style="color:#b91c1c;font-weight:600;margin:4px 0">Red boxes mark the values that did not match.</p>'
              : ""
          }${result.sources
            .map(
              (src, i) =>
                `${
                  result.sources.length > 1
                    ? `<p style="margin:6px 0 2px;font-weight:600">Part ${
                        i + 1
                      } of ${result.sources.length} · ${escapeHtml(
                        src.image_name || ""
                      )}</p>`
                    : ""
                }<img src="${src.image}"/>`
            )
            .join("")}</div>`
        : result.image
        ? `<div class="formimg"><h3>Form image</h3>${
            s.mismatched
              ? '<p style="color:#b91c1c;font-weight:600;margin:4px 0">Red boxes mark the values that did not match.</p>'
              : ""
          }<img src="${result.image}"/></div>`
        : ""
    }
    <div class="ocr"><h3>Text read from the form</h3><pre>${escapeHtml(
      result.ocr_text
    )}</pre></div>
  </div>`;
}

function pageShell(title, bodies) {
  return `<!doctype html>
<html><head><meta charset="utf-8"><title>${title}</title>
<style>${REPORT_STYLE}</style></head>
<body>${bodies.join("\n")}</body></html>`;
}

export function buildReportHtml(result) {
  const title = `validation_${String(result.record_no || "report").replace(
    /[^a-z0-9]/gi,
    "_"
  )}`;
  return pageShell(title, [reportBody(result)]);
}

export function buildCombinedReportHtml(results) {
  return pageShell("validation_reports", results.map(reportBody));
}

// Download as PDF via the browser's built-in print-to-PDF: open the document and
// trigger the print dialog (destination "Save as PDF"). Keeps selectable text
// and needs no external library. The <title> is the default PDF file name.
function printHtml(html) {
  const printScript =
    "<scr" +
    "ipt>window.onload=function(){window.focus();window.print();};" +
    "window.onafterprint=function(){window.close();};</scr" +
    "ipt></body>";
  const w = window.open("", "_blank");
  if (!w) {
    alert("Please allow pop-ups to download the PDF report.");
    return;
  }
  w.document.write(html.replace("</body>", printScript));
  w.document.close();
}

export function downloadReport(result) {
  printHtml(buildReportHtml(result));
}

// One PDF containing every form's report (page-break between forms). Browsers
// can't write many separate files into a folder without extra libraries, so we
// produce a single combined PDF that holds all reports together.
export function downloadAllReports(results) {
  if (!results || !results.length) return;
  printHtml(buildCombinedReportHtml(results));
}
