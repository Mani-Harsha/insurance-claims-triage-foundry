# 9. Deployment guide

## Deployment status and prerequisites

Local execution and automated tests are the verified baseline. Live Azure provisioning/inference and a production rollout require a configured subscription/project, model deployment, credentials, access and quota. None were supplied for this implementation. The included opt-in smoke test is the gate for asserting live Foundry compatibility. The installed adapter targets the `azure-ai-agents==1.1.0` threads/runs service contract. Check that the target project supports that contract; do not substitute new Responses SDK types without adapting and testing the runtime.

You need Python 3.11–3.13; for containers Docker with Linux containers. Azure mode additionally requires an existing Foundry project endpoint, a model deployment supporting function tools/file search, and Entra credentials with appropriate project permissions. Follow Microsoft's [Agent Service setup](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/environment-setup) and [SDK prerequisites and authentication](https://learn.microsoft.com/en-us/python/api/overview/azure/ai-agents-readme?view=azure-python). Region, model availability and quota are deployment-specific; this project does not assume a subscription or create chargeable resources during local setup.

## Configure and create Azure agents

Install the frozen dependencies and package as in the README. Authenticate locally with your approved Azure CLI/Entra workflow. In Azure, prefer a managed identity with the minimum project roles documented by Microsoft. Do not store a service-principal password in source control.

```powershell
$env:TRIAGE_MODE = "azure"
$env:TRIAGE_AZURE_ENDPOINT = "https://<resource>.services.ai.azure.com/api/projects/<project>"
$env:TRIAGE_AZURE_MODEL = "<existing-model-deployment-name>"
$env:TRIAGE_DATABASE = "var/azure-claims.db"
.\.venv\Scripts\python.exe -m claims_triage provision
.\.venv\Scripts\python.exe -m claims_triage triage data/claims.json --synthetic
```

Provisioning uploads the synthetic markdown knowledge, creates its vector store, and creates Supervisor, Intake, Coverage and Briefing with code-defined instructions/tools. Each successful resource ID is saved under `metadata.azure_manifest` for resumable setup. Re-running with identical configuration reuses IDs. Do not run provisioning concurrently. If the process dies between a remote creation and saving its ID, inspect the project for an orphan before retrying. If a remote resource was manually deleted, use a fresh deployment profile and clean up orphaned resources deliberately; the application will not silently recreate or delete remote resources during requests.

The fingerprint includes endpoint, model, knowledge version, instructions and tool contracts. A changed fingerprint requires a separate database/profile, protecting previous evidence. Do not reuse an old manifest with a different project. Upload/vector polling has a timeout; each inference run has a configurable 1–120 second deadline, a six-round tool cap and HTTP timeouts. A currently executing HTTP call can finish after the polling deadline; timeout cancellation is best effort. Azure mode reports failed roles and conservatively asks for documentation, with no hidden mock switch.

Verify all roles against your actual service:

```powershell
$env:TRIAGE_RUN_LIVE = "1"
.\.venv\Scripts\python.exe -m pytest tests/test_live_azure.py -m live --basetemp=.pytest-live-tmp
Remove-Item Env:TRIAGE_RUN_LIVE
```

The live test calls Azure and can incur charges. It uses the configured profile and retains evidence/resource IDs for inspection. Review the test before running. For 403, verify identity/project roles and network access; for 404, check deployment and project endpoint; for quota/model errors, resolve access or use explicitly configured `TRIAGE_MODE=mock` for the assignment demonstration. Never alter a subscription's network/security settings merely to make a smoke test pass.

## Container deployment on one host

```powershell
docker build -t claims-triage:1.0.0 .
$env:TRIAGE_API_TOKEN = .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
docker compose up -d
docker compose logs --tail 50 claims
```

The image runs as UID 10001, drops Linux capabilities, uses a read-only root filesystem and mounts a persistent **local** Docker volume at `/app/var`. Compose publishes only `127.0.0.1:8000`. A health check probes `/health`. One worker and one replica are intentional. Do not put SQLite WAL files on Azure Files/NFS or another network filesystem. `docker compose down` preserves the named volume; do not add `--volumes` unless deliberately discarding synthetic state.

For an Azure-hosted deployment, run this container on a hardened Azure Linux VM with a managed disk backing Docker's volume directory and a system-assigned identity authorized for Foundry. Place an HTTPS reverse proxy on that host (or a private ingress path with TLS termination); forward to loopback port 8000. Open only the required HTTPS port to approved client networks; keep direct API access private. Back up the managed disk/database and configure host patching, log collection and restarts. Configure `TRIAGE_MODE`, endpoint and model in the service environment. The container needs outbound access to Entra and the configured Foundry endpoint. Verify managed-identity reachability from the container; do not mount developer credential caches into production.

This guide deliberately uses local managed-disk persistence on a single host. Container Apps/App Service horizontal replicas are not a drop-in target for this SQLite build. To use them, replace the repository with PostgreSQL/Azure SQL, add a distributed lock/job queue, and retest transaction semantics. No unverified infrastructure-as-code template or production cloud rollout is claimed.

## Operations and release procedure

1. Run unit/integration/SDK contract tests, Ruff and mypy. CI also builds the image. Review dependency lock changes.
2. Run the opt-in live smoke in a nonproduction project. Confirm four agents, required tools, indexed knowledge, session thread reuse, citations and no `service_issues`.
3. Provision a release-specific profile; capture the image digest and manifest fingerprint. Keep the previous image and compatible database backup for rollback.
4. Stop writers briefly for a SQLite online backup using Python's `sqlite3.Connection.backup`; restore to a separate file and exercise a read. Never copy only the `.db` file while WAL writes are active.
5. Deploy one replica, mount persistent storage, inject the token from an approved secret store, and terminate TLS. Check `/health`, authenticated batch ingestion, follow-up explanation and review persistence after restart.
6. Send JSON logs to Azure Monitor or the host collector. Alert on repeated `agent_failed`, `request_failed`, `FAILED`, missing citations and a growing pending-review queue. This implementation provides console traces; it does not claim native OpenTelemetry export.
7. Roll back the image and matching profile if validation fails. Schema version 1 is explicitly checked; future schema upgrades need migrations and restore rehearsal.

Use a random API token of at least 24 characters. Rotate it by restarting the service with a new secret and updating trusted clients. All API callers share a tenant/adjuster identity; user-level SSO/RBAC must be added before a broader rollout. Define retention for messages, evidence, history, remote threads, uploads and vector stores; no automatic deletion is implemented. The 100-message read window is not a retention policy. Review notes and model transcripts can contain user text even though application logs are redacted.

The synthetic declaration is not a PII detector. This assignment has no authorization to ingest actual policyholder data. Real insurance deployment additionally needs domain/legal validation, identity governance, retention controls and load/security testing; those cannot be certified by this local test suite.
