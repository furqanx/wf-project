import hmac
import hashlib
import base64
import requests
from datetime import datetime

class AccurateAuthHelper:
    def __init__(self, api_token: str, signature_secret: str):
        """
        Inisialisasi helper dengan API Token dan Signature Secret dari Area Developer Accurate.
        """
        self.api_token = api_token
        self.signature_secret = signature_secret
        self.auth_gateway_url = "https://account.accurate.id/api/api-token.do"

    def _generate_timestamp(self) -> str:
        """
        Menghasilkan timestamp dengan format dd/mm/yyyy HH:MM:SS sesuai standar Accurate.
        """
        return datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    def _generate_signature(self, timestamp: str) -> str:
        """
        Menghasilkan X-Api-Signature menggunakan HMAC-SHA256 dari Timestamp,
        lalu di-encode menggunakan Base64.
        """
        secret = self.signature_secret.encode('utf-8')
        message = timestamp.encode('utf-8')

        # Enkripsi HMAC-SHA256
        hash_digest = hmac.new(secret, message, hashlib.sha256).digest()

        # Base64 Encode
        signature = base64.b64encode(hash_digest).decode('utf-8')
        return signature

    def get_auth_headers(self) -> dict:
        """
        Membangun 3 Header pilar utama untuk setiap request API Accurate.
        """
        timestamp = self._generate_timestamp()
        signature = self._generate_signature(timestamp)

        return {
            "Authorization": f"Bearer {self.api_token}",
            "X-Api-Timestamp": timestamp,
            "X-Api-Signature": signature
        }

    def get_dynamic_host(self) -> str:
        """
        Memanggil /api-token.do untuk mendapatkan URL Host spesifik milik Data Usaha.
        Host ini akan menjadi Base URL untuk penarikan data operasional.
        """
        headers = self.get_auth_headers()

        try:
            # Memanggil API gateway untuk mendapatkan host
            response = requests.post(self.auth_gateway_url, headers=headers)
            response.raise_for_status()

            result = response.json()

            # Memastikan response sukses (s: true) dan mengambil nilai 'host'
            if result.get("s"):
                host = result.get("d", {}).get("database", {}).get("host")
                if not host:
                    raise ValueError("URL Host tidak ditemukan dalam response Accurate.")
                return host
            else:
                raise ValueError(f"Gagal mendapatkan Host Accurate: {result}")

        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Gagal memanggil API Accurate Gateway: {e}")
