"""The stroller's MuJoCo body, from the rigged scan (<scan source, outside the repo>/Stroller/Unreal/stroller_vehicle.blend, probed
with Blender 2026-11-10; numbers below, metres, x forward / y left / z up, ground at z 0, the same frame as the rig):

  wheel_rear_l  hub (-0.232,  0.2935, 0.168), radius 0.168, width 0.06
  wheel_rear_r  hub (-0.232, -0.2935, 0.168)
  wheel_front   hub ( 0.437, -0.0175, 0.128), radius 0.128, width 0.045
  frame         x -0.60..0.55; push handle at x -0.55, z 0.95; seat back / canopy x -0.42..-0.05, z 0.62..0.92;
                seat bucket x -0.25..0.25, z 0.18..0.62; front fork x 0.25..0.50, z 0.28..0.38

A wheeled racer, no legs: the brain drives the two rear wheels (torque motors, independent, so it can also turn by
driving them apart) and steers the front wheel (a position servo on a vertical fork, +-45 deg). The frame collides only
through boxes kept at least 10 cm off the ground, so only the wheels touch the floor (the scan's lowest frame vertices
sit at 1 cm). Mass 14 kg (README_Unreal_Setup.md), centre of mass low and toward the rear axle.

Options are the race's (training/models/tracks/*_fingerprint.json): 4 ms step, 1 solver iteration, 5 line-search
iterations, Euler damping off (disableflags 32768), floor friction 0.6 (the floor geom has priority 1). Euler damping ON
made this body blow up at rest under 1 iteration (the front wheel spun to 345 rad/s on touchdown); the race has it off.

    python stroller/make_model.py      -> training/stroller/assets/stroller_porace.xml and scene_stroller.xml
"""

from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE / "assets"

REAR_X, REAR_Y, REAR_R, REAR_HW = -0.232, 0.2935, 0.168, 0.03
FRONT_X, FRONT_Y, FRONT_R, FRONT_HW = 0.437, -0.0175, 0.128, 0.0225
CHASSIS_MASS, REAR_MASS, FRONT_MASS, FORK_MASS = 12.0, 0.7, 0.4, 0.2
COM = (-0.10, 0.0, 0.30)
STEER_MAX = 0.785  # rad, 45 deg
WHEEL_TORQUE = 2.0  # N.m per rear wheel at full action (1 N.m already reaches 2.7 m/s in 4 s)
HOME_Z = 0.002  # the chassis frame sits at the rig's origin: ground level (wheels touch at z 0)


def body_xml(prefix=""):
    p = prefix
    # inertia of a 1.0 x 0.6 x 0.8 m box of the chassis mass
    ix, iy, iz = (
        CHASSIS_MASS / 12 * (0.6**2 + 0.8**2),
        CHASSIS_MASS / 12 * (1.0**2 + 0.8**2),
        CHASSIS_MASS / 12 * (1.0**2 + 0.6**2),
    )
    return f"""
    <body name="{p}chassis" pos="0 0 {HOME_Z}">
      <freejoint name="{p}root"/>
      <inertial pos="{COM[0]} {COM[1]} {COM[2]}" mass="{CHASSIS_MASS}" diaginertia="{ix:.4f} {iy:.4f} {iz:.4f}"/>
      <site name="{p}imu" pos="{COM[0]} {COM[1]} {COM[2]}" size="0.01"/>
      <geom name="{p}seat" class="{p}frame" type="box" pos="0.0 -0.03 0.40" size="0.25 0.28 0.22"/>
      <geom name="{p}canopy" class="{p}frame" type="box" pos="-0.235 -0.01 0.77" size="0.185 0.30 0.15"/>
      <geom name="{p}handle" class="{p}frame" type="capsule" fromto="-0.55 -0.30 0.95 -0.55 0.30 0.95" size="0.025"/>
      <geom name="{p}fork" class="{p}frame" type="box" pos="0.36 -0.0175 0.33" size="0.11 0.05 0.05"/>
      <body name="{p}steer" pos="{FRONT_X} {FRONT_Y} {FRONT_R}">
        <joint name="{p}steer" type="hinge" axis="0 0 1" range="{-STEER_MAX} {STEER_MAX}" damping="0.5" armature="0.01"/>
        <inertial pos="0 0 0.08" mass="{FORK_MASS}" diaginertia="0.001 0.001 0.001"/>
        <body name="{p}wheel_front">
          <joint name="{p}wheel_front" type="hinge" axis="0 1 0" damping="0.002" armature="0.002"/>
          <geom name="{p}wheel_front" class="{p}wheel" size="{FRONT_R} {FRONT_HW}" mass="{FRONT_MASS}"/>
        </body>
      </body>
      <body name="{p}wheel_rear_l" pos="{REAR_X} {REAR_Y} {REAR_R}">
        <joint name="{p}wheel_rear_l" type="hinge" axis="0 1 0" damping="0.01" armature="0.01"/>
        <geom name="{p}wheel_rear_l" class="{p}wheel" size="{REAR_R} {REAR_HW}" mass="{REAR_MASS}"/>
      </body>
      <body name="{p}wheel_rear_r" pos="{REAR_X} {-REAR_Y} {REAR_R}">
        <joint name="{p}wheel_rear_r" type="hinge" axis="0 1 0" damping="0.01" armature="0.01"/>
        <geom name="{p}wheel_rear_r" class="{p}wheel" size="{REAR_R} {REAR_HW}" mass="{REAR_MASS}"/>
      </body>
    </body>"""


