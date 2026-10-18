#!/usr/bin/env python3

import argparse
import base64
import copy
import hashlib
import json
import re
import urllib.request
from pathlib import Path


AUGMENTER_VERSION = "phase-c-1"
PROMPT_VERSION = "visual-evidence-v1"
SUPPORTED_SCHEMA = "document-manifest-v2"

DEFAULT_DPI = 160
DEFAULT_JPEG_QUALITY = 85

VECTOR_ITEM_THRESHOLD = 500
LOW_EFFECTIVE_TEXT_THRESHOLD = 250
OCR_RECOVERY_THRESHOLD = 300
IMAGE_COVERAGE_THRESHOLD = 0.25

HERMES_ENV = Path(
    "/data/coolify/services/"
    "rgu4flce2juuzyq6idzr49z2/.hermes/.env"
)

HERMES_CONFIG = Path(
    "/data/coolify/services/"
    "rgu4flce2juuzyq6idzr49z2/.hermes/config.yaml"
)


def normalize_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)

    return h.hexdigest()


def load_env_file(path: Path) -> dict:
    values = {}

    if not path.exists():
        return values

    for line in path.read_text(
        encoding="utf-8",
        errors="ignore",
    ).splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")

    return values


def get_model_config(model_override: str | None = None):
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError(
            "PyYAML is required for vision augmentation"
        ) from exc

    env = load_env_file(HERMES_ENV)

    api_key = env.get("DEEPSEEK_API_KEY")

    if not api_key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY not found in Hermes environment"
        )

    config = {}

    if HERMES_CONFIG.exists():
        with HERMES_CONFIG.open("r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

    model_cfg = config.get("model", {})

    model = (
        model_override
        or model_cfg.get("default")
        or "deepseek-v4-flash"
    )

    base_url = (
        model_cfg.get("base_url")
        or env.get("DEEPSEEK_BASE_URL")
        or "https://api.deepseek.com"
    ).rstrip("/")

    return api_key, model, base_url


def load_manifest(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))

    if data.get("schema_version") != SUPPORTED_SCHEMA:
        raise RuntimeError(
            f"Unsupported manifest schema: {data.get('schema_version')!r}"
        )

    if not isinstance(data.get("units"), list):
        raise RuntimeError("Manifest units must be a list")

    source = data.get("source") or {}

    if not source.get("sha256"):
        raise RuntimeError("Manifest source.sha256 is missing")

    if (data.get("document") or {}).get("kind") != "pdf":
        raise RuntimeError(
            "Phase C vision currently supports PDF manifests only"
        )

    return data


def validate_pdf_against_manifest(
    pdf_path: Path,
    manifest: dict,
) -> None:
    expected_sha = manifest["source"]["sha256"]
    actual_sha = sha256_file(pdf_path)

    if actual_sha != expected_sha:
        raise RuntimeError(
            "PDF SHA256 does not match manifest source.sha256: "
            f"expected {expected_sha}, got {actual_sha}"
        )


def parse_page_spec(spec: str | None):
    if not spec:
        return None

    pages = set()

    for token in spec.split(","):
        token = token.strip()

        if not token:
            continue

        if "-" in token:
            start_text, end_text = token.split("-", 1)
            start = int(start_text.strip())
            end = int(end_text.strip())

            if start < 1 or end < start:
                raise ValueError(
                    f"Invalid page range: {token}"
                )

            pages.update(range(start, end + 1))

        else:
            page_number = int(token)

            if page_number < 1:
                raise ValueError(
                    f"Invalid page number: {token}"
                )

            pages.add(page_number)

    return sorted(pages)


def bbox_area(bbox) -> float:
    if not bbox or len(bbox) != 4:
        return 0.0

    try:
        x0, y0, x1, y1 = [
            float(value)
            for value in bbox
        ]
    except Exception:
        return 0.0

    return (
        max(0.0, x1 - x0)
        * max(0.0, y1 - y0)
    )


def max_image_coverage(unit: dict) -> float:
    width = float(unit.get("width") or 0)
    height = float(unit.get("height") or 0)
    page_area = width * height

    if page_area <= 0:
        return 0.0

    coverage = 0.0

    for image in unit.get("images") or []:
        coverage = max(
            coverage,
            min(
                1.0,
                bbox_area(image.get("bbox")) / page_area,
            ),
        )

    return round(coverage, 4)


def ocr_text_chars(unit: dict) -> int:
    ocr = unit.get("ocr") or {}

    try:
        return int(ocr.get("text_chars") or 0)
    except Exception:
        return 0


def effective_text_chars(unit: dict) -> int:
    try:
        original = int(unit.get("text_chars") or 0)
    except Exception:
        original = 0

    return max(original, ocr_text_chars(unit))


