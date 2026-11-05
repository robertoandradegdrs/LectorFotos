"""
Motor de reconocimiento óptico de caracteres (OCR) para LectorFotos.

Soporta de forma automática:
1. Motor OCR nativo de Windows (Windows.Media.Ocr via WinRT) — sin dependencias externas.
2. Tesseract OCR (si se encuentra instalado en el sistema).
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageEnhance, ImageOps


# Plantilla de PowerShell 5.1 para invocar Windows.Media.Ocr (WinRT) en proceso
_WIN_OCR_PS_TEMPLATE = r"""
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ImagePath = $env:LECTOR_FOTOS_IMG
$LangTag = $env:LECTOR_FOTOS_LANG

Add-Type -AssemblyName System.Runtime.WindowsRuntime

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and
    $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    return $netTask.GetAwaiter().GetResult()
}

[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.SoftwareBitmap, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapPixelFormat, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapAlphaMode, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null

$engine = $null
if (-not [string]::IsNullOrWhiteSpace($LangTag)) {
    $lang = New-Object Windows.Globalization.Language($LangTag)
    if ([Windows.Media.Ocr.OcrEngine]::IsLanguageSupported($lang)) {
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
    }
}
if ($null -eq $engine) {
    $langs = [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages
    $esLang = $langs | Where-Object { $_.LanguageTag -like "es*" } | Select-Object -First 1
    if ($null -ne $esLang) {
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($esLang)
    }
}
if ($null -eq $engine) {
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
}
if ($null -eq $engine) {
    $firstLang = [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | Select-Object -First 1
    if ($null -ne $firstLang) {
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($firstLang)
    }
}
if ($null -eq $engine) {
    throw "No se encontró ningún paquete de idioma de OCR instalado en Windows."
}

$fs = [System.IO.File]::OpenRead($ImagePath)
try {
    $ras = [System.IO.WindowsRuntimeStreamExtensions]::AsRandomAccessStream($fs)
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($ras)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync([Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8, [Windows.Graphics.Imaging.BitmapAlphaMode]::Ignore)) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $ocrResult = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
} finally {
    $fs.Dispose()
}

$linesOut = @()
foreach ($line in $ocrResult.Lines) {
    if ($line.Words.Count -eq 0) { continue }
    $minX = [double]::PositiveInfinity
    $minY = [double]::PositiveInfinity
    $maxX = [double]::NegativeInfinity
    $maxY = [double]::NegativeInfinity
    foreach ($w in $line.Words) {
        $r = $w.BoundingRect
        if ($r.X -lt $minX) { $minX = $r.X }
        if ($r.Y -lt $minY) { $minY = $r.Y }
        if (($r.X + $r.Width) -gt $maxX) { $maxX = $r.X + $r.Width }
        if (($r.Y + $r.Height) -gt $maxY) { $maxY = $r.Y + $r.Height }
    }
    $linesOut += [PSCustomObject]@{
        text = $line.Text
        x = [math]::Round($minX, 1)
        y = [math]::Round($minY, 1)
        w = [math]::Round($maxX - $minX, 1)
        h = [math]::Round($maxY - $minY, 1)
    }
}

$payload = [PSCustomObject]@{
    language = $engine.RecognizerLanguage.DisplayName
    language_tag = $engine.RecognizerLanguage.LanguageTag
    lines = $linesOut
}
$payload | ConvertTo-Json -Depth 5 -Compress
"""

_ENCODED_WIN_OCR_CMD = base64.b64encode(_WIN_OCR_PS_TEMPLATE.encode("utf-16-le")).decode("ascii")


@dataclass
class DetectedLine:
    """Representa una línea de texto identificada junto con su recuadro en la imagen original."""

    text: str
    bbox: Tuple[int, int, int, int]  # (x1, y1, x2, y2) en coordenadas de la imagen orientada


@dataclass
class OcrExtractionResult:
    """Resultado completo del proceso de extracción de texto."""

    text: str
    lines: List[DetectedLine] = field(default_factory=list)
    engine_name: str = ""
    language: str = ""
    word_count: int = 0
    char_count: int = 0


def find_tesseract_executable() -> Optional[str]:
    """Busca el ejecutable de Tesseract OCR en PATH o rutas habituales de Windows."""
    in_path = shutil.which("tesseract")
    if in_path:
        return in_path

    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tesseract-OCR" / "tesseract.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Tesseract-OCR" / "tesseract.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Tesseract-OCR" / "tesseract.exe",
    ]
    for path in candidates:
        if path.is_file():
            return str(path)
    return None


def load_oriented_image(image_path: str | Path) -> Image.Image:
    """Carga una imagen aplicando rotación EXIF y componiendo transparencia sobre fondo blanco."""
    with Image.open(image_path) as raw_img:
        img = ImageOps.exif_transpose(raw_img)
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            white_bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            img = Image.alpha_composite(white_bg, rgba).convert("RGB")
        else:
            img = img.convert("RGB")
        return img.copy()


def preprocess_for_ocr(
    img: Image.Image,
    enhance_contrast: bool = False,
    max_dim: int = 3800,
    min_dim: int = 450,
) -> Tuple[Image.Image, float]:
    """
    Prepara la imagen para maximizar la precisión del OCR.
    Retorna (imagen_procesada, factor_escala) donde coord_original = coord_ocr / factor_escala.
    """
    width, height = img.size
    scale = 1.0

    largest = max(width, height)
    smallest = min(width, height)

    if largest > max_dim:
        scale = max_dim / float(largest)
    elif smallest < min_dim and largest * 2 <= max_dim:
        scale = min(2.0, min_dim / float(max(smallest, 1)))

    work = img
    if abs(scale - 1.0) > 1e-3:
        new_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
        work = work.resize(new_size, Image.Resampling.LANCZOS)

    if enhance_contrast:
        gray = ImageOps.grayscale(work)
        gray = ImageOps.autocontrast(gray, cutoff=1)
        work = ImageEnhance.Sharpness(gray.convert("RGB")).enhance(1.6)

    return work, scale


def _format_lines_into_paragraphs(lines: List[DetectedLine]) -> str:
    """Ordena visualmente las líneas detectadas y reconstruye saltos de línea y párrafos."""
    if not lines:
        return ""

    sorted_by_y = sorted(lines, key=lambda ln: (ln.bbox[1], ln.bbox[0]))
    rows: List[List[DetectedLine]] = []

    for ln in sorted_by_y:
        height = max(1, ln.bbox[3] - ln.bbox[1])
        cy = (ln.bbox[1] + ln.bbox[3]) / 2.0
        placed = False
        for row in rows:
            ref = row[0]
            ref_h = max(1, ref.bbox[3] - ref.bbox[1])
            ref_cy = (ref.bbox[1] + ref.bbox[3]) / 2.0
            if abs(cy - ref_cy) <= min(height, ref_h) * 0.55:
                row.append(ln)
                placed = True
                break
        if not placed:
            rows.append([ln])

    output_lines: List[str] = []
    prev_bottom: Optional[int] = None
    prev_height: Optional[int] = None

    for row in rows:
        row.sort(key=lambda ln: ln.bbox[0])
        row_text = "   ".join(item.text.strip() for item in row if item.text.strip())
        if not row_text:
            continue

        top = min(item.bbox[1] for item in row)
        bottom = max(item.bbox[3] for item in row)
        row_h = max(1, bottom - top)

        if prev_bottom is not None and prev_height is not None:
            vertical_gap = top - prev_bottom
            if vertical_gap > max(prev_height, row_h) * 1.45:
                output_lines.append("")

        output_lines.append(row_text)
        prev_bottom = bottom
        prev_height = row_h

    return "\n".join(output_lines).strip()


def extract_text_windows_ocr(
    img: Image.Image,
    enhance_contrast: bool = False,
    lang_tag: str = "",
) -> OcrExtractionResult:
    """Ejecuta el reconocimiento de texto usando Windows.Media.Ocr."""
    processed_img, scale = preprocess_for_ocr(img, enhance_contrast=enhance_contrast)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img:
        tmp_img_path = tmp_img.name

    try:
        processed_img.save(tmp_img_path, format="PNG")

        env = os.environ.copy()
        env["LECTOR_FOTOS_IMG"] = tmp_img_path
        env["LECTOR_FOTOS_LANG"] = lang_tag

        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        cmd = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-EncodedCommand",
            _ENCODED_WIN_OCR_CMD,
        ]

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
            env=env,
            creationflags=creation_flags,
        )

        if proc.returncode != 0:
            err_detail = (proc.stderr or proc.stdout or "Error desconocido en Windows OCR").strip()
            raise RuntimeError(f"Error al ejecutar Windows OCR:\n{err_detail}")

        raw_json = proc.stdout.strip()
        data = json.loads(raw_json) if raw_json else {}
    finally:
        try:
            os.remove(tmp_img_path)
        except OSError:
            pass

    raw_lines = data.get("lines") or []
    if isinstance(raw_lines, dict):
        raw_lines = [raw_lines]

    detected_lines: List[DetectedLine] = []
    inv_scale = 1.0 / scale if scale > 0 else 1.0
    max_w, max_h = img.size

    for item in raw_lines:
        txt = str(item.get("text", "")).strip()
        if not txt:
            continue
        x1 = max(0, int(round(float(item.get("x", 0.0)) * inv_scale)))
        y1 = max(0, int(round(float(item.get("y", 0.0)) * inv_scale)))
        w = max(1, int(round(float(item.get("w", 1.0)) * inv_scale)))
        h = max(1, int(round(float(item.get("h", 1.0)) * inv_scale)))
        x2 = min(max_w, x1 + w)
        y2 = min(max_h, y1 + h)
        detected_lines.append(DetectedLine(text=txt, bbox=(x1, y1, x2, y2)))

    full_text = _format_lines_into_paragraphs(detected_lines)
    words = full_text.split()

    return OcrExtractionResult(
        text=full_text,
        lines=detected_lines,
        engine_name="Windows OCR Nativo",
        language=data.get("language") or data.get("language_tag") or "Automático",
        word_count=len(words),
        char_count=len(full_text),
    )


def extract_text_tesseract(
    img: Image.Image,
    tesseract_cmd: str,
    enhance_contrast: bool = False,
) -> OcrExtractionResult:
    """Ejecuta el reconocimiento de texto usando Tesseract OCR si está disponible."""
    processed_img, _ = preprocess_for_ocr(img, enhance_contrast=enhance_contrast)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_img:
        tmp_img_path = tmp_img.name

    try:
        processed_img.save(tmp_img_path, format="PNG")
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        langs_proc = subprocess.run(
            [tesseract_cmd, "--list-langs"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            creationflags=creation_flags,
        )
        installed_langs = [
            line.strip()
            for line in (langs_proc.stdout or "").splitlines()
            if line.strip() and not line.lower().startswith("list of")
        ]
        if "spa" in installed_langs and "eng" in installed_langs:
            lang_arg = "spa+eng"
        elif "spa" in installed_langs:
            lang_arg = "spa"
        elif "eng" in installed_langs:
            lang_arg = "eng"
        elif installed_langs:
            lang_arg = installed_langs[0]
        else:
            lang_arg = "eng"

        proc = subprocess.run(
            [tesseract_cmd, tmp_img_path, "stdout", "-l", lang_arg],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=45,
            creationflags=creation_flags,
        )
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or "Error al ejecutar Tesseract OCR").strip())

        full_text = (proc.stdout or "").strip()
        words = full_text.split()
        return OcrExtractionResult(
            text=full_text,
            lines=[],
            engine_name="Tesseract OCR",
            language=lang_arg,
            word_count=len(words),
            char_count=len(full_text),
        )
    finally:
        try:
            os.remove(tmp_img_path)
        except OSError:
            pass


def extract_text_from_image(
    img: Image.Image,
    enhance_contrast: bool = False,
    prefer_tesseract: bool = False,
) -> OcrExtractionResult:
    """Extrae texto eligiendo automáticamente el mejor motor disponible."""
    tesseract_cmd = find_tesseract_executable()
    if prefer_tesseract and tesseract_cmd:
        return extract_text_tesseract(img, tesseract_cmd, enhance_contrast=enhance_contrast)

    try:
        return extract_text_windows_ocr(img, enhance_contrast=enhance_contrast)
    except Exception:
        if tesseract_cmd:
            return extract_text_tesseract(img, tesseract_cmd, enhance_contrast=enhance_contrast)
        raise