def defaults_xml(prefix=""):
    p = prefix
    return f"""
    <default class="{p}stroller">
      <default class="{p}frame"><geom rgba="0.15 0.15 0.18 1" density="0" condim="3"/></default>
      <default class="{p}wheel"><geom type="cylinder" euler="1.5707963 0 0" rgba="0.75 0.75 0.75 1" condim="3" friction="1 0.005 0.0001"/></default>
    </default>"""


def actuators_xml(prefix=""):
    p = prefix
    return f"""
    <position name="{p}steer" joint="{p}steer" kp="8" kv="0.3" ctrlrange="{-STEER_MAX} {STEER_MAX}"/>
    <motor name="{p}wheel_rear_l" joint="{p}wheel_rear_l" gear="1" ctrlrange="{-WHEEL_TORQUE} {WHEEL_TORQUE}"/>
    <motor name="{p}wheel_rear_r" joint="{p}wheel_rear_r" gear="1" ctrlrange="{-WHEEL_TORQUE} {WHEEL_TORQUE}"/>"""


def sensors_xml(prefix=""):
    p = prefix
    return f"""
    <gyro name="{p}gyro" site="{p}imu"/>
    <velocimeter name="{p}local_linvel" site="{p}imu"/>
    <framezaxis name="{p}upvector" objtype="site" objname="{p}imu"/>
    <framelinvel name="{p}global_linvel" objtype="site" objname="{p}imu"/>
    <frameangvel name="{p}global_angvel" objtype="site" objname="{p}imu"/>"""


def model_xml():
    return f"""<mujoco model="stroller">
  <!-- generated by training/stroller/make_model.py: edit that, not this -->
  <compiler angle="radian" autolimits="true"/>
  <default>{defaults_xml()}
  </default>
  <worldbody>{body_xml().replace('<body name="chassis"', '<body name="chassis" childclass="stroller"')}
  </worldbody>
  <actuator>{actuators_xml()}
  </actuator>
  <sensor>{sensors_xml()}
  </sensor>
  <keyframe>
    <key name="home" qpos="0 0 {HOME_Z} 1 0 0 0 0 0 0 0" ctrl="0 0 0"/>
  </keyframe>
</mujoco>
"""


def scene_xml():
    return """<mujoco model="stroller scene">
  <!-- generated by training/stroller/make_model.py: the race's options and floor -->
  <include file="stroller_porace.xml"/>
  <option timestep="0.004" impratio="100" iterations="1" ls_iterations="5">
    <flag eulerdamp="disable"/>
  </option>
  <worldbody>
    <light pos="0 0 3" dir="0 0 -1" directional="true"/>
    <geom name="floor" size="0 0 0.01" type="plane" conaffinity="0" priority="1" friction="0.6" rgba="0.22 0.24 0.27 1"/>
  </worldbody>
</mujoco>
"""


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    (ASSETS / "stroller_porace.xml").write_text(model_xml(), encoding="utf-8")
    (ASSETS / "scene_stroller.xml").write_text(scene_xml(), encoding="utf-8")
    print("wrote", ASSETS / "stroller_porace.xml", "and scene_stroller.xml")


if __name__ == "__main__":
    main()
