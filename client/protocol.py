from __future__ import annotations

import hashlib
import json
import random
import secrets
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence


VALIDITY_VALID = "valid"
VALIDITY_SUSPECT = "suspect"
VALIDITY_INVALID = "invalid"


def _merge_validity_state(left: str, right: str) -> str:
    rank = {
        VALIDITY_VALID: 0,
        VALIDITY_SUSPECT: 1,
        VALIDITY_INVALID: 2,
    }
    return left if rank.get(left, 0) >= rank.get(right, 0) else right


def _stable_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except Exception:
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _stable_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


@dataclass(frozen=True)
class ValidityReason:
    code: str
    severity: str
    message: str
    metric: Optional[str] = None
    actual: Optional[Any] = None
    threshold: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ValidityResult:
    state: str = VALIDITY_VALID
    reasons: List[ValidityReason] = field(default_factory=list)

    def add_reason(
        self,
        *,
        severity: str,
        code: str,
        message: str,
        metric: Optional[str] = None,
        actual: Optional[Any] = None,
        threshold: Optional[Any] = None,
    ) -> None:
        self.state = _merge_validity_state(self.state, severity)
        self.reasons.append(
            ValidityReason(
                code=code,
                severity=severity,
                message=message,
                metric=metric,
                actual=actual,
                threshold=threshold,
            )
        )

    def merge(self, other: "ValidityResult") -> "ValidityResult":
        merged = ValidityResult(state=_merge_validity_state(self.state, other.state))
        merged.reasons = list(self.reasons) + list(other.reasons)
        return merged

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "reasons": [reason.to_dict() for reason in self.reasons],
        }


@dataclass(frozen=True)
class EnvironmentThresholds:
    invalid_background_cpu_pct: float = 75.0
    suspect_background_cpu_pct: float = 35.0
    invalid_background_gpu_pct: float = 75.0
    suspect_background_gpu_pct: float = 35.0
    invalid_memory_pressure_pct: float = 95.0
    suspect_memory_pressure_pct: float = 85.0
    invalid_free_memory_mb: float = 512.0
    suspect_free_memory_mb: float = 2048.0
    invalid_cpu_temp_c: float = 95.0
    suspect_cpu_temp_c: float = 85.0
    invalid_gpu_temp_c: float = 95.0
    suspect_gpu_temp_c: float = 85.0
    require_ac_power: bool = True
    invalidate_on_thermal_throttle: bool = True


@dataclass(frozen=True)
class StructuralTolerance:
    duration_ratio: float = 0.02
    frame_count_delta: int = 0
    fps_ratio: float = 0.01
    time_base_ratio: float = 0.01


@dataclass(frozen=True)
class ProtocolConfig:
    version: str
    warmup_runs: int
    minimum_measured_runs: int
    stability_threshold_ratio: float
    max_adaptive_repeats: int
    environment: EnvironmentThresholds = field(default_factory=EnvironmentThresholds)
    structural_tolerance: StructuralTolerance = field(default_factory=StructuralTolerance)

    @classmethod
    def for_version(
        cls,
        version: str,
        *,
        stability_threshold_ratio: float = 0.03,
        max_adaptive_repeats: int = 2,
        environment: Optional[EnvironmentThresholds] = None,
        structural_tolerance: Optional[StructuralTolerance] = None,
    ) -> "ProtocolConfig":
        normalized = str(version or "").strip()
        if normalized != "7.0":
            raise ValueError(f"Unsupported benchmark protocol version: {version}")
        return cls(
            version=normalized,
            warmup_runs=1,
            minimum_measured_runs=2,
            stability_threshold_ratio=float(stability_threshold_ratio),
            max_adaptive_repeats=int(max_adaptive_repeats),
            environment=environment or EnvironmentThresholds(),
            structural_tolerance=structural_tolerance or StructuralTolerance(),
        )


