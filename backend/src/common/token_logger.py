"""Token usage logging to BigQuery, with per-user context via ContextVar."""
import datetime, logging, contextvars
log = logging.getLogger("token_logger")
try:
    from google.cloud import bigquery
    _bq = bigquery.Client(project="ltm-craftstudio-poc")
    log.info("TOKENLOG: bigquery client initialized")
except Exception as e:
    _bq = None
    log.warning("TOKENLOG: bq init failed: %s", e)

_TABLE = "ltm-craftstudio-poc.token_usage.usage"
current_user_email = contextvars.ContextVar("current_user_email", default="unknown")

def log_tokens(platform: str, model: str, resp):
    if _bq is None:
        log.warning("TOKENLOG: skip — no bq client"); return
    u = getattr(resp, "usage_metadata", None)
    if u is None:
        log.warning("TOKENLOG: skip — no usage_metadata on resp (type=%s)", type(resp).__name__); return
    row = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "platform": platform,
        "user_email": current_user_email.get() or "unknown",
        "model": str(model),
        "tokens_in": int(getattr(u, "prompt_token_count", 0) or 0),
        "tokens_out": int(getattr(u, "candidates_token_count", 0) or 0),
        "total": int(getattr(u, "total_token_count", 0) or 0),
    }
    try:
        errors = _bq.insert_rows_json(_TABLE, [row])
        if errors:
            log.warning("TOKENLOG: insert errors: %s", errors)   # ← now surfaced!
        else:
            log.info("TOKENLOG: inserted %s tokens for %s", row["total"], model)
    except Exception as e:
        log.warning("TOKENLOG: insert exception: %s", e)
