import asyncio
import math

from mavsdk import System


async def main():
    drone = System()

    print("Connecting to ArduPilot SITL...")

    await drone.connect(
        system_address="udpin://127.0.0.1:14551"
    )

    print("Waiting for drone connection...")

    async for state in drone.core.connection_state():
        if state.is_connected:
            print("✓ Drone connected")
            break

    print("Starting telemetry...\n")

    data = {
        # Status
        "mode": "UNKNOWN",
        "armed": False,
        "landed": "UNKNOWN",

        # Position
        "lat": 0.0,
        "lon": 0.0,
        "alt": 0.0,

        # Velocity
        "north": 0.0,
        "east": 0.0,
        "down": 0.0,
        "ground_speed": 0.0,
        "vertical_speed": 0.0,

        # Attitude
        "roll": 0.0,
        "pitch": 0.0,
        "yaw": 0.0,

        # Heading
        "heading": 0.0,

        # GPS
        "satellites": 0,
        "fix_type": "UNKNOWN",

        # Battery
        "battery": 0.0,

        # Health
        "global_position_ok": False,
        "home_position_ok": False,
        "accelerometer_ok": False,
        "gyrometer_ok": False,
        "magnetometer_ok": False,

        # Angular velocity
        "roll_rate": 0.0,
        "pitch_rate": 0.0,
        "yaw_rate": 0.0,
    }

    async def update_position():
        async for pos in drone.telemetry.position():
            data["lat"] = pos.latitude_deg
            data["lon"] = pos.longitude_deg
            data["alt"] = pos.relative_altitude_m

    async def update_velocity():
        async for velocity in drone.telemetry.velocity_ned():

            north = velocity.north_m_s
            east = velocity.east_m_s
            down = velocity.down_m_s

            data["north"] = north
            data["east"] = east
            data["down"] = down

            data["ground_speed"] = math.sqrt(
                north ** 2 + east ** 2
            )

            # NED convention:
            # positive down = descending
            data["vertical_speed"] = -down

    async def update_heading():
        async for heading in drone.telemetry.heading():
            data["heading"] = heading.heading_deg

    async def update_attitude():
        async for attitude in drone.telemetry.attitude_euler():

            data["roll"] = attitude.roll_deg
            data["pitch"] = attitude.pitch_deg
            data["yaw"] = attitude.yaw_deg

    async def update_battery():
        async for battery in drone.telemetry.battery():
            data["battery"] = battery.remaining_percent

    async def update_flight_mode():
        async for mode in drone.telemetry.flight_mode():
            data["mode"] = str(mode).replace(
                "FlightMode.", ""
            )

    async def update_armed():
        async for armed in drone.telemetry.armed():
            data["armed"] = armed

    async def update_landed():
        async for state in drone.telemetry.landed_state():
            data["landed"] = str(state).replace(
                "LandedState.", ""
            )

    async def update_gps():
        async for gps in drone.telemetry.gps_info():
            data["satellites"] = gps.num_satellites

            # MAVSDK GPS fix enum
            data["fix_type"] = str(
                gps.fix_type
            ).replace("FixType.", "")

    async def update_health():
        async for health in drone.telemetry.health():

            data["global_position_ok"] = (
                health.is_global_position_ok
            )

            data["home_position_ok"] = (
                health.is_home_position_ok
            )

            data["accelerometer_ok"] = (
                health.is_accelerometer_calibration_ok
            )

            data["gyrometer_ok"] = (
                health.is_gyrometer_calibration_ok
            )

            data["magnetometer_ok"] = (
                health.is_magnetometer_calibration_ok
            )

    async def update_angular_velocity():
        async for velocity in (
            drone.telemetry.attitude_angular_velocity_body()
        ):
            data["roll_rate"] = velocity.roll_rad_s
            data["pitch_rate"] = velocity.pitch_rad_s
            data["yaw_rate"] = velocity.yaw_rad_s

    async def display():

        while True:

            print("\033[2J\033[H", end="")

            print("╔════════════════════════════════════════════╗")
            print("║            SIH DRONE TELEMETRY            ║")
            print("╠════════════════════════════════════════════╣")

            print("║                                            ║")
            print("║ STATUS                                     ║")
            print(
                f"║   Armed:        {str(data['armed']):<25}║"
            )
            print(
                f"║   Mode:         {data['mode']:<25}║"
            )
            print(
                f"║   Landed:       {data['landed']:<25}║"
            )

            print("║                                            ║")
            print("║ POSITION                                   ║")
            print(
                f"║   Latitude:     {data['lat']:>12.6f}             ║"
            )
            print(
                f"║   Longitude:    {data['lon']:>12.6f}             ║"
            )
            print(
                f"║   Altitude:     {data['alt']:>12.2f} m           ║"
            )
            print(
                f"║   Heading:      {data['heading']:>12.2f}°          ║"
            )

            print("║                                            ║")
            print("║ VELOCITY                                   ║")
            print(
                f"║   North:        {data['north']:>12.2f} m/s         ║"
            )
            print(
                f"║   East:         {data['east']:>12.2f} m/s         ║"
            )
            print(
                f"║   Down:         {data['down']:>12.2f} m/s         ║"
            )
            print(
                f"║   Ground:       {data['ground_speed']:>12.2f} m/s         ║"
            )
            print(
                f"║   Vertical:     {data['vertical_speed']:>12.2f} m/s         ║"
            )

            print("║                                            ║")
            print("║ ATTITUDE                                   ║")
            print(
                f"║   Roll:         {data['roll']:>12.2f}°          ║"
            )
            print(
                f"║   Pitch:        {data['pitch']:>12.2f}°          ║"
            )
            print(
                f"║   Yaw:          {data['yaw']:>12.2f}°          ║"
            )

            print("║                                            ║")
            print("║ ANGULAR VELOCITY                           ║")
            print(
                f"║   Roll rate:    {data['roll_rate']:>12.3f} rad/s      ║"
            )
            print(
                f"║   Pitch rate:   {data['pitch_rate']:>12.3f} rad/s      ║"
            )
            print(
                f"║   Yaw rate:     {data['yaw_rate']:>12.3f} rad/s      ║"
            )

            print("║                                            ║")
            print("║ GPS                                        ║")
            print(
                f"║   Satellites:   {data['satellites']:<25}║"
            )
            print(
                f"║   Fix:          {data['fix_type']:<25}║"
            )

            print("║                                            ║")
            print("║ BATTERY                                    ║")
            print(
                f"║   Remaining:    {data['battery']:>10.1f}%              ║"
            )

            print("║                                            ║")
            print("║ HEALTH                                     ║")
            print(
                f"║   Global pos:   {'✓ OK' if data['global_position_ok'] else '✗ NOT OK':<25}║"
            )
            print(
                f"║   Home:         {'✓ OK' if data['home_position_ok'] else '✗ NOT OK':<25}║"
            )
            print(
                f"║   Accelerometer:{'✓ OK' if data['accelerometer_ok'] else '✗ NOT OK':<24}║"
            )
            print(
                f"║   Gyrometer:    {'✓ OK' if data['gyrometer_ok'] else '✗ NOT OK':<25}║"
            )
            print(
                f"║   Magnetometer: {'✓ OK' if data['magnetometer_ok'] else '✗ NOT OK':<25}║"
            )

            print("║                                            ║")
            print("╚════════════════════════════════════════════╝")

            await asyncio.sleep(1)

    await asyncio.gather(
        update_position(),
        update_velocity(),
        update_heading(),
        update_attitude(),
        update_battery(),
        update_flight_mode(),
        update_armed(),
        update_landed(),
        update_gps(),
        update_health(),
        update_angular_velocity(),
        display(),
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTelemetry stopped.")