@dataclass(frozen=True)
class EnvironmentSnapshot:
    background_cpu_pct: Optional[float] = None
    background_gpu_pct: Optional[float] = None
    power_source: Optional[str] = None
    cpu_temp_c: Optional[float] = None
    gpu_temp_c: Optional[float] = None
    thermal_throttle: Optional[bool] = None
    free_memory_mb: Optional[float] = None
    memory_pressure_pct: Optional[float] = None
    gpu_power_w: Optional[float] = None
    gpu_memory_mb: Optional[float] = None
    cpu_frequency_mhz: Optional[float] = None
    selected_accelerator: Optional[str] = None
    accelerator_is_hardware: bool = False
    gpu_load_trustworthy: bool = True
    gpu_sample_count: int = 0
    telemetry_sources: Optional[str] = None
    telemetry_missing: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StructuralExpectation:
    duration_s: Optional[float] = None
    frame_count: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    codec: Optional[str] = None
    codec_tag: Optional[str] = None
    profile: Optional[str] = None
    level: Optional[str] = None
    pix_fmt: Optional[str] = None
    bit_depth: Optional[int] = None
    chroma_subsampling: Optional[str] = None
    color_range: Optional[str] = None
    color_space: Optional[str] = None
    color_transfer: Optional[str] = None
    color_primaries: Optional[str] = None
    container_format: Optional[str] = None
    gop_frames: Optional[int] = None
    keyint_min: Optional[int] = None
    max_b_frames: Optional[int] = None
    b_frame_reordering: Optional[bool] = None
    avg_frame_rate: Optional[float] = None
    time_base: Optional[float] = None
    single_video_stream: bool = True
    no_audio: bool = True


@dataclass(frozen=True)
class ArtifactProbe:
    decodable: bool
    duration_s: Optional[float] = None
    frame_count: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    codec: Optional[str] = None
    codec_tag: Optional[str] = None
    profile: Optional[str] = None
    level: Optional[str] = None
    pix_fmt: Optional[str] = None
    bit_depth: Optional[int] = None
    chroma_subsampling: Optional[str] = None
    color_range: Optional[str] = None
    color_space: Optional[str] = None
    color_transfer: Optional[str] = None
    color_primaries: Optional[str] = None
    container_format: Optional[str] = None
    keyframe_interval_min: Optional[int] = None
    keyframe_interval_max: Optional[int] = None
    max_b_frames: Optional[int] = None
    b_frame_reordering: Optional[bool] = None
    avg_frame_rate: Optional[float] = None
    time_base: Optional[float] = None
    video_stream_count: int = 1
    auxiliary_stream_count: int = 0
    has_audio: bool = False
    size_bytes: Optional[int] = None
    truncated: bool = False
    decode_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RecipeSpec:
    recipe_id: str
    expectation: StructuralExpectation
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EncodeTiming:
    start_monotonic_ns: int
    end_monotonic_ns: int
    elapsed_s: float
    source_frame_count: int
    encoded_frame_count: int
    source_fps: float
    encode_fps: float
    realtime_multiple: float
    ffmpeg_cpu_time_s: Optional[float] = None

    @classmethod
    def from_measurement(
        cls,
        *,
        start_monotonic_ns: int,
        end_monotonic_ns: int,
        source_frame_count: int,
        encoded_frame_count: int,
        source_fps: float,
        ffmpeg_cpu_time_s: Optional[float] = None,
    ) -> "EncodeTiming":
        start_ns = _stable_int(start_monotonic_ns)
        end_ns = _stable_int(end_monotonic_ns)
        source_frames = _stable_int(source_frame_count)
        encoded_frames = _stable_int(encoded_frame_count)
        source_rate = _stable_float(source_fps)
        cpu_time = _stable_float(ffmpeg_cpu_time_s)
        if start_ns is None or end_ns is None or end_ns <= start_ns:
            raise ValueError("encode timing requires increasing monotonic timestamps")
        if source_frames is None or source_frames <= 0:
            raise ValueError("encode timing requires a positive source frame count")
        if encoded_frames is None or encoded_frames <= 0:
            raise ValueError("encode timing requires a positive encoded frame count")
        if source_rate is None or source_rate <= 0:
            raise ValueError("encode timing requires a positive source fps")
        elapsed_s = (end_ns - start_ns) / 1_000_000_000.0
        if elapsed_s <= 0:
            raise ValueError("encode timing elapsed seconds must be positive")
        encode_fps = encoded_frames / elapsed_s
        realtime_multiple = encode_fps / source_rate
        return cls(
            start_monotonic_ns=start_ns,
            end_monotonic_ns=end_ns,
            elapsed_s=elapsed_s,
            source_frame_count=source_frames,
            encoded_frame_count=encoded_frames,
            source_fps=source_rate,
            encode_fps=encode_fps,
            realtime_multiple=realtime_multiple,
            ffmpeg_cpu_time_s=cpu_time,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EncodeOutcome:
    timing: EncodeTiming
    probe: ArtifactProbe
    artifact_path: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ScheduledRun:
    campaign_id: str
    recipe_id: str
    phase: str
    repetition_index: int
    execution_order: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkRunRecord:
    schedule: ScheduledRun
    environment_snapshot: Optional[EnvironmentSnapshot] = None
    environment_validity: ValidityResult = field(default_factory=ValidityResult)
    structural_validity: ValidityResult = field(default_factory=ValidityResult)
    overall_validity: ValidityResult = field(default_factory=ValidityResult)
    timing: Optional[EncodeTiming] = None
    probe: Optional[ArtifactProbe] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    counted_for_stability: bool = False
    skipped_before_encode: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schedule": self.schedule.to_dict(),
            "environmentSnapshot": self.environment_snapshot.to_dict() if self.environment_snapshot else None,
            "environmentValidity": self.environment_validity.to_dict(),
            "structuralValidity": self.structural_validity.to_dict(),
            "overallValidity": self.overall_validity.to_dict(),
            "timing": self.timing.to_dict() if self.timing else None,
            "probe": self.probe.to_dict() if self.probe else None,
            "metadata": dict(self.metadata),
            "countedForStability": self.counted_for_stability,
            "skippedBeforeEncode": self.skipped_before_encode,
        }


