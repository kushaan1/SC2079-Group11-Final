# Derived from Pante/SC2079 (AY2023 S2, Group 14). See algorithm/PROVENANCE.md
"""
Entry point for the pathfinding service.

Run it from this directory so that ``import config`` and ``from pathfinding...`` resolve::

    python app.py                 # real planner
    python app.py --stub          # canned responses, no planning

Needs Python 3.11+ (the planner uses ``match``, and teammates will not all have 3.12) with the
packages in ``requirements.txt``. ``algorithm/README.md`` has the setup and a ``curl`` example.

Binding, in precedence order — command line, then environment, then ``config``::

    --host / --port        > MDP_HOST / MDP_PORT        > config.SERVER_HOST / SERVER_PORT

The default is ``0.0.0.0``, i.e. every interface. **This is deliberate and must not become
``localhost``**: the RPi reaches this laptop over the arena WiFi, and a service bound to
127.0.0.1 is unreachable from anywhere but the laptop itself. The reference instead hardcoded
its own lab IP (``192.168.14.13``), which is meaningless on any other network — the laptop's
address is handed out by whatever network the arena uses, usually the RPi's hotspot, so it
cannot be baked in.
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys

from flask_cors import CORS
from flask_openapi3 import Info, OpenAPI

import config
from pathfinding_controller import api as pathfinding_api


def create_app(stub: bool = False) -> OpenAPI:
    """
    Build the WSGI application.

    Separated from :func:`main` so that a test can build an app and use Flask's test client
    without binding a socket, and so a production WSGI server can import it.

    :param stub: Whether to answer with canned responses instead of planning. Stored on the app
        rather than in a module-level global so that both modes can exist in one process — a
        test needs to check that the same route behaves differently under each.
    """
    app = OpenAPI(__name__, info=Info(title="MDP API", version="1.0.0"))
    app.config["MDP_STUB"] = stub
    app.register_api(pathfinding_api)

    # The simulator is a browser page served from a different origin, so it cannot call this
    # service at all without CORS. Kept as permissive as the reference had it: the service is
    # only ever reachable on a closed arena network, and locking it down would break whichever
    # port a teammate happens to serve the simulator on.
    CORS(app)

    return app


def _resolve(cli_value, env_name: str, config_value, cast=str):
    """
    Resolve one setting from the CLI, the environment, or config — in that order.

    :raises SystemExit: If the environment variable is set but unusable. Failing loudly beats
        silently falling back to the config default, which would bind a port nobody asked for
        and be found only when the RPi could not connect.
    """
    if cli_value is not None:
        return cli_value

    raw = os.environ.get(env_name)
    if raw is None:
        return config_value

    try:
        return cast(raw)
    except ValueError:
        raise SystemExit(f"{env_name}={raw!r} is not a valid {cast.__name__}")


def _advertise(host: str, port: int, stub: bool) -> None:
    """
    Log the addresses the RPi should actually use.

    ``0.0.0.0`` is not an address a client can dial, so printing only the bind address leaves
    the RPi owner guessing. This resolves the LAN address the same way an outbound connection
    would — no packet is sent, the UDP socket is only used to ask the routing table which
    interface it would leave by.
    """
    logger = logging.getLogger(__name__)
    logger.info("Listening on %s:%s (stub=%s)", host, port, "yes" if stub else "no")

    if host != "0.0.0.0":
        return

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            lan_address = probe.getsockname()[0]
        logger.info("RPi should POST to http://%s:%s/pathfinding/", lan_address, port)
    except OSError:
        logger.info("Could not determine this host's LAN address; run `ipconfig getifaddr en0` "
                    "and give the RPi http://<that address>:%s/pathfinding/", port)

    logger.info("Swagger UI: http://127.0.0.1:%s/openapi/swagger", port)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="MDP pathfinding service.",
        epilog="Settings resolve CLI > environment (MDP_HOST/MDP_PORT) > config.py.",
    )
    parser.add_argument(
        "--stub",
        action="store_true",
        help="Answer with canned, schema-valid responses without running the planner. For "
             "unblocking RPi/Android integration. NOT safe to drive a robot with.",
    )
    parser.add_argument("--host", default=None, help=f"Interface to bind (default {config.SERVER_HOST}).")
    parser.add_argument("--port", default=None, type=int, help=f"Port to bind (default {config.SERVER_PORT}).")
    parser.add_argument("--debug", action="store_true", help="Flask debug mode with the reloader.")
    arguments = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if arguments.debug else logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    host = _resolve(arguments.host, "MDP_HOST", config.SERVER_HOST)
    port = _resolve(arguments.port, "MDP_PORT", config.SERVER_PORT, cast=int)

    if arguments.stub:
        logging.getLogger(__name__).warning(
            "STUB MODE — responses are fabricated and no planning happens. Do not drive the robot "
            "with these instructions, and do not measure timings against them."
        )

    application = create_app(stub=arguments.stub)
    _advertise(host, port, arguments.stub)

    application.run(host=host, port=port, debug=arguments.debug)


if __name__ == "__main__":
    main()
