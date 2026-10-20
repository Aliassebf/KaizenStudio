from __future__ import annotations

import json
import hashlib
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .video import open_video_capture, orient_video_frame

FEATURE_VERSION = "hog-flow-64-v1"
MIN_TRAIN_EXAMPLES_PER_OPERATION = 2
MIN_SUGGESTION_CONFIDENCE = 0.55
HOG = cv2.HOGDescriptor((64, 64), (16, 16), (8, 8), (8, 8), 9)


@dataclass(frozen=True)
class OperationSample:
    station_id: int
    video_path: str
    roi: str | None
    start_s: float
    end_s: float
    operation_id: int
    operation: str


class OperationLearningError(ValueError):
    pass


def _video_feature(
    video_path: str,
    start_s: float,
    end_s: float,
    roi: tuple[float, float, float, float]
    | tuple[tuple[float, float, float, float], ...]
    | None,
) -> np.ndarray:
    capture = open_video_capture(video_path)
    if not capture.isOpened():
        capture.release()
        raise OperationLearningError(f"Impossible de lire la vidéo : {Path(video_path).name}.")

    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if fps <= 0 or frame_count <= 0:
        capture.release()
        raise OperationLearningError(f"La vidéo {Path(video_path).name} ne fournit pas de fréquence valide.")

    duration_s = frame_count / fps
    start_s = max(0.0, min(start_s, duration_s))
    end_s = max(start_s, min(end_s, duration_s))
    if end_s <= start_s:
        capture.release()
        raise OperationLearningError("Une annotation a une durée nulle ou dépasse la vidéo.")

    frames: list[np.ndarray] = []
    try:
        for fraction in (0.1, 0.3, 0.5, 0.7, 0.9):
            time_s = start_s + (end_s - start_s) * fraction
            capture.set(cv2.CAP_PROP_POS_MSEC, time_s * 1000)
            ok, frame = capture.read()
            if not ok:
                raise OperationLearningError(
                    f"Impossible d'extraire une image de {Path(video_path).name} à {time_s:.1f} s."
                )
            frame = orient_video_frame(capture, frame)

            height, width = frame.shape[:2]
            if roi is not None and isinstance(roi[0], tuple):
                rectangles = roi
                left = min(max(0, round(x * width)) for x, _, _, _ in rectangles)
                top = min(max(0, round(y * height)) for _, y, _, _ in rectangles)
                right = max(min(width, round((x + roi_width) * width)) for x, _, roi_width, _ in rectangles)
                bottom = max(min(height, round((y + roi_height) * height)) for _, y, _, roi_height in rectangles)
                frame = frame[top:bottom, left:right]
                mask = np.zeros(frame.shape[:2], dtype=np.uint8)
                for x, y, roi_width, roi_height in rectangles:
                    x0 = max(0, round(x * width) - left)
                    y0 = max(0, round(y * height) - top)
                    x1 = min(frame.shape[1], round((x + roi_width) * width) - left)
                    y1 = min(frame.shape[0], round((y + roi_height) * height) - top)
                    mask[y0:y1, x0:x1] = 255
                frame[mask == 0] = 0
            elif roi is not None:
                x, y, roi_width, roi_height = roi
                left = min(width - 1, max(0, round(x * width)))
                top = min(height - 1, max(0, round(y * height)))
                right = min(width, max(left + 1, round((x + roi_width) * width)))
                bottom = min(height, max(top + 1, round((y + roi_height) * height)))
                frame = frame[top:bottom, left:right]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            frames.append(cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA))
    finally:
        capture.release()

    hog_features = np.asarray([HOG.compute(frame).reshape(-1) for frame in frames], dtype=np.float32)
    mean_hog = np.mean(hog_features, axis=0)
    variation_hog = np.std(hog_features, axis=0)
    difference_hog = np.asarray(
        [HOG.compute(cv2.absdiff(first, second)).reshape(-1) for first, second in zip(frames, frames[1:])],
        dtype=np.float32,
    )
    mean_difference_hog = np.mean(difference_hog, axis=0) if difference_hog.size else np.zeros_like(mean_hog)

    flow_histograms: list[np.ndarray] = []
    for first, second in zip(frames, frames[1:]):
        flow = cv2.calcOpticalFlowFarneback(first, second, None, 0.5, 2, 12, 2, 5, 1.1, 0)
        magnitude, angle = cv2.cartToPolar(flow[..., 0], flow[..., 1], angleInDegrees=False)
        bins = np.floor(angle * (8 / (2 * math.pi))).astype(np.int32) % 8
        histogram = np.zeros((4, 4, 8), dtype=np.float32)
        for row in range(4):
            for column in range(4):
                y0, y1 = row * 16, (row + 1) * 16
                x0, x1 = column * 16, (column + 1) * 16
                histogram[row, column] = np.bincount(
                    bins[y0:y1, x0:x1].reshape(-1),
                    weights=magnitude[y0:y1, x0:x1].reshape(-1),
                    minlength=8,
                )
        flow_histograms.append(histogram.reshape(-1))
    mean_flow = np.mean(flow_histograms, axis=0) if flow_histograms else np.zeros(128, dtype=np.float32)

    feature = np.concatenate((mean_hog, variation_hog, mean_difference_hog, mean_flow)).astype(np.float32)
    norm = float(np.linalg.norm(feature))
    if norm <= 1e-8:
        raise OperationLearningError("Les images de l'annotation ne contiennent pas de signal exploitable.")
    return feature / norm


