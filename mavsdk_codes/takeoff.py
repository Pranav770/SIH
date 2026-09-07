import asyncio
from mavsdk import System
from mavsdk.action import ActionError
from mavsdk.telemetry import LandedState


async def main():
    drone = System()

    print("Connecting to ArduPilot SITL...")

    await drone.connect(
        system_address="udpin://127.0.0.1:14551"
    )

    print("Waiting for connection...")

    async for state in drone.core.connection_state():
        if state.is_connected:
            print("✓ Connected")
            break

    print("Waiting for global position...")

    async for health in drone.telemetry.health():
        print(
            f"GPS: {health.is_global_position_ok} | "
            f"Home: {health.is_home_position_ok}"
        )

        if health.is_global_position_ok and health.is_home_position_ok:
            print("✓ Global position OK")
            break

    print("Waiting for vehicle to be ready...")

    await asyncio.sleep(2)

    try:
        print("Arming...")
        await drone.action.arm()
        print("✓ Armed")

        print("Taking off to 5 meters...")
        await drone.action.set_takeoff_altitude(5)
        await drone.action.takeoff()
        print("✓ Takeoff command accepted")

    except ActionError as e:
        print(f"✗ Action failed: {e}")
        return

    print("Monitoring altitude...")

    async for position in drone.telemetry.position():
        altitude = position.relative_altitude_m

        print(f"Altitude: {altitude:.2f} m")

        if altitude >= 4.5:
            print("✓ Reached approximately 5 meters")
            break

    print("Holding for 5 seconds...")
    await asyncio.sleep(5)

    print("Landing...")

    try:
        await drone.action.land()
        print("✓ Land command accepted")
    except ActionError as e:
        print(f"✗ Landing failed: {e}")
        return

    print("Monitoring landing...")

    async for landed in drone.telemetry.landed_state():
        print(f"Landed state: {landed}")

        if landed == LandedState.ON_GROUND:
            print("✓ Drone is on the ground")
            break


if __name__ == "__main__":
    asyncio.run(main())
