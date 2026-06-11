from sqlalchemy import text

from src.transform._audit_log import log_transform_audit


def _scalar(conn, sql, params=None):
    return conn.execute(text(sql), params or {}).scalar() or 0


def _latest_pre_eligible(conn, module_name, marketplace):
    return _scalar(conn, """
        SELECT row_count
        FROM staging.transform_audit_log
        WHERE phase = 'pre'
          AND module_name = :module_name
          AND marketplace = :marketplace
          AND check_name = 'eligible_grains'
        ORDER BY detected_at DESC, audit_id DESC
        LIMIT 1
    """, {
        "module_name": module_name,
        "marketplace": marketplace,
    })


def _severity_for_count(row_count):
    return "ERROR" if row_count else "INFO"


def _columns_csv(columns):
    return ", ".join(columns)


def post_audit_fact_table(
    conn,
    module_name,
    marketplace,
    table_name,
    grain_columns,
    required_columns,
    rowcount,
):
    rows_affected = rowcount if rowcount is not None and rowcount >= 0 else 0
    eligible_grains = _latest_pre_eligible(conn, module_name, marketplace)

    log_transform_audit(
        conn,
        "post",
        module_name,
        marketplace,
        "INFO",
        "rows_affected",
        rows_affected,
        "Jumlah baris yang dilaporkan insert/update/delete oleh query transform.",
    )

    severity = "ERROR" if eligible_grains and not rows_affected else "INFO"
    log_transform_audit(
        conn,
        "post",
        module_name,
        marketplace,
        severity,
        "eligible_but_zero_rows_affected",
        1 if eligible_grains and not rows_affected else 0,
        "Eligible staging ada tetapi query transform menghasilkan 0 affected row.",
    )

    grain_csv = _columns_csv(grain_columns)
    duplicate_grain = _scalar(conn, f"""
        SELECT COALESCE(SUM(cnt - 1), 0)
        FROM (
            SELECT COUNT(*) AS cnt
            FROM public.{table_name}
            WHERE source_marketplace = :marketplace
            GROUP BY {grain_csv}
            HAVING COUNT(*) > 1
        ) d
    """, {"marketplace": marketplace})
    log_transform_audit(
        conn,
        "post",
        module_name,
        marketplace,
        _severity_for_count(duplicate_grain),
        "duplicate_public_grain",
        duplicate_grain,
        f"Baris ekstra dengan grain public duplikat pada ({grain_csv}).",
    )

    if required_columns:
        null_condition = " OR ".join(f"{column_name} IS NULL" for column_name in required_columns)
        null_required = _scalar(conn, f"""
            SELECT COUNT(*)
            FROM public.{table_name}
            WHERE source_marketplace = :marketplace
              AND ({null_condition})
        """, {"marketplace": marketplace})
        log_transform_audit(
            conn,
            "post",
            module_name,
            marketplace,
            _severity_for_count(null_required),
            "null_required_public_columns",
            null_required,
            f"Baris public dengan NULL di kolom wajib: {', '.join(required_columns)}.",
        )
