"""
2FA (Two-Factor Authentication) utilities using TOTP (Time-based One-Time Password)
"""
import pyotp
import qrcode
import io
import base64
import json
import secrets
from typing import List, Optional, Tuple


class TwoFactorAuth:
    """Handle 2FA operations using TOTP"""
    
    @staticmethod
    def generate_secret() -> str:
        """Generate a new TOTP secret key"""
        return pyotp.random_base32()
    
    @staticmethod
    def generate_qr_code(email: str, secret: str, issuer_name: str = "OpenCircle") -> str:
        """
        Generate QR code for TOTP setup
        Returns base64 encoded PNG image
        """
        # Create TOTP URI
        totp_uri = pyotp.totp.TOTP(secret).provisioning_uri(
            name=email,
            issuer_name=issuer_name
        )
        
        # Generate QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(totp_uri)
        qr.make(fit=True)
        
        # Create image
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Convert to base64
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        
        img_base64 = base64.b64encode(buffer.read()).decode()
        return img_base64
    
    @staticmethod
    def verify_totp(secret: str, token: str) -> bool:
        """Verify TOTP token"""
        totp = pyotp.TOTP(secret)
        return totp.verify(token, valid_window=1)  # Allow 1 window tolerance (30 seconds)
    
    @staticmethod
    def generate_backup_codes(count: int = 10) -> List[str]:
        """Generate backup codes for 2FA recovery"""
        codes = []
        for _ in range(count):
            # Generate 8-character alphanumeric codes
            code = ''.join(secrets.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') for _ in range(8))
            codes.append(code)
        return codes
    
    @staticmethod
    def verify_backup_code(backup_codes_json: str, provided_code: str) -> Tuple[bool, Optional[str]]:
        """
        Verify backup code and remove it from the list
        Returns (is_valid, updated_backup_codes_json)
        """
        try:
            backup_codes = json.loads(backup_codes_json)
            provided_code = provided_code.upper().strip()
            
            if provided_code in backup_codes:
                # Remove the used code
                backup_codes.remove(provided_code)
                updated_json = json.dumps(backup_codes)
                return True, updated_json
            else:
                return False, backup_codes_json
                
        except (json.JSONDecodeError, TypeError):
            return False, backup_codes_json
    
    @staticmethod
    def format_backup_codes(codes: List[str]) -> str:
        """Format backup codes as JSON string for database storage"""
        return json.dumps(codes)
    
    @staticmethod
    def get_backup_codes_list(backup_codes_json: str) -> List[str]:
        """Get backup codes list from JSON string"""
        try:
            return json.loads(backup_codes_json) if backup_codes_json else []
        except (json.JSONDecodeError, TypeError):
            return []