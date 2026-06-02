"""Magic Link Authentication Service"""

import logging
import os
import secrets
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import redis.asyncio as redis
from pydantic import BaseModel, EmailStr

logger = logging.getLogger(__name__)


class MagicLinkRequest(BaseModel):
    email: EmailStr


class MagicLinkService:
    """Service for handling Magic Link authentication"""

    def __init__(self, redis_client: Optional[redis.Redis] = None):
        """Initialize Magic Link service"""
        self.redis = redis_client
        self.token_expiry = 15 * 60  # 15 minutes
        self.frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
        self.email_from = os.getenv("EMAIL_FROM", "noreply@brain-researcher.ai")

        # Email configuration
        self.smtp_host = os.getenv("EMAIL_SERVER_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("EMAIL_SERVER_PORT", "587"))
        self.smtp_user = os.getenv("EMAIL_SERVER_USER")
        self.smtp_pass = os.getenv("EMAIL_SERVER_PASSWORD")

        # In-memory storage fallback if Redis not available
        self.memory_store = {} if not redis_client else None

    async def generate_magic_link(self, email: str) -> str:
        """Generate a secure magic link token"""
        token = secrets.token_urlsafe(32)

        if self.redis:
            # Store in Redis with expiry
            await self.redis.setex(f"magic_link:{token}", self.token_expiry, email)
        else:
            # Fallback to in-memory storage
            expiry_time = datetime.utcnow() + timedelta(seconds=self.token_expiry)
            self.memory_store[token] = {"email": email, "expires_at": expiry_time}
            # Clean up expired tokens
            self._cleanup_expired_tokens()

        return f"{self.frontend_url}/auth/verify?token={token}"

    async def verify_magic_link(self, token: str) -> Optional[str]:
        """Verify a magic link token and return the associated email"""
        if self.redis:
            key = f"magic_link:{token}"
            email = await self.redis.get(key)

            if email:
                # Delete token after use (one-time use)
                await self.redis.delete(key)
                return email.decode("utf-8") if isinstance(email, bytes) else email
        else:
            # Fallback to in-memory storage
            if token in self.memory_store:
                token_data = self.memory_store[token]
                if datetime.utcnow() < token_data["expires_at"]:
                    email = token_data["email"]
                    # Delete token after use
                    del self.memory_store[token]
                    return email
                else:
                    # Token expired
                    del self.memory_store[token]

        return None

    def _cleanup_expired_tokens(self):
        """Clean up expired tokens from memory store"""
        if not self.memory_store:
            return

        now = datetime.utcnow()
        expired_tokens = [
            token
            for token, data in self.memory_store.items()
            if data["expires_at"] <= now
        ]

        for token in expired_tokens:
            del self.memory_store[token]

    async def send_magic_link(self, email: str) -> bool:
        """Send magic link email to user"""
        try:
            # Generate the magic link
            link = await self.generate_magic_link(email)

            # Create email message
            message = MIMEMultipart("alternative")
            message["Subject"] = "Login to Brain Researcher"
            message["From"] = self.email_from
            message["To"] = email

            # HTML content
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                    .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
                    .header {{ background: linear-gradient(to right, #3b82f6, #8b5cf6); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                    .content {{ background: white; padding: 30px; border: 1px solid #ddd; border-radius: 0 0 10px 10px; }}
                    .button {{ display: inline-block; padding: 12px 30px; background: #3b82f6; color: white; text-decoration: none; border-radius: 6px; font-weight: bold; margin: 20px 0; }}
                    .footer {{ margin-top: 20px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #666; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>Brain Researcher</h1>
                    </div>
                    <div class="content">
                        <h2>Login Request</h2>
                        <p>Click the button below to securely login to Brain Researcher:</p>
                        <div style="text-align: center;">
                            <a href="{link}" class="button">Login to Brain Researcher</a>
                        </div>
                        <p style="font-size: 14px; color: #666;">This link will expire in 15 minutes for your security.</p>
                        <p style="font-size: 14px; color: #666;">If you didn't request this login link, you can safely ignore this email.</p>
                        <div class="footer">
                            <p>Or copy and paste this link into your browser:</p>
                            <p style="word-break: break-all; color: #3b82f6;">{link}</p>
                        </div>
                    </div>
                </div>
            </body>
            </html>
            """

            # Plain text content (fallback)
            text_content = f"""
            Login to Brain Researcher

            Click the following link to login:
            {link}

            This link will expire in 15 minutes.

            If you didn't request this login link, you can safely ignore this email.
            """

            # Attach parts
            part1 = MIMEText(text_content, "plain")
            part2 = MIMEText(html_content, "html")
            message.attach(part1)
            message.attach(part2)

            # Send email
            if self.smtp_user and self.smtp_pass:
                with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                    server.starttls()
                    server.login(self.smtp_user, self.smtp_pass)
                    server.send_message(message)

                logger.info(f"Magic link sent to {email}")
                return True
            else:
                # Development mode - just log the link
                logger.warning(f"Email not configured. Magic link for {email}: {link}")
                return True

        except Exception as e:
            logger.error(f"Failed to send magic link to {email}: {str(e)}")
            return False

    async def rate_limit_check(self, email: str) -> bool:
        """Check if email has exceeded rate limit for magic link requests"""
        if not self.redis:
            return True  # No rate limiting without Redis

        key = f"magic_link_rate:{email}"
        count = await self.redis.get(key)

        if count:
            count = int(count)
            if count >= 3:  # Max 3 requests per hour
                return False

        # Increment counter with 1 hour expiry
        pipe = self.redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, 3600)  # 1 hour
        await pipe.execute()

        return True
