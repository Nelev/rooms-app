"""Deterministic metrics of the Room Analyst: the features of a predicted RoomSpec against a labeled one.

A predicted feature matches a labeled one of the same type on the same wall when their spans along the wall overlap; pairs are
matched one to one, closest first. Positions are in meters from each wall's start corner, each spec with its own dimensions, so a
wrong room size shows up as position error.
"""

from dataclasses import dataclass, field
from math import hypot

from app.schemas.room import Feature, FeatureType, RoomSpec


@dataclass
class FeatureScores:
    """One feature type: matched (true positive), predicted only (false positive), labeled only (false negative), and the position
    error of each match in cm."""

    tp: int = 0
    fp: int = 0
    fn: int = 0
    errors_cm: list[float] = field(default_factory=list)

    @property
    def precision(self) -> float:
        """1 when nothing was predicted (no false positive)."""
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        """1 when nothing was labeled (nothing missed)."""
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0


def _center(spec: RoomSpec, f: Feature) -> float:
    """The feature's center, in meters along its wall."""
    return f.offset * (spec.dimensions.width if f.wall in "AC" else spec.dimensions.length)


def position_error_cm(predicted: RoomSpec, p: Feature, labeled: RoomSpec, label: Feature) -> float:
    """The distance between the two features' bottom centers on the wall (along the wall and in sill height), in cm."""
    return 100 * hypot(_center(predicted, p) - _center(labeled, label), p.sill_height - label.sill_height)


def feature_scores(predicted: RoomSpec, labeled: RoomSpec) -> dict[FeatureType, FeatureScores]:
    """Precision, recall and position errors per feature type found in either spec."""
    scores: dict[FeatureType, FeatureScores] = {}
    for kind in sorted({f.type for f in predicted.features + labeled.features}):
        preds = [f for f in predicted.features if f.type == kind]
        labels = [f for f in labeled.features if f.type == kind]
        pairs = sorted(
            (position_error_cm(predicted, p, labeled, label), i, j)
            for (i, p) in enumerate(preds)
            for (j, label) in enumerate(labels)
            if p.wall == label.wall and abs(_center(predicted, p) - _center(labeled, label)) < (p.width + label.width) / 2
        )
        used_p: set[int] = set()
        used_l: set[int] = set()
        errors = []
        for error, i, j in pairs:
            if i not in used_p and j not in used_l:
                used_p.add(i)
                used_l.add(j)
                errors.append(error)
        scores[kind] = FeatureScores(len(errors), len(preds) - len(errors), len(labels) - len(errors), errors)
    return scores
