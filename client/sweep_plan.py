"""Shared deterministic sweep planner for the guided TUI and the Windows GUI.

A sweep plan is a bounded, reproducible encoder × preset × native-quality grid
over the frozen EncodingDB Test Suite v1 clips. The planner is pure: given the
same candidate encoder names and the same preset configuration it always emits
the same ordered task list. Hardware usability is decided by the caller and
passed in as ``is_usable`` so this module never probes devices itself.

Rate-control correctness rules (mirrored by ffmpeg._build_rate_control_args):
- Software encoders (libx264, libx265, libsvtav1, libaom-av1, libvpx-vp9,
  libopenh264) are CRF-driven and receive a native CRF value only.
- NVENC receives its native CQ quality value, QSV its native ICQ
  (``-global_quality``) value, and AMF/VAAPI/V4L2/OMX their native QP value.
  These are passed on each encoder's own scale; the planner never claims the
  numbers are equivalent across families.
- VideoToolbox is bitrate-driven and only ever receives explicit native bitrate
  values in kbps. A CRF/CQ/QP number is never routed to it.
"""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .encoders import (
    HARDWARE_ENCODERS,
    SOFTWARE_ENCODERS_ORDER,
    enumerate_supported_presets_for_encoder,
    is_hardware_encoder_name,
    sort_presets_by_speed_desc,
)
from .recipe import infer_default_rate_control_mode

SWEEP_MODES: Tuple[str, ...] = ("small", "medium", "large", "full")
PLANNER_VERSION = 1
# Manifest keys that persist a sweep plan; a resumed campaign must reproduce them
# verbatim because the journal rejects any manifest drift.
MANIFEST_KEYS = ("sweepMode", "plannerVersion", "clipPolicy", "sweepEncoders", "sweepSkipped")

# Clip coverage per mode over the frozen seven-clip suite. The suite itself is
# never modified; a mode only decides how much of it the sweep covers, and the
# summary shown to the user must state that coverage honestly.
CLIP_POLICY_QUICK = "quick"        # the canonical quick clip only
CLIP_POLICY_CLASSES = "classes"    # one clip per required content class; the frozen
                                   # suite declares seven 1:1 classes, so this equals
                                   # full clip coverage and the modes differ by sweep
                                   # breadth only
CLIP_POLICY_SUITE = "suite"        # all seven frozen clips
CLIP_POLICY_BY_MODE: Dict[str, str] = {
    "small": CLIP_POLICY_QUICK,
    "medium": CLIP_POLICY_CLASSES,
    "large": CLIP_POLICY_SUITE,
    "full": CLIP_POLICY_SUITE,
}

# Native quality values for cq/icq/qp families when presets.json does not
# override them. Values stay on each encoder's own native scale.
DEFAULT_NATIVE_QUALITY_VALUES: Dict[str, List[int]] = {
    "small": [23],
    "medium": [20, 27],
    "large": [18, 23, 29],
    "full": [12, 14, 16, 18, 20, 22, 24, 26, 28, 30],
}

# Explicit native VideoToolbox bitrate ladder (kbps) when presets.json does not
# override it. VideoToolbox has no portable CRF; these are the only quality
# knobs the planner may apply to it.
DEFAULT_VIDEOTOOLBOX_BITRATES_KBPS: Dict[str, List[int]] = {
    "small": [6000],
    "medium": [3000, 10000],
    "large": [2000, 6000, 15000],
    "full": [1000, 2000, 4000, 6000, 9000, 13000, 18000],
}

DEFAULT_CRF_VALUES: Dict[str, List[int]] = {
    "small": [24],
    "medium": [22, 26],
    "large": [20, 24, 28],
    "full": [12, 14, 16, 18, 20, 22, 24, 26, 28, 30],
}

_FAMILY_ORDER: Tuple[str, ...] = ("h264", "hevc", "av1", "vp9")


