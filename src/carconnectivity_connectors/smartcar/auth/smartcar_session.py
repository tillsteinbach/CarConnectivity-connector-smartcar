"""
Module implements the WeConnect Session handling.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

import logging
from datetime import datetime, timezone

import smartcar

from carconnectivity.errors import AuthenticationError

if TYPE_CHECKING:
    from typing import Dict

    from carconnectivity_connectors.smartcar.auth.session_manager import SessionCredentials


LOG: logging.Logger = logging.getLogger("carconnectivity.connectors.smartcar.auth")


class SmartcarSession():
    """
    SmartcarSession class handles the authentication and session management for Smartcar service.
    """
    def __init__(self, session_credentials: SessionCredentials, code, token, metadata) -> None:
        self.token: Dict = token
        if self.token is not None:
            if 'expiration' in self.token and self.token['expiration'] is not None:
                self.token['expiration'] = datetime.fromisoformat(self.token['expiration'])
                if self.token['expiration'].tzinfo is None:
                    self.token['expiration'] = self.token['expiration'].replace(tzinfo=timezone.utc)
            if 'refresh_expiration' in self.token and self.token['refresh_expiration'] is not None:
                self.token['refresh_expiration'] = datetime.fromisoformat(self.token['refresh_expiration'])
                if self.token['refresh_expiration'].tzinfo is None:
                    self.token['refresh_expiration'] = self.token['refresh_expiration'].replace(tzinfo=timezone.utc)
        self.metadata: Dict = metadata
        self.session_credentials: SessionCredentials = session_credentials
        self.code: str = code
        self.auth_client = smartcar.AuthClient(client_id=session_credentials.client_id, client_secret=session_credentials.client_secret,
                                               mode='simulated', redirect_uri='http://localhost:4000')
        self.refresh()

    def login(self):
        """
        Handles the login process for the Smartcar API.

        If the authorization code is not provided, it generates an authentication URL
        with the required scopes and raises an AuthenticationError to prompt the user
        to visit the URL and authenticate.

        If the authorization code is provided, it exchanges the code for an access token
        and sets the token with proper timezone information for expiration and refresh expiration.

        Raises:
            AuthenticationError: If the authorization code is not provided or if there is an error during login.
        """
        if self.code is None or self.code == '':
            scopes: list[str] = ['control_charge', 'control_climate', 'control_navigation', 'control_pin', 'control_security',
                                 'control_trunk', 'read_alerts', 'read_battery', 'read_charge', 'read_climate', 'read_compass', 'read_diagnostics',
                                 'read_engine_oil', 'read_extended_vehicle_info', 'read_fuel', 'read_location', 'read_odometer', 'read_security',
                                 'read_service_history', 'read_speedometer', 'read_thermometer', 'read_tires', 'read_user_profile', 'read_vehicle_info',
                                 'read_vin']
            auth_url = self.auth_client.get_auth_url(scopes)
            raise AuthenticationError(f'Please visit {auth_url} to authenticate and provide code from URL to the configuration')
        else:
            try:
                self.token = self.auth_client.exchange_code(self.code)._asdict()
                if 'expiration' in self.token and self.token['expiration'] is not None and self.token['refresh_expiration'].tzinfo is None:
                    self.token['expiration'] = self.token['expiration'].replace(tzinfo=timezone.utc)
                if 'refresh_expiration' in self.token and self.token['refresh_expiration'] is not None and self.token['refresh_expiration'].tzinfo is None:
                    self.token['refresh_expiration'] = self.token['refresh_expiration'].replace(tzinfo=timezone.utc)

            except smartcar.exception.SmartcarException as e:
                LOG.error('Error during login: %s', e)
                raise AuthenticationError(f'Error during login: {e}') from e

    def refresh(self) -> None:
        """
        Refreshes the authentication token if the refresh token is available and not expired.

        This method checks if the current token contains a refresh token and if it is not expired.
        If the refresh token is valid, it exchanges the refresh token for a new access token.
        It also ensures that the expiration and refresh expiration times are timezone-aware.
        If the refresh token is not available or expired, it triggers the login process.

        Returns:
            None
        """
        return
        LOG.debug('Refreshing token')
        if 'refresh_token' in self.token and self.token['refresh_token'] is not None\
                and 'refresh_expiration' in self.token and self.token['refresh_expiration'] is not None \
                and self.token['refresh_expiration'] > datetime.now(tz=timezone.utc):
            try:
                self.token = self.auth_client.exchange_refresh_token(refresh_token=self.token['refresh_token'])
                if 'expiration' in self.token and self.token['expiration'] is not None and self.token['refresh_expiration'].tzinfo is None:
                    self.token['expiration'] = self.token['expiration'].replace(tzinfo=timezone.utc)
                if 'refresh_expiration' in self.token and self.token['refresh_expiration'] is not None and self.token['refresh_expiration'].tzinfo is None:
                    self.token['refresh_expiration'] = self.token['refresh_expiration'].replace(tzinfo=timezone.utc)
            except smartcar.exception.SmartcarException as e:
                self.login()
        else:
            self.login()

    def get_access_token(self) -> str:
        """
        Retrieves the access token from the current session.

        This method checks if the current token is valid and not expired. If the access token is valid,
        it returns the access token. If the access token is expired but the refresh token is still valid,
        it refreshes the token and returns the new access token. If both tokens are invalid or not present,
        it initiates a new login process to obtain a new access token.

        Returns:
            str: The access token.

        Raises:
            Exception: If unable to obtain a valid access token.
        """
        if self.token is not None:
            if 'access_token' in self.token and self.token['access_token'] is not None \
                    and 'expiration' in self.token and self.token['expiration'] is not None \
                    and self.token['expiration'] > datetime.now(tz=timezone.utc):
                return self.token['access_token']
            if 'refresh_token' in self.token and self.token['refresh_token'] is not None\
                    and 'refresh_expiration' in self.token and self.token['refresh_expiration'] is not None \
                    and self.token['refresh_expiration'] > datetime.now(tz=timezone.utc):
                self.refresh()
                return self.token['access_token']
        self.login()
        return self.token['access_token']
