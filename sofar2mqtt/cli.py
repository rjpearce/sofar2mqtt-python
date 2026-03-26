"""Main entry point for sofar2mqtt CLI."""

import logging
import os
from pathlib import Path

import click

from sofar2mqtt.core.sofar_client import SofarClient

logger = logging.getLogger(__name__)


@click.command(context_settings={"show_default": True})
@click.option(
    "--refresh-interval",
    envvar="REFRESH_INTERVAL",
    default=1,
    type=int,
    help="Refresh data every N seconds",
)
@click.option("--broker", envvar="MQTT_HOST", default="localhost", help="MQTT broker address")
@click.option("--port", envvar="MQTT_PORT", default=1883, type=int, help="MQTT broker port")
@click.option("--username", envvar="MQTT_USERNAME", default=None, help="MQTT username")
@click.option("--password", envvar="MQTT_PASSWORD", default=None, help="MQTT password")
@click.option(
    "--log-level",
    envvar="LOG_LEVEL",
    default="INFO",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
    help="Log level",
)
@click.option("--device", envvar="TTY_DEVICE", default="/dev/ttyUSB0", help="RS485 device path")
@click.option(
    "--config",
    envvar="CONFIG_FILE",
    required=True,
    help="Path to JSON config file",
)
def main(
    refresh_interval,
    broker,
    port,
    username,
    password,
    log_level,
    device,
    config,
):
    """Sofar2MQTT - Read data from Sofar inverters and publish to MQTT."""

    # Configure logging
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=getattr(logging, log_level.upper()),
    )

    # Resolve config path relative to config directory if not absolute
    if not os.path.isabs(config):
        config_dir = Path(__file__).parent.parent / "config"
        config_path = config_dir / config
        if config_path.exists():
            config = str(config_path)

    try:
        # Initialize and run client
        client = SofarClient(
            config_path=config,
            modbus_device=device,
            mqtt_broker=broker,
            mqtt_port=port,
            mqtt_user=username,
            mqtt_password=password,
            poll_interval=refresh_interval,
        )

        client.setup()
        client.run()

    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
