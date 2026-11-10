#include "RacerHuman.h"

#include "Dom/JsonObject.h"
#include "RaceNames.h"
#include <cmath>

namespace
{
	constexpr double Pi = 3.14159265358979323846;
	constexpr double CmdSlewStep = 6.0 * (0.004 * 5);	// racelib/human.py: 6.0 * CTRL_DT
}

double FHumanRacer::Wrap(double P)
{
	// (p + pi) % (2 pi) - pi with Python / NumPy float modulo: fmod, then a negative remainder moved up by 2 pi
	const double TwoPi = 2.0 * Pi;
	double R = std::fmod(P + Pi, TwoPi);
	if (R != 0.0 && R < 0.0) R += TwoPi;
	return R - Pi;
}

bool FHumanRacer::Bind(const mjModel* m, const FString& InPrefix, const FJsonObject& Card, const FJsonObject& Creature)
{
	Prefix = InPrefix;
	HomeHeight = Card.GetNumberField(TEXT("homeHeight"));
	const TArray<TSharedPtr<FJsonValue>>& Joints = Creature.GetArrayField(TEXT("joints"));
	const TArray<TSharedPtr<FJsonValue>>& Actuators = Creature.GetArrayField(TEXT("actuators"));
	const TArray<double> Pose = Race::Numbers(Creature.GetArrayField(TEXT("default_pose")));
	Nu = Joints.Num();
	Act.Reset(); Qadr.Reset(); JointDofs.Reset(); Default.Reset();
	bool bOk = Actuators.Num() == Nu && Pose.Num() == Nu;
	for (int32 i = 0; i < Nu && bOk; ++i)
	{
		const int32 A = Race::Find(m, mjOBJ_ACTUATOR, m->nu, Prefix + Actuators[i]->AsString());
		const int32 J = Race::Find(m, mjOBJ_JOINT, m->njnt, Prefix + Joints[i]->AsString());
		bOk &= A >= 0 && J >= 0;
		Act.Add(A);
		Qadr.Add(J >= 0 ? m->jnt_qposadr[J] : -1);
		JointDofs.Add(J >= 0 ? m->jnt_dofadr[J] : -1);
		Default.Add((float)Pose[i]);
	}
	bOk &= ResolveRoot(m, Creature.GetStringField(TEXT("root_body")));
	const TSharedPtr<FJsonObject> S = Card.GetObjectField(TEXT("sensors"));
	Imu = Race::Find(m, mjOBJ_SITE, m->nsite, Prefix + S->GetStringField(TEXT("imu")));
	auto Sensor = [&](const TCHAR* Key) { const int32 Id = Race::Find(m, mjOBJ_SENSOR, m->nsensor, Prefix + S->GetStringField(Key)); return Id >= 0 ? m->sensor_adr[Id] : -1; };
	AdrLinvel = Sensor(TEXT("linvel"));
	AdrGyro = Sensor(TEXT("gyro"));
	AdrUp = Sensor(TEXT("up"));
	bOk &= Imu >= 0 && AdrLinvel >= 0 && AdrGyro >= 0 && AdrUp >= 0;
	const TSharedPtr<FJsonObject> G = Card.GetObjectField(TEXT("gait"));
	GaitHz = G->GetNumberField(TEXT("hz"));
	GaitSlope = G->GetNumberField(TEXT("slope"));
	GaitV0 = G->GetNumberField(TEXT("v0"));
	FallenPelvisZ = Card.GetNumberField(TEXT("fallenPelvisZ"));
	FallenUpZ = Card.GetNumberField(TEXT("fallenUpZ"));
	LimpAfter = (int32)Card.GetNumberField(TEXT("limpAfterDecisions"));
	UE_CLOG(!bOk, LogRace, Error, TEXT("human \"%s\": the model is missing some of its names (base %d, imu %d, sensors %d %d %d)"),
		*Prefix, Base, Imu, AdrLinvel, AdrGyro, AdrUp);
	Cmd.Init(0.f, 3);
	LastAction.Init(0.f, Nu);
	Obs.Init(0.f, 12 + 3 * Nu + 4);
	Spawn[0] = Spawn[1] = 0.0;
	Spawn[2] = HomeHeight;
	Resets = 0;
	Clear();
	return bOk;
}

void FHumanRacer::Clear()
{
	bLimp = false;
	State = ERacerState::Racing;
	for (float& C : Cmd) C = 0.f;
	for (float& A : LastAction) A = 0.f;
	Phase = 0.0;
	Decisions = StepPhase = 0;
	DownDecisions = 0;
	bUpright = true;
	FallenFor = StalledFor = 0;
	bDecided = false;
}

bool FHumanRacer::UpdateState(const mjModel* m, mjData* d)
{
	const double Up = UpZ(d);
	State = (Up < 0.0 || !bUpright) ? ERacerState::Fallen : Up < StumbleZ ? ERacerState::Stumble : ERacerState::Racing;
	return AutoReset(m, d, State == ERacerState::Fallen);
}

