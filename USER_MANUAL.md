# Data Entry Validator - User Manual

## What this tool is for

This tool compares the data already entered in the CRM against the scanned
insurance form, field by field, and points out where they don't match.

**Important: this is a checking aid, not an auto-correct.**
- It does **not** mean the CRM is wrong every time a field is flagged.
- The OCR (the text-reading engine) can also make mistakes - handwriting,
  faint ink, underlines under a word, or a tiny mark like a blood group can be
  misread or missed entirely.
- A flag is a **"please look at this"**, not a verdict. You make the final call
  by looking at the actual form image.

Never blind-trust the tool and update the CRM from it. Always confirm against
the image first (Step 2 below).

---

## Step 1 - Read the report (understand the errors)

After you upload the form image(s), each form gets a report:

- **Verdict** - `PASS` (everything matched) or `FAIL` (at least one mismatch).
- **Score** - the percentage of checked fields that matched.
- **Field table** - one row per field, with:
  - **# / Field** - which field it is (e.g. 19 - Nominee State).
  - **Entered (CRM)** - the value currently stored in the CRM (left).
  - **Found in image** - the value the tool read from the form image (right).
  - **Status** - green `Match` or red `Mismatch`.

### How to read the colours

- **Green `Match`** - the CRM and the form agree. No action needed.
- **Red `Mismatch`** - the CRM and what was read do not agree. Verify it.
- **Red / highlighted characters** in a row show the exact characters that
  differ between the two columns, so you can spot the difference at a glance.
- **Red on the right ("Found in image") with a `—` or blank** means the value
  is **missing** - the OCR did not read anything there. Treat this as "not
  confirmed", and check the image to see what is actually written.

Focus first on the **red (mismatch / missing)** rows - those are the ones that
clearly need verifying. Green rows already agree, so they need no action in the
normal flow.

### Can a "Match" still be wrong?

Yes, occasionally - and it is important to understand why. A green **Match**
means the tool found **no disagreement** between the CRM and what it read. It
does **not** guarantee the value was independently confirmed against the image.
Two things can make a field show as matched without a true confirmation:

- **Unreadable fields fall back to the CRM.** If the OCR could not read a field,
  the tool fills it with the CRM value and shows it as a match - so that field
  was never actually checked against the image.
- **Look-alike characters are treated as equal.** To avoid being derailed by
  harmless OCR quirks, the tool treats characters like `I`/`l` or `O`/`0` as the
  same. A genuine difference hidden inside those characters can therefore slip
  through as a match.

So read green as **"nothing wrong was found"**, not **"100% certified correct"**.
The tool's purpose is to shrink your workload down to the flagged rows - but for
high-value or critical fields, a quick spot-check of the image is still good
practice.

---

## Step 2 - Cross-validate against the form image

This is the most important step. **Do not skip it.**

- The scanned form is shown right in the report, with a **red box drawn
  around each value that didn't match**.
- For every red row, look at the red-boxed area on the image and read the
  real value with your own eyes.
- Then decide which of these is true:
  1. **The image agrees with the CRM** -> the OCR misread it. The CRM is fine,
     no change needed. (Mark it as a scan error / ignore.)
  2. **The image agrees with the "Scanned" value, not the CRM** -> the CRM
     really is wrong. This is a genuine data-entry error to fix.
  3. **The image is unclear / wrong image** -> get a clearer scan before
     deciding anything.

### Example of an OCR mistake

A real case: the form has a value like `(123)` but the OCR dropped the opening
bracket and read it as `123)`. The tool then flags it as a mismatch even though
the CRM is perfectly correct - the form and the CRM actually agree, the reader
just missed one character.

This is why you should **always cross-check the image** before changing
anything.

---

## Step 3 - Update the CRM only when cross-validation also confirms it

Update the CRM record **only** when Step 2 confirms the form image actually
shows a different value than the CRM.

- Image confirms a real difference -> correct the CRM to match the form.
- OCR mistake (image matched the CRM) -> **leave the CRM as it is.**

In short: the report tells you *where* to look, the image tells you *what is
true*, and only a confirmed difference justifies changing the CRM.

---

## Known limitation - split / next-page screenshots

The tool reads **one form from one image**. It cannot stitch a form that has
been split across two screenshots (for example, the top half captured in one
image and the bottom half scrolled onto the next "page" / next screenshot).

When a form is split like this:
- The tool only reads the part that is actually inside the image it processes,
  so the fields on the other half come back empty or wrong.
- Because empty reads fall back to the CRM value, those off-screen fields can
  look like they "passed" even though they were never really checked.

What to do:
- Make sure **the whole form fits in a single image** before uploading.
- Re-capture / re-scan the form as one full image rather than two halves.
- After validating, **check how much of the form the tool actually read** -
  glance at the form image shown in the report and confirm the values it picked
  up cover the entire form, not just the visible portion. If the bottom (or top)
  of the form is cut off, the report for those fields cannot be trusted.

---

## Quick recap

1. **Read** the report and find the red (mismatch) rows.
2. **Cross-validate** each red row against the red-boxed area on the form image.
3. **Update the CRM only** when the image confirms the CRM is actually wrong.

This tool exists to help you *catch* errors - both data-entry errors and OCR
errors - not to replace your judgement. The human check in Step 2 is what makes
it reliable.
