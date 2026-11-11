# Journey Navigator inspection candidate

This records the earlier inspection release. See [Guided Patrol](NAVIGATOR_PATROL.md) for the current operational candidate.

## Start an inspection

1. Extract the Windows x64 ZIP and open **Journey Navigator.exe**. The
   Navigator opens in your browser and runs on your computer.
2. Under **Inspect**, choose a project folder or an existing shortcut,
   junction, or symbolic link. Browse can show local folders for you to choose.
   For a destination outside the current scope, review the path shown and
   choose **Authorize this destination**. Each outside hop gets its own review.
3. Choose **Keep a local checkpoint** if you want **Manage** to reopen the
   results, thumbnails, extracted text, and corrections. An unchecked box
   keeps this review in memory for the session. **Suggest names and draft a
   plan** is a separate choice. For an added link destination, the approval
   displays the review's retention mode and its own suggestions checkbox.
   Select a link in a separate review to use a different retention mode.
4. Use **Images** or **Find** to search filenames, paths, and text found in
   images. Expand **Evidence and naming preview** to see the full source path,
   clues and their origin, and a preliminary filename where warranted.
   Resolve material conflicts by recording a correction. A confirmed subject
   and purpose can produce a destination preview. Save a JSON plan from a
   retained review with suggestions enabled.
5. **Review or revoke permissions** shows the selected scope and each separately
   authorized destination. You can turn suggestions on or off, revoke
   inspection, or forget a checkpoint and its corrections. To continue
   without retention after forgetting a checkpoint, start a temporary review.
   An exported plan is a separate copy.

The selected source is read-only. Journey saves checkpoints and plan exports
under `%LOCALAPPDATA%\Journey\Navigator Inspection` when authorized. Keep
these files private. Closing the Navigator service from **Manage** ends a
temporary review. A checkpoint from the earlier Navigator build needs explicit
reselection. Reauthorizing an external target is separate from reopening its
parent checkpoint.

## What Journey can observe

- Image assessment uses pixels, filename and relative folder clues, the
  bundled CareBloom profile vocabulary, text, and corrections from the same
  scope. A registered reference can suggest a subject. Competing clues stay
  visible, and only an explicit human decision confirms an identity. Visually
  similar images can share a virtual group independently of identity. Names
  preserve original extensions and recognized filename version and timestamp
  tokens. Extracted dates and version text remain labeled as image evidence.
- The bundled Windows text reader runs Tesseract OCR (optical character
  recognition) locally with English language data. The reader receives a
  resized image in memory, with a three-second timeout and one engine thread.
  Text recognition works best for clear printed labels. Stylized, rotated,
  tiny, multilingual, or densely arranged text can be missed or misread.
  If the reader is unavailable, filename, folder, and visual assessment
  remain available. A refresh can retry text reading or backfill it for
  previously analyzed images.
- The checkpoint caches pixels and image text by review, scope, and content
  hash. The text cache also tracks the engine, language data, and processing
  configuration. A warm scan checks source fingerprints again. Search results
  identify whether a match came from image text. Plans carry relevant
  evidence and provenance. Full extracted text is available in the review.
- Images have the existing 16 MiB and 20-megapixel limits. Discovery and
  analysis run in batches and can pause. **Links and destinations** and
  **Skipped entries** describe coverage gaps. The first frame represents a
  multi-frame image. Visual groups compare a bounded set of representatives.
- This build works with local paths. Account access, source holds, system
  directory protections, and applicable Journey perception policies still
  apply. Drive-wide selection, network/device paths and shell-only links are
  blocked. The link record and resolved destination are separate. Journey
  validates the target again and prevents duplicate directory visits and
  recursive cycles. Its inspection service offers no physical operation or
  cross-scope reuse capability.

The interface uses standard browser controls with keyboard navigation and
text labels. Extracted text helps with images that contain text. People who
rely on nonvisual interpretation of unlabeled artwork or on screen-reader
workflows still need direct usability testing. The boundaries of this program
are not the boundaries of human possibility.

## Reproduce

Run `python -B -m journey_navigator` from the source checkout with Pillow.
Linux source runs discover a local Tesseract installation with English data.
Windows source runs can use a standard local Tesseract installation, while
the package includes the pinned runtime and its third-party notices.

The Windows workflow builds the ZIP, extracts it to a folder with spaces, and
exercises it in a browser. It covers existing Windows links, bounded resumption
and reopening, OCR-only search, naming preview, retained correction, revocation,
plan export and source integrity. The contextual tests generate 36 labeled
and misleading reference boards for the six registered names, aliases,
conflicting folder placement, image-only titles, and cold and warm OCR.
The RC1/RC2 Folder Planner and standalone Vision Lab keep their own data formats.
