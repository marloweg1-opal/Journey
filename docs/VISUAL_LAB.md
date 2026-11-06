# Journey Vision Lab 0.1

This standalone experiment adds image inspection and contextual stewardship to
the RC2 folder inventory. It uses the existing local-drive and reparse checks,
scan bounds, collision checks, and atomic output safeguards. It has a separate
workspace format and launcher. RC1 and RC2 continue to use their own plan format.

## Try it

Extract the Windows x64 ZIP and open **Start Vision Lab.cmd**. Choose **D** for
the included demonstration or **I** to select a local image folder. For a real
scan, choose an existing workspace folder outside the source. The console's
**O** command opens an offline thumbnail review sheet. Use **R** and its image
number to confirm an identity, reject one, or record a purpose. **U** retracts
the latest review. **N** saves a naming convention for this workspace.

The workspace retains thumbnails, content fingerprints, visual descriptors,
review history, and plan snapshots. Use a dedicated local workspace per source.
Plans and reports may contain private image content or paths. PNG, JPEG, WebP,
BMP, TIFF, and ICO are sampled at up to 50 files, 16 MiB and 20 megapixels per
image, within a 60-second analysis budget checked between images. The inventory
has RC2's separate limits. The first frame represents a multiframe
image. Source files are opened read-only. The lab writes only in the workspace
and has no physical execution step.

## What the lab does

- Pixel layout, foreground palette, transparency, and shape provide visual
  grouping evidence. Strongly related groups can be found without initial user
  labels. A close composition can be a possible variation. Wider semantic
  neighbors are shown as possibly related when the optional encoder is used.
- Virtual series, purposes, and identities can overlap. Purposes can be inferred
  from image structure, confirmed examples, and visual matches to repeated
  confirmed uses in a directory. Widescreen format suggests wallpaper candidacy.
- Identity proposals cite a human-confirmed visual example. Exact confirmation
  is scoped to the reviewed content fingerprint. A rejection remains explicit
  on that fingerprint and can suppress a proposed association on later close
  examples. New look-alikes stay open for review. Decisions preserve the input
  source, exact content fingerprint, and time. Undo retracts a recorded decision.
- Filename and single-folder templates can use `{project}`, `{subject}`,
  `{purpose}`, `{variation}`, and `{stamp}`. Physical previews require confirmed
  subject and purpose. They retain original extension spelling and recognized
  literal date/time and version tokens. Modification time remains provenance.
  An image with insufficient context keeps its original name and shows that it
  needs identification. Proposals include a rationale and any blocker.

The experiment handles localized, related visual material. The bundled example
uses stylized variants and four public Journey crystal images, so its measured
quality describes that fixture. The review sheet exposes filenames, text
statuses, and thumbnails with filename alternative text. Independent
recognition of what a thumbnail depicts still requires sight. Screen reader
operation and accessible visual descriptions need direct evaluation.

## Reproduce

Use Python 3.12 or later with Pillow 12.2.0. Run from the checkout.

```text
python -B -m journey_vision demo
python -B -m unittest discover -s tests -p "test_vision_lab.py" -v
python -B -m unittest discover -s tests -p "test_folder_planner.py" -v
```

The demo uses generated fictional subjects and the four existing public
Navigator crystal PNGs. It starts with 36 images and reveals four holdouts after
two scripted reviewer decisions. The saved results include an HTML review sheet,
JSON plan, and metrics comparing the same holdouts with and without the rejection.

The optional CLIP image encoder accepts the pinned local
[`vision_model_int8.onnx`](https://huggingface.co/Xenova/clip-vit-base-patch32/blob/6b7c523703ae26e39be4b03774966f8571c7f523/onnx/vision_model_int8.onnx)
file in a source environment with NumPy and ONNX Runtime installed. Use
`python -B -m journey_vision demo --clip PATH` or the `scan` command with
`--clip PATH`. Failed or missing encoder setup falls back to pixel analysis.
The encoder supplies relationship evidence. Review decisions still determine
canonical identity. The Windows ZIP includes the pixel baseline.

On Linux, run `python -B -m tools.benchmark_vision_lab --help` for the reproducible
CPU comparison. The benchmark also uses the
[ONNX Model Zoo MobileNetV2-12](https://huggingface.co/onnxmodelzoo/mobilenetv2-12)
penultimate features and
[SmolVLM-256M-Instruct Q8](https://huggingface.co/ggml-org/SmolVLM-256M-Instruct-GGUF)
via llama.cpp. MobileNetV2 and SmolVLM are evaluation backends.

## Acceptance evidence

The 40-image set contains 36 generated fixtures and four already-public Journey
assets. The fictional Aster and Briar portraits use a shared purple composition.
Several files carry misleading asset names. Four new images enter the scope
after a scripted reviewer confirms one Aster image and rejects Aster for one
Briar image. The review sheet records both the shared visual series and the
separate identity evidence.

| Measure | Observed |
|---|---:|
| Automatic purpose assignments before review | 23 of 36, all matching fixture labels |
| Automatic purpose assignments after review | 34 of 40, all matching fixture labels |
| Purpose still open after review | 5 of 40 |
| Grouped pairs matching fixture visual series | 113 of 113, with 119 expected pairs |
| False identity proposals among two new look-alikes | 2 without the rejection, 0 with it |
| Genuine holdout proposals preserved | 2 of 2 |
| False human-confirmed identities | 0 |
| Operator interventions | 2 scripted decisions |
| Warm observation cache | 40 hits and 0 decodes |

The destination draft for the reviewed example is
`Aster/Field Studio - Aster - Character Artwork - v02 - 2026-10-18T14-23-51.png`.
The rest of the sample exercises unknown names, proposed and rejected identity,
and overlapping collections. The demo checks source paths, SHA-256 content
hashes, and modification times before and after each review phase.

### CPU model comparison

These measurements used a Linux AMD EPYC 9V74 runner with four inference
threads, Python 3.12, Pillow 12.2.0, and CPU-only ONNX Runtime 1.24.4 for the
encoders. They characterize the test runner and sample. HEXSEED's i7-9700
requires its own timing measurements.

| Method | 40-image cold time | Warm observation | Peak resident memory | Quality measure |
|---|---:|---:|---:|---|
| Pixel descriptor | 0.39 s | 0.004 s | 31.5 MiB | 40/40 same-series nearest neighbors |
| MobileNetV2-12 features | 0.83 s | 0.008 s | 130.7 MiB | 40/40 same-series nearest neighbors |
| CLIP ViT-B/32 INT8 | 1.54 s | 0.008 s | 199.1 MiB | 40/40 same-series nearest neighbors |
| SmolVLM-256M Q8 | 128.46 s | — | 528.2 MiB | 11/40 correct four-way purpose choices |

The cold embedding times include image decode and descriptor extraction.
One-time encoder setup adds 0.33 seconds for MobileNetV2 and 0.95 seconds for
CLIP. The warm measurement covers content hashing and lookup with zero
decodes or inference. All three retrieval methods matched purpose for 40/40
nearest neighbors and the fictional subject for 12/12 portraits. Neighbor
agreement measures retrieval on this set. It does not validate identity claims.

SmolVLM ran through llama.cpp b12144 with the Q8 text and image projector
files, using a fresh process per image. Its median was 3.01 seconds per image.
The four-way task supplied category choices and evaluated one answer per image.
Pixels remain the portable default. The optional CLIP adapter can surface
broader tentative visual relationships, and its model weights and dependencies
are installed separately. MobileNetV2 and SmolVLM stay in the benchmark.

The boundaries of this program are not the boundaries of human possibility.
