#include "RacerGo2.h"

#include "RaceNames.h"
#include <cmath>

using namespace RaceContract;

bool FGo2Racer::Bind(const mjModel* m, const FString& InPrefix, double InHomeHeight)
{
	Prefix = InPrefix;
	HomeHeight = InHomeHeight;
	static const TCHAR* Legs[] = { TEXT("FL"), TEXT("FR"), TEXT("RL"), TEXT("RR") };
	static const TCHAR* Parts[] = { TEXT("hip"), TEXT("thigh"), TEXT("calf") };
	bool bOk = true;
	for (int32 i = 0; i < Nu; ++i)
	{
		const FString Leg = Legs[i / 3], Part = Parts[i % 3];
		Act[i] = Race::Find(m, mjOBJ_ACTUATOR, m->nu, Prefix + Leg + TEXT("_") + Part);
		const int32 J = Race::Find(m, mjOBJ_JOINT, m->njnt, Prefix + Leg + TEXT("_") + Part + TEXT("_joint"));
		bOk &= Act[i] >= 0 && J >= 0;
		Qadr[i] = J >= 0 ? m->jnt_qposadr[J] : -1;
		Vadr[i] = J >= 0 ? m->jnt_dofadr[J] : -1;
	}
	bOk &= ResolveRoot(m, TEXT("base"));
	JointDofs.Reset();
	for (int32 i = 0; i < Nu; ++i) JointDofs.Add(Vadr[i]);
	Imu = Race::Find(m, mjOBJ_SITE, m->nsite, Prefix + TEXT("imu"));
	auto Sensor = [&](const TCHAR* Name) { const int32 S = Race::Find(m, mjOBJ_SENSOR, m->nsensor, Prefix + Name); return S >= 0 ? m->sensor_adr[S] : -1; };
	AdrLinvel = Sensor(TEXT("local_linvel"));
	AdrGyro = Sensor(TEXT("gyro"));
	AdrUp = Sensor(TEXT("upvector"));
	bOk &= Imu >= 0 && AdrLinvel >= 0 && AdrGyro >= 0 && AdrUp >= 0;
	UE_CLOG(!bOk, LogRace, Error, TEXT("Go2 \"%s\": the model is missing some of its names (base %d, imu %d, sensors %d %d %d)"),
		*Prefix, Base, Imu, AdrLinvel, AdrGyro, AdrUp);
	Spawn[2] = HomeHeight;
	Resets = 0;
	Clear();
	return bOk;
}

void FGo2Racer::Clear()
{
	Mode = ERacerMode::Loco;
	State = ERacerState::Racing;
	Cmd[0] = Cmd[1] = Cmd[2] = 0.f;
	for (float& A : LastAction) A = 0.f;
	Phase = 0;
	UprightCount = FallenFor = StalledFor = 0;
	bDecided = false;
}

bool FGo2Racer::UpdateState(const mjModel* m, mjData* d)
{
	const double Up = UpZ(d);
	State = Up <= 0.0 ? ERacerState::Fallen : Up < StumbleZ ? ERacerState::Stumble : ERacerState::Racing;
	return AutoReset(m, d, State == ERacerState::Fallen);
}

void FGo2Racer::Control(const mjModel* m, mjData* d)
{
	bDecided = Phase % Go2::Decimation == 0;
	if (bDecided) Decide(m, d);
	++Phase;
}