def _extract_samples(samples: list[OperationSample]) -> list[np.ndarray]:
    features: list[np.ndarray] = []
    for sample in samples:
        try:
            roi = None
            if sample.roi:
                from .motion import parse_roi

                try:
                    roi = parse_roi(sample.roi)
                except ValueError as error:
                    raise OperationLearningError(f"ROI invalide : {error}") from error
            features.append(_video_feature(sample.video_path, sample.start_s, sample.end_s, roi))
        except OperationLearningError as error:
            raise OperationLearningError(f"Annotation du poste {sample.station_id} : {error}") from error
        except cv2.error as error:
            raise OperationLearningError(
                f"Erreur OpenCV sur l'annotation du poste {sample.station_id} : {error}"
            ) from error
    return features


def train_operation_model(
    project_id: int,
    train_samples: list[OperationSample],
    validation_samples: list[OperationSample],
    model_path: Path,
    metadata_path: Path,
    training_signature: str,
) -> dict[str, Any]:
    counts: dict[int, int] = {}
    names: dict[int, str] = {}
    for sample in train_samples:
        counts[sample.operation_id] = counts.get(sample.operation_id, 0) + 1
        names[sample.operation_id] = sample.operation

    eligible_ids = sorted(
        operation_id
        for operation_id, count in counts.items()
        if count >= MIN_TRAIN_EXAMPLES_PER_OPERATION
    )
    if len(eligible_ids) < 2:
        raise OperationLearningError(
            "Il faut au moins deux opérations, avec deux annotations chacune dans les vidéos "
            "affectées à l'entraînement."
        )

    validation_operation_names = {sample.operation_id: sample.operation for sample in validation_samples}
    validation_untrained_operations = sorted(
        {
            operation_id: operation
            for operation_id, operation in validation_operation_names.items()
            if operation_id not in eligible_ids
        }.items()
    )
    train_samples = [sample for sample in train_samples if sample.operation_id in eligible_ids]
    validation_samples = [sample for sample in validation_samples if sample.operation_id in eligible_ids]
    if not validation_samples:
        raise OperationLearningError(
            "Ajoutez au moins une annotation d'une opération entraînée dans une vidéo affectée à la validation."
        )

    training_features = _extract_samples(train_samples)
    validation_features = _extract_samples(validation_samples)
    label_to_index = {operation_id: index for index, operation_id in enumerate(eligible_ids)}
    training_labels = np.asarray(
        [label_to_index[sample.operation_id] for sample in train_samples],
        dtype=np.int32,
    )
    training_matrix = np.vstack(training_features).astype(np.float32)
    validation_matrix = np.vstack(validation_features).astype(np.float32)
    try:
        svm = cv2.ml.SVM_create()
        svm.setType(cv2.ml.SVM_C_SVC)
        svm.setKernel(cv2.ml.SVM_LINEAR)
        svm.setC(2.0)
        if not svm.train(training_matrix, cv2.ml.ROW_SAMPLE, training_labels):
            raise OperationLearningError("OpenCV n'a pas pu entraîner le classifieur sur ces annotations.")
        raw_predictions = svm.predict(validation_matrix)[1].reshape(-1).astype(np.int32)
    except cv2.error as error:
        raise OperationLearningError(f"Erreur OpenCV pendant l'entraînement ou l'évaluation : {error}") from error
    expected_labels = np.asarray(
        [label_to_index[sample.operation_id] for sample in validation_samples],
        dtype=np.int32,
    )
    correct = raw_predictions == expected_labels
    centroids: dict[int, list[float]] = {}
    for operation_id in eligible_ids:
        class_features = training_matrix[training_labels == label_to_index[operation_id]]
        centroid = np.mean(class_features, axis=0)
        centroid_norm = float(np.linalg.norm(centroid))
        if centroid_norm <= 1e-8:
            raise OperationLearningError(f"Impossible de calculer le prototype de {names[operation_id]}.")
        centroids[operation_id] = (centroid / centroid_norm).tolist()
    per_operation: list[dict[str, Any]] = []
    for operation_id in eligible_ids:
        label_index = label_to_index[operation_id]
        selected = expected_labels == label_index
        operation_predictions = raw_predictions == label_index
        true_positive = int(np.count_nonzero(selected & operation_predictions))
        precision_denominator = int(np.count_nonzero(operation_predictions))
        recall_denominator = int(np.count_nonzero(selected))
        per_operation.append(
            {
                "operation_id": operation_id,
                "operation": names[operation_id],
                "validation": recall_denominator,
                "precision_pct": round(100 * true_positive / precision_denominator, 1)
                if precision_denominator
                else 0.0,
                "recall_pct": round(100 * true_positive / recall_denominator, 1)
                if recall_denominator
                else 0.0,
            }
        )

    metadata = {
        "version": 1,
        "feature_version": FEATURE_VERSION,
        "project_id": project_id,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_signature": training_signature,
        "labels": [
            {"index": label_to_index[operation_id], "operation_id": operation_id, "operation": names[operation_id]}
            for operation_id in eligible_ids
        ],
        "training_examples": len(train_samples),
        "training_counts": [
            {"operation_id": operation_id, "operation": names[operation_id], "count": counts[operation_id]}
            for operation_id in eligible_ids
        ],
        "excluded_operations": [
            {"operation_id": operation_id, "operation": names[operation_id], "count": count}
            for operation_id, count in sorted(counts.items())
            if operation_id not in eligible_ids
        ],
        "validation_untrained_operations": [
            {"operation_id": operation_id, "operation": operation}
            for operation_id, operation in validation_untrained_operations
        ],
        "centroids": {str(operation_id): centroids[operation_id] for operation_id in eligible_ids},
        "validation": {
            "examples": len(validation_samples),
            "correct": int(np.count_nonzero(correct)),
            "accuracy_pct": round(100 * float(np.mean(correct)), 1),
            "per_operation": per_operation,
        },
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_model_path = model_path.with_name(f"{model_path.stem}.tmp.yml")
    temporary_metadata_path = metadata_path.with_name(f"{metadata_path.stem}.tmp.json")
    try:
        svm.save(str(temporary_model_path))
        metadata["model_sha256"] = hashlib.sha256(temporary_model_path.read_bytes()).hexdigest()
        temporary_metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary_model_path, model_path)
        os.replace(temporary_metadata_path, metadata_path)
    except OSError:
        temporary_model_path.unlink(missing_ok=True)
        temporary_metadata_path.unlink(missing_ok=True)
        raise
    return metadata


