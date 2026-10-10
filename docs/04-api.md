# 4. API design

Base URL: `http://127.0.0.1:8000` locally. In deployment, use HTTPS. The live machine-readable contract is `/openapi.json`; the generated snapshot is `docs/openapi.json`. Swagger UI is `/docs`. All data routes require `Authorization: Bearer <TRIAGE_API_TOKEN>`; the single credential represents one trusted adjuster tenant. Do not put credentials in query strings. The API intentionally has no model-callable decision tool.

| Method | Path | Input | Success |
|---|---|---|---|
| GET | `/health` | None; unauthenticated | 200 mode/status/synthetic |
| POST | `/sessions` | No body | 201 new `session_id` |
| GET | `/sessions/{session_id}/messages` | Session ID | 200 latest 100 messages in chronological order |
| GET | `/sessions/{session_id}/batches` | Session ID | 200 latest 100 saved batch summaries, newest first; supports UI resume/timeout recovery |
| POST | `/sessions/{session_id}/batches` | `synthetic: true`, `claims: object[]` | 201 triage evidence and pending human gate |
| POST | `/sessions/{session_id}/uploads?format=csv&synthetic=true` | Raw UTF-8 CSV/JSON body; `format=csv` or `json` | 201 same batch response |
| GET | `/sessions/{session_id}/batches/{batch_id}` | IDs | 200 evidence, audit events and human review overlays |
| POST | `/sessions/{session_id}/chat` | `message`, optional `claims` and `synthetic` for triage | 200 routed reply or batch |
| POST | `/sessions/{session_id}/batches/{batch_id}/reviews/{row_index}` | `decision`, `note` | 200 recorded human decision |

Request models reject unknown top-level fields. All request bodies are capped at one MiB, including chunked uploads. A batch has 1–100 object rows. Missing/invalid row fields become intake issues; malformed envelopes/files are rejected. CSV must have exactly the seven unique headers from the sample; JSON cannot contain duplicate keys or NaN/Infinity. Use strings for decimal amounts when preserving exact external numeric formatting matters. Row indexes are zero-based and preserve input order even though coverage runs chronologically.

## PowerShell example

```powershell
$headers = @{ Authorization = "Bearer $env:TRIAGE_API_TOKEN" }
$session = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/sessions -Headers $headers
$claims = Get-Content data/claims.json -Raw | ConvertFrom-Json
$body = @{ synthetic = $true; claims = $claims } | ConvertTo-Json -Depth 20
$batch = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/sessions/$($session.session_id)/batches" -Headers $headers -ContentType application/json -Body $body
$question = @{ message = "why was claim C2031 flagged?" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/sessions/$($session.session_id)/chat" -Headers $headers -ContentType application/json -Body $question
$review = @{ decision = "investigate"; note = "Reviewed synthetic history and near-term pattern" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/sessions/$($session.session_id)/batches/$($batch.id)/reviews/0" -Headers $headers -ContentType application/json -Body $review
```

For raw CSV upload use `-InFile data/claims_auto.csv -ContentType text/csv` with the upload endpoint. Multipart form uploads are not used.

## Result contract

```json
{
  "id": "<batch UUID>",
  "session_id": "<session UUID>",
  "mode": "mock",
  "synthetic": true,
  "state": "HUMAN_REVIEW_PENDING",
  "knowledge_version": "<SHA-256>",
  "results": [{
    "row_index": 0,
    "claim_id": "C-2031",
    "intake": {"claim": {}, "issues": [], "valid": true},
    "coverage": {
      "status": "checked",
      "covered": true,
      "issues": [{"code":"similar_history","message":"Earlier similar flagged loss requires review.","field":null,"rule_id":"UW06"}],
      "citations": [{"id":"UW06","title":"Repeated similar flagged losses","text":"<retrieved rule>","source":"knowledge/rules.json#UW06","version":"<SHA-256>"}],
      "history": [], "policy": {}
    },
    "service_issues": [],
    "brief": {"summary":"<grounded synthetic summary>","recommended_action":"route_to_investigator","review_status":"pending","synthetic":true}
  }],
  "events": [{"state":"INTAKE","detail":{"row_count":1}}]
}
```

This abbreviated example shows the shape; actual evidence includes all evaluated citations and complete applicable policy/history. An invalid row has `claim: null`, `valid: false`, and `coverage.status: skipped_invalid_intake`. Such rows are never silently dropped. Monetary values in validated claims are canonical decimal strings. `recommended_action` is `auto_approve`, `route_to_investigator`, or `request_more_documentation`. Review decisions are `approve`, `investigate`, or `request_documentation`. A decision needs a 3–2000 character note. Approval requires a clean original recommendation. Review records are immutable; a second decision returns 409. Once every row is reviewed, the batch becomes `REVIEWED`.

`C2031` and `C-2031` both resolve in conversation. Subsequent “why was it flagged?” uses the session's last discussed claim. A claim from another session is not disclosed through explanation. Long-term policy history is shared within the single tenant. If several rows/batches have the same ID, explanation includes all matching evidence and summarizes the latest row; batch and row identify review targets unambiguously.

## Errors and retry rules

Errors use `{"error":{"code":"stable_code","message":"sanitized explanation"}}`. Request-shape errors additionally identify field locations without echoing values.

| HTTP | Cases | Client handling |
|---|---|---|
| 400 | malformed input, missing synthetic declaration, invalid note/decision | Correct request |
| 401 | Missing/wrong token | Authenticate |
| 404 | Session/batch/row not found in session | Verify IDs |
| 409 | Session busy, lease lost, already reviewed, unsafe approval | Retry busy sessions later; otherwise review evidence |
| 413 | File/body/batch byte limit exceeded | Split input |
| 422 | Invalid Pydantic envelope/path/query shape | Correct indicated fields |
| 503 | Missing knowledge/configuration or deterministic triage failure | Restore dependencies; inspect audit batch |
| 500 | Unexpected persistence/HTTP failure | Inspect sanitized service logs |

An agent outage can still return 201 with deterministic evidence, explicit `service_issues`, and documentation review required. That is a degraded triage result, never an automatic approval. Batch submissions are not idempotency-key APIs: after a response timeout, inspect stored results before resubmitting. Same-session duplicate detection prevents an unmarked repeated clean recommendation, but not duplicate record creation. Production clients should use a durable job/idempotency layer if they need exactly-once submission semantics.
