import json
import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from logging import Logger
from pathlib import Path
from typing import Any, Optional


class ControlCommand(Enum):
    NONE = "NONE"
    EXIT = "EXIT"


@dataclass
class ControlRequest:
    command: ControlCommand
    issued_at: Optional[datetime] = None


DEFAULT_CONTROL = {
    "command": "NONE",
    "issued_at": None,
}


class ControlManager:
    def __init__(
        self,
        control_file_path: str,
        logger: Logger,
    ) -> None:
        self._control_file = Path(control_file_path)
        self._control_file.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logger

        if not self._control_file.exists():
            self._write(DEFAULT_CONTROL)
            self._logger.info("Created control file: %s", self._control_file)

        self._validate_initial_state()

    def _validate_initial_state(self) -> None:
        try:
            data = self._read()
            command = data.get("command", "NONE")
            ControlCommand(command)
        except (json.JSONDecodeError, ValueError, OSError) as e:
            self._logger.warning(
                "Invalid control file state (%s) — resetting to defaults", e,
            )
            self._write(DEFAULT_CONTROL)

    def get_command(self) -> ControlRequest:
        try:
            data = self._read()
        except FileNotFoundError:
            self._logger.info("Control file missing — creating with defaults")
            self._write(DEFAULT_CONTROL)
            return ControlRequest(command=ControlCommand.NONE)
        except (json.JSONDecodeError, OSError) as e:
            self._logger.warning(
                "Failed to read control file (%s) — treating as NONE", e,
            )
            return ControlRequest(command=ControlCommand.NONE)

        raw_command = data.get("command", "NONE")
        try:
            command = ControlCommand(raw_command)
        except ValueError:
            self._logger.warning(
                "Unknown control command '%s' — ignoring and treating as NONE",
                raw_command,
            )
            return ControlRequest(command=ControlCommand.NONE)

        issued_at: Optional[datetime] = None
        raw_issued = data.get("issued_at")
        if raw_issued is not None:
            try:
                issued_at = datetime.fromisoformat(raw_issued)
            except (ValueError, TypeError):
                self._logger.warning(
                    "Invalid issued_at timestamp '%s' — ignoring", raw_issued,
                )

        return ControlRequest(command=command, issued_at=issued_at)

    def clear_command(self) -> None:
        self._write(DEFAULT_CONTROL)
        self._logger.info("Control command cleared")

    def _read(self) -> dict[str, Any]:
        with open(self._control_file, "r") as f:
            return json.load(f)  # type: ignore[no-any-return]

    def _write(self, data: dict[str, Any]) -> None:
        tmp_path = self._control_file.with_suffix(".json.tmp")
        with open(tmp_path, "w") as f:
            json.dump(data, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(self._control_file))
