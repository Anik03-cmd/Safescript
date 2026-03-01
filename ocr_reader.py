"""
ocr_reader.py  –  Prescription OCR with accurate dose extraction
================================================================
Strategy:
  - Two-pass OCR: full image (PSM 11) for medicine names +
                  cropped Rx section (PSM 6, 3x upscale) for doses
  - Aggressive OCR digit correction (O→0, S→5, l→1 etc.)
  - Min token length 5 to kill false positives
  - Fuzzy match with strict length + prefix filters
"""

import re
import cv2
import numpy as np
import pytesseract
from PIL import Image
from difflib import SequenceMatcher


# ─────────────────────────────────────────────
# 1.  PREPROCESSING
# ─────────────────────────────────────────────

def _clahe_otsu(gray):
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    cl = clahe.apply(gray)
    _, thresh = cv2.threshold(cl, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return thresh


def _full_image(image_path: str):
    """Preprocess full image for medicine name detection."""
    img = cv2.imread(image_path)
    if img is None:
        return Image.open(image_path).convert("L")
    h, w = img.shape[:2]
    # Cap size
    if max(h, w) > 1400:
        scale = 1400 / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return Image.fromarray(_clahe_otsu(gray))


def _rx_crop(image_path: str):
    """
    Crop to the handwritten Rx section (middle of image) and upscale 3x.
    This dramatically improves digit recognition.
    """
    img = cv2.imread(image_path)
    if img is None:
        return None
    h, w = img.shape[:2]
    # Rx body: slightly tighter crop avoids the Rx symbol and header noise
    crop = img[int(h * 0.35): int(h * 0.85), int(w * 0.10): int(w * 0.75)]
    # 3x upscale before OCR
    big = cv2.resize(crop, (crop.shape[1] * 3, crop.shape[0] * 3),
                     interpolation=cv2.INTER_LANCZOS4)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    return Image.fromarray(_clahe_otsu(gray))


# ─────────────────────────────────────────────
# 2.  OCR DIGIT CLEANING
# ─────────────────────────────────────────────

# Common OCR confusions in digit contexts (lowercase 'i' intentionally excluded)
_DIGIT_MAP = str.maketrans({
    'O': '0', 'o': '0',
    'l': '1', 'I': '1',
    'S': '5', 's': '5', 'Z': '2',
    '[': '1', '(': '1',
    ' ': '',
})

def _clean_digits(s: str) -> str:
    """Translate OCR noise chars → correct digits, strip spaces."""
    return s.translate(_DIGIT_MAP)


# ─────────────────────────────────────────────
# 3.  TWO-PASS OCR
# ─────────────────────────────────────────────

def run_ocr(image_path: str) -> tuple[str, str]:
    """
    Returns (full_text, crop_text).
    full_text  → used for medicine name detection (PSM 11)
    crop_text  → used for dose extraction (PSM 6 on upscaled crop)
    """
    full_img  = _full_image(image_path)
    full_text = pytesseract.image_to_string(
        full_img, config="--psm 11 --oem 1"
    ).lower()

    crop_img  = _rx_crop(image_path)
    crop_text = ""
    if crop_img:
        crop_text = pytesseract.image_to_string(
            crop_img, config="--psm 6 --oem 1"
        ).lower()

    return full_text, crop_text


# ─────────────────────────────────────────────
# 4.  DOSE EXTRACTION  (from high-res crop)
# ─────────────────────────────────────────────

def _extract_doses(text: str) -> dict:
    """
    Extract doses from any OCR text (full image or crop).
    Handles:
      "1. Metformin 1000 mg"  → {'metformin': 1000}
      "Ibuprofen 4 OO ng"     → {'ibuprofen': 400}   (space in number)
      "Warfarin [O mg"        → {'warfarin': 10}      (bracket noise)
      "ibuprofen 400 \"9."   → {'ibuprofen': 400}   (trailing noise ignored)
    """
    doses = {}
    SKIP = {"date", "address", "signature", "specialist", "medicine",
            "doctor", "from", "name", "time", "rk", "once", "twice",
            "daily", "note", "check", "avoid", "monitor", "complete",
            "stamp", "prescription", "valid", "issue", "days"}

    for raw_line in text.splitlines():
        line = raw_line.strip().lower()
        # Strip leading numbering like "1." "2."
        line = re.sub(r"^\d+[.)\s]+", "", line).strip()
        if not line:
            continue

        # Find medicine name (first word ≥4 alpha chars)
        name_m = re.search(r"([a-z][a-z\-]{3,})", line)
        if not name_m or name_m.group(1) in SKIP:
            continue
        name_frag = name_m.group(1)

        rest = line[name_m.end():]

        # Strategy 1: clean numeric pattern right after name
        # Look for a run of digit-like chars as ONE unit (before any letter word)
        # e.g. "1000 mg", "4 OO ng", "[O mg"
        # Split rest into space-separated chunks, try each leading chunk
        dose = None
        chunks = rest.split()
        for j, chunk in enumerate(chunks[:4]):   # only look at first 4 chunks
            # Skip "mg", "mcg" etc — these mark end of number
            if re.match(r"^(mg|mcg|ml|g)$", chunk):
                break
            # Stop if chunk has letters that aren't digit-noise chars
            clean = _clean_digits(chunk)
            digits_only = re.sub(r"[^\d]", "", clean)
            if not digits_only:
                # If we already have a dose candidate, stop here
                if dose is not None:
                    break
                continue
            # Accumulate digits (handles "4" + "OO" = "400")
            if dose is None:
                dose = digits_only
            else:
                # Only join if next chunk looks purely numeric (no real letters)
                real_letters = re.sub(r"[0-9OoSslIZz\[\(]", "", chunk)
                if not real_letters:
                    dose += digits_only
                else:
                    break
            # Stop once we have a plausible dose (2–4 digits)
            if len(dose) >= 2:
                # Peek: if next chunk is "mg" or empty, we're done
                next_chunk = chunks[j+1] if j+1 < len(chunks) else ""
                if re.match(r"^(mg|mcg|ml|g)?$", next_chunk):
                    break

        if not dose:
            continue
        try:
            val = int(dose[:4])
            if 1 <= val <= 5000:
                doses[name_frag] = val
        except ValueError:
            pass

    return doses


# ─────────────────────────────────────────────
# 5.  TOKENISE  (from full image text)
# ─────────────────────────────────────────────

def _tokenize(text: str) -> list:
    # Min length 5 → kills garbage like "tin", "oma", "acy"
    words = re.findall(r"[a-z][a-z\-]{4,}", text)
    # Return individual words only — bigrams caused display pollution
    # and confused the matcher (multiple meds sharing same bigram token)
    return list(set(words))


# ─────────────────────────────────────────────
# 6.  FUZZY MATCHING
# ─────────────────────────────────────────────

def _score(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _match_medicines(tokens: list, medicine_list: list,
                     threshold: float = 0.50) -> list:
    """
    Two-tier matching:
    - Exact / substring hits: always accepted (score 1.0 / 0.96)
    - Pure fuzzy hits: need score >= 0.82 to avoid false positives
      like ampicillin↔aspirin or sertraline↔specialist
    """
    found = {}
    FUZZY_MIN = 0.82   # strict bar for non-substring fuzzy matches

    for med in medicine_list:
        best_score = 0.0
        best_token = ""

        for token in tokens:
            # Exact match → perfect, stop immediately
            if med == token:
                best_score = 1.0
                best_token = token
                break

            # Substring: med inside token or token inside med
            if med in token or token in med:
                score = 0.96
            else:
                # Length + prefix pre-filters
                ratio = len(token) / max(len(med), 1)
                if ratio < 0.60 or ratio > 1.50:
                    continue
                if token[0] != med[0]:
                    continue
                score = _score(med, token)
                # Pure fuzzy needs a high bar to avoid garbage matches
                if score < FUZZY_MIN:
                    continue

            if score > best_score:
                best_score = score
                best_token = token

        if best_score >= threshold:
            found[med] = {
                "name":          med,
                "confidence":    round(best_score * 100, 1),
                "matched_token": best_token,
            }

    return sorted(found.values(), key=lambda x: -x["confidence"])


# ─────────────────────────────────────────────
# 7.  ATTACH DOSES TO MATCHES
# ─────────────────────────────────────────────

def _attach_doses(matches: list, doses: dict) -> list:
    """For each matched medicine, find best dose from extracted dose dict."""
    for m in matches:
        med_name  = m["name"]
        best_dose = None
        best_sim  = 0.0

        for frag, dose_val in doses.items():
            # Substring match
            if med_name in frag or frag in med_name:
                sim = 0.95
            else:
                sim = _score(med_name, frag)

            if sim > best_sim and sim >= 0.60:
                best_sim  = sim
                best_dose = dose_val

        m["dose"] = best_dose
    return matches


# ─────────────────────────────────────────────
# 8.  PUBLIC API
# ─────────────────────────────────────────────

def extract_prescription(image_path: str,
                         medicine_list: list,
                         threshold: float = 0.72) -> list:
    """
    Returns [{name, confidence, matched_token, dose}, ...]
    sorted by confidence (highest first).
    """
    full_text, crop_text = run_ocr(image_path)

    print("\n── FULL OCR TEXT ──")
    print(full_text[:500])
    print("\n── CROP OCR TEXT ──")
    print(crop_text[:500])

    # Try full text first (more complete), fall back to crop for any missing
    doses_full = _extract_doses(full_text)
    doses_crop = _extract_doses(crop_text)
    # Merge: full text takes priority, crop fills gaps
    doses = {**doses_crop, **doses_full}
    print("\n── Extracted doses ──", doses)

    tokens  = _tokenize(full_text)
    matches = _match_medicines(tokens, medicine_list, threshold)
    matches = _attach_doses(matches, doses)

    print(f"\n── {len(matches)} medicines detected ──")
    for m in matches:
        print(f"  {m['name']:<20} conf={m['confidence']}%  "
              f"dose={m['dose']}mg  token='{m['matched_token']}'")

    return matches


if __name__ == "__main__":
    import sys
    path  = sys.argv[1] if len(sys.argv) > 1 else "uploaded.png"
    dummy = ["ibuprofen", "amoxicillin", "metformin", "paracetamol",
             "aspirin", "atorvastatin", "omeprazole", "cetirizine", "warfarin"]
    print(extract_prescription(path, dummy))


# ─────────────────────────────────────────────
# 9.  DISEASE / DIAGNOSIS EXTRACTION
# ─────────────────────────────────────────────

def extract_disease(image_path: str) -> str:
    """
    Try to read the diagnosis/disease from the prescription image.
    Returns the disease string if found, else empty string.
    """
    full_text, _ = run_ocr(image_path)

    # Common label patterns found on prescriptions
    patterns = [
        r"diagnosis\s*[:\-]\s*(.+)",
        r"dx\s*[:\-]\s*(.+)",
        r"disease\s*[:\-]\s*(.+)",
        r"condition\s*[:\-]\s*(.+)",
        r"complaint\s*[:\-]\s*(.+)",
        r"for\s*[:\-]\s*(.+)",
    ]

    for line in full_text.splitlines():
        line = line.strip()
        for pat in patterns:
            m = re.match(pat, line, re.IGNORECASE)
            if m:
                disease = m.group(1).strip()
                # Clean trailing noise (punctuation, extra spaces)
                disease = re.sub(r"[^\w\s/\-]", "", disease).strip()
                if 2 < len(disease) < 60:
                    return disease.title()

    return ""