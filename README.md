

# CarConnectivity Connector for Vehicles integrated in Smartcar
[![GitHub sourcecode](https://img.shields.io/badge/Source-GitHub-green)](https://github.com/tillsteinbach/CarConnectivity-connector-smartcar/)
[![GitHub release (latest by date)](https://img.shields.io/github/v/release/tillsteinbach/CarConnectivity-connector-smartcar)](https://github.com/tillsteinbach/CarConnectivity-connector-smartcar/releases/latest)
[![GitHub](https://img.shields.io/github/license/tillsteinbach/CarConnectivity-connector-smartcar)](https://github.com/tillsteinbach/CarConnectivity-connector-smartcar/blob/master/LICENSE)
[![GitHub issues](https://img.shields.io/github/issues/tillsteinbach/CarConnectivity-connector-smartcar)](https://github.com/tillsteinbach/CarConnectivity-connector-smartcar/issues)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/carconnectivity-connector-smartcar?label=PyPI%20Downloads)](https://pypi.org/project/carconnectivity-connector-smartcar/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/carconnectivity-connector-smartcar)](https://pypi.org/project/carconnectivity-connector-smartcar/)
[![Donate at PayPal](https://img.shields.io/badge/Donate-PayPal-2997d8)](https://www.paypal.com/donate?hosted_button_id=2BVFF5GJ9SXAJ)
[![Sponsor at Github](https://img.shields.io/badge/Sponsor-GitHub-28a745)](https://github.com/sponsors/tillsteinbach)


## CarConnectivity will become the successor of [WeConnect-python](https://github.com/tillsteinbach/WeConnect-python) in 2025 with similar functionality but support for other brands beyond Volkswagen!

[CarConnectivity](https://github.com/tillsteinbach/CarConnectivity) is a python API to connect to various car services. This connector enables the integration of  vehicles that are conencted to Smartcar. This connector is meant for vehicles that do not yet have an implementation of a native connector. Look at [CarConnectivity](https://github.com/tillsteinbach/CarConnectivity) for native connectors for your vehicle.

## General
The possibilities of this connector are very limited to what Smartcar shares on their API. This connector does only make sense for users that drive a car that is not supported by a native carconnectivity-connector.

## Configuration
First go to [Tronity Platform Portal at https://app.tronity.tech/apps](https://app.tronity.tech/apps). Open `TRONITY Extension` and copy `Client Id` and `Client Secret` to your carconnectivity.json. Check that your vechile appears in `Assigned Vehciles`. If not use `Link to add vehicle`
In your carconnectivity.json configuration add a section for the tronity connector like this:
```
{
    "carConnectivity": {
        "connectors": [
            {
                "type": "tronity",
                "config": {
                    "interval": 60,
                    "client_id": "68c623bf-dbbe-4569-1e9a-2eae9c45e4721c5",
                    "client_secret": "faeb52e8-954d-5feb-ee8f-e5280f78d915"
                }
            }
        ]
    }
}
```

<img src="https://raw.githubusercontent.com/tillsteinbach/CarConnectivity-connector-tronity/main/screenshots/tronity1.png" width="400"><img src="https://raw.githubusercontent.com/tillsteinbach/CarConnectivity-connector-tronity/main/screenshots/tronity2.png" width="600">