def load_operation_model(model_path: Path, metadata_path: Path) -> tuple[Any, dict[str, Any]]:
    if not model_path.is_file() or not metadata_path.is_file():
        raise OperationLearningError("Le modèle local est absent. Entraînez-le avant de demander des suggestions.")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("version") != 1 or metadata.get("feature_version") != FEATURE_VERSION:
        raise OperationLearningError("Le format du modèle n'est pas compatible. Entraînez-le à nouveau.")
    try:
        digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
    except OSError as error:
        raise OperationLearningError(f"Impossible de lire le fichier du modèle : {error}") from error
    if metadata.get("model_sha256") != digest:
        raise OperationLearningError("Le fichier du modèle ne correspond pas à ses métadonnées.")
    try:
        svm = cv2.ml.SVM_load(str(model_path))
    except cv2.error as error:
        raise OperationLearningError(f"Le fichier du modèle OpenCV est illisible : {error}") from error
    if svm.empty():
        raise OperationLearningError("Le fichier du modèle est vide ou illisible. Entraînez-le à nouveau.")
    return svm, metadata


def predict_operation(
    svm: Any,
    metadata: dict[str, Any],
    video_path: str,
    start_s: float,
    end_s: float,
    roi: str | None,
) -> dict[str, Any]:
    parsed_roi = None
    if roi:
        from .motion import parse_roi

        try:
            parsed_roi = parse_roi(roi)
        except ValueError as error:
            raise OperationLearningError(f"ROI invalide : {error}") from error
    try:
        feature = _video_feature(video_path, start_s, end_s, parsed_roi)
    except cv2.error as error:
        raise OperationLearningError(f"Erreur OpenCV pendant l'extraction de la phase : {error}") from error
    try:
        index = int(round(float(svm.predict(feature.reshape(1, -1))[1][0, 0])))
    except cv2.error as error:
        raise OperationLearningError(f"OpenCV n'a pas pu classer cette phase : {error}") from error
    label = next((item for item in metadata["labels"] if item["index"] == index), None)
    if label is None:
        raise OperationLearningError("Le modèle renvoie une classe absente de son référentiel.")

    similarities = {
        int(operation_id): float(np.dot(feature, np.asarray(centroid, dtype=np.float32)))
        for operation_id, centroid in metadata["centroids"].items()
    }
    predicted_similarity = similarities[label["operation_id"]]
    next_similarity = max(
        score for operation_id, score in similarities.items() if operation_id != label["operation_id"]
    )
    margin_score = min(1.0, max(0.0, (predicted_similarity - next_similarity) / 0.15))
    confidence = round(min(1.0, max(0.0, predicted_similarity)) * margin_score, 3)
    accepted = confidence >= MIN_SUGGESTION_CONFIDENCE
    return {
        "operation_id": label["operation_id"] if accepted else None,
        "operation": label["operation"] if accepted else "Autre / incertain",
        "confidence": confidence,
        "accepted": accepted,
    }
