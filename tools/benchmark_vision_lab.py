"""Measure the authorized lab sample in a fresh Linux process per backend."""

import argparse
from hashlib import file_digest
import json
from pathlib import Path
import resource
import shutil
import statistics
import subprocess
import tempfile
from time import perf_counter

from journey_planner.catalog import scan_folder
from journey_vision.demo import CONCEPT, ICON, PORTRAIT, WALLPAPER, make_sample
from journey_vision.embedding import ClipEncoder
from journey_vision.observe import observe
from journey_vision.steward import pixel_distance


class MobileNetFeatures:
    identifier = "mobilenetv2-12-pool:torchvision-onnx"

    def __init__(self, path):
        import numpy as np
        import onnx
        import onnxruntime as ort

        with Path(path).open("rb") as stream:
            if file_digest(stream, "sha256").hexdigest() != "c0c3f76d93fa3fd6580652a45618618a220fced18babf65774ed169de0432ad5":
                raise ValueError("Use the pinned ONNX Model Zoo MobileNetV2-12 file.")
        model = onnx.load(path, load_external_data=False)
        pool = model.graph.node[-1].input[0]
        del model.graph.output[:]
        model.graph.output.append(onnx.helper.make_tensor_value_info(pool, onnx.TensorProto.FLOAT, [None, 1280]))
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(model.SerializeToString(), options, providers=["CPUExecutionProvider"])
        self.output = pool
        self.np = np

    def embed(self, image):
        from PIL import Image, ImageOps

        backing = Image.new("RGBA", image.size, "#465266")
        backing.alpha_composite(image)
        crop = ImageOps.fit(backing.convert("RGB"), (224, 224), method=Image.Resampling.BILINEAR)
        pixels = self.np.asarray(crop, dtype=self.np.float32) / 255
        pixels -= self.np.array([0.485, 0.456, 0.406], dtype=self.np.float32)
        pixels /= self.np.array([0.229, 0.224, 0.225], dtype=self.np.float32)
        vector = self.session.run([self.output], {"input": pixels.transpose(2, 0, 1)[None]})[0][0]
        return (vector / self.np.linalg.norm(vector)).tolist()


def nearest_scores(assets, truth, encoder):
    hits, purpose_hits, identity_hits, identity_total = 0, 0, 0, 0

    def distance(left, right):
        if encoder:
            return 1 - sum(x * y for x, y in zip(left["embedding"], right["embedding"]))
        return pixel_distance(left["features"], right["features"])

    for path, item in assets.items():
        nearest = min((name for name in assets if name != path), key=lambda name: distance(item, assets[name]))
        hits += truth[path]["series"] == truth[nearest]["series"]
        purpose_hits += truth[path]["purpose"] == truth[nearest]["purpose"]
        if truth[path]["identity"]:
            identity_total += 1
            identity_hits += truth[path]["identity"] == truth[nearest]["identity"]
    return {"same_series_top1": hits, "same_purpose_top1": purpose_hits, "same_identity_top1": identity_hits,
            "identity_examples": identity_total, "images": len(assets)}


def embedding_trial(kind, root, truth, model):
    start = perf_counter()
    encoder = ClipEncoder(model) if kind == "clip" else MobileNetFeatures(model) if kind == "mobilenet" else None
    load_seconds = perf_counter() - start
    inventory = scan_folder(root)
    cache = {}
    start = perf_counter()
    assets, skipped, cold, notes = observe(inventory, cache, encoder)
    cold_seconds = perf_counter() - start
    start = perf_counter()
    _, _, warm, _ = observe(inventory, cache, encoder)
    warm_seconds = perf_counter() - start
    if len(assets) != len(truth) or skipped or notes or (encoder and cold["model_runs"] != len(truth)):
        raise RuntimeError(f"Incomplete benchmark: {skipped} {notes} {cold}")
    return {"setup_seconds": round(load_seconds, 4), "cold_seconds": round(cold_seconds, 4),
            "warm_seconds": round(warm_seconds, 4), "cold": cold, "warm": warm,
            "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
            **nearest_scores(assets, truth, encoder)}


def vision_language_trial(root, truth, cli, model, projector):
    labels = {"A": ICON, "B": WALLPAPER, "C": PORTRAIT, "D": CONCEPT}
    prompt = ("Choose the asset type. A: icon or badge. B: widescreen wallpaper artwork. "
              "C: illustrated character portrait. D: concept or layout sketch. Answer with only one letter.")
    options = [cli, "-m", model, "--mmproj", projector, "-ngl", "0", "--no-mmproj-offload",
               "-t", "4", "-tb", "4", "--no-warmup", "--temp", "0", "-n", "6",
               "--grammar", 'root ::= "A" | "B" | "C" | "D"', "-p", prompt]
    elapsed, predictions = [], []
    for path, expected in sorted(truth.items()):
        start = perf_counter()
        result = subprocess.run([*options, "--image", str(root / path)], capture_output=True, text=True,
                                check=True, timeout=60)
        elapsed.append(perf_counter() - start)
        output = result.stdout.strip()
        predictions.append({"expected": expected["purpose"], "prediction": labels.get(output, "unresolved")})
    return {"images": len(truth), "correct_forced_choice": sum(item["prediction"] == item["expected"] for item in predictions),
            "unresolved": sum(item["prediction"] == "unresolved" for item in predictions),
            "total_seconds": round(sum(elapsed), 2), "median_seconds_per_image": round(statistics.median(elapsed), 2),
            "peak_child_rss_mib": round(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024, 1),
            "predictions": predictions}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backend", choices=("pixels", "clip", "mobilenet", "smolvlm"))
    parser.add_argument("--model")
    parser.add_argument("--projector")
    parser.add_argument("--cli")
    args = parser.parse_args()
    if args.backend != "pixels" and not args.model:
        parser.error("This backend requires --model.")
    if args.backend == "smolvlm" and not (args.cli and args.projector):
        parser.error("SmolVLM requires --cli and --projector.")
    with tempfile.TemporaryDirectory(prefix="journey-vision-bench-") as temp:
        root, holdout = Path(temp) / "Sample", Path(temp) / "Holdout"
        truth = make_sample(root, holdout)
        for path in holdout.iterdir():
            shutil.copyfile(path, root / path.name)
        if args.backend == "smolvlm":
            result = vision_language_trial(root, truth, args.cli, args.model, args.projector)
        else:
            result = embedding_trial(args.backend, root, truth, args.model)
        print(json.dumps({"backend": args.backend, **result}, indent=2))


if __name__ == "__main__":
    main()
