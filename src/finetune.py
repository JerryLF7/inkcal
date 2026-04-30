"""
Fine-tune the SigLIP2 food classifier on user-labeled data.

Collects records with user_label from data/*.json, downloads images,
trains a binary classifier, saves to data/finetuned-model/.
"""

import io
import json
import logging
import os
from pathlib import Path

import torch
from datasets import Dataset
from PIL import Image
from transformers import (
    AutoImageProcessor,
    AutoModelForImageClassification,
    Trainer,
    TrainingArguments,
)

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MODEL_NAME = "prithivMLmods/Food-or-Not-SigLIP2"
OUTPUT_DIR = DATA_DIR / "finetuned-model"
EXPORT_DIR = DATA_DIR / "training"
MIN_SAMPLES = 4  # Minimum before fine-tuning


def collect_labeled_data(immich_client=None):
    """Scan data/*.json for labeled records, return [(PIL.Image, label_str), ...]."""
    samples = []
    json_files = sorted(DATA_DIR.glob("*.json"))
    logger.info("Scanning %d date files for labeled data...", len(json_files))

    for f in json_files:
        try:
            records = json.loads(f.read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            continue
        for r in records:
            label = r.get("user_label")
            if not label:
                continue
            try:
                img = _get_image(r, immich_client)
                if img:
                    samples.append((img, label))  # label = "correct" | "wrong"
            except Exception as e:
                logger.warning("Failed to get image for %s: %s", r.get("asset_id", "?"), e)

    logger.info("Collected %d labeled samples", len(samples))
    return samples


def _get_image(record, immich_client):
    """Get PIL Image for a record. Prefer replacement_image, then Immich thumbnail."""
    if record.get("replacement_image"):
        path = Path(record["replacement_image"])
        if path.exists():
            return Image.open(path).convert("RGB")

    if record.get("thumbnail_url") and immich_client:
        asset_id = record.get("asset_id")
        if asset_id:
            img_bytes = immich_client.download_thumbnail(asset_id)
            return Image.open(io.BytesIO(img_bytes)).convert("RGB")

    return None


def export_dataset(samples):
    """Save labeled images to data/training/{food,not-food}/ for inspection."""
    food_dir = EXPORT_DIR / "food"
    not_food_dir = EXPORT_DIR / "not-food"
    food_dir.mkdir(parents=True, exist_ok=True)
    not_food_dir.mkdir(parents=True, exist_ok=True)

    # Clear previous export
    for d in [food_dir, not_food_dir]:
        for f in d.glob("*"):
            f.unlink()

    for i, (img, label) in enumerate(samples):
        target = "not-food" if label == "wrong" else "food"
        out_dir = not_food_dir if label == "wrong" else food_dir
        img.save(out_dir / f"{i:04d}.jpg")

    logger.info("Exported %d samples to %s", len(samples), EXPORT_DIR)


def build_dataset(samples):
    """Convert [(PIL.Image, label_str), ...] to HuggingFace Dataset with train/test splits."""
    # Map "correct" -> 0 (food), "wrong" -> 1 (not-food)
    data = {
        "image": [s[0] for s in samples],
        "label": [0 if s[1] == "correct" else 1 for s in samples],
    }
    dataset = Dataset.from_dict(data)
    if len(dataset) >= 6:
        split = dataset.train_test_split(test_size=0.2, seed=42)
        return split["train"], split["test"]
    return dataset, None


def finetune(samples, output_dir=None):
    """Fine-tune SigLIP2 on labeled samples and save model."""
    if len(samples) < MIN_SAMPLES:
        logger.warning("Need at least %d labeled samples, have %d. Skipping.", MIN_SAMPLES, len(samples))
        return None

    out = Path(output_dir or OUTPUT_DIR)
    train_ds, eval_ds = build_dataset(samples)
    logger.info("Train: %d, Eval: %d", len(train_ds), len(eval_ds) if eval_ds else 0)

    processor = AutoImageProcessor.from_pretrained(MODEL_NAME)
    model = AutoModelForImageClassification.from_pretrained(
        MODEL_NAME,
        id2label={0: "food", 1: "not-food"},
        label2id={"food": 0, "not-food": 1},
        ignore_mismatched_sizes=True,
    )

    def transform(batch):
        inputs = processor([img.convert("RGB") for img in batch["image"]], return_tensors="pt")
        inputs["labels"] = batch["label"]
        return inputs

    train_ds.set_transform(transform)
    if eval_ds:
        eval_ds.set_transform(transform)

    training_args = TrainingArguments(
        output_dir=str(out / "checkpoints"),
        num_train_epochs=3,
        per_device_train_batch_size=2,
        per_device_eval_batch_size=2,
        learning_rate=2e-5,
        weight_decay=0.01,
        logging_steps=5,
        eval_strategy="epoch" if eval_ds else "no",
        save_strategy="epoch",
        load_best_model_at_end=bool(eval_ds),
        remove_unused_columns=False,
        report_to="none",
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=eval_ds,
    )

    logger.info("Starting fine-tuning (this may take a few minutes)...")
    trainer.train()

    # Save model + processor
    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(out))
    processor.save_pretrained(str(out))
    logger.info("Fine-tuned model saved to %s", out)
    return out