@dataclass(frozen=True)
class StabilityReport:
    stable: bool
    sample_count: int
    elapsed_mean_s: Optional[float]
    elapsed_relative_spread: Optional[float]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RecipeCampaignResult:
    recipe_id: str
    runs: List[BenchmarkRunRecord]
    stability: StabilityReport
    measured_runs_required: int
    measured_runs_completed: int
    measured_runs_counted: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recipeId": self.recipe_id,
            "runs": [run.to_dict() for run in self.runs],
            "stability": self.stability.to_dict(),
            "measuredRunsRequired": self.measured_runs_required,
            "measuredRunsCompleted": self.measured_runs_completed,
            "measuredRunsCounted": self.measured_runs_counted,
        }


@dataclass
class CampaignResult:
    campaign_id: str
    protocol_version: str
    seed: Optional[int]
    recipe_results: List[RecipeCampaignResult]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaignId": self.campaign_id,
            "protocolVersion": self.protocol_version,
            "seed": self.seed,
            "recipeResults": [result.to_dict() for result in self.recipe_results],
        }


def generate_campaign_id(protocol_version: str, recipe_ids: Sequence[str], seed: Optional[int]) -> str:
    payload = json.dumps(
        {
            "protocolVersion": str(protocol_version),
            "recipeIds": list(recipe_ids),
            "seed": seed,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"campaign-{digest}"


def order_recipes_for_repetition(recipe_ids: Sequence[str], *, seed: Optional[int], repetition_index: int) -> List[str]:
    base = list(recipe_ids)
    rng = random.Random(seed if seed is not None else 0)
    rng.shuffle(base)
    if repetition_index % 2 == 0:
        base.reverse()
    return base


def validate_environment(snapshot: EnvironmentSnapshot, thresholds: EnvironmentThresholds) -> ValidityResult:
    result = ValidityResult()

    if thresholds.require_ac_power and snapshot.power_source and str(snapshot.power_source).lower() != "ac":
        result.add_reason(
            severity=VALIDITY_SUSPECT,
            code="power-source-battery",
            message="Measured repetition ran off AC power.",
            metric="powerSource",
            actual=snapshot.power_source,
            threshold="ac",
        )
    if not snapshot.selected_accelerator:
        result.add_reason(
            severity=VALIDITY_SUSPECT,
            code="accelerator-unresolved",
            message="Selected accelerator identity was not captured.",
            metric="selectedAccelerator",
        )
    if snapshot.accelerator_is_hardware and not snapshot.gpu_load_trustworthy:
        result.add_reason(
            severity=VALIDITY_SUSPECT,
            code="gpu-environment-unobserved",
            message="Selected hardware accelerator GPU load or temperature could not be observed before the run.",
            metric="gpuSampleCount",
            actual=snapshot.gpu_sample_count,
            threshold=">0",
        )

    cpu_pct = _stable_float(snapshot.background_cpu_pct)
    if cpu_pct is not None:
        if cpu_pct >= thresholds.invalid_background_cpu_pct:
            result.add_reason(
                severity=VALIDITY_INVALID,
                code="background-cpu-high",
                message="Background CPU load exceeded the invalid threshold.",
                metric="backgroundCpuPct",
                actual=cpu_pct,
                threshold=thresholds.invalid_background_cpu_pct,
            )
        elif cpu_pct >= thresholds.suspect_background_cpu_pct:
            result.add_reason(
                severity=VALIDITY_SUSPECT,
                code="background-cpu-suspect",
                message="Background CPU load exceeded the suspect threshold.",
                metric="backgroundCpuPct",
                actual=cpu_pct,
                threshold=thresholds.suspect_background_cpu_pct,
            )

    if snapshot.gpu_load_trustworthy:
        gpu_pct = _stable_float(snapshot.background_gpu_pct)
        if gpu_pct is not None:
            if gpu_pct >= thresholds.invalid_background_gpu_pct:
                result.add_reason(
                    severity=VALIDITY_INVALID,
                    code="background-gpu-high",
                    message="Background GPU load exceeded the invalid threshold.",
                    metric="backgroundGpuPct",
                    actual=gpu_pct,
                    threshold=thresholds.invalid_background_gpu_pct,
                )
            elif gpu_pct >= thresholds.suspect_background_gpu_pct:
                result.add_reason(
                    severity=VALIDITY_SUSPECT,
                    code="background-gpu-suspect",
                    message="Background GPU load exceeded the suspect threshold.",
                    metric="backgroundGpuPct",
                    actual=gpu_pct,
                    threshold=thresholds.suspect_background_gpu_pct,
                )

    if snapshot.thermal_throttle is True and thresholds.invalidate_on_thermal_throttle:
        result.add_reason(
            severity=VALIDITY_INVALID,
            code="thermal-throttle",
            message="The host reported thermal throttling before the repetition.",
            metric="thermalThrottle",
            actual=True,
            threshold=False,
        )

    free_memory_mb = _stable_float(snapshot.free_memory_mb)
    if free_memory_mb is not None:
        if free_memory_mb <= thresholds.invalid_free_memory_mb:
            result.add_reason(
                severity=VALIDITY_INVALID,
                code="free-memory-low",
                message="Free memory was below the invalid threshold.",
                metric="freeMemoryMB",
                actual=free_memory_mb,
                threshold=thresholds.invalid_free_memory_mb,
            )
        elif free_memory_mb <= thresholds.suspect_free_memory_mb:
            result.add_reason(
                severity=VALIDITY_SUSPECT,
                code="free-memory-suspect",
                message="Free memory was below the suspect threshold.",
                metric="freeMemoryMB",
                actual=free_memory_mb,
                threshold=thresholds.suspect_free_memory_mb,
            )

    memory_pressure = _stable_float(snapshot.memory_pressure_pct)
    if memory_pressure is not None:
        if memory_pressure >= thresholds.invalid_memory_pressure_pct:
            result.add_reason(
                severity=VALIDITY_INVALID,
                code="memory-pressure-high",
                message="Memory pressure exceeded the invalid threshold.",
                metric="memoryPressurePct",
                actual=memory_pressure,
                threshold=thresholds.invalid_memory_pressure_pct,
            )
        elif memory_pressure >= thresholds.suspect_memory_pressure_pct:
            result.add_reason(
                severity=VALIDITY_SUSPECT,
                code="memory-pressure-suspect",
                message="Memory pressure exceeded the suspect threshold.",
                metric="memoryPressurePct",
                actual=memory_pressure,
                threshold=thresholds.suspect_memory_pressure_pct,
            )

    cpu_temp_c = _stable_float(snapshot.cpu_temp_c)
    if cpu_temp_c is not None:
        if cpu_temp_c >= thresholds.invalid_cpu_temp_c:
            result.add_reason(
                severity=VALIDITY_INVALID,
                code="cpu-temp-high",
                message="CPU temperature exceeded the invalid threshold.",
                metric="cpuTempC",
                actual=cpu_temp_c,
                threshold=thresholds.invalid_cpu_temp_c,
            )
        elif cpu_temp_c >= thresholds.suspect_cpu_temp_c:
            result.add_reason(
                severity=VALIDITY_SUSPECT,
                code="cpu-temp-suspect",
                message="CPU temperature exceeded the suspect threshold.",
                metric="cpuTempC",
                actual=cpu_temp_c,
                threshold=thresholds.suspect_cpu_temp_c,
            )

    gpu_temp_c = _stable_float(snapshot.gpu_temp_c)
    if gpu_temp_c is not None:
        if gpu_temp_c >= thresholds.invalid_gpu_temp_c:
            result.add_reason(
                severity=VALIDITY_INVALID,
                code="gpu-temp-high",
                message="GPU temperature exceeded the invalid threshold.",
                metric="gpuTempC",
                actual=gpu_temp_c,
                threshold=thresholds.invalid_gpu_temp_c,
            )
        elif gpu_temp_c >= thresholds.suspect_gpu_temp_c:
            result.add_reason(
                severity=VALIDITY_SUSPECT,
                code="gpu-temp-suspect",
                message="GPU temperature exceeded the suspect threshold.",
                metric="gpuTempC",
                actual=gpu_temp_c,
                threshold=thresholds.suspect_gpu_temp_c,
            )

    return result


def _validate_scalar_match(
    result: ValidityResult,
    *,
    actual: Any,
    expected: Any,
    field_name: str,
    code: str,
    message: str,
    normalize_text: bool = False,
) -> None:
    if expected is None:
        return
    compared_actual = actual
    compared_expected = expected
    if normalize_text and isinstance(actual, str) and isinstance(expected, str):
        compared_actual = actual.strip().lower()
        compared_expected = expected.strip().lower()
    if compared_actual != compared_expected:
        result.add_reason(
            severity=VALIDITY_INVALID,
            code=code,
            message=message,
            metric=field_name,
            actual=actual,
            threshold=expected,
        )


def _validate_float_ratio(
    result: ValidityResult,
    *,
    actual: Optional[float],
    expected: Optional[float],
    tolerance_ratio: float,
    field_name: str,
    code: str,
    message: str,
) -> None:
    if expected is None:
        return
    actual_value = _stable_float(actual)
    expected_value = _stable_float(expected)
    if actual_value is None or expected_value is None:
        result.add_reason(
            severity=VALIDITY_INVALID,
            code=code,
            message=message,
            metric=field_name,
            actual=actual,
            threshold=expected,
        )
        return
    tolerance = abs(expected_value) * tolerance_ratio
    if abs(actual_value - expected_value) > tolerance:
        result.add_reason(
            severity=VALIDITY_INVALID,
            code=code,
            message=message,
            metric=field_name,
            actual=actual_value,
            threshold=expected_value,
        )


def validate_structural_contract(
    probe: ArtifactProbe,
    expectation: StructuralExpectation,
    tolerance: StructuralTolerance,
) -> ValidityResult:
    result = ValidityResult()
    if not probe.decodable:
        result.add_reason(
            severity=VALIDITY_INVALID,
            code="artifact-not-decodable",
            message="Encoded artifact failed full decode validation.",
            metric="decodable",
            actual=probe.decode_error or False,
            threshold=True,
        )
        return result
    size_bytes = _stable_int(probe.size_bytes)
    if size_bytes is None or size_bytes <= 0:
        result.add_reason(
            severity=VALIDITY_INVALID,
            code="artifact-empty",
            message="Encoded artifact size was zero or unavailable.",
            metric="sizeBytes",
            actual=probe.size_bytes,
            threshold=">0",
        )
    if probe.truncated:
        result.add_reason(
            severity=VALIDITY_INVALID,
            code="artifact-truncated",
            message="Encoded artifact appears truncated.",
            metric="truncated",
            actual=True,
            threshold=False,
        )
    if expectation.no_audio and probe.has_audio:
        result.add_reason(
            severity=VALIDITY_INVALID,
            code="audio-stream-present",
            message="Benchmark artifacts must not contain audio.",
            metric="hasAudio",
            actual=True,
            threshold=False,
        )
    if expectation.single_video_stream and probe.video_stream_count != 1:
        result.add_reason(
            severity=VALIDITY_INVALID,
            code="video-stream-count-mismatch",
            message="Benchmark artifacts must contain exactly one video stream.",
            metric="videoStreamCount",
            actual=probe.video_stream_count,
            threshold=1,
        )
    if probe.auxiliary_stream_count > 0:
        result.add_reason(
            severity=VALIDITY_INVALID,
            code="auxiliary-stream-present",
            message="Benchmark artifacts must not contain subtitle, data, or attachment streams.",
            metric="auxiliaryStreamCount",
            actual=probe.auxiliary_stream_count,
            threshold=0,
        )

    _validate_float_ratio(
        result,
        actual=probe.duration_s,
        expected=expectation.duration_s,
        tolerance_ratio=tolerance.duration_ratio,
        field_name="durationSeconds",
        code="duration-mismatch",
        message="Encoded artifact duration was outside the allowed tolerance.",
    )

    expected_frames = _stable_int(expectation.frame_count)
    actual_frames = _stable_int(probe.frame_count)
    if expected_frames is not None:
        if actual_frames is None or abs(actual_frames - expected_frames) > tolerance.frame_count_delta:
            result.add_reason(
                severity=VALIDITY_INVALID,
                code="frame-count-mismatch",
                message="Encoded artifact frame count did not match the expected contract.",
                metric="frameCount",
                actual=probe.frame_count,
                threshold=expectation.frame_count,
            )

    _validate_scalar_match(
        result,
        actual=probe.width,
        expected=expectation.width,
        field_name="width",
        code="width-mismatch",
        message="Encoded artifact width did not match the expected contract.",
    )
    _validate_scalar_match(
        result,
        actual=probe.height,
        expected=expectation.height,
        field_name="height",
        code="height-mismatch",
        message="Encoded artifact height did not match the expected contract.",
    )
    _validate_scalar_match(
        result,
        actual=probe.codec,
        expected=expectation.codec,
        field_name="codec",
        code="codec-mismatch",
        message="Encoded artifact codec did not match the requested recipe.",
        normalize_text=True,
    )
    _validate_scalar_match(
        result,
        actual=probe.codec_tag,
        expected=expectation.codec_tag,
        field_name="codecTag",
        code="codec-tag-mismatch",
        message="Encoded artifact codec tag did not match the expected contract.",
        normalize_text=True,
    )
    _validate_scalar_match(
        result,
        actual=probe.profile,
        expected=expectation.profile,
        field_name="profile",
        code="profile-mismatch",
        message="Encoded artifact profile did not match the expected contract.",
        normalize_text=True,
    )
    _validate_scalar_match(
        result,
        actual=probe.level,
        expected=expectation.level,
        field_name="level",
        code="level-mismatch",
        message="Encoded artifact level did not match the expected contract.",
        normalize_text=True,
    )
    _validate_scalar_match(
        result,
        actual=probe.pix_fmt,
        expected=expectation.pix_fmt,
        field_name="pixFmt",
        code="pixfmt-mismatch",
        message="Encoded artifact pixel format did not match the expected contract.",
        normalize_text=True,
    )
    _validate_scalar_match(
        result,
        actual=probe.bit_depth,
        expected=expectation.bit_depth,
        field_name="bitDepth",
        code="bitdepth-mismatch",
        message="Encoded artifact bit depth did not match the expected contract.",
    )
    _validate_scalar_match(
        result,
        actual=probe.chroma_subsampling,
        expected=expectation.chroma_subsampling,
        field_name="chromaSubsampling",
        code="chroma-mismatch",
        message="Encoded artifact chroma subsampling did not match the expected contract.",
        normalize_text=True,
    )
    _validate_scalar_match(
        result,
        actual=probe.color_range,
        expected=expectation.color_range,
        field_name="colorRange",
        code="color-range-mismatch",
        message="Encoded artifact color range did not match the expected contract.",
        normalize_text=True,
    )
    _validate_scalar_match(
        result,
        actual=probe.color_space,
        expected=expectation.color_space,
        field_name="colorSpace",
        code="color-space-mismatch",
        message="Encoded artifact color space did not match the expected contract.",
        normalize_text=True,
    )
    _validate_scalar_match(
        result,
        actual=probe.color_transfer,
        expected=expectation.color_transfer,
        field_name="colorTransfer",
        code="color-transfer-mismatch",
        message="Encoded artifact color transfer did not match the expected contract.",
        normalize_text=True,
    )
    _validate_scalar_match(
        result,
        actual=probe.color_primaries,
        expected=expectation.color_primaries,
        field_name="colorPrimaries",
        code="color-primaries-mismatch",
        message="Encoded artifact color primaries did not match the expected contract.",
        normalize_text=True,
    )
    _validate_scalar_match(
        result,
        actual=probe.container_format,
        expected=expectation.container_format,
        field_name="containerFormat",
        code="container-mismatch",
        message="Encoded artifact container did not match the requested recipe.",
        normalize_text=True,
    )
    _validate_scalar_match(
        result,
        actual=probe.max_b_frames,
        expected=expectation.max_b_frames,
        field_name="maxBFrames",
        code="bframes-mismatch",
        message="Encoded artifact B-frame behavior did not match the requested recipe.",
    )
    _validate_scalar_match(
        result,
        actual=probe.b_frame_reordering,
        expected=expectation.b_frame_reordering,
        field_name="bFrameReordering",
        code="frame-reordering-mismatch",
        message="Encoded artifact frame reordering did not match the requested recipe.",
    )
    expected_gop = _stable_int(expectation.gop_frames)
    observed_gop = _stable_int(probe.keyframe_interval_max)
    expected_frame_total = _stable_int(expectation.frame_count)
    if expected_gop is not None and (expected_frame_total is None or expected_frame_total > expected_gop) and (
        observed_gop is None or abs(observed_gop - expected_gop) > tolerance.frame_count_delta
    ):
        result.add_reason(
            severity=VALIDITY_INVALID,
            code="gop-mismatch",
            message="Encoded artifact maximum keyframe interval did not match the requested GOP.",
            metric="keyframeIntervalMax",
            actual=probe.keyframe_interval_max,
            threshold=expected_gop,
        )
    expected_keyint_min = _stable_int(expectation.keyint_min)
    observed_keyint_min = _stable_int(probe.keyframe_interval_min)
    if expected_keyint_min is not None and (expected_frame_total is None or expected_frame_total > expected_keyint_min) and (
        observed_keyint_min is None or observed_keyint_min < expected_keyint_min
    ):
        result.add_reason(
            severity=VALIDITY_INVALID,
            code="keyint-min-mismatch",
            message="Encoded artifact minimum keyframe interval was below the requested contract.",
            metric="keyframeIntervalMin",
            actual=probe.keyframe_interval_min,
            threshold=expected_keyint_min,
        )

    _validate_float_ratio(
        result,
        actual=probe.avg_frame_rate,
        expected=expectation.avg_frame_rate,
        tolerance_ratio=tolerance.fps_ratio,
        field_name="avgFrameRate",
        code="fps-mismatch",
        message="Encoded artifact frame rate was outside the allowed tolerance.",
    )
    _validate_float_ratio(
        result,
        actual=probe.time_base,
        expected=expectation.time_base,
        tolerance_ratio=tolerance.time_base_ratio,
        field_name="timeBase",
        code="time-base-mismatch",
        message="Encoded artifact time base was outside the allowed tolerance.",
    )
    return result


def evaluate_stability(records: Sequence[BenchmarkRunRecord], config: ProtocolConfig) -> StabilityReport:
    eligible = [
        record.timing.elapsed_s
        for record in records
        if record.schedule.phase == "measured"
        and record.counted_for_stability
        and record.timing is not None
    ]
    if not eligible:
        return StabilityReport(stable=False, sample_count=0, elapsed_mean_s=None, elapsed_relative_spread=None)
    mean_value = statistics.fmean(eligible)
    spread = 0.0 if len(eligible) == 1 else (max(eligible) - min(eligible)) / mean_value
    stable = len(eligible) >= config.minimum_measured_runs and spread <= config.stability_threshold_ratio
    return StabilityReport(
        stable=stable,
        sample_count=len(eligible),
        elapsed_mean_s=mean_value,
        elapsed_relative_spread=spread,
    )


def execute_protocol_campaign(
    *,
    recipes: Sequence[RecipeSpec],
    config: ProtocolConfig,
    encode_runner: Callable[[ScheduledRun, RecipeSpec], EncodeOutcome],
    environment_sampler: Optional[Callable[[ScheduledRun, RecipeSpec], EnvironmentSnapshot]] = None,
    seed: Optional[int] = None,
) -> CampaignResult:
    # A campaign is a new measurement event by default. Reproducible ordering is
    # available by passing an explicit seed, but an omitted seed must never make
    # separate campaigns share an identity or silently reuse the same ordering.
    effective_seed = int(seed) if seed is not None else secrets.randbits(63)
    recipe_ids = [recipe.recipe_id for recipe in recipes]
    campaign_id = generate_campaign_id(config.version, recipe_ids, effective_seed)
    recipe_map = {recipe.recipe_id: recipe for recipe in recipes}
    run_records: Dict[str, List[BenchmarkRunRecord]] = {recipe.recipe_id: [] for recipe in recipes}
    adaptive_repeats_used: Dict[str, int] = {recipe.recipe_id: 0 for recipe in recipes}
    measured_attempt_limit = config.minimum_measured_runs + config.max_adaptive_repeats
    execution_order = 0

    for warmup_index in range(1, config.warmup_runs + 1):
        for recipe_id in order_recipes_for_repetition(recipe_ids, seed=effective_seed, repetition_index=warmup_index):
            execution_order += 1
            schedule = ScheduledRun(
                campaign_id=campaign_id,
                recipe_id=recipe_id,
                phase="warmup",
                repetition_index=warmup_index,
                execution_order=execution_order,
            )
            outcome = encode_runner(schedule, recipe_map[recipe_id])
            structural = validate_structural_contract(
                outcome.probe,
                recipe_map[recipe_id].expectation,
                config.structural_tolerance,
            )
            record = BenchmarkRunRecord(
                schedule=schedule,
                timing=outcome.timing,
                probe=outcome.probe,
                structural_validity=structural,
                overall_validity=structural,
                metadata=dict(outcome.metadata),
            )
            run_records[recipe_id].append(record)

    active = set(recipe_ids)
    repetition_index = 1
    while active:
        current_order = order_recipes_for_repetition(recipe_ids, seed=effective_seed, repetition_index=repetition_index)
        for recipe_id in current_order:
            if recipe_id not in active:
                continue
            execution_order += 1
            schedule = ScheduledRun(
                campaign_id=campaign_id,
                recipe_id=recipe_id,
                phase="measured",
                repetition_index=repetition_index,
                execution_order=execution_order,
            )
            environment = environment_sampler(schedule, recipe_map[recipe_id]) if environment_sampler else None
            environment_validity = (
                validate_environment(environment, config.environment)
                if environment is not None
                else ValidityResult()
            )
            if environment_validity.state == VALIDITY_INVALID:
                record = BenchmarkRunRecord(
                    schedule=schedule,
                    environment_snapshot=environment,
                    environment_validity=environment_validity,
                    structural_validity=ValidityResult(),
                    overall_validity=environment_validity,
                    skipped_before_encode=True,
                )
                run_records[recipe_id].append(record)
            else:
                outcome = encode_runner(schedule, recipe_map[recipe_id])
                structural = validate_structural_contract(
                    outcome.probe,
                    recipe_map[recipe_id].expectation,
                    config.structural_tolerance,
                )
                overall = environment_validity.merge(structural)
                record = BenchmarkRunRecord(
                    schedule=schedule,
                    environment_snapshot=environment,
                    environment_validity=environment_validity,
                    structural_validity=structural,
                    overall_validity=overall,
                    timing=outcome.timing,
                    probe=outcome.probe,
                    metadata=dict(outcome.metadata),
                    counted_for_stability=overall.state != VALIDITY_INVALID,
                )
                run_records[recipe_id].append(record)

            stability = evaluate_stability(run_records[recipe_id], config)
            completed_measured = [
                run for run in run_records[recipe_id]
                if run.schedule.phase == "measured"
            ]
            if stability.stable:
                active.discard(recipe_id)
                continue
            if len(completed_measured) >= measured_attempt_limit:
                active.discard(recipe_id)
                continue
            if stability.sample_count < config.minimum_measured_runs:
                continue
            if adaptive_repeats_used[recipe_id] < config.max_adaptive_repeats:
                adaptive_repeats_used[recipe_id] += 1
                continue
            active.discard(recipe_id)
            if len(completed_measured) >= config.minimum_measured_runs + config.max_adaptive_repeats:
                continue
        repetition_index += 1

    recipe_results: List[RecipeCampaignResult] = []
    for recipe in recipes:
        runs = run_records[recipe.recipe_id]
        stability = evaluate_stability(runs, config)
        measured_runs = [run for run in runs if run.schedule.phase == "measured"]
        recipe_results.append(
            RecipeCampaignResult(
                recipe_id=recipe.recipe_id,
                runs=runs,
                stability=stability,
                measured_runs_required=config.minimum_measured_runs,
                measured_runs_completed=len(measured_runs),
                measured_runs_counted=stability.sample_count,
            )
        )
    return CampaignResult(
        campaign_id=campaign_id,
        protocol_version=config.version,
        seed=effective_seed,
        recipe_results=recipe_results,
    )