@dataclass(frozen=True)
class SweepPlan:
    mode: str
    planner_version: int
    clip_policy: str
    encoders: Tuple[str, ...]
    skipped: Tuple[Tuple[str, str], ...]
    steps: Tuple[Dict[str, Any], ...]
    approx_runtime: Optional[float] = None

    @property
    def recipe_count(self) -> int:
        return len(self.steps)

    def is_empty(self) -> bool:
        return not self.steps or not self.encoders

    def estimated_encodes(self, *, warmup_runs: int, minimum_measured_runs: int, max_adaptive_repeats: int) -> Tuple[int, int]:
        """(minimum, maximum) protocol attempts for this plan's recipes.

        Each recipe always performs every warmup plus at least the minimum
        measured repetitions; adaptive repeats extend it up to the maximum.
        The planner never trims repetitions to fit a budget.
        """
        per_recipe_min = int(warmup_runs) + int(minimum_measured_runs)
        per_recipe_max = per_recipe_min + int(max_adaptive_repeats)
        return self.recipe_count * per_recipe_min, self.recipe_count * per_recipe_max

    def manifest_metadata(self) -> Dict[str, Any]:
        return {
            "sweepMode": self.mode,
            "plannerVersion": self.planner_version,
            "clipPolicy": self.clip_policy,
            "sweepEncoders": list(self.encoders),
            "sweepSkipped": [{"encoder": name, "reason": reason} for name, reason in self.skipped],
        }


def native_quality_label(encoder: str) -> str:
    """Human name of the encoder family's native quality control."""
    mode = infer_default_rate_control_mode(str(encoder or ""))
    return {
        "crf": "CRF",
        "cq": "CQ",
        "icq": "ICQ (global quality)",
        "qp": "QP",
        "cqp": "CQP",
        "vbr": "bitrate (kbps)",
    }.get(mode, "quality")


def is_bitrate_driven(encoder: str) -> bool:
    return infer_default_rate_control_mode(str(encoder or "")) == "vbr"


def canonical_software_encoders() -> List[str]:
    ordered: List[str] = []
    for family in _FAMILY_ORDER:
        for encoder in SOFTWARE_ENCODERS_ORDER.get(family, []):
            if encoder not in ordered:
                ordered.append(encoder)
    return ordered


def canonical_hardware_encoders() -> List[str]:
    ordered: List[str] = []
    for family in _FAMILY_ORDER:
        for encoder, _label in HARDWARE_ENCODERS.get(family, []):
            if encoder not in ordered:
                ordered.append(encoder)
    return ordered


def select_sweep_encoders(
    candidates: Sequence[str],
    *,
    is_usable: Optional[Callable[[str], bool]] = None,
) -> Tuple[List[str], List[Tuple[str, str]]]:
    """Order candidate encoders canonically and drop unusable hardware.

    ``is_usable`` is consulted for hardware-named encoders only (it runs real
    device probes); software encoders from the supported tables are accepted
    whenever they are present in ``candidates``.
    """
    present = {str(name or "").strip().lower() for name in candidates}
    usable: List[str] = []
    skipped: List[Tuple[str, str]] = []
    for family in _FAMILY_ORDER:
        for encoder in SOFTWARE_ENCODERS_ORDER.get(family, []):
            if encoder in present:
                usable.append(encoder)
        for encoder, label in HARDWARE_ENCODERS.get(family, []):
            if encoder not in present:
                continue
            if is_usable is None or is_usable(encoder):
                usable.append(encoder)
            else:
                skipped.append((encoder, f"{label} detected but not usable on this machine"))
    return usable, skipped


