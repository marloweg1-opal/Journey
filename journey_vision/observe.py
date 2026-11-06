"""Bounded observation of raster images in an RC2 inventory."""

from base64 import b64encode
from collections import Counter
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path, PurePosixPath
import stat
from time import monotonic

from core.file_paths import safe_metadata, signature


IMAGE_FORMATS = {
    ".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG", ".webp": "WEBP",
    ".bmp": "BMP", ".tif": "TIFF", ".tiff": "TIFF", ".ico": "ICO",
}
MAX_IMAGES = 50
MAX_BYTES = 16 * 1024 * 1024
MAX_PIXELS = 20_000_000
MAX_SECONDS = 60
FEATURE_VERSION = "pixels-v2"


def image_bytes(path, observed=None):
    before = safe_metadata(path)
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
        raise ValueError("Requires a regular image no larger than 16 MiB.")
    if observed and (before.st_size, before.st_mtime_ns) != (observed.size, observed.mtime_ns):
        raise ValueError("The image changed after folder inspection. Scan again.")
    with path.open("rb") as stream:
        if signature(os.fstat(stream.fileno())) != signature(before):
            raise ValueError("The image changed before it could be read.")
        data = stream.read(MAX_BYTES + 1)
    after = safe_metadata(path)
    if signature(after) != signature(before) or len(data) != before.st_size:
        raise ValueError("The image changed while it was being read.")
    return data


def decode_image(data, expected_format):
    from PIL import Image, ImageOps

    with Image.open(BytesIO(data), formats=sorted(set(IMAGE_FORMATS.values()))) as image:
        if image.format != expected_format:
            raise ValueError(f"The image contains {image.format} data under a different extension.")
        if image.width * image.height > MAX_PIXELS:
            raise ValueError("The image exceeds the 20-megapixel lab limit.")
        return ImageOps.exif_transpose(image).convert("RGBA")


def describe(image):
    from PIL import Image

    reduced = image.resize((32, 32), Image.Resampling.BILINEAR)
    alpha = reduced.getchannel("A").histogram()
    transparent = sum(alpha[:192]) / 1024
    backing = Image.new("RGBA", reduced.size, "#465266")
    backing.alpha_composite(reduced)
    rgb = backing.convert("RGB")
    raster = rgb.resize((12, 12), Image.Resampling.BILINEAR).tobytes()
    pixels = zip(raster[::3], raster[1::3], raster[2::3])
    mask = list(reduced.getchannel("A").resize((12, 12), Image.Resampling.BILINEAR).tobytes())
    counts = Counter((r // 64) * 16 + (g // 64) * 4 + b // 64 for (r, g, b), opacity in zip(pixels, mask) if opacity >= 80)
    foreground = max(1, counts.total())
    thumb = image.copy()
    thumb.thumbnail((160, 112))
    encoded = BytesIO()
    thumb.save(encoded, "WEBP", quality=78)
    return {
        "width": image.width, "height": image.height, "transparency": transparent,
        "pixels": list(raster),
        "mask": mask,
        "palette": [round(counts[index] / foreground, 5) for index in range(64)],
        "thumbnail": b64encode(encoded.getvalue()).decode("ascii"),
    }


def observe(inventory, cache, encoder=None):
    """Re-hash bytes to detect replacements, then reuse the content-keyed analysis."""
    root = Path(inventory.root)
    candidates = [(path, file) for path, file in inventory.files.items()
                  if PurePosixPath(path).suffix.lower() in IMAGE_FORMATS]
    assets, skipped, notes = {}, {}, []
    counts = {"candidates": len(candidates), "decoded": 0, "cache_hits": 0, "model_runs": 0}
    if len(candidates) > MAX_IMAGES:
        notes.append(f"Only the first {MAX_IMAGES} raster candidates were sampled. Choose a smaller source folder.")
    if inventory.limited:
        notes.append(inventory.scan_limit)
    try:
        from PIL import Image
    except ImportError:
        return assets, skipped, counts, [*notes, "Pillow is unavailable. Only folder metadata was inspected."]

    deadline = monotonic() + MAX_SECONDS
    for path, file in candidates[:MAX_IMAGES]:
        if monotonic() >= deadline:
            notes.append(f"Visual analysis stopped at its {MAX_SECONDS}-second budget.")
            break
        try:
            data = image_bytes(root / path, file)
            digest = sha256(data).hexdigest()
            fmt = IMAGE_FORMATS[PurePosixPath(path).suffix.lower()]
            entry = cache.get(digest)
            image = None
            if entry is None:
                image = decode_image(data, fmt)
                entry = {"format": fmt, "features": describe(image)}
                cache[digest] = entry
                counts["decoded"] += 1
            elif entry["format"] != fmt:
                raise ValueError(f"The image contains {entry['format']} data under a different extension.")
            else:
                counts["cache_hits"] += 1
            if encoder and entry.get("encoder") != encoder.identifier:
                try:
                    if image is None:
                        image = decode_image(data, fmt)
                    entry["embedding"] = encoder.embed(image)
                    entry["encoder"] = encoder.identifier
                    counts["model_runs"] += 1
                except (OSError, ValueError, RuntimeError) as error:
                    notes.append(f"Optional encoder stopped. Pixel analysis continues. {error}")
                    encoder = None
            assets[path] = {"digest": digest, "mtime_ns": file.mtime_ns, "features": entry["features"],
                            "embedding": entry.get("embedding") if encoder and entry.get("encoder") == encoder.identifier else None}
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            skipped[path] = str(error)
    return assets, skipped, counts, notes
