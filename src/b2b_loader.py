# src/b2b_loader.py

import os
import pandas as pd
from sqlalchemy import text
from src.db_config import logger

_B2B_VALID_TYPES    = {'DISTRIBUTOR', 'KONSIYANSI', 'AGEN', 'AGEN-B', 'COSTUMER', 'SAMPLE'}
_B2B_TYPE_NORMALIZE = {'AGEN-B': 'AGEN'}


def load_dim_b2b_partner(csv_path: str, engine):
    logger.info(f"[LOAD] dim_b2b_partner ← {csv_path}")

    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns={
        'TPY':              'partner_type',
        'Online / Offline': 'channel',
        'Wilayah':          'wilayah',
        'NAMA':             'nama',
        'COMPANYNAME':      'company_name',
        'TITLE':            'title',
        'FIRSTNAME':        'firstname',
        'MIDDLENAME':       'middlename',
        'LASTNAME':         'lastname',
        'EMAIL':            'email',
        'MOBILE':           'mobile',
        'PHONE':            'phone',
        'ALAMAT DO':        'address_do',
    })

    df['partner_type'] = df['partner_type'].str.strip()
    df = df[df['partner_type'].isin(_B2B_VALID_TYPES)].copy()
    df['partner_type'] = df['partner_type'].replace(_B2B_TYPE_NORMALIZE)

    def _build_contact_name(row):
        parts = [row[c].strip() for c in ('title', 'firstname', 'middlename', 'lastname') if row[c].strip()]
        return ' '.join(parts) if parts else None

    df['contact_name'] = df.apply(_build_contact_name, axis=1)

    def _clean(val):
        v = str(val).strip() if val is not None else ''
        return v if v and v.lower() != 'nan' else None

    source_filename = os.path.basename(csv_path)
    records = []
    for _, row in df.iterrows():
        nama_val = _clean(row.get('nama', ''))
        if not nama_val:
            continue
        records.append({
            'partner_type':    _clean(row.get('partner_type')),
            'channel':         _clean(row.get('channel')),
            'wilayah':         _clean(row.get('wilayah')),
            'nama':            nama_val,
            'company_name':    _clean(row.get('company_name')),
            'contact_name':    row.get('contact_name'),
            'email':           _clean(row.get('email')),
            'mobile':          _clean(row.get('mobile')),
            'phone':           _clean(row.get('phone')),
            'address_do':      _clean(row.get('address_do')),
            'source_filename': source_filename,
        })

    logger.info(f"  {len(records)} baris valid dari {len(df)} baris setelah filter.")

    with engine.begin() as conn:
        deleted = conn.execute(
            text("DELETE FROM public.dim_b2b_partner WHERE source_filename = :fn"),
            {'fn': source_filename}
        ).rowcount
        if deleted:
            logger.info(f"  Menghapus {deleted} baris lama.")

        if not records:
            logger.warning("  Tidak ada baris untuk dimasukkan.")
            return

        conn.execute(text("""
            INSERT INTO public.dim_b2b_partner
                (partner_type, channel, wilayah, nama, company_name,
                 contact_name, email, mobile, phone, address_do, source_filename)
            VALUES
                (:partner_type, :channel, :wilayah, :nama, :company_name,
                 :contact_name, :email, :mobile, :phone, :address_do, :source_filename)
        """), records)

    logger.info(f"✅ dim_b2b_partner: {len(records)} baris berhasil dimasukkan.")
