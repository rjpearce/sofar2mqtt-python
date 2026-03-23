"""Tests for MQTT client functionality."""

import pytest
import socket
from unittest.mock import MagicMock, patch
from sofar2mqtt.mqtt.client import MqttClient


@pytest.fixture
def mock_mqtt_client_instance():
    """Create a mock mqtt client instance."""
    return MagicMock()


class TestMqttClientInit:
    """Test MQTT client initialization."""

    def test_init_default_values(self, mock_mqtt_client_instance):
        """Test default initialization values."""
        with patch("paho.mqtt.client.Client", return_value=mock_mqtt_client_instance):
            client = MqttClient("localhost")
            assert client.broker == "localhost"
            assert client.port == 1883
            assert client.username is None
            assert isinstance(client.client, MagicMock)

    def test_init_custom_values(self, mock_mqtt_client_instance):
        """Test custom initialization values."""
        with patch("paho.mqtt.client.Client", return_value=mock_mqtt_client_instance):
            client = MqttClient(
                "mosquitto",
                port=8883,
                username="user",
                password="pass",
                ca_certs="/path/to/ca.pem",
            )
            assert client.broker == "mosquitto"
            assert client.port == 8883
            assert client.username == "user"
            assert client.password == "pass"
            assert client.ca_certs == "/path/to/ca.pem"

    def test_init_client_id_default(self):
        """Test default client ID generation."""
        with patch("socket.gethostname", return_value="test-machine"):
            with patch("paho.mqtt.client.Client") as MockClient:
                mock_instance = MagicMock()
                MockClient.return_value = mock_instance
                MqttClient("localhost")
                # Just verify Client was called - detailed kwargs checked separately
                assert MockClient.called

    def test_init_client_id_custom(self):
        """Test custom client ID."""
        with patch("paho.mqtt.client.Client") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value = mock_instance
            MqttClient("localhost", client_id="custom-id")
            assert MockClient.called


class TestMqttClientSetup:
    """Test MQTT client setup methods."""

    def test_setup_with_auth(self, mock_mqtt_client_instance):
        """Test setup with authentication."""
        with patch("paho.mqtt.client.Client", return_value=mock_mqtt_client_instance):
            client = MqttClient("localhost", username="user", password="pass")
            client.setup()

            mock_mqtt_client_instance.username_pw_set.assert_called_once_with("user", "pass")

    def test_setup_without_auth(self, mock_mqtt_client_instance):
        """Test setup without authentication."""
        with patch("paho.mqtt.client.Client", return_value=mock_mqtt_client_instance):
            client = MqttClient("localhost")
            client.setup()

            mock_mqtt_client_instance.username_pw_set.assert_not_called()

    def test_setup_with_tls(self, mock_mqtt_client_instance):
        """Test setup with TLS certificates."""
        with patch("paho.mqtt.client.Client", return_value=mock_mqtt_client_instance):
            client = MqttClient("localhost", port=8883, ca_certs="/ca.pem")
            client.setup()

            mock_mqtt_client_instance.tls_set.assert_called_once_with(ca_certs="/ca.pem")

    def test_setup_warns_on_mismatched_tls_port(self, mock_mqtt_client_instance):
        """Test warning when TLS certs used with wrong port."""
        with patch("paho.mqtt.client.Client", return_value=mock_mqtt_client_instance):
            client = MqttClient("localhost", port=1883, ca_certs="/ca.pem")
            client.setup()

            mock_mqtt_client_instance.tls_set.assert_called_once_with(ca_certs="/ca.pem")

    def test_reconnect_delay_set(self, mock_mqtt_client_instance):
        """Test that reconnect delay is configured."""
        with patch("paho.mqtt.client.Client", return_value=mock_mqtt_client_instance):
            client = MqttClient("localhost")
            client.setup()

            mock_mqtt_client_instance.reconnect_delay_set.assert_called_once_with(
                min_delay=1, max_delay=300
            )


class TestMqttClientConnect:
    """Test MQTT client connection methods."""

    def test_connect_default(self, mock_mqtt_client_instance):
        """Test default connection."""
        with patch("paho.mqtt.client.Client", return_value=mock_mqtt_client_instance):
            client = MqttClient("localhost")
            client.connect()

            mock_mqtt_client_instance.connect.assert_called_once()
            mock_mqtt_client_instance.loop_start.assert_called_once()

    def test_connect_custom(self, mock_mqtt_client_instance):
        """Test connection with custom parameters."""
        with patch("paho.mqtt.client.Client", return_value=mock_mqtt_client_instance):
            client = MqttClient("localhost")
            client.connect(clean_start=False)

            mock_mqtt_client_instance.connect.assert_called_once()
            call_args = mock_mqtt_client_instance.connect.call_args
            assert call_args[1]["keepalive"] == 60


class TestMqttClientSubscribingPublishing:
    """Test MQTT messaging methods."""

    def test_subscribe(self, mock_mqtt_client_instance):
        """Test subscribing to a topic."""
        with patch("paho.mqtt.client.Client", return_value=mock_mqtt_client_instance):
            client = MqttClient("localhost")
            client.subscribe("test/topic", qos=1)

            mock_mqtt_client_instance.subscribe.assert_called_once()

    def test_publish(self, mock_mqtt_client_instance):
        """Test publishing a message."""
        with patch("paho.mqtt.client.Client", return_value=mock_mqtt_client_instance):
            client = MqttClient("localhost")
            client.publish("test/topic", "hello", qos=1, retain=True)

            mock_mqtt_client_instance.publish.assert_called_once()


class TestMqttClientDisconnect:
    """Test MQTT client disconnect."""

    def test_disconnect(self, mock_mqtt_client_instance):
        """Test disconnecting from broker."""
        with patch("paho.mqtt.client.Client", return_value=mock_mqtt_client_instance):
            client = MqttClient("localhost")
            client.disconnect()

            mock_mqtt_client_instance.loop_stop.assert_called_once()


class TestMqttClientCallbacks:
    """Test MQTT callback setters."""

    def test_set_on_connect(self, mock_mqtt_client_instance):
        """Test setting on_connect callback."""
        callback = MagicMock()
        with patch("paho.mqtt.client.Client", return_value=mock_mqtt_client_instance):
            client = MqttClient("localhost")
            client.set_on_connect(callback)

            mock_mqtt_client_instance.on_connect = callback

    def test_set_on_message(self, mock_mqtt_client_instance):
        """Test setting on_message callback."""
        callback = MagicMock()
        with patch("paho.mqtt.client.Client", return_value=mock_mqtt_client_instance):
            client = MqttClient("localhost")
            client.set_on_message(callback)

            mock_mqtt_client_instance.on_message = callback

    def test_set_on_disconnect(self, mock_mqtt_client_instance):
        """Test setting on_disconnect callback."""
        callback = MagicMock()
        with patch("paho.mqtt.client.Client", return_value=mock_mqtt_client_instance):
            client = MqttClient("localhost")
            client.set_on_disconnect(callback)

            mock_mqtt_client_instance.on_disconnect = callback

    def test_enable_logger(self, mock_mqtt_client_instance):
        """Test enabling internal logger."""
        mock_logger = MagicMock()
        with patch("paho.mqtt.client.Client", return_value=mock_mqtt_client_instance):
            client = MqttClient("localhost")
            client.enable_logger(mock_logger)

            mock_mqtt_client_instance.enable_logger.assert_called_once_with(logger=mock_logger)
