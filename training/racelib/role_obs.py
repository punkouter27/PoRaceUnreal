"""The role-ordered interface for this app: 131 observations in, 28 role actions out.

RULES.md R6-R8/R13/R14 in ``global/UNITE/RULES.md``. Race builds three brains (Go2, Matt, Grandma, G1) plus the
Unreal and web twins, and each of those bodies already has a contract under ``global/UNITE/creatures``. This
module is the portable view of any of them, so a brain trained against the shared interface can be driven in a
race without re-deriving the layout.

It does **not** replace the racer's own observation. ``racelib/human.py`` builds the racing layout (linvel,
gyro, gravity, command, q-default, qdot, last action, gait clock) and ``Source/PoRaceUnreal/RacerHuman.cpp``
mirrors that class line for line; the two must keep agreeing with each other, not with this file. This file
answers the other question: can this body be driven by a brain trained anywhere in the family?

Every implementation must reproduce the creature's ``golden_role_obs.npz`` to 1e-5 — written by
``global/UNITE/tools/role_obs.py``, which is the authority. ``tests/test_role_obs.py`` is the proof, per creature.

R28: a body with no contract is not invented here. ``find_contract`` returns ``None`` and the caller reports the gap.
"""

from __future__ import annotations

import hashlib
import json
import math
import pathlib
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

ROLE_SLOTS = (
    "joint_pos_rel",
    "joint_vel",
    "prev_action",
    "base_ang_vel",
    "projected_gravity",
    "velocity_commands",
    "gait_phase",
    "role_mask",
    "morphology_onehot",
)
DEFAULT_GAIT_PERIOD_S = 0.8
MOVING_COMMAND_THRESHOLD = 0.1

UNITE = pathlib.Path(__file__).resolve().parents[3] / "global" / "UNITE"
CREATURES = UNITE / "creatures"


class ContractMismatch(RuntimeError):
    """The policy does not match the contract it would drive (R14): refuse, never degrade."""


@dataclass
class RoleState:
    """The four inputs the universal observation needs, in this app's joint order."""

    q: np.ndarray
    dq: np.ndarray
    imu_quat: np.ndarray  # (w, x, y, z), root body in world
    gyro: np.ndarray  # body-frame angular velocity, (3,)


def available() -> bool:
    return CREATURES.is_dir()


def contract_for(creature_id: str) -> dict:
    path = CREATURES / creature_id / "contract.json"
    if not path.is_file():
        raise ContractMismatch(f"no contract at {path}; R28: report the gap, do not invent one")
    return json.loads(path.read_text(encoding="utf-8"))


def find_contract(joint_names: Sequence[str]) -> str | None:
    """The creature whose contract joint set is contained in ``joint_names`` (largest match wins)."""
    if not available():
        return None
    names = set(joint_names)
    best: tuple[str, int] | None = None
    for path in sorted(CREATURES.iterdir()):
        if not (path / "contract.json").is_file():
            continue
        c = json.loads((path / "contract.json").read_text(encoding="utf-8"))
        cj = {j["name"] for j in c["morphology"]["joints"]}
        if cj <= names and (best is None or len(cj) > best[1]):
            best = (path.name, len(cj))
    return None if best is None else best[0]


def projected_gravity(quat: Sequence[float]) -> np.ndarray:
    """World gravity (0, 0, -1) in the body frame: ``R^T g``, unit quaternion assumed."""
    w, x, y, z = (float(v) for v in quat)
    n = w * w + x * x + y * y + z * z
    if n < 1e-12:
        return np.array([0.0, 0.0, -1.0])
    s = 2.0 / n
    R = np.array(
        [
            [1 - s * (y * y + z * z), s * (x * y - z * w), s * (x * z + y * w)],
            [s * (x * y + z * w), 1 - s * (x * x + z * z), s * (y * z - x * w)],
            [s * (x * z - y * w), s * (y * z + x * w), 1 - s * (x * x + y * y)],
        ]
    )
    return R.T @ np.array([0.0, 0.0, -1.0])


