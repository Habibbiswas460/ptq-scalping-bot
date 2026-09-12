"""Authentication: login (TOTP), token refresh, logout, profile/funds.

Mixed into AngelOneClient — methods here read/write self.smart_api, self.auth_token,
self.refresh_token, self.feed_token, self.is_logged_in, self.login_time, and the
credentials (self.api_key/client_id/password/totp_secret) set up in AngelOneClient.__init__,
and call self._rate_limit()/self._ensure_logged_in() from market_data_rest.py and
self.stop_websocket() from websocket_client.py — all mixed into the same instance.
"""

from datetime import datetime
from typing import Dict

import pyotp

try:
    from SmartApi import SmartConnect
except ImportError:
    SmartConnect = None

from .exceptions import AngelOneApiError, AngelOneLoginError


class AuthMixin:

    def login(self) -> bool:
        """
        Login to Angel One SmartAPI

        Returns:
            True if login successful

        Raises:
            AngelOneLoginError on failure
        """
        if SmartConnect is None:
            raise AngelOneLoginError("smartapi-python not installed. Run: pip install smartapi-python")

        self._rate_limit('login')
        self.logger.info("🔐 Logging in to Angel One SmartAPI...")

        try:
            self.smart_api = SmartConnect(api_key=self.api_key)

            # Generate TOTP
            totp = pyotp.TOTP(self.totp_secret).now()

            # Login
            data = self.smart_api.generateSession(
                self.client_id,
                self.password,
                totp
            )

            if data and data.get('status'):
                self.auth_token = data['data']['jwtToken']
                self.refresh_token = data['data']['refreshToken']
                self.feed_token = self.smart_api.getfeedToken()
                self.is_logged_in = True
                self.login_time = datetime.now()

                self.logger.info("✅ Angel One login successful")
                return True
            else:
                error_msg = data.get('message', 'Unknown error') if data else 'No response'
                raise AngelOneLoginError(f"Login failed: {error_msg}")

        except AngelOneLoginError:
            raise
        except Exception as e:
            self.logger.error(f"❌ Login error: {e}")
            raise AngelOneLoginError(f"Login error: {str(e)}")

    def refresh_tokens(self) -> bool:
        """
        Refresh JWT tokens when expired

        Returns:
            True if refresh successful
        """
        self._rate_limit('generateTokens')

        if not self.refresh_token:
            self.logger.warning("No refresh token available, need full login")
            return False

        try:
            data = self.smart_api.generateToken(self.refresh_token)

            if data and data.get('status'):
                self.auth_token = data['data']['jwtToken']
                self.refresh_token = data['data']['refreshToken']
                self.feed_token = data['data'].get('feedToken', self.feed_token)
                self.logger.info("🔄 Tokens refreshed successfully")
                return True
            else:
                self.logger.error(f"Token refresh failed: {data.get('message')}")
                return False

        except Exception as e:
            self.logger.error(f"Token refresh error: {e}")
            return False

    def logout(self) -> bool:
        """
        Logout from Angel One

        Returns:
            True if logout successful
        """
        self.logger.info("👋 Logging out from Angel One...")

        try:
            # Stop WebSocket
            self.stop_websocket()

            # Terminate session
            if self.smart_api and self.is_logged_in:
                self.smart_api.terminateSession(self.client_id)

            self.is_logged_in = False
            self.auth_token = None
            self.refresh_token = None
            self.feed_token = None

            self.logger.info("✅ Logged out successfully")
            return True

        except Exception as e:
            self.logger.error(f"Logout error: {e}")
            return False

    def get_profile(self) -> Dict:
        """
        Get user profile information

        Returns:
            User profile data
        """
        self._rate_limit('getProfile')
        self._ensure_logged_in()

        try:
            data = self.smart_api.getProfile(self.auth_token)
            if data and data.get('status'):
                return data['data']
            raise AngelOneApiError(f"Profile fetch failed: {data.get('message')}")
        except AngelOneApiError:
            raise
        except Exception as e:
            raise AngelOneApiError(f"Profile error: {str(e)}")

    def get_funds(self) -> Dict:
        """
        Get RMS (Risk Management System) funds and margins

        Returns:
            Funds data including available cash, margins, etc.
        """
        self._rate_limit('getRMS')
        self._ensure_logged_in()

        try:
            data = self.smart_api.rmsLimit()
            if data and data.get('status'):
                return data['data']
            raise AngelOneApiError(f"Funds fetch failed: {data.get('message')}")
        except AngelOneApiError:
            raise
        except Exception as e:
            raise AngelOneApiError(f"Funds error: {str(e)}")
