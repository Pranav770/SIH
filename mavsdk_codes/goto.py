import asyncio
import math

from mavsdk import System
from mavsdk.action import ActionError
from mavsdk.telemetry import LandedState


# ============================================================
# CONFIGURATION
# ============================================================

TAKEOFF_ALTITUDE = 5.0
MAX_TARGET_DISTANCE = 50.0
TARGET_REACHED_DISTANCE = 2.0
HOLD_TIME = 5

METERS_PER_DEG_LAT = 111_320


# ============================================================
# DISTANCE
# ============================================================

def distance_meters(lat1, lon1, lat2, lon2):
    north = (lat2 - lat1) * METERS_PER_DEG_LAT

    meters_per_deg_lon = (
        METERS_PER_DEG_LAT
        * math.cos(math.radians(lat1))
    )

    east = (lon2 - lon1) * meters_per_deg_lon

    return math.sqrt(north ** 2 + east ** 2)


# ============================================================
# MAIN
# ============================================================

async def main():

    drone = System()

    print()
    print("========================================")
    print("        SIH DRONE CONTROL")
    print("========================================")
    print()

    # --------------------------------------------------------
    # CONNECT
    # --------------------------------------------------------

    print("Connecting to ArduPilot SITL...")

    await drone.connect(
        system_address="udpin://127.0.0.1:14551"
    )

    print("Waiting for connection...")

    async for state in drone.core.connection_state():

        if state.is_connected:
            print("✓ Connected")
            break

    # --------------------------------------------------------
    # GPS + HOME
    # --------------------------------------------------------

    print()
    print("Waiting for GPS and home position...")

    async for health in drone.telemetry.health():

        print(
            f"GPS: {health.is_global_position_ok} | "
            f"Home: {health.is_home_position_ok}"
        )

        if (
            health.is_global_position_ok
            and health.is_home_position_ok
        ):
            print("✓ Position OK")
            break

    # --------------------------------------------------------
    # HOME POSITION
    # --------------------------------------------------------

    print()
    print("========== HOME POSITION ==========")

    async for position in drone.telemetry.position():

        home_lat = position.latitude_deg
        home_lon = position.longitude_deg

        print(f"Latitude : {home_lat:.6f}")
        print(f"Longitude: {home_lon:.6f}")

        break

    print("===================================")

    # --------------------------------------------------------
    # USER TARGET
    # --------------------------------------------------------

    print()
    print("Enter target coordinates.")
    print(
        f"Maximum allowed distance: "
        f"{MAX_TARGET_DISTANCE:.0f} m"
    )
    print()

    try:

        target_lat = float(
            input("Target latitude : ").strip()
        )

        target_lon = float(
            input("Target longitude: ").strip()
        )

    except ValueError:

        print()
        print("✗ Invalid coordinates.")
        return

    # --------------------------------------------------------
    # VALIDATE COORDINATES
    # --------------------------------------------------------

    if not -90 <= target_lat <= 90:

        print("✗ Invalid latitude.")
        return

    if not -180 <= target_lon <= 180:

        print("✗ Invalid longitude.")
        return

    # --------------------------------------------------------
    # DISTANCE FROM HOME
    # --------------------------------------------------------

    target_distance = distance_meters(
        home_lat,
        home_lon,
        target_lat,
        target_lon,
    )

    print()
    print("========== TARGET ==========")
    print(f"Latitude : {target_lat:.6f}")
    print(f"Longitude: {target_lon:.6f}")
    print(f"Distance : {target_distance:.2f} m")
    print("============================")

    # --------------------------------------------------------
    # SAFETY CHECK
    # --------------------------------------------------------

    if target_distance > MAX_TARGET_DISTANCE:

        print()
        print("✗ Target rejected.")

        print(
            f"Target is {target_distance:.2f} m "
            f"from home."
        )

        print(
            f"Maximum allowed is "
            f"{MAX_TARGET_DISTANCE:.2f} m."
        )

        return

    print()
    print("✓ Target is inside safety boundary.")

    # --------------------------------------------------------
    # ARM
    # --------------------------------------------------------

    print()
    print("Arming...")

    try:

        await drone.action.arm()

        print("✓ Armed")

    except ActionError as e:

        print(
            f"✗ Arming failed: {e}"
        )

        return

    # --------------------------------------------------------
    # TAKEOFF
    # --------------------------------------------------------

    print()
    print(
        f"Taking off to "
        f"{TAKEOFF_ALTITUDE:.1f} m..."
    )

    try:

        await drone.action.set_takeoff_altitude(
            TAKEOFF_ALTITUDE
        )

        await drone.action.takeoff()

        print("✓ Takeoff command accepted")

    except ActionError as e:

        print(
            f"✗ Takeoff failed: {e}"
        )

        return

    # --------------------------------------------------------
    # WAIT FOR ALTITUDE
    # --------------------------------------------------------

    print()
    print(
        f"Waiting for "
        f"{TAKEOFF_ALTITUDE:.1f} m altitude..."
    )

    async for position in drone.telemetry.position():

        altitude = position.relative_altitude_m

        print(
            f"Altitude: {altitude:.2f} m"
        )

        if altitude >= TAKEOFF_ALTITUDE - 0.5:

            print()
            print(
                f"✓ Reached approximately "
                f"{TAKEOFF_ALTITUDE:.1f} m"
            )

            break

    await asyncio.sleep(2)

    # --------------------------------------------------------
    # GOTO
    # --------------------------------------------------------

    print()
    print("========== NAVIGATION ==========")

    print(
        f"Target latitude : "
        f"{target_lat:.6f}"
    )

    print(
        f"Target longitude: "
        f"{target_lon:.6f}"
    )

    print("=================================")

    try:

        await drone.action.goto_location(
            target_lat,
            target_lon,
            TAKEOFF_ALTITUDE,
            0,
        )

        print("✓ Goto command accepted")

    except ActionError as e:

        print(
            f"✗ Goto failed: {e}"
        )

        return

    # --------------------------------------------------------
    # MONITOR POSITION
    # --------------------------------------------------------

    print()
    print("Monitoring position...")

    async for position in drone.telemetry.position():

        lat = position.latitude_deg
        lon = position.longitude_deg
        alt = position.relative_altitude_m

        distance = distance_meters(
            lat,
            lon,
            target_lat,
            target_lon,
        )

        print(
            f"Position: "
            f"{lat:.6f}, {lon:.6f} | "
            f"Alt: {alt:.2f} m | "
            f"Distance: {distance:.2f} m"
        )

        if distance <= TARGET_REACHED_DISTANCE:

            print()
            print("✓ Reached target")

            break

    # --------------------------------------------------------
    # HOLD
    # --------------------------------------------------------

    print()
    print(
        f"Holding position for "
        f"{HOLD_TIME} seconds..."
    )

    await asyncio.sleep(HOLD_TIME)

    # --------------------------------------------------------
    # LAND
    # --------------------------------------------------------

    print()
    print("Landing...")

    try:

        await drone.action.land()

        print("✓ Land command accepted")

    except ActionError as e:

        print(
            f"✗ Landing failed: {e}"
        )

        return

    # --------------------------------------------------------
    # MONITOR LANDING
    # --------------------------------------------------------

    print()
    print("Monitoring landing...")

    async for landed in drone.telemetry.landed_state():

        print(
            f"Landed state: {landed}"
        )

        if landed == LandedState.ON_GROUND:

            print()
            print("✓ Drone is on the ground")

            break

    # --------------------------------------------------------
    # COMPLETE
    # --------------------------------------------------------

    print()
    print("========================================")
    print("          MISSION COMPLETE")
    print("========================================")
    print()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        print()
        print("Mission interrupted by user.")
