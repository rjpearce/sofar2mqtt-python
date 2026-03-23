"""Main entry point for sofar2mqtt CLI."""

import logging
import click

from sofar2mqtt.core.sofar_client import SofarClient


@click.command(context_settings={"show_default": True})
@click.option("--daemon", envvar="DAEMON", is_flag=True, default=False, help="Run as a daemon")
@click.option(
    "--retry",
    envvar="RETRY_ATTEMPT",
    default=2,
    type=int,
    help="Number of read retries per register",
)
@click.option(
    "--retry-delay",
    envvar="RETRY_DELAY",
    default=0.1,
    type=float,
    help="Delay before retrying read (seconds)",
)
@click.option(
    "--write-retry",
    envvar="WRITE_RETRY_ATTEMPTS",
    default=5,
    type=int,
    help="Number of write retries per register",
)
@click.option(
    "--write-retry-delay",
    envvar="WRITE_RETRY_DELAY",
    default=5,
    type=float,
    help="Delay before retrying write (seconds)",
)
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
@click.option("--topic", envvar="MQTT_TOPIC", default="sofar/", help="MQTT topic prefix")
@click.option(
    "--write-topic", envvar="MQTT_WRITE_TOPIC", default="sofar/rw", help="MQTT topic for writes"
)
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
    default=None,
    help="Path to JSON config file (auto-detected if not provided)",
)
@click.option(
    "--legacy-publish",
    envvar="LEGACY_PUBLISH",
    default=True,
    is_flag=True,
    help="Publish individual register topics",
)
def main(
    daemon,
    retry,
    retry_delay,
    write_retry,
    write_retry_delay,
    refresh_interval,
    broker,
    port,
    username,
    password,
    topic,
    write_topic,
    log_level,
    device,
    config,
    legacy_publish,
):
    """Sofar2MQTT - Read data from Sofar inverters and publish to MQTT."""

    # Configure logging
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=getattr(logging, log_level.upper()),
    )

    # Determine config file
    if not config:
        import os
        from pathlib import Path

        config_type = os.environ.get("DEVICE_TYPE", "")
        if config_type:
            config = f"{config_type}.json"
        else:
            # Try to auto-detect (would need serial number read first)
            config = "SOFAR-HYD-3PH-AND-G3.json"  # Default

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
            device=device,
            broker=broker,
            port=port,
            username=username,
            password=password,
            retry=retry,
            retry_delay=retry_delay,
            write_retry=write_retry,
            write_retry_delay=write_retry_delay,
            refresh_interval=refresh_interval,
            topic=topic,
            write_topic=write_topic,
            legacy_publish=legacy_publish,
        )

        client.setup()
        client.run(daemon=daemon)

    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
