#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "jubilant>=1.7,<2"
# ]
# ///

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from jubilant import Juju

LOGGER = logging.getLogger(__name__)


class SetupVaultError(Exception):
    """Exception thrown when the script fails to run correctly."""

    @property
    def msg(self):
        return self.args[0]


def main():
    if (vault_cli := shutil.which("vault")) is None:
        raise SetupVaultError("script could not find command `vault`")

    juju = Juju()
    model = juju.show_model()
    status = juju.status().apps
    unseal_output = Path.home() / f"unseal_output.{model.short_name}"

    LOGGER.info("setting up vault on model `%s` (%s).", model.name, model.model_uuid)
    LOGGER.info("output will be written to `%s`", unseal_output)

    try:
        units = status["vault"].units

        if len(units) == 0:
            raise SetupVaultError("could not find units for vault application")

    except KeyError:
        raise SetupVaultError("failed to find vault application")

    leader_name, leader_info = next(((k, v) for k, v in units.items() if v.leader))

    LOGGER.info("initializing vault with leader unit %s", leader_name)

    env = os.environ.copy()

    with unseal_output.open("w") as f:
        env["VAULT_ADDR"] = f"http://{leader_info.public_address}:8200"

        try:
            cmd = [
                vault_cli,
                "operator",
                "init",
                "-key-shares=5",
                "-key-threshold=3",
                "-format=json",
            ]
            LOGGER.info("running command `%s`", " ".join(cmd))
            result = subprocess.check_output(
                cmd,
                text=True,
                env=env,
            )

            vault_init = json.loads(result)

        except subprocess.CalledProcessError as e:
            LOGGER.error(e.stderr)
            raise SetupVaultError("failed to run `vault` command")
        except json.JSONDecodeError:
            raise SetupVaultError("failed to parse vault output as JSON")

        vault_init["model_uuid"] = model.model_uuid
        json.dump(vault_init, f)

    keys = vault_init["unseal_keys_b64"][0:3]
    token = vault_init["root_token"]

    env["VAULT_TOKEN"] = token

    for unit in units.values():
        env["VAULT_ADDR"] = f"http://{unit.public_address}:8200"

        try:
            for key in keys:
                cmd = [vault_cli, "operator", "unseal"]
                LOGGER.info("running command `%s`", " ".join(cmd))
                subprocess.run(
                    cmd + [key],
                    check=True,
                    text=True,
                    env=env,
                )

            cmd = [vault_cli, "token", "create", "-ttl=10m"]
            LOGGER.info("running command `%s`", " ".join(cmd))
            subprocess.run(
                cmd,
                check=True,
                text=True,
                env=env,
            )

        except subprocess.CalledProcessError as e:
            LOGGER.error(e.stderr)
            raise SetupVaultError("failed to run `vault` command")

    LOGGER.info("running `authorize-charm` action on leader unit `%s`", leader_name)
    juju.run(leader_name, "authorize-charm", {"token": token})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    main()