void FHumanRacer::Control(const mjModel* m, mjData* d)
{
	bDecided = StepPhase % Decimation == 0;
	if (bDecided) Decide(m, d);
	++StepPhase;
}

void FHumanRacer::Decide(const mjModel* m, mjData* d)
{
	const bool bDown = d->qpos[RootQ + 2] < FallenPelvisZ || UpZ(d) < FallenUpZ;
	DownDecisions = bDown ? DownDecisions + 1 : 0;
	bUpright = !bDown;
	for (int32 k = 0; k < 3; ++k)
	{
		const float Tgt = (float)Target[k];
		Cmd[k] = Cmd[k] + FMath::Clamp(Tgt - Cmd[k], -(float)CmdSlewStep, (float)CmdSlewStep);
	}
	// the observation: linvel 3, gyro 3, gravity 3, command 3, q - default, qvel, last action, cos L R, sin L R
	float* O = Obs.GetData();
	for (int32 k = 0; k < 3; ++k) *O++ = (float)d->sensordata[AdrLinvel + k];
	for (int32 k = 0; k < 3; ++k) *O++ = (float)d->sensordata[AdrGyro + k];
	const mjtNum* R = d->site_xmat + 9 * Imu;	// world down in the imu frame: -(third row)
	for (int32 k = 0; k < 3; ++k) *O++ = (float)(-R[6 + k]);
	for (int32 k = 0; k < 3; ++k) *O++ = Cmd[k];
	for (int32 j = 0; j < Nu; ++j) *O++ = (float)(d->qpos[Qadr[j]] - (double)Default[j]);
	for (int32 j = 0; j < Nu; ++j) *O++ = (float)d->qvel[JointDofs[j]];
	for (int32 j = 0; j < Nu; ++j) *O++ = LastAction[j];
	const double PhL = Wrap(Phase), PhR = Wrap(Pi + Phase);
	*O++ = (float)std::cos(PhL);
	*O++ = (float)std::cos(PhR);
	*O++ = (float)std::sin(PhL);
	*O++ = (float)std::sin(PhR);

	if (DownDecisions > LimpAfter)
	{
		// limp on the ground: targets follow the joints, so the motors push nothing into the floor
		bLimp = true;
		for (int32 j = 0; j < Nu; ++j) { LastAction[j] = 0.f; d->ctrl[Act[j]] = (double)(float)d->qpos[Qadr[j]]; }
	}
	else
	{
		bLimp = false;
		TArray<float, TInlineAllocator<64>> Action;
		Action.SetNumZeroed(Nu);
		if (Loco.IsValid() && !Loco.Run(Obs.GetData(), Action.GetData(), Nu)) UE_LOG(LogRace, Error, TEXT("%sbrain %s failed"), *Prefix, *Loco.Label);
		for (int32 j = 0; j < Nu; ++j)	// the trainer does not clip actions
		{
			d->ctrl[Act[j]] = (double)(Default[j] + ActionScale * Action[j]);
			LastAction[j] = Action[j];
		}
	}
	if (Decisions >= 1)
	{
		const double CtrlDt = SimDt * Decimation;
		const double Dphi = 2.0 * Pi * CtrlDt * (GaitHz + GaitSlope * std::max(0.0, std::abs((double)Cmd[0]) - GaitV0));
		Phase = Wrap(Phase + Dphi);
	}
	++Decisions;
}

void FHumanRacer::ResetToSpawn(const mjModel* m, mjData* d)
{
	for (int32 k = 0; k < 6; ++k) d->qvel[RootV + k] = 0.0;
	for (const int32 V : JointDofs) d->qvel[V] = 0.0;
	d->qpos[RootQ] = Spawn[0];
	d->qpos[RootQ + 1] = Spawn[1];
	d->qpos[RootQ + 2] = Spawn[2];
	d->qpos[RootQ + 3] = std::cos(SpawnYaw * 0.5);
	d->qpos[RootQ + 4] = 0.0;
	d->qpos[RootQ + 5] = 0.0;
	d->qpos[RootQ + 6] = std::sin(SpawnYaw * 0.5);
	for (int32 j = 0; j < Nu; ++j)
	{
		d->qpos[Qadr[j]] = (double)Default[j];
		d->ctrl[Act[j]] = (double)Default[j];
	}
	Clear();
	mj_forward(m, d);
}

void FHumanRacer::KnockOver(const mjModel* m, mjData* d)
{
	// on his back, as the Unity MattController: pelvis at 0.35 m, pitched 90 degrees back (racelib/human.py knock_over)
	d->qpos[RootQ + 2] = 0.35;
	d->qpos[RootQ + 3] = std::cos(Pi / 4);
	d->qpos[RootQ + 4] = 0.0;
	d->qpos[RootQ + 5] = -std::sin(Pi / 4);
	d->qpos[RootQ + 6] = 0.0;
	for (int32 k = 0; k < 6; ++k) d->qvel[RootV + k] = 0.0;
	mj_forward(m, d);
}
