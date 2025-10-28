"""
Email OTP (One-Time PIN) Utility for OpenCircle

This module provides functionality for generating, sending, and verifying
email-based one-time PINs for account registration verification.
"""

import random
import smtplib
import os
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Tuple, Optional
import logging

# Configure logging
logger = logging.getLogger(__name__)

class EmailOTP:
    """
    Email One-Time PIN utility class for account verification
    """
    
    # OTP configuration
    OTP_LENGTH = 6
    OTP_EXPIRY_MINUTES = 15
    MAX_ATTEMPTS = 5
    
    # Email configuration from environment variables
    SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
    FROM_EMAIL = os.environ.get("FROM_EMAIL", SMTP_USERNAME)
    FROM_NAME = os.environ.get("FROM_NAME", "OpenCircle")
    
    @classmethod
    def generate_otp(cls) -> str:
        """
        Generate a random 6-digit OTP code
        
        Returns:
            str: 6-digit OTP code
        """
        return ''.join([str(random.randint(0, 9)) for _ in range(cls.OTP_LENGTH)])
    
    @classmethod
    def get_otp_expiry(cls) -> datetime:
        """
        Get the expiry time for a new OTP
        
        Returns:
            datetime: UTC timestamp when OTP expires
        """
        return datetime.now(timezone.utc) + timedelta(minutes=cls.OTP_EXPIRY_MINUTES)
    
    @classmethod
    def is_otp_expired(cls, expiry_time: datetime) -> bool:
        """
        Check if an OTP has expired
        
        Args:
            expiry_time (datetime): UTC expiry timestamp
            
        Returns:
            bool: True if expired, False if still valid
        """
        if not expiry_time:
            return True
        
        # Ensure expiry_time is timezone-aware
        if expiry_time.tzinfo is None:
            expiry_time = expiry_time.replace(tzinfo=timezone.utc)
            
        return datetime.now(timezone.utc) > expiry_time
    
    @classmethod
    def verify_otp(cls, provided_otp: str, stored_otp: str, expiry_time: datetime) -> bool:
        """
        Verify an OTP code
        
        Args:
            provided_otp (str): OTP provided by user
            stored_otp (str): OTP stored in database
            expiry_time (datetime): UTC expiry timestamp
            
        Returns:
            bool: True if valid and not expired, False otherwise
        """
        if not provided_otp or not stored_otp:
            return False
        
        # Check if expired
        if cls.is_otp_expired(expiry_time):
            return False
        
        # Check if codes match (case-insensitive for safety)
        return provided_otp.strip().upper() == stored_otp.strip().upper()
    
    @classmethod
    def create_email_content(cls, otp_code: str, account_type: str, name: str) -> Tuple[str, str]:
        """
        Create email subject and HTML content for OTP verification
        
        Args:
            otp_code (str): The OTP code to include
            account_type (str): "user" or "organization"
            name (str): User's name or organization name
            
        Returns:
            Tuple[str, str]: (subject, html_content)
        """
        subject = f"Verify Your OpenCircle {account_type.title()} Account - OTP: {otp_code}"
        
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Email Verification - OpenCircle</title>
            <style>
                body {{
                    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    background-color: #f8f9fa;
                    margin: 0;
                    padding: 20px;
                }}
                .container {{
                    max-width: 600px;
                    margin: 0 auto;
                    background-color: #ffffff;
                    border-radius: 10px;
                    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                    overflow: hidden;
                }}
                .header {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 30px;
                    text-align: center;
                }}
                .header h1 {{
                    margin: 0;
                    font-size: 28px;
                    font-weight: 300;
                }}
                .content {{
                    padding: 40px 30px;
                }}
                .otp-code {{
                    background-color: #f8f9fa;
                    border: 2px dashed #667eea;
                    border-radius: 8px;
                    padding: 20px;
                    text-align: center;
                    margin: 30px 0;
                }}
                .otp-number {{
                    font-size: 36px;
                    font-weight: bold;
                    color: #667eea;
                    letter-spacing: 8px;
                    font-family: 'Courier New', monospace;
                }}
                .warning {{
                    background-color: #fff3cd;
                    border: 1px solid #ffeaa7;
                    border-radius: 6px;
                    padding: 15px;
                    margin: 20px 0;
                    color: #856404;
                }}
                .footer {{
                    background-color: #f8f9fa;
                    padding: 20px 30px;
                    text-align: center;
                    color: #6c757d;
                    font-size: 14px;
                }}
                .button {{
                    display: inline-block;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 12px 30px;
                    text-decoration: none;
                    border-radius: 6px;
                    font-weight: bold;
                    margin: 20px 0;
                }}
                .highlight {{
                    color: #667eea;
                    font-weight: bold;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🎯 OpenCircle</h1>
                    <p>Email Verification Required</p>
                </div>
                
                <div class="content">
                    <h2>Hello {name}! 👋</h2>
                    
                    <p>Welcome to OpenCircle! To complete your <span class="highlight">{account_type}</span> account registration, please verify your email address using the One-Time PIN below:</p>
                    
                    <div class="otp-code">
                        <p style="margin: 0; font-size: 14px; color: #6c757d;">Your Verification Code:</p>
                        <div class="otp-number">{otp_code}</div>
                        <p style="margin: 10px 0 0 0; font-size: 12px; color: #6c757d;">
                            Valid for {cls.OTP_EXPIRY_MINUTES} minutes
                        </p>
                    </div>
                    
                    <p>Please enter this code in the verification form to activate your account and start connecting with your community!</p>
                    
                    <div class="warning">
                        <strong>⚠️ Security Note:</strong>
                        <ul style="margin: 10px 0 0 0; padding-left: 20px;">
                            <li>This code expires in <strong>{cls.OTP_EXPIRY_MINUTES} minutes</strong></li>
                            <li>Do not share this code with anyone</li>
                            <li>If you didn't request this, please ignore this email</li>
                        </ul>
                    </div>
                    
                    <p>Need help? Contact our support team or visit our help center.</p>
                </div>
                
                <div class="footer">
                    <p>This email was sent to verify your OpenCircle account registration.</p>
                    <p>© 2025 OpenCircle. Building communities, one connection at a time.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return subject, html_content
    
    @classmethod
    def send_otp_email(cls, recipient_email: str, otp_code: str, account_type: str, name: str) -> bool:
        """
        Send OTP verification email
        
        Args:
            recipient_email (str): Email address to send OTP to
            otp_code (str): The OTP code to send
            account_type (str): "user" or "organization"
            name (str): User's name or organization name
            
        Returns:
            bool: True if email sent successfully, False otherwise
        """
        try:
            # Check if email configuration is available
            if not cls.SMTP_USERNAME or not cls.SMTP_PASSWORD:
                logger.error("SMTP credentials not configured")
                return False
            
            # Create email content
            subject, html_content = cls.create_email_content(otp_code, account_type, name)
            
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"{cls.FROM_NAME} <{cls.FROM_EMAIL}>"
            msg['To'] = recipient_email
            
            # Create plain text version
            text_content = f"""
            Hello {name}!
            
            Welcome to OpenCircle! To complete your {account_type} account registration, 
            please verify your email address using this One-Time PIN:
            
            Verification Code: {otp_code}
            
            This code expires in {cls.OTP_EXPIRY_MINUTES} minutes.
            
            If you didn't request this, please ignore this email.
            
            © 2025 OpenCircle
            """
            
            # Attach parts
            part1 = MIMEText(text_content, 'plain')
            part2 = MIMEText(html_content, 'html')
            msg.attach(part1)
            msg.attach(part2)
            
            # Send email
            with smtplib.SMTP(cls.SMTP_SERVER, cls.SMTP_PORT) as server:
                server.starttls()
                server.login(cls.SMTP_USERNAME, cls.SMTP_PASSWORD)
                server.send_message(msg)
            
            logger.info(f"OTP email sent successfully to {recipient_email}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send OTP email to {recipient_email}: {str(e)}")
            return False
    
    @classmethod
    def generate_and_send_otp(cls, recipient_email: str, account_type: str, name: str) -> Optional[Tuple[str, datetime]]:
        """
        Generate OTP and send verification email
        
        Args:
            recipient_email (str): Email address to send OTP to
            account_type (str): "user" or "organization"
            name (str): User's name or organization name
            
        Returns:
            Optional[Tuple[str, datetime]]: (otp_code, expiry_time) if successful, None if failed
        """
        try:
            # Generate OTP and expiry time
            otp_code = cls.generate_otp()
            expiry_time = cls.get_otp_expiry()
            
            # Send email
            if cls.send_otp_email(recipient_email, otp_code, account_type, name):
                return otp_code, expiry_time
            else:
                return None
                
        except Exception as e:
            logger.error(f"Failed to generate and send OTP: {str(e)}")
            return None


# For development/testing when SMTP is not configured
class MockEmailOTP(EmailOTP):
    """
    Mock email OTP class for development/testing
    Always returns success and logs OTP to console
    """
    
    @classmethod
    def send_otp_email(cls, recipient_email: str, otp_code: str, account_type: str, name: str) -> bool:
        """Mock email sending - just log the OTP"""
        print(f"\n🔔 [MOCK EMAIL] OTP for {recipient_email}")
        print(f"   Account Type: {account_type}")
        print(f"   Name: {name}")
        print(f"   OTP Code: {otp_code}")
        print(f"   Expires in: {cls.OTP_EXPIRY_MINUTES} minutes")
        print(f"   Subject: Verify Your OpenCircle {account_type.title()} Account - OTP: {otp_code}")
        print("   ✅ Email would be sent in production\n")
        return True


# Use mock email in development if SMTP is not configured
def get_email_otp_service() -> EmailOTP:
    """
    Get the appropriate EmailOTP service based on configuration
    
    Returns:
        EmailOTP: Real or mock email service
    """
    if EmailOTP.SMTP_USERNAME and EmailOTP.SMTP_PASSWORD:
        return EmailOTP()
    else:
        logger.warning("SMTP not configured, using mock email service")
        return MockEmailOTP()