def _preset_picks(encoder: str, mode: str) -> List[str]:
    supported = enumerate_supported_presets_for_encoder(encoder)
    ordered = sort_presets_by_speed_desc(encoder, list(supported))
    if not ordered:
        return []
    if mode in ("small", "medium"):
        return [ordered[(len(ordered) - 1) // 2]]
    if mode == "large":
        last = len(ordered) - 1
        picks: List[str] = []
        for index in (last // 4, last // 2, (3 * last) // 4):
            if ordered[index] not in picks:
                picks.append(ordered[index])
        return picks
    return list(ordered)


def _quality_values(mode: str, encoder: str, presets_cfg: Dict[str, Any]) -> List[Any]:
    sweep_cfg = presets_cfg.get("sweepPlans", {}) if isinstance(presets_cfg, dict) else {}
    mode_cfg = sweep_cfg.get(mode, {}) if isinstance(sweep_cfg.get(mode, {}), dict) else {}
    rc_mode = infer_default_rate_control_mode(encoder)
    if rc_mode == "crf":
        values = mode_cfg.get("crfValues")
        if not values:
            values = DEFAULT_CRF_VALUES.get(mode, [24])
        return [int(v) for v in values]
    if rc_mode == "vbr":
        values = mode_cfg.get("bitrateKbpsValues")
        if not values:
            values = DEFAULT_VIDEOTOOLBOX_BITRATES_KBPS.get(mode, [6000])
        return [int(v) for v in values]
    values = mode_cfg.get("nativeQualityValues")
    if not values:
        values = DEFAULT_NATIVE_QUALITY_VALUES.get(mode, [23])
    return [int(v) for v in values]


def _rate_control_for(encoder: str, quality: Any) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    """Return the task-level (crf, rateControl) pair for one native point.

    CRF families keep the legacy ``crf`` field so recipe identity matches
    existing single-recipe runs; every other family gets an explicit native
    rate-control descriptor. VideoToolbox receives an explicit bitrate target
    only, never a quality number.
    """
    rc_mode = infer_default_rate_control_mode(encoder)
    if rc_mode == "crf":
        return int(quality), None
    if rc_mode == "vbr":
        return None, {"mode": "vbr", "targetBitrateKbps": int(quality)}
    return None, {"mode": rc_mode, "qualityValue": int(quality)}


def _encoders_for_mode(mode: str, usable: Sequence[str]) -> List[str]:
    if mode != "small":
        return list(usable)
    picks: List[str] = []
    for family in _FAMILY_ORDER:
        family_software = [e for e in SOFTWARE_ENCODERS_ORDER.get(family, []) if e in usable]
        family_hardware = [e for e, _ in HARDWARE_ENCODERS.get(family, []) if e in usable]
        if family_software:
            picks.append(family_software[0])
        if family_hardware:
            picks.append(family_hardware[0])
        if not family_software and not family_hardware:
            continue
    return picks


def plan_sweep(
    mode: str,
    candidates: Sequence[str],
    *,
    presets_cfg: Optional[Dict[str, Any]] = None,
    is_usable: Optional[Callable[[str], bool]] = None,
) -> SweepPlan:
    mode_key = str(mode or "").strip().lower()
    if mode_key not in SWEEP_MODES:
        raise ValueError(f"Unsupported sweep mode: {mode}")
    usable, skipped = select_sweep_encoders(candidates, is_usable=is_usable)
    encoders = _encoders_for_mode(mode_key, usable)
    presets_cfg = presets_cfg if isinstance(presets_cfg, dict) else {}
    steps: List[Dict[str, Any]] = []
    for encoder in encoders:
        for preset in _preset_picks(encoder, mode_key):
            for quality in _quality_values(mode_key, encoder, presets_cfg):
                crf_value, rate_control = _rate_control_for(encoder, quality)
                steps.append({
                    "encoder": encoder,
                    "preset": preset,
                    "crf": crf_value,
                    "rateControl": rate_control,
                })
    return SweepPlan(
        mode=mode_key,
        planner_version=PLANNER_VERSION,
        clip_policy=CLIP_POLICY_BY_MODE[mode_key],
        encoders=tuple(encoders),
        skipped=tuple(skipped),
        steps=tuple(steps),
    )