class RoleObs:
    """131 floats, role ordered, zero where this body has no joint for a role (R6)."""

    def __init__(self, contract: dict, joint_names: Sequence[str]):
        self.roles: list[str] = list(contract["roles"]["canonical_order"])
        self.n_roles = len(self.roles)
        self.mask = np.asarray(contract["roles"]["mask"], dtype=np.float32)
        self.slots = {
            s["name"]: (int(s["start"]), int(s["size"]), float(s["scale"])) for s in contract["observation"]["slots"]
        }
        self.n_obs = int(contract["observation"]["n_obs"])
        self.onehot_size = int(contract["roles"].get("morphology_onehot_size", 8))
        self.morphology_id = int(contract["roles"].get("morphology_id", 0))
        self.joint_index: dict[str, int] = {n: i for i, n in enumerate(joint_names)}

        self.joint_of_role: dict[str, int] = {}
        self.default_of_role = np.zeros(self.n_roles, dtype=np.float64)
        for j in contract["morphology"]["joints"]:
            role = j.get("role")
            i = self.joint_index.get(j["name"])
            if role in self.roles and i is not None:
                self.joint_of_role[role] = i
                self.default_of_role[self.roles.index(role)] = float(j.get("default") or 0.0)

        missing = [n for n in ROLE_SLOTS if n not in self.slots]
        if missing:
            raise ValueError(f"contract is missing observation slots {missing}")
        self.obs = np.zeros(self.n_obs, dtype=np.float32)

    def slice_of(self, obs: np.ndarray, name: str) -> np.ndarray:
        start, size, _ = self.slots[name]
        return obs[start : start + size]

    def build(
        self,
        state: RoleState,
        prev_action: np.ndarray,
        command: Sequence[float] | None = None,
        t: float = 0.0,
        gait_period_s: float = DEFAULT_GAIT_PERIOD_S,
    ) -> np.ndarray:
        obs = self.obs
        pos = np.zeros(self.n_roles, dtype=np.float64)
        vel = np.zeros(self.n_roles, dtype=np.float64)
        act = np.zeros(self.n_roles, dtype=np.float64)
        prev = np.asarray(prev_action, dtype=np.float64).reshape(-1)

        for i, role in enumerate(self.roles):
            if self.mask[i] == 0:
                continue
            j = self.joint_of_role.get(role)
            if j is None:
                continue
            pos[i] = float(state.q[j]) - self.default_of_role[i]
            vel[i] = float(state.dq[j])
            if i < prev.shape[0]:
                act[i] = prev[i]

        cmd = np.zeros(3, dtype=np.float64)
        if command is not None:
            c = np.asarray(command, dtype=np.float64).reshape(-1)
            cmd[: min(3, c.shape[0])] = c[:3]
        if float(np.linalg.norm(cmd)) >= MOVING_COMMAND_THRESHOLD:
            phase = (t / float(gait_period_s)) % 1.0
            gait = np.array([math.sin(2.0 * math.pi * phase), math.cos(2.0 * math.pi * phase)])
        else:
            gait = np.zeros(2)

        onehot = np.zeros(self.onehot_size, dtype=np.float64)
        if 0 <= self.morphology_id < self.onehot_size:
            onehot[self.morphology_id] = 1.0

        blocks = {
            "joint_pos_rel": pos,
            "joint_vel": vel,
            "prev_action": act,
            "base_ang_vel": np.asarray(state.gyro, dtype=np.float64).reshape(3),
            "projected_gravity": projected_gravity(state.imu_quat),
            "velocity_commands": cmd,
            "gait_phase": gait,
            "role_mask": self.mask,
            "morphology_onehot": onehot,
        }
        for name, values in blocks.items():
            start, size, scale = self.slots[name]
            if len(values) != size:
                raise ValueError(f"slot {name}: built {len(values)} values, contract says {size}")
            obs[start : start + size] = np.asarray(values, dtype=np.float64) * scale
        return obs


class RoleActionMap:
    """28 role actions -> joint targets, with the contract's gains (R7, layer 6)."""

    def __init__(self, contract: dict, joint_names: Sequence[str]):
        self.roles: list[str] = list(contract["roles"]["canonical_order"])
        self.mask = np.asarray(contract["roles"]["mask"], dtype=np.float64)
        self.n_roles = len(self.roles)
        self.joint_names = list(joint_names)
        self.index: dict[str, int] = {n: i for i, n in enumerate(self.joint_names)}
        self.n_joints = len(self.joint_names)

        factor = float(contract["action"].get("soft_limit_factor", 0.9))
        self.q_default = np.zeros(self.n_joints, dtype=np.float64)
        self.kp = np.zeros(self.n_joints, dtype=np.float64)
        self.kd = np.zeros(self.n_joints, dtype=np.float64)
        self.scale = np.zeros(self.n_joints, dtype=np.float64)
        self.lo = np.zeros(self.n_joints, dtype=np.float64)
        self.hi = np.zeros(self.n_joints, dtype=np.float64)

        self.joint_of_role: dict[str, int] = {}
        for j in contract["morphology"]["joints"]:
            i = self.index.get(j["name"])
            if i is None:
                continue
            self.q_default[i] = float(j.get("default") or 0.0)
            self.kp[i] = float(j.get("kp") or 0.0)
            self.kd[i] = float(j.get("kd") or 0.0)
            self.scale[i] = float(j.get("action_scale") or 0.0)
            lo, hi = (float(x) for x in j["range"])
            pad = (1.0 - factor) * 0.5 * (hi - lo)
            self.lo[i] = lo + pad
            self.hi[i] = hi - pad
            role = j.get("role")
            if role in self.roles:
                self.joint_of_role[role] = i

    @property
    def unmapped_joints(self) -> list[str]:
        driven = set(self.joint_of_role.values())
        return [n for i, n in enumerate(self.joint_names) if i not in driven]

    def targets(self, action: np.ndarray) -> np.ndarray:
        a = np.asarray(action, dtype=np.float64).reshape(-1)
        if a.shape[0] != self.n_roles:
            raise ValueError(f"action has {a.shape[0]} values, the role interface wants {self.n_roles}")
        q = self.q_default.copy()
        for i, role in enumerate(self.roles):
            j = self.joint_of_role.get(role)
            if j is None or self.mask[i] == 0:
                continue
            q[j] = min(max(self.q_default[j] + a[i] * self.scale[j], self.lo[j]), self.hi[j])
        return q


