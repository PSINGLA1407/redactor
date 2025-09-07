# PDF PII Redactor

## What This Project Does
This app takes a PDF (even scanned ones), finds personal information in it (like names, emails, phone numbers, addresses, IPs, passwords, and API keys), and automatically blacks it out.  

You can upload a file through a simple Streamlit web app, pick which categories you want to redact, and then see the original vs. redacted PDFs side by side. It also produces a small report so you know what got removed.

👉 **Live Demo:** [http://34.133.7.30/](http://34.133.7.30/)

We used a mix of:
- **OCR (Tesseract)** to handle scanned PDFs and get word positions.
- **Gemini Flash 2.0** to spot trickier PII like names and addresses in context.
- **Regex + heuristics** for things that need hard rules (like emails, phone numbers, or passwords).

This way, we get the flexibility of an LLM but the safety of deterministic rules.

---

## Assumptions and Limitations
- Assumes English-language PDFs that OCR can read.  
- Redaction is **word-level**. If OCR splits/merges tokens oddly, boxes may misalign.  
- Doesn’t redact handwriting or embedded images yet.  
- There can be false positives/negatives:
  - Regex sometimes over-matches (random numbers can look like phone numbers).  
  - Gemini may miss tokens if context is split across OCR chunks.  
- Gemini API usage has free request limits — heavy use will hit quotas.  
- Current app is single-user, no login/authentication layer.  

---

## If We Had More Time
- Smarter redaction options: blur, replace with `[EMAIL]`, partial masking.  
- Detect more PII: credit cards, IBANs, passport numbers.  
- Better in-app PDF viewer with search, zoom, and inline highlight editing.  
- Offline mode with a small NER model for no-API environments.  
- Batch processing (whole folders of PDFs).  
- Helm/K8s deployment with CI/CD for Docker images.  

---

## How to Run It Yourself
### Docker
```bash
docker build -t pdf-pii-redactor .
docker run -p 8080:8080 --env-file .env pdf-pii-redactor