void FGo2Racer::Decide(const mjModel* m, mjData* d)
{
	const double Up = UpZ(d);
	UprightCount = Up > UprightZ ? UprightCount + 1 : 0;
	if (Getup.IsValid())	// without a get-up brain (the parity testbed) the locomotion brain keeps the joints
	{
		if (Mode == ERacerMode::Loco && Up <= 0.0)
		{
			Mode = ERacerMode::Getup;
			for (float& A : LastAction) A = 0.f;
			Cmd[0] = Cmd[1] = Cmd[2] = 0.f;
		}
		else if (Mode == ERacerMode::Getup && UprightCount >= UprightDecisions)
		{
			Mode = ERacerMode::Loco;
			for (float& A : LastAction) A = 0.f;
		}
	}

	// state as mj_step left it (sensordata and site_xmat from the step's start: training read them the same way)
	float* O = Obs;
	const bool bLoco = Mode == ERacerMode::Loco;
	if (bLoco)
	{
		for (int32 k = 0; k < 3; ++k)
		{
			const float Tgt = (float)Target[k];
			Cmd[k] = Cmd[k] + FMath::Clamp(Tgt - Cmd[k], -Go2::CmdSlewStep, Go2::CmdSlewStep);
		}
		for (int32 k = 0; k < 3; ++k) *O++ = (float)d->sensordata[AdrLinvel + k];
	}
	for (int32 k = 0; k < 3; ++k) *O++ = (float)d->sensordata[AdrGyro + k];
	const mjtNum* R = d->site_xmat + 9 * Imu;	// world down in the imu frame: -(third row)
	for (int32 k = 0; k < 3; ++k) *O++ = (float)(-R[6 + k]);
	for (int32 j = 0; j < Nu; ++j) *O++ = (float)(d->qpos[Qadr[j]] - (double)Go2::DefaultPose[j]);
	for (int32 j = 0; j < Nu; ++j) *O++ = (float)d->qvel[Vadr[j]];
	for (int32 j = 0; j < Nu; ++j) *O++ = LastAction[j];
	if (bLoco) for (int32 k = 0; k < 3; ++k) *O++ = Cmd[k];

	const FRaceBrain& Brain = bLoco ? Loco : Getup;
	float Action[Nu] = {};
	if (Brain.IsValid() && !Brain.Run(Obs, Action, Nu))
	{
		UE_LOG(LogRace, Error, TEXT("%sbrain %s failed"), *Prefix, *Brain.Label);
		for (float& A : Action) A = 0.f;
	}
	for (int32 j = 0; j < Nu; ++j)
	{
		const float A = FMath::Clamp(Action[j], -1.f, 1.f);
		const float Base0 = bLoco ? Go2::DefaultPose[j] : (float)d->qpos[Qadr[j]];
		d->ctrl[Act[j]] = (double)(Base0 + Go2::ActionScale * A);	// float32, as training computes it
		LastAction[j] = A;
	}
}

void FGo2Racer::ResetToSpawn(const mjModel* m, mjData* d)
{
	for (int32 k = 0; k < 6; ++k) d->qvel[RootV + k] = 0.0;
	for (int32 j = 0; j < Nu; ++j) d->qvel[Vadr[j]] = 0.0;
	d->qpos[RootQ] = Spawn[0];
	d->qpos[RootQ + 1] = Spawn[1];
	d->qpos[RootQ + 2] = Spawn[2];
	d->qpos[RootQ + 3] = std::cos(SpawnYaw * 0.5);
	d->qpos[RootQ + 4] = 0.0;
	d->qpos[RootQ + 5] = 0.0;
	d->qpos[RootQ + 6] = std::sin(SpawnYaw * 0.5);
	for (int32 j = 0; j < Nu; ++j)
	{
		d->qpos[Qadr[j]] = (double)Go2::DefaultPose[j];
		d->ctrl[Act[j]] = (double)Go2::DefaultPose[j];
	}
	Clear();
	mj_forward(m, d);
}

void FGo2Racer::KnockOver(const mjModel* m, mjData* d)
{
	d->qpos[RootQ + 2] = 0.45;
	d->qpos[RootQ + 3] = 0.0;
	d->qpos[RootQ + 4] = 1.0;
	d->qpos[RootQ + 5] = 0.0;
	d->qpos[RootQ + 6] = 0.0;
	for (int32 k = 0; k < 6; ++k) d->qvel[RootV + k] = 0.0;
	mj_forward(m, d);
}
