"""
2FA (Two-Factor Authentication) management endpoints
"""
from fastapi import APIRouter, HTTPException, Form, Cookie
from lib.database import Database
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from utils.session_utils import get_account_uuid_from_session
from utils.two_factor_auth import TwoFactorAuth
import json

router = APIRouter(
    prefix="/2fa",
    tags=["Two-Factor Authentication"],
)

db = Database()
table = db.tables

@router.post("/setup", tags=["Setup 2FA"])
async def setup_2fa(
    session_token: str = Cookie(None, alias="session_token"),
):
    """
    Generate TOTP secret and QR code for 2FA setup
    """
    session = db.session
    
    # Validate session token
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")
    
    # Get account_uuid from session
    account_uuid = get_account_uuid_from_session(session_token)
    if not account_uuid:
        raise HTTPException(status_code=401, detail="Invalid session token")
    
    try:
        # Get account details
        account_stmt = select(table["account"]).where(table["account"].c.uuid == account_uuid)
        account_result = session.execute(account_stmt).first()
        if not account_result:
            raise HTTPException(status_code=404, detail="Account not found")
        
        account = account_result._mapping
        
        # Check if 2FA is already enabled
        if account["two_factor_enabled"]:
            raise HTTPException(status_code=400, detail="2FA is already enabled for this account")
        
        # Generate new TOTP secret
        secret = TwoFactorAuth.generate_secret()
        
        # Generate QR code
        qr_code_base64 = TwoFactorAuth.generate_qr_code(
            email=account["email"],
            secret=secret,
            issuer_name="OpenCircle"
        )
        
        # Generate backup codes
        backup_codes = TwoFactorAuth.generate_backup_codes()
        backup_codes_json = TwoFactorAuth.format_backup_codes(backup_codes)
        
        # Store the secret temporarily (not enabled yet)
        update_stmt = (
            update(table["account"])
            .where(table["account"].c.uuid == account_uuid)
            .values(
                totp_secret=secret,
                backup_codes=backup_codes_json
            )
        )
        session.execute(update_stmt)
        session.commit()
        
        return {
            "secret": secret,
            "qr_code": qr_code_base64,
            "backup_codes": backup_codes,
            "message": "2FA setup initiated. Use the QR code to configure your authenticator app, then verify with a token to enable 2FA."
        }
        
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.post("/enable", tags=["Enable 2FA"])
async def enable_2fa(
    totp_token: str = Form(..., description="6-digit TOTP token from authenticator app"),
    session_token: str = Cookie(None, alias="session_token"),
):
    """
    Enable 2FA by verifying TOTP token
    """
    session = db.session
    
    # Validate session token
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")
    
    # Get account_uuid from session
    account_uuid = get_account_uuid_from_session(session_token)
    if not account_uuid:
        raise HTTPException(status_code=401, detail="Invalid session token")
    
    try:
        # Get account details
        account_stmt = select(table["account"]).where(table["account"].c.uuid == account_uuid)
        account_result = session.execute(account_stmt).first()
        if not account_result:
            raise HTTPException(status_code=404, detail="Account not found")
        
        account = account_result._mapping
        
        # Check if 2FA is already enabled
        if account["two_factor_enabled"]:
            raise HTTPException(status_code=400, detail="2FA is already enabled for this account")
        
        # Check if TOTP secret exists
        if not account["totp_secret"]:
            raise HTTPException(status_code=400, detail="2FA setup not initiated. Please call /2fa/setup first.")
        
        # Verify TOTP token
        if not TwoFactorAuth.verify_totp(account["totp_secret"], totp_token):
            raise HTTPException(status_code=400, detail="Invalid TOTP token")
        
        # Enable 2FA
        update_stmt = (
            update(table["account"])
            .where(table["account"].c.uuid == account_uuid)
            .values(two_factor_enabled=True)
        )
        session.execute(update_stmt)
        session.commit()
        
        return {
            "message": "2FA has been successfully enabled for your account",
            "backup_codes": TwoFactorAuth.get_backup_codes_list(account["backup_codes"])
        }
        
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.post("/disable", tags=["Disable 2FA"])
async def disable_2fa(
    totp_token: str = Form(..., description="6-digit TOTP token or backup code"),
    session_token: str = Cookie(None, alias="session_token"),
):
    """
    Disable 2FA by verifying TOTP token or backup code
    """
    session = db.session
    
    # Validate session token
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")
    
    # Get account_uuid from session
    account_uuid = get_account_uuid_from_session(session_token)
    if not account_uuid:
        raise HTTPException(status_code=401, detail="Invalid session token")
    
    try:
        # Get account details
        account_stmt = select(table["account"]).where(table["account"].c.uuid == account_uuid)
        account_result = session.execute(account_stmt).first()
        if not account_result:
            raise HTTPException(status_code=404, detail="Account not found")
        
        account = account_result._mapping
        
        # Check if 2FA is enabled
        if not account["two_factor_enabled"]:
            raise HTTPException(status_code=400, detail="2FA is not enabled for this account")
        
        # Try TOTP first, then backup code
        is_valid = False
        updated_backup_codes = account["backup_codes"]
        
        if len(totp_token) == 6 and totp_token.isdigit():
            # Verify TOTP token
            is_valid = TwoFactorAuth.verify_totp(account["totp_secret"], totp_token)
        else:
            # Try backup code
            is_valid, updated_backup_codes = TwoFactorAuth.verify_backup_code(
                account["backup_codes"], totp_token
            )
        
        if not is_valid:
            raise HTTPException(status_code=400, detail="Invalid TOTP token or backup code")
        
        # Disable 2FA and clear secrets
        update_stmt = (
            update(table["account"])
            .where(table["account"].c.uuid == account_uuid)
            .values(
                two_factor_enabled=False,
                totp_secret=None,
                backup_codes=None
            )
        )
        session.execute(update_stmt)
        session.commit()
        
        return {"message": "2FA has been successfully disabled for your account"}
        
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.get("/status", tags=["Get 2FA Status"])
async def get_2fa_status(
    session_token: str = Cookie(None, alias="session_token"),
):
    """
    Get 2FA status for current account
    """
    session = db.session
    
    # Validate session token
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")
    
    # Get account_uuid from session
    account_uuid = get_account_uuid_from_session(session_token)
    if not account_uuid:
        raise HTTPException(status_code=401, detail="Invalid session token")
    
    try:
        # Get account details
        account_stmt = select(table["account"]).where(table["account"].c.uuid == account_uuid)
        account_result = session.execute(account_stmt).first()
        if not account_result:
            raise HTTPException(status_code=404, detail="Account not found")
        
        account = account_result._mapping
        
        return {
            "two_factor_enabled": bool(account["two_factor_enabled"]),
            "backup_codes_count": len(TwoFactorAuth.get_backup_codes_list(account["backup_codes"])) if account["backup_codes"] else 0
        }
        
    except SQLAlchemyError as e:
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@router.post("/regenerate-backup-codes", tags=["Regenerate Backup Codes"])
async def regenerate_backup_codes(
    totp_token: str = Form(..., description="6-digit TOTP token from authenticator app"),
    session_token: str = Cookie(None, alias="session_token"),
):
    """
    Regenerate backup codes (requires TOTP verification)
    """
    session = db.session
    
    # Validate session token
    if not session_token:
        raise HTTPException(status_code=401, detail="Session token missing")
    
    # Get account_uuid from session
    account_uuid = get_account_uuid_from_session(session_token)
    if not account_uuid:
        raise HTTPException(status_code=401, detail="Invalid session token")
    
    try:
        # Get account details
        account_stmt = select(table["account"]).where(table["account"].c.uuid == account_uuid)
        account_result = session.execute(account_stmt).first()
        if not account_result:
            raise HTTPException(status_code=404, detail="Account not found")
        
        account = account_result._mapping
        
        # Check if 2FA is enabled
        if not account["two_factor_enabled"]:
            raise HTTPException(status_code=400, detail="2FA is not enabled for this account")
        
        # Verify TOTP token
        if not TwoFactorAuth.verify_totp(account["totp_secret"], totp_token):
            raise HTTPException(status_code=400, detail="Invalid TOTP token")
        
        # Generate new backup codes
        backup_codes = TwoFactorAuth.generate_backup_codes()
        backup_codes_json = TwoFactorAuth.format_backup_codes(backup_codes)
        
        # Update backup codes
        update_stmt = (
            update(table["account"])
            .where(table["account"].c.uuid == account_uuid)
            .values(backup_codes=backup_codes_json)
        )
        session.execute(update_stmt)
        session.commit()
        
        return {
            "backup_codes": backup_codes,
            "message": "New backup codes have been generated. Please store them securely."
        }
        
    except SQLAlchemyError as e:
        session.rollback()
        raise HTTPException(status_code=500, detail="Database error: " + str(e))
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()