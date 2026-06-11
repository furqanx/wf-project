from sqlalchemy import text

from src.db_config import logger


def ensure_transform_audit_log(conn):
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS staging.transform_audit_log (
            audit_id    SERIAL PRIMARY KEY,
            detected_at TIMESTAMPTZ DEFAULT NOW(),
            phase       TEXT,
            module_name TEXT,
            marketplace TEXT,
            severity    TEXT,
            check_name  TEXT,
            row_count   BIGINT,
            message     TEXT
        )
    """))
    conn.execute(text("""
        ALTER TABLE staging.transform_audit_log
            ADD COLUMN IF NOT EXISTS detected_at TIMESTAMPTZ DEFAULT NOW(),
            ADD COLUMN IF NOT EXISTS phase TEXT,
            ADD COLUMN IF NOT EXISTS module_name TEXT,
            ADD COLUMN IF NOT EXISTS marketplace TEXT,
            ADD COLUMN IF NOT EXISTS severity TEXT,
            ADD COLUMN IF NOT EXISTS check_name TEXT,
            ADD COLUMN IF NOT EXISTS row_count BIGINT,
            ADD COLUMN IF NOT EXISTS message TEXT
    """))


def log_transform_audit(
    conn,
    phase,
    module_name,
    marketplace,
    severity,
    check_name,
    row_count,
    message,
):
    ensure_transform_audit_log(conn)
    conn.execute(text("""
        INSERT INTO staging.transform_audit_log
            (phase, module_name, marketplace, severity, check_name, row_count, message)
        VALUES
            (:phase, :module_name, :marketplace, :severity, :check_name, :row_count, :message)
    """), {
        "phase": phase,
        "module_name": module_name,
        "marketplace": marketplace,
        "severity": severity,
        "check_name": check_name,
        "row_count": row_count,
        "message": message,
    })

    log_message = (
        f"[AUDIT:{phase}] {module_name}/{marketplace} | "
        f"{severity} | {check_name}={row_count} | {message}"
    )
    if severity == "ERROR":
        logger.error(log_message)
    elif severity == "WARNING":
        logger.warning(log_message)
    else:
        logger.info(log_message)