def visual_gate(unit: dict) -> dict:
    page_number = unit.get("page_number")
    reasons = []

    if not unit.get("visual_candidate"):
        return {
            "selected": False,
            "page_number": page_number,
            "reasons": ["not_visual_candidate"],
        }

    vector_metrics = unit.get("vector_metrics") or {}

    try:
        vector_items = int(
            vector_metrics.get("meaningful_drawing_item_count") or 0
        )
    except Exception:
        vector_items = 0

    images = unit.get("images") or []
    image_count = len(images)
    image_coverage = max_image_coverage(unit)
    effective_chars = effective_text_chars(unit)

    ocr = unit.get("ocr") or {}
    ocr_status = ocr.get("status")
    recovered_chars = ocr_text_chars(unit)

    if vector_items >= VECTOR_ITEM_THRESHOLD:
        reasons.append("high_vector_complexity")

    if (
        image_count > 0
        and effective_chars < LOW_EFFECTIVE_TEXT_THRESHOLD
    ):
        reasons.append("image_with_low_effective_text")

    if (
        image_count > 0
        and ocr_status == "empty_result"
    ):
        reasons.append("image_with_empty_ocr")

    if (
        image_count > 0
        and image_coverage >= IMAGE_COVERAGE_THRESHOLD
        and recovered_chars < OCR_RECOVERY_THRESHOLD
    ):
        reasons.append("large_image_with_limited_ocr")

    return {
        "selected": bool(reasons),
        "page_number": page_number,
        "reasons": (
            reasons
            or ["visual_evidence_sufficiently_represented_by_text"]
        ),
        "vector_items": vector_items,
        "image_count": image_count,
        "max_image_coverage": image_coverage,
        "effective_text_chars": effective_chars,
        "ocr_status": ocr_status,
        "ocr_text_chars": recovered_chars,
    }


def render_page_jpeg(
    page,
    dpi: int,
    quality: int,
) -> bytes:
    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF is required for vision augmentation"
        ) from exc

    scale = dpi / 72.0

    pix = page.get_pixmap(
        matrix=pymupdf.Matrix(scale, scale),
        alpha=False,
    )

    return pix.tobytes(
        "jpeg",
        jpg_quality=quality,
    )


def compact_evidence_text(
    unit: dict,
    max_chars: int = 4000,
) -> str:
    original = normalize_text(unit.get("text") or "")
    ocr = normalize_text((unit.get("ocr") or {}).get("text") or "")

    parts = []

    if original:
        parts.append("Phase A extracted text:\n" + original)

    if ocr and ocr != original:
        parts.append("Phase B OCR text:\n" + ocr)

    text = "\n\n".join(parts)

    if len(text) <= max_chars:
        return text

    return text[:max_chars] + "\n[...text evidence truncated...]"


def build_prompt(
    unit: dict,
    gate: dict,
) -> str:
    page_number = unit.get("page_number")
    evidence = compact_evidence_text(unit)

    return f"""
Analyze page {page_number} of a professional construction / property knowledge document.

The purpose is retrieval evidence, not creative description.

Use ONLY what is visibly supported by the page image and the supplied extracted/OCR text.
Do not invent dimensions, labels, standards, relationships, object identities, or conclusions.
Do not infer hidden geometry.
Ignore decorative backgrounds, logos, page furniture, and generic slide design unless they are materially relevant.
If the page contains a technical drawing, diagram, figure, table, annotated photograph, or spatial relationship that text extraction does not adequately capture, describe that evidence concisely.
If the visual content adds no meaningful retrievable information beyond the supplied text, set useful=false.

Deterministic gate diagnostics:
{json.dumps(gate, ensure_ascii=False)}

Existing text evidence:
--- BEGIN TEXT EVIDENCE ---
{evidence or "[none]"}
--- END TEXT EVIDENCE ---

Return JSON only with exactly these keys:
{{
  "useful": true,
  "page_type": "technical_drawing|diagram|photograph|table|mixed|other",
  "summary": "",
  "key_visual_evidence": [],
  "spatial_relationships": [],
  "labels_measurements": [],
  "retrieval_text": "",
  "confidence": 0.0
}}

Rules:
- useful must be boolean
- confidence must be between 0 and 1
- lists must contain short factual strings only
- labels_measurements must include only text or dimensions actually visible
- retrieval_text must be a concise self-contained paragraph suitable for semantic retrieval
- if useful=false, retrieval_text should be empty
""".strip()


