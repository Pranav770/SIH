import asyncio
from mavsdk import System


async def main():
    drone = System()

    print("Connecting...")

    await drone.connect(
        system_address="tcpout://127.0.0.1:5760"
    )

    async for state in drone.core.connection_state():
        if state.is_connected:
            print("✓ Connected")
            break

    print("Reading vehicle state...")

    async def print_health():
        async for health in drone.telemetry.health():
            print(
                f"GPS: {health.is_global_position_ok} | "
                f"Home: {health.is_home_position_ok} | "
                f"Gyro: {health.is_gyrometer_calibration_ok} | "
                f"Accel: {health.is_accelerometer_calibration_ok} | "
                f"Mag: {health.is_magnetometer_calibration_ok}"
            )
            await asyncio.sleep(1)

    async def print_state():
        async for armed in drone.telemetry.armed():
            print("Armed:", armed)
            await asyncio.sleep(1)

    async def print_mode():
        async for mode in drone.telemetry.flight_mode():
            print("Flight mode:", mode)
            await asyncio.sleep(1)

    await asyncio.gather(
        print_health(),
        print_state(),
        print_mode(),
    )


if __name__ == "__main__":
    asyncio.run(main())
