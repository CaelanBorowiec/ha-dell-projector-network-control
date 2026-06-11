"""Standalone smoke test for the Dell 7609WU API client.

Runs against a live projector without Home Assistant:

    python tools/smoke_test.py 10.10.0.227 [--password XXXX] [--command]

By default only reads state. With --command it additionally exercises the
command path by re-submitting the current volume (a no-op on the device,
but a full round-trip through POST /tgi/status.tgi).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import aiohttp

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "custom_components" / "dell_7609wu")
)

from api import Dell7609Client, state_as_dict  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("--password", default=None)
    parser.add_argument(
        "--command",
        action="store_true",
        help="also exercise the command path (re-submits current volume)",
    )
    args = parser.parse_args()

    async with aiohttp.ClientSession() as session:
        client = Dell7609Client(args.host, session, password=args.password)

        print(f"== Validating projector at {args.host} ==")
        state = await client.async_validate()
        print(json.dumps(state_as_dict(state), indent=2))

        problems: list[str] = []
        if not state.mac_address:
            problems.append("MAC address not parsed")
        if state.power_status is None:
            problems.append("power status not parsed")
        if not state.raw_form:
            problems.append("status form state not parsed")

        if args.command:
            volume = state.volume
            if volume is None:
                problems.append("volume not parsed; skipping command test")
            else:
                print(f"== Command test: re-submitting volume {volume} ==")
                await client.async_set_volume(volume)
                state2 = await client.async_get_state()
                print(f"Volume after command: {state2.volume}")
                if state2.volume != volume:
                    problems.append(
                        f"volume changed unexpectedly: {volume} -> {state2.volume}"
                    )

        if problems:
            print("FAILURES:")
            for problem in problems:
                print(f"  - {problem}")
            return 1
        print("Smoke test OK")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