def parse_json_content(content: str) -> dict:
    content = (content or "").strip()
    fence = chr(96) * 3

    if content.startswith(fence):
        content = re.sub(
            r"^\x60\x60\x60(?:json)?\s*",
            "",
            content,
            flags=re.I,
        )
        content = re.sub(
            r"\s*\x60\x60\x60$",
            "",
            content,
        )

    result = json.loads(content)

    if not isinstance(result, dict):
        raise RuntimeError(
            "Vision response is not a JSON object"
        )

    return result


def validate_vision_result(result: dict) -> dict:
    page_types = {
        "technical_drawing",
        "diagram",
        "photograph",
        "table",
        "mixed",
        "other",
    }

    useful = bool(result.get("useful"))
    page_type = str(result.get("page_type") or "other")

    if page_type not in page_types:
        page_type = "other"

    def clean_list(name):
        value = result.get(name) or []

        if not isinstance(value, list):
            value = []

        cleaned = []

        for item in value:
            text = normalize_text(str(item))

            if text:
                cleaned.append(text)

        return cleaned

    summary = normalize_text(str(result.get("summary") or ""))
    retrieval_text = normalize_text(
        str(result.get("retrieval_text") or "")
    )

    try:
        confidence = float(result.get("confidence") or 0.0)
    except Exception:
        confidence = 0.0

    confidence = min(1.0, max(0.0, confidence))

    if not useful:
        retrieval_text = ""

    return {
        "useful": useful,
        "page_type": page_type,
        "summary": summary,
        "key_visual_evidence": clean_list("key_visual_evidence"),
        "spatial_relationships": clean_list("spatial_relationships"),
        "labels_measurements": clean_list("labels_measurements"),
        "retrieval_text": retrieval_text,
        "confidence": confidence,
    }


def call_vision(
    api_key: str,
    model: str,
    base_url: str,
    prompt: str,
    image_bytes: bytes,
):
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    image_url = "data:image/jpeg;base64," + image_b64

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a conservative visual evidence extractor. "
                    "Ground every statement in visible page evidence."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt,
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_url,
                            "detail": "high",
                        },
                    },
                ],
            },
        ],
        "response_format": {
            "type": "json_object",
        },
        "temperature": 0,
    }

    req = urllib.request.Request(
        base_url + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=180) as response:
        result = json.loads(response.read().decode("utf-8"))

    content = result["choices"][0]["message"]["content"]
    usage = result.get("usage") or {}

    return (
        validate_vision_result(parse_json_content(content)),
        usage,
    )


