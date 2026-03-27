"""Tests for MQTT client and discovery."""

from sofar2mqtt.mqtt.discovery import HomeAssistantDiscovery, build_device_info


class TestHomeAssistantDiscovery:
    """Test Home Assistant discovery functionality."""

    def test_init(self, mock_mqtt_client):
        """Test discovery initialization."""
        discovery = HomeAssistantDiscovery(mock_mqtt_client, "SN12345")
        assert discovery.serial == "SN12345"
        assert discovery.mqtt == mock_mqtt_client

    def test_publish_bridge_status(self, mock_mqtt_client):
        """Test bridge status publication."""
        discovery = HomeAssistantDiscovery(mock_mqtt_client, "SN12345")
        discovery.publish_bridge_status()

        # Check that bridge topic was published
        mock_mqtt_client.publish.assert_any_call("sofar2mqtt_python/bridge", "online", retain=True)

        # Verify bridge discovery was attempted
        calls = mock_mqtt_client.publish.call_args_list
        bridge_topics = [c[0][0] for c in calls if "homeassistant" in c[0][0]]
        assert any("connection_state" in topic for topic in bridge_topics)

    def test_publish_register_discovery(self, mock_mqtt_client):
        """Test register discovery publication."""
        discovery = HomeAssistantDiscovery(mock_mqtt_client, "SN12345")

        register = {
            "name": "battery_voltage",
            "ha": {
                "name": "Battery Voltage",
                "device_class": "voltage",
                "state_class": "measurement",
                "unit_of_measurement": "V",
            },
        }

        device_info = {
            "name": "Sofar Inverter",
            "identifiers": ["SN12345"],
        }

        discovery.publish_register_discovery(register, device_info)

        # Verify discovery was published
        calls = mock_mqtt_client.publish.call_args_list
        discovery_topics = [c[0][0] for c in calls if "homeassistant" in c[0][0]]
        assert any("battery_voltage" in topic for topic in discovery_topics)

    def test_publish_register_discovery_skips_no_ha(self, mock_mqtt_client):
        """Test that registers without HA config are skipped."""
        discovery = HomeAssistantDiscovery(mock_mqtt_client, "SN12345")

        register = {"name": "test_register"}  # No HA config

        discovery.publish_register_discovery(register, {})

        # Should only have bridge publish, no register discoveries
        calls = mock_mqtt_client.publish.call_args_list
        discovery_topics = [c[0][0] for c in calls if "homeassistant" in c[0][0]]
        assert all("battery" not in topic for topic in discovery_topics)


class TestDeviceInfoBuilder:
    """Test device information building."""

    def test_build_device_info_minimal(self):
        """Test building device info with minimal data."""
        config = {}
        raw_data = {}

        device = build_device_info(config, raw_data)

        assert device["name"] == "Sofar Inverter"  # Default
        assert device["model"] == "Unknown"
        assert device["sw_version"] == "unknown"
        assert device["hw_version"] == "unknown"
        assert device["manufacturer"] == "Sofar"

    def test_build_device_info_with_data(self):
        """Test building device info with actual data."""
        config = {"model": "HYD-3PH-AND-G3"}
        raw_data = {
            "sw_version_com": "1.2.3",
            "hw_version": "A1",
            "serial_number": "SN12345",
        }

        device = build_device_info(config, raw_data)

        assert device["name"] == "HYD-3PH-AND-G3"
        assert device["model"] == "HYD-3PH-AND-G3"
        assert device["sw_version"] == "1.2.3"
        assert device["hw_version"] == "A1"
        assert device["identifiers"] == ["SN12345"]
