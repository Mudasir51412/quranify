"""One-time, local conversion of the Quran checkpoint for faster GPU inference."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=settings.optimized_model_dir)
    args = parser.parse_args()
    target = Path(args.output).resolve()
    if not target.is_relative_to(ROOT):
        raise SystemExit("Keep the converted model inside this project")
    if target.exists():
        raise SystemExit(f"Output already exists; refusing to overwrite: {target}")
    from ctranslate2.converters import TransformersConverter
    from transformers import WhisperProcessor
    converter = TransformersConverter(
        settings.model_id, copy_files=["preprocessor_config.json"])
    converter.convert(str(target), quantization="float16")
    processor = WhisperProcessor.from_pretrained(settings.model_id)
    processor.tokenizer.backend_tokenizer.save(str(target / "tokenizer.json"))
    # Auto-selection ignores a conversion until its completion marker exists.
    (target / ".ready").write_text(settings.model_id, encoding="utf-8")
    print(f"Live model prepared: {target}", flush=True)


if __name__ == "__main__":
    main()
