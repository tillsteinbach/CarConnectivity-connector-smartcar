"""Module implements the connector to interact with the Smartcar API."""
from __future__ import annotations
from typing import TYPE_CHECKING

import threading

import os
import logging
import netrc
from datetime import datetime, timezone, timedelta

import smartcar

from carconnectivity.garage import Garage
from carconnectivity.errors import AuthenticationError, TooManyRequestsError, RetrievalError, APICompatibilityError, \
    TemporaryAuthenticationError, ConfigurationError
from carconnectivity.util import robust_time_parse, config_remove_credentials
from carconnectivity.units import Length
from carconnectivity.attributes import BooleanAttribute, DurationAttribute
from carconnectivity.commands import Commands

from carconnectivity_connectors.base.connector import BaseConnector
from carconnectivity_connectors.smartcar._version import __version__
from carconnectivity_connectors.smartcar.auth.session_manager import SessionManager, Service, SessionCredentials, SmartcarSession
from carconnectivity_connectors.smartcar.vehicle import SmartcarVehicle


if TYPE_CHECKING:
    from typing import Dict, List, Optional

    from carconnectivity.carconnectivity import CarConnectivity

LOG: logging.Logger = logging.getLogger("carconnectivity.connectors.smartcar")
LOG_API: logging.Logger = logging.getLogger("carconnectivity.connectors.smartcar-api-debug")


