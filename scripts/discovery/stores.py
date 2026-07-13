"""Canonical store names used by normalized marketplace filenames."""

STORE_NAME_BY_MARKETPLACE_AND_SLUG = {
    "lazada": {
        "beras_sehat": "Lazada Beras Sehat",
        "merapi": "Lazada Merapi",
        "official": "Lazada Official",
    },
    "shopee": {
        "bandar_organik": "Shopee Bandar Organik",
        "basecamp_organik": "Shopee Basecamp Organik",
        "beras_diabeta_shop": "Shopee Beras Diabeta Shop",
        "beras_medan_organik": "Shopee Beras Medan Organik",
        "beras_porang_porice": "Shopee Beras Porang Porice",
        "beras_sehat": "Shopee Beras Sehat",
        "bogor_healthy_store": "Shopee Bogor Healthy Store",
        "bromo_organik": "Shopee Bromo Organik",
        "diet_healthy_corner": "Shopee Diet Healthy Corner",
        "indo_porang_market": "Shopee Indo Porang Market",
        "lembah_organik_store": "Shopee Lembah Organik Store",
        "mapan_organik": "Shopee Mapan Organik",
        "medan_organik": "Shopee Medan Organik",
        "mekar_organik": "Shopee Mekar Organik",
        "merapi_organik": "Shopee Merapi Organik",
        "merbabu_organik": "Shopee Merbabu Organik",
        "official": "Shopee Official",
        "organic_groceries": "Shopee Organic Groceries",
        "owellness": "Shopee Owellness",
        "porang_sachet_store": "Shopee Porang Sachet Store",
        "pusat_beras_berkualitas": "Shopee Pusat Beras Berkualitas",
        "solo_organik": "Shopee Solo Organik",
        "solusi_beras_sehat": "Shopee Solusi Beras Sehat",
        "sumber_organik_shop": "Shopee Sumber Organik Shop",
        "sumber_pangan_pokok": "Shopee Sumber Pangan Pokok",
        "trully_organik": "Shopee Trully Organik",
        "wellfarm_id": "Shopee Wellfarm ID",
        "zona_pangan": "Shopee Zona Pangan",
    },
    "tiktok_tokopedia": {
        "basecamp_organik": "TikTok Basecamp Organik",
        "beras_organikid": "TikTok Beras OrganikID",
        "beras_sehat_shop": "TikTok Beras Sehat Shop",
        "bogor_healthy_store": "TikTok Bogor Healthy Store",
        "bromo_organik": "TikTok Bromo Organik",
        "diy_jateng": "TikTok DIY Jateng",
        "merapi_organik": "TikTok Merapi Organik",
        "owellness": "TikTok Owellness",
        "porang_porice": "TikTok Porang Porice",
        "pundi_organik": "TikTok Pundi Organik",
        "wellfarm_id": "TikTok Wellfarm ID",
        "wellfarm_shop": "TikTok Wellfarm Shop",
    },
}


def display_store_name(marketplace: str, store_slug: str) -> str:
    marketplace_names = STORE_NAME_BY_MARKETPLACE_AND_SLUG.get(marketplace, {})
    return marketplace_names.get(store_slug, store_slug.replace("_", " "))

