""" This module contains the SessionManager class, which is responsible for managing the sessions of the Smartcar API."""
from __future__ import annotations
from typing import TYPE_CHECKING

from enum import Enum

import hashlib
import logging

from carconnectivity_connectors.smartcar.auth.smartcar_session import SmartcarSession

if TYPE_CHECKING:
    from typing import Dict, Any, Optional

LOG = logging.getLogger("carconnectivity.connectors.smartcar.auth")


class SessionCredentials():
    """
    A class to represent a session client with a client_id and client_secret.

    Methods:
    -------
    __str__():
        Returns a string representation of the session user in the format 'username:password'.
    """
    def __init__(self, client_id: str, client_secret: str) -> None:
        self.client_id: str = client_id
        self.client_secret: str = client_secret

    def __str__(self) -> str:
        return f'{self.client_id}:{self.client_secret}'


class Service(Enum):
    """
    Enum class representing different services.

    Attributes:
        SMARTCAR (str): Represents the Smartcar service.
    """
    SMARTCAR = 'Smartcar'

    def __str__(self) -> str:
        return self.value


class SessionManager():
    """
    Manages sessions for car connectivity services, specifically for Smartcar.
    """
    def __init__(self, tokenstore: Dict[str, Any], cache:  Dict[str, Any]) -> None:
        self.tokenstore: Dict[str, Any] = tokenstore
        self.cache: Dict[str, Any] = cache
        self.sessions: dict[tuple[Service, SessionCredentials], SmartcarSession] = {}

    @staticmethod
    def generate_hash(service: Service, session_credentials: SessionCredentials) -> str:
        """
        Generates a SHA-512 hash for the given service and session credentials.

        Args:
            service (Service): The service for which the hash is being generated.
            session_credentials (SessionCredentials): The session credentials to be included in the hash.

        Returns:
            str: The generated SHA-512 hash as a hexadecimal string.
        """
        hash_str: str = service.value + str(session_credentials)
        return hashlib.sha512(hash_str.encode()).hexdigest()

    @staticmethod
    def generate_identifier(service: Service, session_credentials: SessionCredentials) -> str:
        """
        Generates a unique identifier for a given service and session credentials.

        Args:
            service (Service): The service for which the identifier is being generated.
            session_credentials (SessionCredentials): The session credentials associated with the service.

        Returns:
            str: A unique identifier string for the service and session credentials.
        """
        return 'CarConnectivity-connector-smartcar:' + SessionManager.generate_hash(service, session_credentials)

    def get_session(self, service: Service, session_credentials: SessionCredentials, code: Optional[str]) -> SmartcarSession:
        """
        Retrieve or create a session for the given service and session credentials.

        Args:
            service (Service): The service for which the session is being requested.
            session_credentials (SessionCredentials): The credentials for the session.
            code (Optional[str]): An optional authorization code.

        Returns:
            SmartcarSession: The session object for the given service and credentials.
        """
        session = None
        if (service, session_credentials) in self.sessions:
            return self.sessions[(service, session_credentials)]

        identifier: str = SessionManager.generate_identifier(service, session_credentials)
        token = None
        metadata = {}

        if identifier in self.tokenstore:
            if 'token' in self.tokenstore[identifier]:
                LOG.info('Reusing tokens from previous session')
                token = self.tokenstore[identifier]['token']
            if 'metadata' in self.tokenstore[identifier]:
                metadata = self.tokenstore[identifier]['metadata']

        if service == Service.SMARTCAR:
            session = SmartcarSession(session_credentials=session_credentials, token=token, metadata=metadata, code=code)
        self.sessions[(service, session_credentials)] = session
        return session

    def persist(self) -> None:
        """
        Persist the current sessions to the token store.

        This method iterates over the sessions and stores the token and metadata
        for each session in the token store if the session has a token.

        The identifier for each session is generated using the service and user
        information.

        Returns:
            None
        """
        for (service, user), session in self.sessions.items():
            if session.token is not None:
                identifier: str = SessionManager.generate_identifier(service, user)
                self.tokenstore[identifier] = {}
                self.tokenstore[identifier]['token'] = session.token
                self.tokenstore[identifier]['metadata'] = session.metadata
