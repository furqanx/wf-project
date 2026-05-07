import hmac
import hashlib
import json
import requests
import logging

logger = logging.getLogger(__name__)

class BigSellerAuthHelper:
    def __init__(self, app_id, app_key, base_url="https://api.bigseller.com"):
        """
        Inisialisasi helper dengan kredensial utama dari BigSeller.
        """
        self.app_id = app_id
        self.app_key = app_key
        self.base_url = base_url.rstrip('/')

    def generate_signature(self, api_path, params: dict) -> str:
        """
        Menghasilkan signature x-bs-sign menggunakan HMAC-SHA256 berdasarkan 
        pengurutan ASCII parameter sesuai spesifikasi BigSeller.
        """
        # 1. Buang parameter bernilai None atau kosong, dan parameter 'sign'
        filtered_params = {k: v for k, v in params.items() if v not in [None, ""] and k != "sign"}

        # 2. Urutkan parameter berdasarkan nama (kunci) dalam tabel ASCII
        sorted_keys = sorted(filtered_params.keys())

        query_parts = []
        for k in sorted_keys:
            v = filtered_params[k]

            # Jika value berupa dictionary atau list (object/array), ubah menjadi JSON String
            # Pastikan tidak ada spasi ekstra (separators=(',', ':')) agar hash identik dengan Java
            if isinstance(v, (dict, list)):
                v_str = json.dumps(v, separators=(',', ':'))
            else:
                v_str = str(v)

            query_parts.append(f"{k}={v_str}")

        # 3. Gabungkan parameter menjadi format k=v&k=v
        query_string = "&".join(query_parts)
        
        # Pastikan api_path diawali garis miring
        if not api_path.startswith('/'):
            api_path = '/' + api_path
            
        # 4. Rangkai appId + apiName + / + query_string
        string_to_sign = f"{self.app_id}{api_path}/"
        if query_string:
            string_to_sign += query_string
            
        # 5. Enkripsi dengan HMAC_SHA256 menggunakan app_key
        secret = self.app_key.encode('utf-8')
        message = string_to_sign.encode('utf-8')
        
        # 6. Konversi ke hexadecimal huruf kecil
        signature = hmac.new(secret, message, hashlib.sha256).hexdigest().lower()
        
        return signature

    def build_headers(self, api_path, access_token, params: dict) -> dict:
        """
        Membangun header wajib (x-bs-app-id, x-bs-access-token, x-bs-sign)
        untuk setiap panggilan API operasional.
        """
        signature = self.generate_signature(api_path, params)
        
        return {
            "x-bs-app-id": self.app_id,
            "x-bs-access-token": access_token,
            "x-bs-sign": signature,
            "Content-Type": "application/json"
        }

    def refresh_access_token(self, refresh_token: str) -> dict:
        """
        Memperbarui access_token yang kedaluwarsa menggunakan refresh_token.
        """
        api_path = "/api/auth/v1/refreshAccessToken"
        url = f"{self.base_url}{api_path}"
        
        # Payload untuk refresh token 
        payload = {
            "refresh_token": refresh_token
        }
        
        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()
            
            # Response sukses BigSeller memiliki field 'success' bernilai True
            result = response.json()
            if result.get("success"):
                logger.info("Access token berhasil diperbarui.")
                return result.get("data", {})
            else:
                logger.error(f"Gagal refresh token: {result.get('msg')}")
                raise ValueError(result.get('msg'))
                
        except Exception as e:
            logger.error(f"Terjadi kesalahan saat memanggil refreshAccessToken: {e}")
            raise