# pylint: disable=too-many-lines
class Connector(BaseConnector):
    """
    Connector class for Smartcar API connectivity.
    Args:
        car_connectivity (CarConnectivity): An instance of CarConnectivity.
        config (Dict): Configuration dictionary containing connection details.
    Attributes:
        max_age (Optional[int]): Maximum age for cached data in seconds.
    """
    def __init__(self, connector_id: str, car_connectivity: CarConnectivity, config: Dict) -> None:
        BaseConnector.__init__(self, connector_id=connector_id, car_connectivity=car_connectivity, config=config)

        self._background_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        self.connected: BooleanAttribute = BooleanAttribute(name="connected", parent=self)
        self.interval: DurationAttribute = DurationAttribute(name="interval", parent=self)
        self.commands: Commands = Commands(parent=self)

        # Configure logging
        if 'log_level' in config and config['log_level'] is not None:
            config['log_level'] = config['log_level'].upper()
            if config['log_level'] in logging._nameToLevel:
                LOG.setLevel(config['log_level'])
                self.log_level._set_value(config['log_level'])  # pylint: disable=protected-access
                logging.getLogger('requests').setLevel(config['log_level'])
                logging.getLogger('urllib3').setLevel(config['log_level'])
                logging.getLogger('oauthlib').setLevel(config['log_level'])
            else:
                raise ConfigurationError(f'Invalid log level: "{config["log_level"]}" not in {list(logging._nameToLevel.keys())}')
        if 'api_log_level' in config and config['api_log_level'] is not None:
            config['api_log_level'] = config['api_log_level'].upper()
            if config['api_log_level'] in logging._nameToLevel:
                LOG_API.setLevel(config['api_log_level'])
            else:
                raise ConfigurationError(f'Invalid log level: "{config["log_level"]}" not in {list(logging._nameToLevel.keys())}')
        LOG.info("Loading smartcar connector with config %s", config_remove_credentials(self.config))

        client_id: Optional[str] = None
        client_secret: Optional[str] = None
        if 'client_id' in self.config and 'client_secret' in self.config:
            client_id = self.config['client_id']
            client_secret = self.config['client_secret']
        else:
            if 'netrc' in self.config:
                netrc_filename: str = self.config['netrc']
            else:
                netrc_filename = os.path.join(os.path.expanduser("~"), ".netrc")
            try:
                secrets = netrc.netrc(file=netrc_filename)
                secret: tuple[str, str, str] | None = secrets.authenticators("Smartcar")
                if secret is None:
                    raise AuthenticationError(f'Authentication using {netrc_filename} failed: volkswagen not found in netrc')
                client_id, _, client_secret = secret

            except netrc.NetrcParseError as err:
                LOG.error('Authentification using %s failed: %s', netrc_filename, err)
                raise AuthenticationError(f'Authentication using {netrc_filename} failed: {err}') from err
            except TypeError as err:
                if 'client_id' not in self.config:
                    raise AuthenticationError(f'"Smartcar" entry was not found in {netrc_filename} netrc-file.'
                                              ' Create it or provide client_id and client_secret in config') from err
            except FileNotFoundError as err:
                raise AuthenticationError(f'{netrc_filename} netrc-file was not found. Create it or provide client_id and client_secret in config') from err

        interval: int = 180
        if 'interval' in self.config:
            interval = self.config['interval']
            if interval < 60:
                raise ValueError('Intervall must be at least 60 seconds')
        self.interval._set_value(value=timedelta(seconds=interval))
        self.max_age: int = interval - 1

        if client_id is None or client_secret is None:
            raise AuthenticationError('client_id or client_secret not provided')

        self._elapsed: List[timedelta] = []

        if 'code' in self.config:
            code: Optional[str] = self.config['code']
        else:
            code = None

        self._manager: SessionManager = SessionManager(tokenstore=car_connectivity.get_tokenstore(), cache=car_connectivity.get_cache())
        self.session: SmartcarSession = self._manager.get_session(Service.SMARTCAR, SessionCredentials(client_id=client_id, client_secret=client_secret),
                                                                  code=code)
        if not isinstance(self.session, SmartcarSession):
            raise AuthenticationError('Could not create session')

    def startup(self) -> None:
        self._background_thread = threading.Thread(target=self._background_loop, daemon=False)
        self._background_thread.start()

    def _background_loop(self) -> None:
        self._stop_event.clear()
        first: bool = True
        while not self._stop_event.is_set():
            interval: float = 300
            if self.interval.value is not None:
                interval = self.interval.value.total_seconds()
            try:
                try:
                    if first:
                        self.fetch_all()
                        first = False
                    else:
                        garage: Garage = self.car_connectivity.garage
                        for vehicle in garage.list_vehicles():
                            if isinstance(vehicle, SmartcarVehicle) and vehicle.is_managed_by_connector(self):
                                self.fetch_vehicle_status(vehicle)
                    self.last_update._set_value(value=datetime.now(tz=timezone.utc))  # pylint: disable=protected-access
                except Exception:
                    self.connected._set_value(value=False)  # pylint: disable=protected-access
                    if self.interval.value is not None:
                        interval: float = self.interval.value.total_seconds()
                    raise
            except TooManyRequestsError as err:
                if err.retry_after is not None:
                    retry_after: int = err.retry_after
                else:
                    retry_after = 900
                LOG.error('Retrieval error during update. Too many requests from your account (%s). Will try again after %ds', str(err), retry_after)
                self._stop_event.wait(retry_after)
            except RetrievalError as err:
                LOG.error('Retrieval error during update (%s). Will try again after configured interval of %ss', str(err), interval)
                self._stop_event.wait(interval)
            except APICompatibilityError as err:
                LOG.error('API compatability error during update (%s). Will try again after configured interval of %ss', str(err), interval)
                self._stop_event.wait(interval)
            except TemporaryAuthenticationError as err:
                LOG.error('Temporary authentification error during update (%s). Will try again after configured interval of %ss', str(err), interval)
                self._stop_event.wait(interval)
            else:
                self.connected._set_value(value=True)  # pylint: disable=protected-access
                self._stop_event.wait(interval)

    def persist(self) -> None:
        self._manager.persist()

    def shutdown(self) -> None:
        self._stop_event.set()
        if self._background_thread is not None:
            self._background_thread.join()
        self.persist()
        BaseConnector.shutdown(self)

    def fetch_all(self) -> None:
        """
        Fetches all necessary data for the connector.

        This method calls the `fetch_vehicles` method to retrieve vehicle data.
        """
        self.fetch_vehicles()
        self.car_connectivity.transaction_end()

    def fetch_vehicles(self) -> None:
        vehicles: smartcar.types.Vehicles = smartcar.get_vehicles(self.session.get_access_token())
        seen_vehicle_vins: set[str] = set()
        garage: Garage = self.car_connectivity.garage
        for vehicle_id in vehicles.vehicles:
            vehicle: Optional[SmartcarVehicle] = None
            for garage_vehicle in garage.list_vehicles():
                if isinstance(garage_vehicle, SmartcarVehicle) and garage_vehicle.smartcar_id.value == vehicle_id:
                    vehicle = garage_vehicle
                    break
            vehicle_request_adapter = smartcar.Vehicle(vehicle_id=vehicle_id, access_token=self.session.get_access_token())
            if vehicle is None:
                try:
                    response = vehicle_request_adapter.batch(paths=['/vin', '/', '/battery/capacity'])
                    vin_response: smartcar.types.Vin = response.vin()
                    garage: Garage = self.car_connectivity.garage
                    vehicle = SmartcarVehicle(vin=vin_response.vin, garage=garage, managing_connector=self)
                    vehicle.smartcar_id._set_value(value=vehicle_id)  # pylint: disable=protected-access
                    garage.add_vehicle(vin_response.vin, vehicle)

                    attributes_response: smartcar.types.Attributes = response.attributes()
                    if attributes_response.model is not None:
                        vehicle.model._set_value(value=attributes_response.model)  # pylint: disable=protected-access
                    if attributes_response.year is not None:
                        vehicle.model_year._set_value(value=attributes_response.year)  # pylint: disable=protected-access
                    if attributes_response.make is not None:
                        vehicle.manufacturer._set_value(value=attributes_response.make)  # pylint: disable=protected-access

                    # battery_capacity_response: smartcar.types.BatteryCapacity = response.battery_capacity()
                    # TODO: Add battery capacity to vehicle
                    # BatteryCapacity(capacity=73.56, meta=Meta(data_age='2025-02-08T22:15:24.294Z', request_id='0a2d7842-3ab2-4565-b6bb-7d44c44016aa'))
                    if vehicle.vin.value is not None:
                        seen_vehicle_vins.add(vehicle.vin.value)

                    self.fetch_vehicle_status(vehicle)
                except smartcar.exception.SmartcarException as e:
                    if e.code == 'VEHICLE':
                        LOG.error(f'Rate limit: Too many requests for vehicle , retry after {e.retry_after}s: {e}')
                        raise TooManyRequestsError(f'Rate limit: Too many requests for vehicle , retry after {e.retry_after}s: {e}',
                                                   retry_after=e.retry_after) from e
                    else:
                        LOG.error(f'Error during vehicle status retrieval: {e}')
                        raise RetrievalError(f'Error during vehicle status retrieval: {e}') from e
        for vin in set(garage.list_vehicle_vins()) - seen_vehicle_vins:
            vehicle_to_remove = garage.get_vehicle(vin)
            if vehicle_to_remove is not None and vehicle_to_remove.is_managed_by_connector(self):
                garage.remove_vehicle(vin)

    def fetch_vehicle_status(self, vehicle: SmartcarVehicle) -> SmartcarVehicle:
        if vehicle.smartcar_id.value is None:
            LOG.error('Vehicle %s has no smartcar_id', vehicle.vin.value)
            return vehicle
        vehicle_request_adapter = smartcar.Vehicle(vehicle_id=vehicle.smartcar_id.value, access_token=self.session.get_access_token())
        try:
            response = vehicle_request_adapter.batch(paths=['/odometer', '/location'])
            #response = vehicle_request_adapter.batch(paths=['/charge', '/battery', '/fuel', '/tire_pressure', '/engine/oil', '/odometer',
            #                                                '/service/history', '/diagnostics/system_status', '/diagnostics/dtcs', '/location',
            #                                                '/permissions', '/charge/limit', '/security'])
            # Charge
            # charge: smartcar.types.Charge = vehicle_request_adapter.charge()
            # print(charge)
            # Charge(is_plugged_in=False, state='CHARGING', meta=Meta(data_age='2025-02-08T22:03:15.831Z', request_id='7ba820d2-79d9-483e-983d-09a5be6686d9'))
            # FULLY_CHARGED, NOT_CHARGING
            # battery: smartcar.types.Battery = vehicle_request_adapter.battery()
            # print(battery)
            # BatteryCapacity(capacity=73.56, meta=Meta(data_age='2025-02-08T22:15:24.294Z', request_id='0a2d7842-3ab2-4565-b6bb-7d44c44016aa'))
            # fuel: smartcar.types.Fuel = vehicle_request_adapter.fuel()
            # print(fuel)
            # Fuel(range=309.31, percent_remaining=0.59, amount_remaining=36, meta=Meta(data_age='2025-02-08T22:22:28.013Z', unit_system='metric', request_id='469ff198-5707-4d37-baac-80e2c5cc881d'))
            # tire_pressure: smartcar.types.TirePressure = vehicle_request_adapter.tire_pressure()
            # print(tire_pressure)
            # TirePressure(front_left=182.9177, front_right=180.0264, back_left=217.7337, back_right=201.5464, meta=Meta(data_age='2025-02-08T22:39:48.343Z', unit_system='metric', request_id='4ccf6b87-5443-4a07-8b03-a643fa6aaa3b'))
            # try:
            #    engine_oil: smartcar.types.EngineOil = vehicle_request_adapter.engine_oil()
            #    print(engine_oil)
            #except smartcar.exception.SmartcarException as e:
            #    if not e.code == 'VEHICLE_NOT_CAPABLE':
            #        raise
            try:
                odometer_response: smartcar.types.Odometer = response.odometer()
                if odometer_response.distance is not None:
                    if odometer_response.meta is not None and odometer_response.meta.data_age is not None:
                        measured_at: Optional[datetime] = robust_time_parse(odometer_response.meta.data_age)
                    else:
                        measured_at = None
                    vehicle.odometer._set_value(value=odometer_response.distance, measured=measured_at, unit=Length.KM)  # pylint: disable=protected-access
                else:
                    vehicle.odometer._set_value(value=None)  # pylint: disable=protected-access
            except smartcar.exception.SmartcarException as e:
                vehicle.odometer._set_value(value=None)  # pylint: disable=protected-access
                if not e.code == 'VEHICLE_NOT_CAPABLE':
                    raise
            # service_history: smartcar.types.ServiceHistory = vehicle_request_adapter.service_history()
            # print(service_history)
            # ServiceHistory(items=[], meta=Meta(data_age='2025-02-08T22:57:13.524Z', unit_system='metric', request_id='27422a7c-ec2c-45bf-827f-c4351213b231'))
            # diagnostic_system_status: smartcar.types.DiagnosticSystemStatus = vehicle_request_adapter.diagnostic_system_status()
            # print(diagnostic_system_status)
            # DiagnosticSystemStatus(systems=[DiagnosticSystem(system_id='SYSTEM_BRAKE_FLUID', status='ALERT', description='FRONT_RIGHT'), DiagnosticSystem(system_id='SYSTEM_ACTIVE_SAFETY', status='ALERT', description='REAR_LEFT'), DiagnosticSystem(system_id='SYSTEM_ENGINE', status='ALERT', description='FRONT_RIGHT'), DiagnosticSystem(system_id='SYSTEM_EV_HV_BATTERY', status='ALERT', description=None), DiagnosticSystem(system_id='SYSTEM_ABS', status='OK', description=None), DiagnosticSystem(system_id='SYSTEM_TELEMATICS', status='OK', description=None), DiagnosticSystem(system_id='SYSTEM_EV_BATTERY_CONDITIONING', status='ALERT', description='FRONT_RIGHT'), DiagnosticSystem(system_id='SYSTEM_TRANSMISSION', status='ALERT', description=None), DiagnosticSystem(system_id='SYSTEM_EMISSIONS', status='ALERT', description=None), DiagnosticSystem(system_id='SYSTEM_WATER_IN_FUEL', status='ALERT', description=None), DiagnosticSystem(system_id='SYSTEM_WASHER_FLUID', status='ALERT', description=None), DiagnosticSystem(system_id='SYSTEM_LIGHTING', status='OK', description=None), DiagnosticSystem(system_id='SYSTEM_TIRE_PRESSURE_MONITORING', status='OK', description=None), DiagnosticSystem(system_id='SYSTEM_AIRBAG', status='OK', description=None), DiagnosticSystem(system_id='SYSTEM_MIL', status='OK', description=None), DiagnosticSystem(system_id='SYSTEM_OIL_LIFE', status='OK', description=None), DiagnosticSystem(system_id='SYSTEM_OIL_TEMPERATURE', status='OK', description=None), DiagnosticSystem(system_id='SYSTEM_DRIVER_ASSISTANCE', status='ALERT', description=None)], meta=Meta(data_age='2025-02-08T22:59:50.521Z', request_id='7ae01549-7d0e-4b77-8695-cdd5420fa2ca'))
            # diagnostic_trouble_codes: smartcar.types.DiagnosticTroubleCodes = vehicle_request_adapter.diagnostic_trouble_codes()
            # print(diagnostic_trouble_codes)
            # DiagnosticTroubleCodes(active_codes=[DiagnosticTroubleCode(code='P5684', timestamp=None)], meta=Meta(data_age='2025-02-08T23:05:48.873Z', request_id='5b082a4f-75ff-4a41-a595-cc7774aefdad'))
            try:
                location_response: smartcar.types.Location = response.location()
                if location_response.latitude is not None and location_response.longitude is not None:
                    if location_response.meta is not None and location_response.meta.data_age is not None:
                        measured_at: Optional[datetime] = robust_time_parse(location_response.meta.data_age)
                    else:
                        measured_at = None
                    # pylint: disable-next=protected-access
                    vehicle.position.latitude._set_value(value=location_response.latitude, measured=measured_at)
                    # pylint: disable-next=protected-access
                    vehicle.position.longitude._set_value(value=location_response.longitude, measured=measured_at)
            except smartcar.exception.SmartcarException as e:
                vehicle.odometer._set_value(value=None)  # pylint: disable=protected-access
                if not e.code == 'VEHICLE_NOT_CAPABLE':
                    raise
            # permissions: smartcar.types.Permissions = vehicle_request_adapter.permissions()
            # print(permissions)
            # Permissions(permissions=['control_charge', 'control_climate', 'control_navigation', 'control_pin', 'control_security', 'control_trunk', 'read_alerts', 'read_battery', 'read_charge', 'read_climate', 'read_compass', 'read_diagnostics', 'read_engine_oil', 'read_extended_vehicle_info', 'read_fuel', 'read_location', 'read_odometer', 'read_security', 'read_service_history', 'read_speedometer', 'read_thermometer', 'read_tires', 'read_user_profile', 'read_vehicle_info', 'read_vin'], paging=Paging(count=25, offset=0), meta=Meta(request_id='1539e564-dacd-49ae-9739-d8918263716b'))
            # attributes: smartcar.types.Attributes = vehicle_request_adapter.attributes()
            # print(attributes)
            # Attributes(id='123e01a2-6d86-4cd9-a6bd-f8ec18eb1abd', make='VOLKSWAGEN', model='ID 7', year=2025, meta=Meta(request_id='cd11bd4e-08e6-4874-910d-5622e64a2568'))
            # charge_limit: smartcar.types.ChargeLimit = vehicle_request_adapter.get_charge_limit()
            # print(charge_limit)
            # ChargeLimit(limit=0.8, meta=Meta(data_age='2025-02-08T23:17:45.454Z', request_id='5a7ce7d2-2716-454a-a85e-628ebbedda52'))
            # lock_status: smartcar.types.LockStatus = vehicle_request_adapter.lock_status()
            # print(lock_status)
            # LockStatus(is_locked=False, doors=[{'type': 'frontLeft', 'status': 'CLOSED'}, {'type': 'frontRight', 'status': 'UNKNOWN'}, {'type': 'backLeft', 'status': 'OPEN'}, {'type': 'backRight', 'status': 'CLOSED'}], windows=[{'type': 'frontLeft', 'status': 'OPEN'}, {'type': 'frontRight', 'status': 'CLOSED'}], sunroof=[{'type': 'sunroof', 'status': 'CLOSED'}], storage=[{'type': 'front', 'status': 'CLOSED'}, {'type': 'rear', 'status': 'UNKNOWN'}], charging_port=[{'type': 'chargingPort', 'status': 'CLOSED'}], meta=Meta(data_age='2025-02-08T23:20:30.055Z', request_id='21125b2f-7afc-45ef-b420-d94f89ca5d0b'))
        except smartcar.exception.SmartcarException as e:
            if e.code == 'VEHICLE':
                LOG.error(f'Rate limit: Too many requests for vehicle {vehicle.vin.value}, retry after {e.retry_after}s: {e}')
                raise TooManyRequestsError(f'Rate limit: Too many requests for vehicle {vehicle.vin.value}, retry after {e.retry_after}s: {e}',
                                           retry_after=e.retry_after) from e
            else:
                LOG.error(f'Error during vehicle status retrieval: {e}')
                raise RetrievalError(f'Error during vehicle status retrieval: {e}') from e

        return vehicle

    def _record_elapsed(self, elapsed: timedelta) -> None:
        """
        Records the elapsed time.

        Args:
            elapsed (timedelta): The elapsed time to record.
        """
        self._elapsed.append(elapsed)

    def get_version(self) -> str:
        return __version__

    def get_type(self) -> str:
        return "carconnectivity-connector-smartcar"
