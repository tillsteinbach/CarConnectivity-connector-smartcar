

# CarConnectivity Connector for Smartcar Config Options
The configuration for CarConnectivity is a .json file.
## Smartcar Connector Options
These are the valid options for the Smartcar Connector
```json
{
    "carConnectivity": {
        "connectors": [
            {
                "type": "smartcar", // Definition for the Smartcar Connector
                "config": {
                    "log_level": "error", // set the connectos log level
                    "client_id": "68c443bf-dba3-4631-8d41-2ebb32e511c5", // client_id optained from https://dashboard.smartcar.com
                    "client_secret": "1bf17732-47ee-4bbd-b7dd-a7656e80ea33", // client_secret configured at https://dashboard.smartcar.com
                    "interval": 300, // Interval in which the server is checked in seconds
                    "netrc": "~/.netr", // netrc file if to be used for passwords
                    "api_log_level": "debug", // Show debug information regarding the API
                }
            }
        ],
        "plugins": []
    }
}
```