def augment_manifest(
    manifest: dict,
    pdf_path: Path,
    selected_pages,
    model_override: str | None,
    dpi: int,
    jpeg_quality: int,
) -> dict:
    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF is required for vision augmentation"
        ) from exc

    api_key, model, base_url = get_model_config(model_override)
    augmented = copy.deepcopy(manifest)

    page_filter = set(selected_pages) if selected_pages else None

    candidate_units = []
    selected_units = []
    skipped_units = []

    for unit in augmented["units"]:
        if unit.get("unit_type") != "page":
            continue

        page_number = unit.get("page_number")

        if not unit.get("visual_candidate"):
            continue

        candidate_units.append(page_number)
        gate = visual_gate(unit)

        if page_filter is not None and page_number not in page_filter:
            gate = dict(gate)
            gate["selected"] = False
            gate["reasons"] = ["excluded_by_page_filter"]

        unit["vision"] = {
            "eligible": True,
            "selected": bool(gate["selected"]),
            "performed": False,
            "status": (
                "selected"
                if gate["selected"]
                else "skipped"
            ),
            "gate": gate,
            "model": model,
            "prompt_version": PROMPT_VERSION,
            "dpi": dpi,
            "jpeg_quality": jpeg_quality,
            "result": None,
            "error": None,
        }

        if gate["selected"]:
            selected_units.append(page_number)
        else:
            skipped_units.append(page_number)

    processed_units = []
    described_units = []
    not_useful_units = []
    empty_description_units = []
    failed_units = []
    total_retrieval_text_chars = 0

    usage_totals = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }

    doc = pymupdf.open(pdf_path)

    try:
        page_count = len(doc)

        for unit in augmented["units"]:
            vision = unit.get("vision") or {}

            if not vision.get("selected"):
                continue

            page_number = unit["page_number"]

            if page_number < 1 or page_number > page_count:
                vision["performed"] = False
                vision["status"] = "failed"
                vision["error"] = (
                    f"Page {page_number} is outside PDF page count {page_count}"
                )
                failed_units.append(page_number)
                continue

            try:
                image_bytes = render_page_jpeg(
                    doc[page_number - 1],
                    dpi=dpi,
                    quality=jpeg_quality,
                )

                prompt = build_prompt(
                    unit,
                    vision["gate"],
                )

                result, usage = call_vision(
                    api_key=api_key,
                    model=model,
                    base_url=base_url,
                    prompt=prompt,
                    image_bytes=image_bytes,
                )

                vision["performed"] = True
                vision["result"] = result
                processed_units.append(page_number)

                for key in usage_totals:
                    try:
                        usage_totals[key] += int(
                            usage.get(key) or 0
                        )
                    except Exception:
                        pass

                retrieval_text = result["retrieval_text"]
                total_retrieval_text_chars += len(retrieval_text)

                if not result["useful"]:
                    vision["status"] = "not_useful"
                    not_useful_units.append(page_number)

                elif retrieval_text:
                    vision["status"] = "described"
                    described_units.append(page_number)

                else:
                    vision["status"] = "empty_description"
                    empty_description_units.append(page_number)

            except Exception as exc:
                vision["performed"] = False
                vision["status"] = "failed"
                vision["error"] = f"{type(exc).__name__}: {exc}"
                failed_units.append(page_number)

    finally:
        doc.close()

    augmented.setdefault("augmentations", {})
    augmented["augmentations"]["vision"] = {
        "augmenter_version": AUGMENTER_VERSION,
        "prompt_version": PROMPT_VERSION,
        "provider": "deepseek",
        "model": model,
        "base_url": base_url,
        "dpi": dpi,
        "jpeg_quality": jpeg_quality,
        "candidate_units": candidate_units,
        "selected_units": selected_units,
        "skipped_units": skipped_units,
        "processed_units": processed_units,
        "described_units": described_units,
        "not_useful_units": not_useful_units,
        "empty_description_units": empty_description_units,
        "failed_units": failed_units,
        "total_retrieval_text_chars": total_retrieval_text_chars,
        "usage": usage_totals,
        "gate": {
            "vector_item_threshold": VECTOR_ITEM_THRESHOLD,
            "low_effective_text_threshold": LOW_EFFECTIVE_TEXT_THRESHOLD,
            "ocr_recovery_threshold": OCR_RECOVERY_THRESHOLD,
            "image_coverage_threshold": IMAGE_COVERAGE_THRESHOLD,
        },
    }

    augmented.setdefault("extraction", {})
    augmented["extraction"]["vision_model_used"] = bool(processed_units)

    return augmented


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Phase C selective visual-understanding augmenter for "
            "document-manifest-v2. Applies deterministic usefulness "
            "gating before any vision-model call."
        )
    )

    parser.add_argument(
        "manifest",
        help="Phase A/B JSON manifest",
    )

    parser.add_argument(
        "pdf",
        help="Original PDF matching manifest source.sha256",
    )

    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Write augmented manifest to a new JSON file",
    )

    parser.add_argument(
        "--pages",
        help="Optional PDF page filter, e.g. '16,17,28'",
    )

    parser.add_argument(
        "--model",
        help="Override Hermes default DeepSeek model",
    )

    parser.add_argument(
        "--dpi",
        type=int,
        default=DEFAULT_DPI,
        help=f"Page render DPI (default: {DEFAULT_DPI})",
    )

    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=DEFAULT_JPEG_QUALITY,
        help=(
            f"JPEG quality 1-100 "
            f"(default: {DEFAULT_JPEG_QUALITY})"
        ),
    )

    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON",
    )

    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    pdf_path = Path(args.pdf)
    output_path = Path(args.output)

    if not manifest_path.is_file():
        raise SystemExit(f"Manifest not found: {manifest_path}")

    if not pdf_path.is_file():
        raise SystemExit(f"PDF not found: {pdf_path}")

    if output_path.resolve() == manifest_path.resolve():
        raise SystemExit("Refusing to overwrite the input manifest")

    if args.dpi < 72 or args.dpi > 300:
        raise SystemExit("--dpi must be between 72 and 300")

    if args.jpeg_quality < 1 or args.jpeg_quality > 100:
        raise SystemExit("--jpeg-quality must be between 1 and 100")

    try:
        selected_pages = parse_page_spec(args.pages)
        manifest = load_manifest(manifest_path)
        validate_pdf_against_manifest(pdf_path, manifest)

        augmented = augment_manifest(
            manifest=manifest,
            pdf_path=pdf_path,
            selected_pages=selected_pages,
            model_override=args.model,
            dpi=args.dpi,
            jpeg_quality=args.jpeg_quality,
        )

    except Exception as exc:
        raise SystemExit(
            f"Vision augmentation failed: {type(exc).__name__}: {exc}"
        ) from exc

    if args.compact:
        payload = json.dumps(
            augmented,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    else:
        payload = json.dumps(
            augmented,
            ensure_ascii=False,
            indent=2,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(payload + "\n", encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
