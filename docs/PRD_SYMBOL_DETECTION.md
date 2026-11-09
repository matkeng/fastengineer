# PRD: Drawing Symbol Detection, Block Templates and Text Tags (`googlevision` app)

**Project:** engtech (`/home/matthew/vms/engtech/myproject`)
**App:** `googlevision`, mounted at `/vision/` (`myproject/urls_tenants.py:51`)
**Status of this document:** reverse-engineered from the source on 2026-11-09. It describes what the code does today, not what it was meant to do. The app was **not run** while writing it. Every defect in §11 comes from reading the code. Where a claim depends on runtime behaviour that was not checked, it says so.

---

## 1. Purpose

Engineers upload PDF drawings: P&IDs, schematics and single-line diagrams. The app finds every instance of a known symbol on each page, then reads the text tags printed in or beside each symbol (for example a valve's `FV` + `1023`). The result is a CSV with one row per detected symbol: page, symbol type, bounding box, and the value of each named tag.

The app is called "googlevision" because the first prototype used the Google Cloud Vision OCR API. **Google Vision is no longer part of the production pipeline.** Text now comes from the PDF's own text layer through PyMuPDF (`fitz`). Google OCR survives only as a manual test button (§5.9).

## 2. Scope

In scope:

- Uploading PDFs, splitting them into pages and rendering each page to an image.
- Extracting text with PyMuPDF.
- Defining **block templates**: symbol images with an auto-generated search mask, a match threshold, a search priority, a drawing type and a block set.
- Defining **text tag points** on each template.
- Per-page threshold overrides.
- Template matching with OpenCV.
- Associating text with each symbol, and exporting CSV.
- The background (Celery) "process all" run, with a progress bar.

Present but **not part of the production flow**:

- Border detection. It runs, but nothing reads its output.
- Blob and cloud detection.
- Horizontal and vertical line removal.
- The XOR/SSIM "bitwise" matcher.
- pdfminer extraction.
- Google OCR.
- The `ModifyBlock`/`NewText`/`OldText` change-tracking models, which are used only by the CSV import/export commands.

## 3. Users, entry points and authentication

| Entry | URL | View |
|---|---|---|
| Upload PDFs / document list ("Vision Home") | `/vision/` | `MultiUpload` (`views.py:673`) |
| Pages of a document | `/vision/pages/<doc>/` | `PdfPagesView` (`views.py:713`) |
| Page detail (all intermediate images, test buttons) | `/vision/images/<page>/` | `PageDetail` (`views.py:643`) |
| Block template list + upload ("Masks") | `/vision/masks/` | `MaskUploadView` (`views.py:221`) |
| Draw a template on a page image | `/vision/image/<visionimage>/create-mask/` | `MaskCreateView` (`views.py:119`) |
| Text tag points on a template | `/vision/masks/<block>/points/` | `BlockTextPointCreateView` (`views.py:264`) |
| Per-page threshold override | `/vision/images/<page>/mask-level/` | `ImageThreshCreate` (`views.py:148`). **No page links to it** (§11). |
| Process one document (Celery) | `/vision/pages/<doc>/form/` | `ProcessAllForm_view` (`views.py:1206`) |
| Process several documents (Celery) | `/vision/run-all/` | `RunAllDocs_formview` (`views.py:1171`) |
| Results CSV | `/vision/pages/<doc>/results/` | `block_results` (`views.py:326`) |
| All text CSV | `/vision/pages/<doc>/all_text/` | `download_fitz_data_csv` (`views.py:475`) |

Auth: only `MultiUpload`'s template, `MaskUploadView` and `BlockTextPointCreateView` require login (`LoginRequiredMixin`). Every other view, including delete views, the results CSV and the Celery triggers, has **no auth check** of its own. They rely on the django-tenants URLconf.

Tenancy: data lives in the tenant schema. The project comes from `request.session['current_project']`. `MultiUpload` raises `NameError` if that session key is missing (`views.py:677-681`, where the `else` branch is just `pass`).

## 4. Data model (`models.py`)

```
PrivateDocument (CommonProject: UUID pk, project FK, added_by)
  upload (S3 private), file_name, file_category, drawing_type, block_set
  └── PdfPage  (related_name="pages")
        original (single-page PDF on S3), page_num, width, height (PDF points, from mediaBox)
        match_count, block_data (JSON: the compiled symbol+text list)
        ├── VisionImage (related_name="images")   one per processing artefact
        │     desc (unique per page), image, thumb (5% size), rev (always 1), jdata (JSON)
        └── ImageThresh (related_name="thresholds")  per-page override
              mask FK → BlockImage, threshold, ignore   [unique (page, mask)]

BlockImage (CommonProject)            ← a "block template" / symbol definition
  upload (template image), mask (auto-generated), mask_points (annotated preview)
  use_mask, active, buffer_space, number (search priority), threshold (default 0.85)
  drawing_type (SCH/SLD/GA/TER/PID/TBC, default PID), block_set (FIR…FIF, default FIR), desc
  └── BlockTextPoint (related_name="points")  ← a "text tag"
        name, x_val, y_val (pixels in the template's frame), min_overlap (default 0.5)
```

Key facts:

- **`VisionImage.desc` is the pipeline's addressing scheme.** Each step finds its input with a literal string, such as `"Initail Image"` (sic), `"Fitz- Red Boxes"` or `"Symbols Boxed - PID"`. `SaveUpdateImage` (`image_routines.py:205`) upserts on `(page, desc, rev=1)`. A step's output therefore *replaces* the previous run's output, and there is no history.
- **`jdata` carries the data between steps.** The image is the visual artefact. `jdata` holds the extracted words (Fitz step) or the symbol boxes (symbol step).
- **`drawing_type` + `block_set` select the template library.** A document is processed against `BlockImage.objects.filter(drawing_type=…, block_set=…, active=True).order_by('number')`. Block sets let one drawing type have alternative libraries, for example per client or per CAD standard.
- `BlockImage` has no unique constraint on `(number, drawing_type, block_set)`. The constraint is commented out at `models.py:127-130`. Priority is managed by a signal instead (§5.4).

## 5. End-to-end flow

### 5.1 Upload and split

`MultiUpload` (`views.py:673`):

1. Saves a `PrivateDocument` for each uploaded file.
2. If a file with the same name already exists in the same project for the same user, it overwrites it only when "Replace existing files with same name?" is ticked. Otherwise the file is silently skipped. A *replaced* file is **not** re-split.
3. For new files, calls `SplitPrivateDocumentPdf` synchronously, inside the request.

`SplitPrivateDocumentPdf` (`views.py:946`):

1. Deletes the document's existing `PdfPage`s, which cascades to all their images and overrides.
2. Downloads the PDF from S3.
3. Uses PyPDF2 to write each page to `trash/pdf_<timestamp>.pdf`, which is relative to the process's working directory.
4. Saves each page as a `PdfPage`, with `width`/`height` taken from `mediaBox[2]`/`[3]` in PDF points.
5. Runs `SaveInitialImage` and `OcrTest_Fitz` for each page (§5.2, §5.3).

A 50-page upload therefore renders 100 images and makes several hundred S3 round trips inside one HTTP request.

### 5.2 Render (`SaveInitialImage`, `image_routines.py:162`)

1. `pdf2image.convert_from_bytes` renders the page at its **default 200 dpi**.
2. The image goes through a temp JPEG and is reloaded as greyscale and then converted to BGR (`convertPIL2cv2Image`). **The JPEG step is lossy.**
3. Saved as `"Initail Image"`.
4. A binary version is made by thresholding at 127, inverting twice (net black lines on white), and saved as `"Initail Image Black & White"`.

200 dpi is load-bearing. Template pixel sizes, tag point coordinates and the 80 MP size limit below all assume it.

### 5.3 Text extraction (`OcrTest_Fitz`, `image_routines.py:225`; `GetData_Fitz`, `:269`)

1. Re-renders the page. This is a second `convert_from_bytes` call for the same page.
2. Opens the single-page PDF with PyMuPDF and takes `page.get_text("words")`, which gives one entry per word.
3. For each word it stores:
   - `string`
   - `coords`: raw, in PDF points
   - `box_data`: `coords × scale_factor`, in image pixels
   - `five`/`six`/`seven`: block, line and word numbers
4. `scale_factor` is `image width px / page width pt`, which is about 2.78 at 200 dpi. A rotation branch handles pages whose image is not landscape (see §11 for its two bugs).
5. Saves `"Fitz- Red Boxes"` (word boxes drawn in red; `jdata` = the word list) and `"Fitz - Whiteout"` (words filled white).

Only the PDF text layer is read. **A scanned or outlined-text PDF produces no words**, so every tag comes back as "Not Found".

### 5.4 Defining block templates

There are two ways to create a `BlockImage`:

**A. Upload** (`MaskUploadView`, `/vision/masks/`). The form fields are: template image, threshold, drawing type, block set, use_mask, buffer_space, active, description and number. The page also lists every template the user owns, with links to Edit / Points / Delete.

**B. Draw on a page** (`MaskCreateView`, `/vision/image/<visionimage>/create-mask/`, opened from the "Create Mask" button on any `VisionImage` detail page):

- The template `createmask_form.html` uses AngularJS 1.8.2 and paper.js 0.12.15 from CDNs.
- It shows the chosen artefact image at its natural pixel size in a scrollable 1200×800 box with a 50–200 % zoom slider.
- The user drags a rectangle. Its `{x1,y1,x2,y2}` in image pixels is POSTed as JSON to the same URL.
- The server crops that region from the artefact image (`getSubImage`) and saves it as a new `BlockImage`:
  - `file_name="sub_mask.jpg"`, `desc='MASK'`
  - **JPEG-encoded**
  - all other fields at their model defaults: PID, FIR, threshold 0.85
- The server returns `redirect_url` to the edit page, where the user sets the real type, set, threshold and priority.
- Because the crop comes from the *rendered* page, the template is automatically at the right scale for 200 dpi matching. This is the recommended path.
- Zoom handling divides paper.js's `event.point` by the CSS scale. Whether that is correct at zoom ≠ 100 % was not verified.

**Mask generation.** `add_block_mask` is a `post_save` receiver in `views.py:187`, not in `signals.py`.

- On **every** save of a `BlockImage` with `use_mask=True`, it re-downloads the upload and builds the mask with `createMask(img, buffer_space)` (`cv2_functions.py:80`):
  1. Convert to greyscale.
  2. Invert, so lines become white.
  3. Dilate with a 2×2 kernel `buffer_space − 1` times.
  4. Threshold at 90.
- The mask is therefore the template's strokes widened by a few pixels. Matching then scores only that neighbourhood, so whatever crosses the symbol's bounding box (pipe lines, other text) does not count against the match.
- `buffer_space` (default 2, meaning one dilation) is the tolerance for line-weight differences between the template and the drawing.
- The receiver disconnects itself while it runs, to avoid recursion.

**Priority (`number`).**

- `BlockImage.save()` (`models.py:134`) gives a new block `max(number)+1` within its type/set.
- A `pre_save` receiver in `signals.py:5` bumps any existing block that already holds the incoming number up by one, and that save cascades on. The intent is "insert at position N and shift the rest down".
- Priority matters because matching runs in `number` order **and whites out each match before the next template runs** (§5.6). A specific symbol, such as a control valve, must therefore come before a generic one, such as a plain valve body, or the generic template claims it first.

### 5.5 Defining text tags (`BlockTextPointCreateView`, `views.py:264`)

A text tag says: "the text found at this point inside the symbol is this tag".

- Fields:
  - `name`, for example `Alpha` or `Number`
  - `x_val`, `y_val`: pixels, measured from the template's top-left corner
  - `min_overlap`, default 0.5
- The page lists the existing points.
- Every GET renders a preview (`mask_points`) and saves it to S3. The preview is the mask on a white canvas widened by 120 px, with a red outline and one labelled leader arrow per point.
- Coordinates are typed in by hand. There is no click-to-place.
- The block size is shown as `shape`, which is `(h, w)` from the mask, to help the user stay in bounds.

How a tag is resolved happens at export time (§5.8). In short, a word is the tag's value when **all** of these hold:

1. The point `(symbol.x1 + x_val, symbol.y1 + y_val)` lies inside the word's box horizontally.
2. It also lies inside the word's box vertically.
3. The word's overlap with the symbol box is at least `min_overlap`, where overlap is intersection ÷ the *smaller* box's area (`calculate_box_overlap`, `cv2_functions.py:137`).

Because overlap is measured against the smaller box, a short word fully inside a large symbol scores 1.0. `min_overlap` therefore mainly rejects words that only clip the symbol's edge.

### 5.6 Symbol matching (`LocateSymbols`, `image_routines.py:732`)

Input is `"Initail Image"`.

1. **Downscale guard.** If the image is larger than `desired_size = 80` MP, scale the image and every template by `sfac = 100·√(80/MP)` percent. Let `mult_factor = 100/sfac`. At 200 dpi this only fires above roughly A0 size.
2. Convert the image to greyscale. Save it as `"Symbols Source "`, with a trailing space.
3. For each active template of the document's drawing type and block set, in `number` order:
   1. Load the template and convert it to greyscale. Scale it by `sfac`.
   2. If `use_mask` is set, load the mask and scale it the same way.
   3. Compute `img_bw = gray2bw(img_gray)`, a threshold at 90. This is **recomputed on every template**, so earlier whiteouts carry forward.
   4. Run `cv2.matchTemplate(..., TM_CCORR_NORMED)`.
      - With a mask: the binary image against the greyscale template, with the mask.
      - Without a mask: the greyscale image against the greyscale template.
   5. Set the threshold to `BlockImage.threshold`. If an `ImageThresh` exists for this (template, page), its threshold replaces it, or the template is skipped when `ignore` is set. **This override never actually applies; see §11 #1.**
   6. Collect `loc = np.where(res >= threshold)`.
   7. **If there are more than 1000 raw hit pixels, skip the template entirely.** This is treated as "threshold too low".
   8. Greedy de-duplication in raster order:
      - Accept a hit unless its centre falls on `dupe_mask`.
      - Paint the accepted box onto `dupe_mask`.
      - Draw red boxes on the outputs.
      - **Fill the box white on `img_gray`.** This is what stops a lower-priority template matching the same symbol.
      - Append `{symbol: upload.name, x1, y1, x2, y2, id}` to `boxData`.
   9. Save `"Symbols Boxed = <desc>"`, one per template. Its `jdata` is the *cumulative* `boxData` so far.
4. Save `"Symbols Removed - <type>"` (the whited-out greyscale image) and `"Symbols Boxed - <type>"` (all boxes; `jdata` = every match). Return the match count.

The code after `return matchCount` (Canny edges, contours, thinning, end points) is unreachable.

**Design notes.**

- Matching is **single-scale and single-orientation**.
  - A symbol drawn at a different size, or rotated 90°, needs its own template.
  - So does a symbol that is mirrored.
  - So does a symbol on a drawing plotted at a different scale.
- `TM_CCORR_NORMED` is not mean-subtracted, so scores run high everywhere. The 0.85 default sits close to the noise floor on dense sheets. That is why per-page overrides and the 1000-hit guard exist.

### 5.7 Compile blocks (`compileBlocks`, `image_routines.py:971`)

For each symbol box in `"Symbols Boxed - <type>"`, the code collects every Fitz word whose `box_data` overlaps it. It records `{text, overlap, left, top, text_coords, count}` for each word.

The result, `[{shape, symbol_coords, textlist}]`, is stored on `PdfPage.block_data`. `match_count` is set to its length.

This step **does not** apply the tag points. It is the raw "which words touch which symbol" table.

### 5.8 Export (`block_results`, `views.py:326`)

Writes one CSV row per entry in each page's `block_data`:

```
page_file, symbol_file, x1, y1, x2, y2, <tag1 name>, <tag1 value>, <tag2 name>, <tag2 value>, …
```

- The symbol is resolved to its `BlockImage` by comparing `upload.name` against **all** `BlockImage`s in the schema.
- Its points are applied in `name` order using the rule in §5.5.
- If several words satisfy a point, all of them are appended.
- If none does, the value is `** Not Found **`.
- The view also downloads `"Symbols Removed - PID"` for every page and writes it to `trash/` (an `if True:` debug block), with PID hard-coded.

`download_fitz_data_csv` exports every Fitz word with its pixel box. `block_results_csv` and `block_results_json` are an untagged variant and a JSON variant; neither is routed.

### 5.9 Background processing (`tasks.py:46`, `do_all_scans_task`)

**Triggers:**

- `ProcessAllForm_view` processes one document. Its optional "reset totals" zeroes `match_count`.
- `RunAllDocs_formview` processes several documents chosen by checkbox.
- Both record a `myuser.User3Task` (due in 30 min) and render `ProcesAll_progress.html`, which polls `celery_progress`.

**Per page, in order:**

1. `SaveInitialImage`
2. `OcrTest_Fitz`
3. `removeBoarder`
4. `LocateSymbols`
5. `compileBlocks`
6. Save `block_data` and `match_count`

Each page has 6 progress steps. The `runCheck` skip-if-done logic is computed but bypassed by `if True:`, so every page is always reprocessed.

**On finish:**

- Sends an email to `"matt"` (hard-coded) through `EmailMe`.
- Marks the `User3Task` inactive in the `public` schema.

**Manual per-step buttons** on page detail (`RunPageTest`, `views.py:603`) use letter codes:

| Code | Step |
|---|---|
| `I` | initial render |
| `F` | Fitz |
| `M` | pdfMiner (disabled in the UI) |
| `O` | **Google Vision OCR** |
| `B` | border |
| `D` | blobs |
| `C` | clouds |
| `S` | symbols, hard-coded to PID/SEC |
| `H` / `V` | horizontal / vertical line removal |
| `T` | XOR+SSIM "bitwise" matcher, hard-coded to the template with `desc="FieldTerminal"` |

"Detect Symbols" (`ProcessOneForm_view`) runs `LocateSymbols` and `compileBlocks` synchronously for one page, with a chosen type and set.

### 5.10 Google Vision OCR (`Google_OCR_Image`, `views.py:1037`)

- Writes `"Initail Image Black & White"` to `./trash/*.png` and base64-encodes it.
- Calls `vision.v1 images.annotate` with `TEXT_DETECTION`. The API key is `settings.GOOGLE_VISION_KEY`, read with `config()`, so the project fails to start without it. The call uses `num_retries=3`.
- Stores each annotation as `string`, 8-point `coords`, 2-point `boxes` and `angle` (from the first edge, via `getPointOrientation`).
- Annotation 0 is Google's whole-page text block and is stored like any other word.
- Saves `"Google Vision API - Red Boxes"` and `"… - Whiteout"`.

**Nothing downstream reads this output.** `compileBlocks` reads only the Fitz artefact. Wiring it in is the obvious fallback for scanned drawings (§12).

### 5.11 Border detection (`cv2_routines/remove_border.py`)

1. Flood-fill from the corner, invert and dilate.
2. Flood-fill again, then probe a 5×5 grid of seed points to find the drawing frame's interior.
3. Split words into border (title-block) text and internal text.
4. Save `"Boarder Mask"`, `"No Boarder"`, `"Boarder Only"` and `"Test View"`.

**Neither symbol matching nor `compileBlocks` uses this output.** Matching runs on the full sheet, title block included, so title-block text can be associated with symbols near the frame.

## 6. Pipeline at a glance

| # | Step | Reads (`VisionImage.desc`) | Writes | Used downstream |
|---|---|---|---|---|
| 1 | `SaveInitialImage` | PDF page | `Initail Image`, `Initail Image Black & White` | yes |
| 2 | `OcrTest_Fitz` | PDF page (re-rendered) | `Fitz- Red Boxes` (jdata = words), `Fitz - Whiteout` | yes (words) |
| 3 | `removeBoarder` | `Initail Image` | `Boarder Mask`, `No Boarder`, `Boarder Only`, `Test View` | **no** |
| 4 | `LocateSymbols` | `Initail Image` + templates | `Symbols Source `, `Symbols Boxed = <desc>` ×N, `Symbols Removed - <type>`, `Symbols Boxed - <type>` (jdata = boxes) | yes (boxes) |
| 5 | `compileBlocks` | `Fitz- Red Boxes`, `Symbols Boxed - <type>` | `PdfPage.block_data`, `match_count` | yes |
| 6 | `block_results` (on demand) | `block_data`, `BlockImage.points` | CSV | — |

## 7. Frontend

- Templates are standalone HTML pages. Most are Bootstrap 4.5 album-example copies, still carrying its Twitter/Facebook placeholder links and favicon references. They do not extend a project base template.
- Static assets are minimal (`static/googlevision/{css,js}`).
- The only interactive editor is `createmask_form.html` (AngularJS + paper.js, all from CDNs).
- JSON is pretty-printed into pages with the `pretty_json` filter (`templatetags/extras.py`).
- `visionimage_detail.html` pages through the same artefact across a document's pages. Its "Previous" and "Next" buttons are swapped.

## 8. URL map

See §3. Other routes:

- `split/<doc>`: re-split. Its link is commented out in the template.
- `pages/<doc>/do_all_scans/`: broken (§11).
- `task/<id>/`: progress page.
- `images/<page>/local/`: proxies an image's bytes.
- `images/<page>/create-initial/`: runs steps 1–2 for one page.
- `images/<page>/matches/`: renders `compileBlocks` output live.
- `progress/`: a celery-progress demo that sleeps 40 s.
- `image/<id>/` and `image/<id>/delete/`.
- `masks/<id>/edit|delete/` and `masks/point/<id>/edit|delete/`.

## 9. Dependencies

- OpenCV (`cv2`; `cv2.ximgproc` only in unreachable code), NumPy, pdf2image + poppler, PyPDF2 (legacy `PdfFileReader` API), PyMuPDF (`fitz`), pdfminer.six, pandas.
- scikit-image (SSIM, bitwise matcher only), Pillow.
- google-api-python-client (Vision).
- Celery + celery-progress, django-tenants, django-postgres-copy, django-import-export, nested_admin, django-storages (S3; `PrivateMediaStorage`, `file_overwrite=False`).
- CDN-only: AngularJS 1.8.2, paper.js 0.12.15, Bootstrap 4.5 and 5.3, jQuery 3.5.1.
- Writable `trash/` and `./csv/` directories relative to the CWD.
- `GOOGLE_VISION_KEY` in the environment.

## 10. Functional requirements (as implemented)

- **FR-1:** Upload one or more PDFs with a drawing type and block set. Split each into single-page PDFs and render each page at 200 dpi.
- **FR-2:** Extract every word in the PDF text layer with its box in image-pixel coordinates.
- **FR-3:** Define a block template either by uploading an image or by dragging a rectangle on any rendered page artefact.
- **FR-4:** Auto-generate a stroke-neighbourhood mask for each template. Its width is controlled by `buffer_space`. The mask is optional per template (`use_mask`).
- **FR-5:** Each template carries a match threshold, a search priority (`number`), an active flag, a drawing type and a block set.
- **FR-6:** Define named text tag points on a template, as template-frame pixel coordinates with a minimum overlap.
- **FR-7:** Override a template's threshold for one page, or ignore the template on that page. *Broken; see §11 #1.*
- **FR-8:** Match all active templates of the document's type and set in priority order. Remove each match from the image before the next template runs. Skip a template that produces more than 1000 raw hits.
- **FR-9:** Associate every overlapping word with every detected symbol and store the result per page.
- **FR-10:** Export a CSV of symbols with resolved tag values, or `** Not Found **`.
- **FR-11:** Export all extracted words as CSV.
- **FR-12:** Run the whole pipeline over one or many documents in Celery, with progress reporting and an email on completion.
- **FR-13:** Inspect every intermediate image per page, and re-run any single step from the page.
- **FR-14:** OCR a page with Google Vision on demand. Display only.

## 11. Known issues (from reading the code; not executed)

1. **Per-page threshold overrides never take effect.**
   - `LocateSymbols` (`image_routines.py:826-832`) uses `ImageThresh`, but `image_routines.py` never imports it. Its model import at line 4 is `PrivateDocument, PdfPage, VisionImage, BlockImage` only, and the star-imports bring in no models.
   - The `NameError` is swallowed by a bare `except: pass`.
   - So both the override threshold and `ignore` are silently skipped on every page, in the Celery path and the single-page path alike. FR-7 does nothing.
   - The dead `LocateBinary` has the same bug.
2. **Overrides cannot be reached or deleted from the UI.**
   - No template links to `mask_level`.
   - Its list's Delete button posts to `delete_mask` (the **BlockImage** delete view) with the `ImageThresh`'s integer id. That id is not a valid UUID, so the button errors instead of deleting.
3. **Symbol and text coordinates diverge when the downscale guard fires.**
   - `boxData` stores *scaled-image* coordinates (`pt`, not `pt·mult_factor`), but Fitz `box_data` is in full-size pixels. `compileBlocks` and the tag points then compare boxes from two different frames.
   - The whiteout is drawn on the *scaled* `img_gray` using *full-size* coordinates, so the wrong area is erased and later templates can re-match the same symbol.
   - This only fires above about 80 MP, roughly larger than A0 at 200 dpi.
4. **The rotation branch is inconsistent.**
   - `OcrTest_Fitz` rotates the coordinates it *draws*, but `box_data`, which is what `compileBlocks` uses, is computed by `GetData_Fitz` without that rotation.
   - The test `myPage.width > myPage.height and iwidth > iheight` also classifies every genuinely **portrait** page as rotated.
   - `width`/`height` come from `mediaBox` and ignore `/Rotate` and a non-zero origin.
   - On those pages, tag association uses the wrong boxes.
5. **An uploaded custom mask is always overwritten.**
   - `MaskEditView` exposes a `mask` file field.
   - `add_block_mask` regenerates the mask from the upload on *every* save while `use_mask` is set.
   - So a hand-made mask can never be used.
6. **Viewing the tag-points page writes to S3 and regenerates the mask.** `BlockTextPointCreateView.get_context_data` saves `mask_points` and calls `thisblock.save()`, which triggers `add_block_mask`. Every GET therefore costs two downloads and two uploads.
7. **The priority signal shifts blocks on every edit.**
   - The `pre_save` lookup `get(number=instance.number, …)` finds the block *itself* when its number has not changed.
   - It bumps that row and cascades the bump up the list. The instance's own save then writes the original number back.
   - Each edit therefore leaves a growing gap above the edited block. Ordering is preserved, but the numbers drift.
   - If two blocks ever share a number, the lookup raises an uncaught `MultipleObjectsReturned`.
   - The receiver also disconnects itself globally while it runs, which is not thread-safe.
8. **The results export resolves templates by file name across the whole schema.**
   - It compares `aRef['upload'] == aList['shape']` with no break and no type, set or user filter.
   - Two templates with the same stored name would append duplicate tag columns.
   - It also runs N+1 queries per symbol.
9. **The results export is hard-wired to PID.** The debug block at `views.py:347-350` loads `"Symbols Removed - PID"` for every page. On a SCH, SLD or other non-PID document it raises `DoesNotExist` (a 500).
10. **`do_all_scans` passes a bare pk.** `views.py:1285` calls `do_all_scans_task.delay(pk, …)`, but the task iterates `pkList`, so it loops over the *characters* of the UUID string and fails on the first one.
11. **De-duplication is greedy in raster order, not by score.** The first pixel above threshold (top-left) wins, not the peak. That shifts boxes up and to the left by up to the width of the score plateau. A proper non-max suppression exists in `cv2_routines/bitwise_search.py:139` but is not used here.
12. **The 1000-hit guard drops the template silently.** It counts raw pixels above threshold, before de-duplication. A threshold slightly too low makes the whole symbol type vanish from the results, with only a `print` to show it.
13. **JPEG is used for binary images.**
    - Page renders go through a temp JPEG (`convertPIL2cv2Image`).
    - Canvas-drawn templates are saved as JPEG (`MaskCreateView`).
    - Compression ringing around line art lowers correlation scores.
14. **Image modes are mismatched.**
    - With a mask, matching compares a *binarised* image (threshold 90) against a *greyscale* template.
    - Without a mask, it compares greyscale with greyscale.
    - The mask is resized with `INTER_AREA` and is no longer strictly binary.
    - `templ` loaded as a single-channel PNG would make `cvtColor(BGR2GRAY)` raise. The bundled `symbols/` PNGs are palette PNGs, which OpenCV expands to BGR. That expansion was not verified at runtime.
15. **Width and height are swapped in several places.**
    - `cv2.resize(myMask, (h, w))`, where OpenCV expects `(w, h)`.
    - `draw_leader(..., im_in.shape[0], ...)` uses the height as the right edge.
    - `draw_rectangle_full(..., shape[0], shape[1])`.
    - The first is harmless while mask and template share a shape. The other two misdraw the points preview on non-square templates.
16. **Border detection and Google OCR are computed but unused.** Their cost (one flood-fill pass plus four uploads per page, and a paid API call) buys nothing in the production result.
17. **Heavy work runs inside requests.** Upload, split, render, Fitz and the "Detect Symbols" button all run synchronously. Everything goes through S3 (download, process, re-upload), and each page is rendered twice.
18. **Auth and ownership are thin.**
    - Most views have no login check.
    - Lookups are by bare pk, with no project or owner filter.
    - The completion email always goes to `"matt"`.
    - `MultiUpload` crashes without `current_project` in the session.
19. **There is dead and duplicate code.**
    - `views from Prod` (38 KB), `views-old` (31 KB) and `upwork_find_symbols_white_boxes_working (2)` are untracked copies.
    - `LocateBinary` references undefined `sfac`/`mult_factor`.
    - `old_do_all_scans_task`, `do_all_scans_old`, `fromColab` (calls `cv2_imshow`) and the unreachable code after `return matchCount` are all dead.
    - `tests.py` is empty.
    - The `pdfminer sitepackage` folder holds a vendored file.
    - `ModifyBlock`/`NewText`/`OldText` are used only by the CSV import/export commands.

## 12. Recommended next steps

1. **Fix the override import** (§11 #1). It is a one-line change: add `ImageThresh` to the model import at `image_routines.py:4`. Then replace both bare `except:` blocks with `except ImageThresh.DoesNotExist:`, and add a link to `mask_level` from page detail. This gives FR-7 back immediately.
2. **Put every coordinate in one frame.**
   - Store symbol boxes as `pt × mult_factor`.
   - Draw the whiteout in the scaled frame.
   - Compute `box_data` *after* rotation.
   - Read page size and rotation from PyMuPDF (`page.rect`, `page.rotation`) instead of `mediaBox`.
   - Add a test with a synthetic page holding one known symbol and one known word, at 0° and 90°, above and below the 80 MP guard.
3. **Make matching robust.**
   - Use `TM_CCOEFF_NORMED` (mean-subtracted) on binary-against-binary images.
   - Use real NMS by score (reuse `bitwise_search.non_max_suppression`).
   - Support optional 90°, 180°, 270° and mirrored variants per template, generated at match time rather than stored as separate templates.
   - Allow an optional small scale range.
   - Report a skipped template (more than 1000 hits) in the page results instead of only printing it.
4. **Make templates trustworthy.**
   - Save templates and renders as PNG.
   - Regenerate the mask only when `upload`, `buffer_space` or `use_mask` change.
   - Honour an uploaded mask, or remove the field.
   - Replace the priority signal with an explicit "move to position N" operation inside a transaction.
   - Add a unique constraint on `(drawing_type, block_set, number)`.
5. **Click-to-place tag points.** Reuse the paper.js canvas from `createmask_form.html` on the points page, so `x_val`/`y_val` come from a click on the template rather than typed pixel numbers.
6. **Fix export correctness.**
   - Store the `BlockImage` id in `boxData` instead of `upload.name`, and resolve tags by that id.
   - Remove the PID debug block.
   - Resolve tags once at compile time and store them in `block_data`, so the CSV and any UI read the same thing.
7. **Add an OCR fallback for scanned sheets.** When Fitz returns no words, or too few, for a page, feed `Google_OCR_Image`'s output, or a local OCR engine, into `compileBlocks`. The data shape already almost matches (`boxes` against `box_data`).
8. **Use the border mask.** Drop title-block text from symbol association, or restrict matching to the frame interior.
9. **Move upload, split and render into Celery.** Render once per page and pass the array between steps instead of re-downloading from S3.
10. **Housekeeping.**
    - Add login and project scoping on every view.
    - Make the email recipient the requesting user.
    - Fix `do_all_scans` to pass `[pk]`.
    - Delete the `views*` copies and the dead functions.
    - Add tests for `createMask`, `calculate_box_overlap`, tag resolution and `compileBlocks`.