class RoleInterface:
    """Both halves plus gains, for a runner that speaks the universal interface."""

    def __init__(self, contract: dict, joint_names: Sequence[str]):
        self.contract = contract
        self.obs = RoleObs(contract, joint_names)
        self.action = RoleActionMap(contract, joint_names)
        self.n_obs = self.obs.n_obs
        self.n_action = self.obs.n_roles
        self.roles = self.obs.roles
        self.mask = self.obs.mask
        self.kp = self.action.kp.copy()
        self.kd = self.action.kd.copy()
        self.foreign = False
        self.trained_for: str | None = None
        if self.n_action != int(contract["action"]["n_action"]):
            raise ValueError(
                f"contract roles ({self.n_action}) disagree with action.n_action ({contract['action']['n_action']})"
            )

    @classmethod
    def from_fingerprint(cls, fingerprint: dict) -> RoleInterface:
        """Build from one of this repo's ``*_fingerprint.json`` files. Raises when no contract covers the body."""
        names = list(fingerprint["joints"])
        creature = find_contract(names)
        if creature is None:
            raise ContractMismatch(
                f"no UNITE contract covers this body ({len(names)} joints); R28: report the gap, do not invent one"
            )
        return cls(contract_for(creature), names)

    def build(self, state: RoleState, prev_action, command=None, t: float = 0.0) -> np.ndarray:
        return self.obs.build(state, prev_action, command, t)

    def targets(self, action: np.ndarray) -> np.ndarray:
        return self.action.targets(action)


def _sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sidecar_problems(policy_path: str | pathlib.Path, contract: dict, *, foreign: bool = False) -> list[str]:
    """What a runtime checks before trusting a brain (R10/R14). Empty list = loadable.

    ``foreign=True`` is R13: another body's brain may run here when the *interface* hash matches.
    """
    path = pathlib.Path(policy_path)
    sidecar = path.with_suffix(".json")
    if not sidecar.is_file():
        return [f"{path.name} has no sidecar ({sidecar.name}); R10 requires one beside every onnx"]
    sc = json.loads(sidecar.read_text(encoding="utf-8"))
    problems: list[str] = []
    for key in ("interface_sha256", "morphology_sha256", "physics_sha256", "policy_sha256"):
        if not sc.get(key):
            problems.append(f"sidecar is missing {key}")
    keys = ("interface_sha256",) if foreign else ("interface_sha256", "morphology_sha256", "physics_sha256")
    for key in keys:
        want = contract["hashes"][key]
        got = sc.get(key)
        if got and got != want:
            problems.append(f"sidecar {key} = {str(got)[:16]}... but this creature's contract has {want[:16]}...")
    if sc.get("policy_sha256") and sc["policy_sha256"] != _sha256(path):
        problems.append("policy_sha256 does not match the onnx; the file changed after the sidecar was written")
    if int(sc.get("n_obs", -1)) != int(contract["observation"]["n_obs"]):
        problems.append(f"sidecar n_obs {sc.get('n_obs')} != contract {contract['observation']['n_obs']}")
    if int(sc.get("n_action", -1)) != int(contract["action"]["n_action"]):
        problems.append(f"sidecar n_action {sc.get('n_action')} != contract {contract['action']['n_action']}")
    return problems


def for_policy(nn, joint_names: Sequence[str], contract: dict | None = None) -> RoleInterface:
    """Build the interface for a conforming ONNX, or raise: this path does not degrade (R14)."""
    c = contract if contract is not None else contract_for(find_contract(joint_names) or "")
    want = (int(c["observation"]["n_obs"]), int(c["action"]["n_action"]))
    if (int(nn.num_obs), int(nn.num_actions)) != want:
        raise ContractMismatch(
            f"policy io {nn.num_obs}->{nn.num_actions} is not the role interface {want[0]}->{want[1]}"
        )
    sc_path = pathlib.Path(nn.path).with_suffix(".json")
    sc = json.loads(sc_path.read_text(encoding="utf-8")) if sc_path.is_file() else {}
    foreign = bool(sc.get("creature")) and sc.get("creature") != c["creature"]
    problems = sidecar_problems(nn.path, c, foreign=foreign)
    if problems:
        raise ContractMismatch(f"role policy refused: {problems[0]}")
    iface = RoleInterface(c, joint_names)
    iface.foreign = foreign
    iface.trained_for = sc.get("creature")
    return iface
