#include "RacerStroller.h"

#include "Dom/JsonObject.h"
#include "RaceNames.h"
#include <cmath>

namespace
{
	constexpr double Pi = 3.14159265358979323846;
	constexpr double CmdSlewStep = 6.0 * (0.004 * 5);	// racelib/stroller.py: 6 m/s^2 per decision
	const TCHAR* Joints[4] = { TEXT("steer"), TEXT("wheel_front"), TEXT("wheel_rear_l"), TEXT("wheel_rear_r") };
	const TCHAR* Actuators[3] = { TEXT("steer"), TEXT("wheel_rear_l"), TEXT("wheel_rear_r") };
}

bool FStrollerRacer::Bind(const mjModel* m, const FString& InPrefix, const FJsonObject& Card)
{
	Prefix = InPrefix;
	HomeHeight = Card.GetNumberField(TEXT("homeHeight"));
	bool bOk = true;
	JointDofs.Reset();
	for (int32 k = 0; k < 4; ++k)
	{
		const int32 J = Race::Find(m, mjOBJ_JOINT, m->njnt, Prefix + Joints[k]);
		bOk &= J >= 0;
		Qadr[k] = J >= 0 ? m->jnt_qposadr[J] : -1;
		Vadr[k] = J >= 0 ? m->jnt_dofadr[J] : -1;
		JointDofs.Add(Vadr[k]);
	}
	for (int32 k = 0; k < NumAct; ++k)
	{
		Act[k] = Race::Find(m, mjOBJ_ACTUATOR, m->nu, Prefix + Actuators[k]);
		bOk &= Act[k] >= 0;
	}
	ActScale[0] = (float)Card.GetNumberField(TEXT("steerMax"));
	ActScale[1] = ActScale[2] = (float)Card.GetNumberField(TEXT("wheelTorque"));
	bOk &= ResolveRoot(m, Card.GetStringField(TEXT("rootBody")));
	Imu = Race::Find(m, mjOBJ_SITE, m->nsite, Prefix + TEXT("imu"));
	auto Sensor = [&](const TCHAR* Name) { const int32 Id = Race::Find(m, mjOBJ_SENSOR, m->nsensor, Prefix + Name); return Id >= 0 ? m->sensor_adr[Id] : -1; };
	AdrLinvel = Sensor(TEXT("local_linvel"));
	AdrGyro = Sensor(TEXT("gyro"));
	AdrUp = Sensor(TEXT("upvector"));
	bOk &= Imu >= 0 && AdrLinvel >= 0 && AdrGyro >= 0 && AdrUp >= 0;
	UE_CLOG(!bOk, LogRace, Error, TEXT("stroller \"%s\": the model is missing some of its names (base %d, imu %d, sensors %d %d %d)"),
		*Prefix, Base, Imu, AdrLinvel, AdrGyro, AdrUp);
	Spawn[0] = Spawn[1] = 0.0;
	Spawn[2] = HomeHeight;
	Resets = 0;
	Clear();
	return bOk;
}

void FStrollerRacer::Clear()
{
	State = ERacerState::Racing;
	for (float& C : Cmd) C = 0.f;
	for (float& A : LastAction) A = 0.f;
	for (float& O : Obs) O = 0.f;
	StepPhase = 0;
	FallenFor = StalledFor = 0;
	bDecided = false;
}

bool FStrollerRacer::UpdateState(const mjModel* m, mjData* d)
{
	const double Up = UpZ(d);
	State = Up < TipUpZ ? ERacerState::Fallen : Up < StumbleZ ? ERacerState::Stumble : ERacerState::Racing;
	return AutoReset(m, d, State == ERacerState::Fallen);
}

void FStrollerRacer::Control(const mjModel* m, mjData* d)
{
	bDecided = StepPhase % Decimation == 0;
	if (bDecided) Decide(m, d);
	++StepPhase;
}

void FStrollerRacer::Decide(const mjModel* m, mjData* d)
{
	for (int32 k = 0; k < 3; ++k)
	{
		const float Tgt = k == 1 ? 0.f : (float)Target[k];	// wheels cannot strafe: the brain never saw a sideways command
		Cmd[k] = Cmd[k] + FMath::Clamp(Tgt - Cmd[k], -(float)CmdSlewStep, (float)CmdSlewStep);
	}
	// linvel 3, gyro 3, gravity 3, steer angle, steer rate, wheel speeds x 0.1 (front, rear l, rear r), last action 3, command 3
	float* O = Obs;
	for (int32 k = 0; k < 3; ++k) *O++ = (float)d->sensordata[AdrLinvel + k];
	for (int32 k = 0; k < 3; ++k) *O++ = (float)d->sensordata[AdrGyro + k];
	const mjtNum* R = d->site_xmat + 9 * Imu;	// world down in the imu frame: -(third row)
	for (int32 k = 0; k < 3; ++k) *O++ = (float)(-R[6 + k]);
	*O++ = (float)d->qpos[Qadr[0]];
	*O++ = (float)d->qvel[Vadr[0]];
	for (int32 k = 1; k < 4; ++k) *O++ = (float)(d->qvel[Vadr[k]] * WheelObsScale);
	for (int32 k = 0; k < NumAct; ++k) *O++ = LastAction[k];
	for (int32 k = 0; k < 3; ++k) *O++ = Cmd[k];

	float Action[NumAct] = {};
	if (Loco.IsValid() && !Loco.Run(Obs, Action, NumAct)) UE_LOG(LogRace, Error, TEXT("%sbrain %s failed"), *Prefix, *Loco.Label);
	for (int32 k = 0; k < NumAct; ++k)
	{
		Action[k] = FMath::Clamp(Action[k], -1.f, 1.f);
		d->ctrl[Act[k]] = (double)(Action[k] * ActScale[k]);
		LastAction[k] = Action[k];
	}
}

void FStrollerRacer::ResetToSpawn(const mjModel* m, mjData* d)
{
	for (int32 k = 0; k < 6; ++k) d->qvel[RootV + k] = 0.0;
	for (int32 k = 0; k < 4; ++k) d->qvel[Vadr[k]] = 0.0;
	d->qpos[RootQ] = Spawn[0];
	d->qpos[RootQ + 1] = Spawn[1];
	d->qpos[RootQ + 2] = Spawn[2];
	d->qpos[RootQ + 3] = std::cos(SpawnYaw * 0.5);
	d->qpos[RootQ + 4] = 0.0;
	d->qpos[RootQ + 5] = 0.0;
	d->qpos[RootQ + 6] = std::sin(SpawnYaw * 0.5);
	for (int32 k = 0; k < 4; ++k) d->qpos[Qadr[k]] = 0.0;
	for (int32 k = 0; k < NumAct; ++k) d->ctrl[Act[k]] = 0.0;
	Clear();
	mj_forward(m, d);
}

void FStrollerRacer::KnockOver(const mjModel* m, mjData* d)
{
	// on its side, in place (racelib/stroller.py knock_over)
	d->qpos[RootQ + 2] = 0.45;
	d->qpos[RootQ + 3] = std::cos(Pi / 4);
	d->qpos[RootQ + 4] = std::sin(Pi / 4);
	d->qpos[RootQ + 5] = 0.0;
	d->qpos[RootQ + 6] = 0.0;
	for (int32 k = 0; k < 6; ++k) d->qvel[RootV + k] = 0.0;
	mj_forward(m, d);
}
