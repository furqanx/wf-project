import os
import requests
import hashlib
import base64

class CrewdibleAuthHelper:
    def __init__(self, client_id, client_secret, email, password):
        self.base_url = "https://oms-beta.api.crewdible.com/api/bites"
        self.client_id = client_id
        self.client_secret = client_secret
        self.email = email
        self.password = password

    def _get_api_token(self):
        auth_str = f"{self.client_id}:{self.client_secret}"
        encoded_auth = base64.b64encode(auth_str.encode()).decode()
        
        headers = {
            "Authorization": f"Basic {encoded_auth}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        payload = {"grant_type": "client_credentials"}
        
        response = requests.post(f"{self.base_url}/oauth/token", headers=headers, data=payload)
        response.raise_for_status()
        return response.json().get("access_token")

    def _get_login_token(self, api_token):
        password_md5 = hashlib.md5(self.password.encode()).hexdigest()
        
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "email": self.email,
            "password": password_md5
        }
        
        response = requests.post(f"{self.base_url}/users/login", headers=headers, json=payload)
        response.raise_for_status()
        return response.json().get("data", {}).get("token")

    def get_auth_headers(self):
        """Menghasilkan kombinasi header final untuk request API Crewdible"""
        api_token = self._get_api_token()
        login_token = self._get_login_token(api_token)
        
        return {
            "Authorization": f"Bearer {api_token}",
            "X-CREW-TOKEN": login_token,
            "Content-Type": "application/json"
        }