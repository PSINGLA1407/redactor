

import json
import sys
import time
import re
import requests
from typing import List, Dict, Any, Tuple
from config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    REQUEST_TIMEOUT_MS,
    MAX_WORDS_PER_CHUNK,
    assert_env,
)

# ----------------- basic regex fallback -----------------
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{2,4}\)?[-.\s]?)?\d{3,4}[-.\s]?\d{3,4})")
IPV4_RE  = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
ADDR_CUES = {
    "street","st.","road","rd.","avenue","ave","sector","block","phase",
    "colony","lane","ln","plot","apt","flat","suite","zip","pincode","pin",
    "city","state"
}

def regex_pii_indices(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    win = 5
    for i, w in enumerate(words):
        t = (w.get("text") or "").strip()
        if not t:
            continue
        if EMAIL_RE.search(t):
            out.append({"index": i, "type": "email"}); continue
        if IPV4_RE.search(t):
            out.append({"index": i, "type": "ip"}); continue
        span = " ".join((words[j].get("text") or "") for j in range(i, min(i+3, len(words))))
        if PHONE_RE.search(span):
            out.append({"index": i, "type": "phone"}); continue
        window = " ".join((words[j].get("text") or "").lower()
                          for j in range(max(0, i-win), min(len(words), i+win)))
        if any(cue in window for cue in ADDR_CUES):
            out.append({"index": i, "type": "address"}); continue
    # distinct by index
    seen = set(); dedup = []
    for r in out:
        if r["index"] not in seen:
            dedup.append(r); seen.add(r["index"])
    return dedup

# ----------------- Gemini v1beta: generateContent -----------------
def _endpoint(model: str) -> str:
    return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

def _build_prompt(words: List[Dict[str, Any]]) -> str:
    header = (
        "You are a precise PII tagger. Given words in order, respond with ONLY JSON:\n"
        '{ "redactions": [ { "index": <int>, "type": "name|email|phone|address|ip|id_number|other" } ] }\n\n'
        "Rules:\n"
        "- Prefer precision (avoid false positives).\n"
        "- 'address' means postal/mailing addresses (street, house no., city, state, zip, etc.).\n"
        "- 'id_number' covers obvious govt/customer/account identifiers.\n"
        "Words (index: text):"
    )
    listing = "\n".join(f"{i}: {json.dumps(str(w.get('text','')))}" for i, w in enumerate(words))
    return f"{header}\n{listing}"

def _call_gemini(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    url = _endpoint(GEMINI_MODEL)
    body = {
        "contents": [
            {"role": "user", "parts": [{"text": _build_prompt(words)}]}
        ],
        "generationConfig": { "response_mime_type": "application/json" }
    }
    params = {"key": GEMINI_API_KEY}
    res = requests.post(url, params=params, json=body, timeout=REQUEST_TIMEOUT_MS/1000)
    res.raise_for_status()
    data = res.json()
    text = (
        data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
    )
    if not text:
        return []
    try:
        parsed = json.loads(text)
        red = parsed.get("redactions", [])
        out = []
        for r in red:
            idx = r.get("index")
            typ = str(r.get("type", "other"))
            if isinstance(idx, int) and 0 <= idx < len(words):
                out.append({"index": idx, "type": typ})
        return out
    except Exception:
        return []

def _chunk(seq: List[Any], size: int) -> List[Tuple[int, List[Any]]]:
    return [(i, seq[i:i+size]) for i in range(0, len(seq), size)]

def _mark(words: List[Dict[str, Any]], red: List[Dict[str, Any]], start: int) -> None:
    for r in red:
        idx = start + int(r["index"])
        if 0 <= idx < len(words):
            words[idx]["pii"] = {"is_pii": True, "type": r.get("type", "other")}

def tag_page(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # copy + default pii flag
    tagged = [{**w, "pii": {"is_pii": False, "type": None}} for w in words]
    for start, chunk_items in _chunk(tagged, MAX_WORDS_PER_CHUNK):
        red = []
        try:
            red = _call_gemini(chunk_items)
        except Exception:
            red = []
        if not red:
            red = regex_pii_indices(chunk_items)
        _mark(tagged, red, start)
        time.sleep(0.15)  # gentle rate-limit
    return tagged

def main():
    assert_env()
    if len(sys.argv) < 2:
        print("Usage: python pii_identify.py input.positions.json [output.with_pii.json]")
        sys.exit(1)

    in_path = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else re.sub(r"\.json$", "", in_path) + ".with_pii.json"

    with open(in_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    pages = data.get("pages", [])
    if not isinstance(pages, list):
        raise SystemExit("Invalid positions JSON: missing 'pages' array")

    result = {"pages": []}
    for page in pages:
        words = page.get("words", [])
        tagged = tag_page(words)
        result["pages"].append({
            "page": page.get("page"),
            "width": page.get("width"),
            "height": page.get("height"),
            "words": tagged
        })
        print(f"page {page.get('page')}: tagged {sum(1 for w in tagged if w['pii']['is_pii'])} PII tokens")

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f" wrote {out_path}")

if __name__ == "__main__":
    main()
