# PDF PII Redactor

## What This Project Does
This app takes a PDF (even scanned ones), finds personal information in it (like names, emails, phone numbers, addresses, IPs, passwords, and API keys), and automatically blacks it out.  

The difference is that we don’t just “find text” — during OCR we also store the **word positions (x/y coordinates)**. That lets us draw precise black boxes in the exact location of the PII inside the PDF. So the redaction isn’t just cosmetic text replacement — it’s true graphical redaction.

👉 **Live Demo:** [http://34.133.7.30/](http://34.133.7.30/)

---

## How It Works (3-Step Workflow)

1. **OCR (pos-ocr.py)**  
   - Runs Tesseract OCR on the PDF.  
   - Extracts not only text but also bounding boxes for every word.  
   - Saves results into a `.positions.json` file.

2. **PII Identification (pii-identifier.py)**  
   - Takes the positions JSON.  
   - Uses **Gemini Flash 2.0** for smart detection of names, addresses, etc.  
   - Uses **regex/heuristics** for guaranteed catches (emails, phone numbers, passwords).  
   - Produces a `.with_pii.json` file with every word tagged as PII or not.

3. **Redaction (redactor.py)**  
   - Reads the original PDF + the tagged JSON.  
   - Converts bounding boxes into true PDF rectangles.  
   - Draws **black redaction boxes** with optional labels (e.g., “EMAIL”, “PHONE”).  
   - Saves a final **redacted PDF** that is safe to share.

The Streamlit app ties this together, so you just upload → choose categories → get the result.

---

## Assumptions and Limitations
- Assumes English PDFs that OCR can handle.  
- Redaction is **word-level**; if OCR splits/merges oddly, boxes can be imperfect.  
- Does not redact handwriting or embedded images.  
- Some false positives/negatives are possible:  
  - Regex may over-match (e.g., random numbers).  
  - Gemini may miss tokens if split across chunks.  
- Gemini API usage has free quotas — heavy loads will hit limits.  
- Currently a single-user Streamlit app (no login/auth).  

---

## If We Had More Time
- Smarter redaction styles: blur, placeholders (`[EMAIL]`), partial masking.  
- Detect more types (credit cards, IBANs, passport numbers).  
- Better inline PDF viewer with zoom/search/edit.  
- Offline mode using a lightweight NER model (no Gemini needed).  
- Batch PDF processing.  
- CI/CD + Kubernetes deployment.  

---

## How to Run It Yourself
### Docker
```bash
docker build -t pdf-pii-redactor .
docker run -p 8080:8080 --env-file .env pdf-pii-redactor
