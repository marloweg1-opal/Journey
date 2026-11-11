"""Opt-in CLIP image embeddings. The default visual lab has no model dependency."""

from hashlib import file_digest
from pathlib import Path


CLIP_SHA256 = "0ab0c1b3ace708e539633af1744d5a95247fe4e14d3e08ff197ef82a6cb9bd93"


class ClipEncoder:
    identifier = "clip-vit-b32-int8:0ab0c1b3"

    def __init__(self, filename):
        import numpy as np
        import onnxruntime as ort

        path = Path(filename)
        with path.open("rb") as model:
            if file_digest(model, "sha256").hexdigest() != CLIP_SHA256:
                raise ValueError("The file does not match the pinned CLIP image encoder.")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 4
        options.inter_op_num_threads = 1
        try:
            self.session = ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])
        except Exception as error:
            raise RuntimeError("The local CPU encoder could not start.") from error
        self.np = np
        self.mean = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
        self.std = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)

    def embed(self, image):
        from PIL import Image, ImageOps

        backing = Image.new("RGBA", image.size, "#465266")
        backing.alpha_composite(image)
        crop = ImageOps.fit(backing.convert("RGB"), (224, 224), method=Image.Resampling.BICUBIC)
        pixels = (self.np.asarray(crop, dtype=self.np.float32) / 255 - self.mean) / self.std
        try:
            vector = self.session.run(["image_embeds"], {"pixel_values": pixels.transpose(2, 0, 1)[None]})[0][0]
        except Exception as error:
            raise RuntimeError("The local encoder could not process this image.") from error
        length = self.np.linalg.norm(vector)
        if not self.np.isfinite(length) or not length:
            raise ValueError("The local encoder returned an invalid vector.")
        return (vector / length).tolist()
