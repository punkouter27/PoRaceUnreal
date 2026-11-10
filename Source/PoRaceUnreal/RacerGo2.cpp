#include "RacerGo2.h"

#include "NNE.h"
#include "NNEModelData.h"
#include "NNERuntimeCPU.h"
#include "RaceNames.h"
#include <cmath>

using namespace RaceContract;

bool FRaceBrain::Load(UNNEModelData* Data)
{
	Net.Reset();
	NumIn = 0;
	if (!Data) return false;
	// ORT on desktop (bit-exact with training's onnxruntime). Android has no ORT in UE 5.8: Slice 12 adds Basic CPU.
	TWeakInterfacePtr<INNERuntimeCPU> Runtime = UE::NNE::GetRuntime<INNERuntimeCPU>(TEXT("NNERuntimeORTCpu"));
	TSharedPtr<UE::NNE::IModelCPU> Model = Runtime.IsValid() ? Runtime->CreateModelCPU(Data) : nullptr;
	Net = Model ? Model->CreateModelInstanceCPU() : nullptr;
	if (!Net)
	{
		UE_LOG(LogRace, Error, TEXT("brain %s: NNERuntimeORTCpu could not load it"), *Data->GetName());
		return false;
	}
	const TConstArrayView<int32> In = Net->GetInputTensorDescs()[0].GetShape().GetData();
	NumIn = In.Num() > 1 && In[1] > 0 ? In[1] : 0;
	const uint32 Shape[] = { 1, (uint32)NumIn };
	Net->SetInputTensorShapes({ UE::NNE::FTensorShape::Make(Shape) });
	Label = Data->GetName();
	return NumIn > 0;
}

bool FRaceBrain::Run(const float* InObs, float* OutAction, int32 NumAction) const
{
	const UE::NNE::FTensorBindingCPU In{ (void*)InObs, (uint64)NumIn * sizeof(float) };
	const UE::NNE::FTensorBindingCPU Out{ OutAction, (uint64)NumAction * sizeof(float) };
	return Net->RunSync({ In }, { Out }) == UE::NNE::EResultStatus::Ok;
}

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
	Base = Race::Find(m, mjOBJ_BODY, m->nbody, Prefix + TEXT("base"));
	bOk &= Base >= 0 && m->body_jntnum[Base] > 0;
	if (bOk)
	{
		const int32 Root = m->body_jntadr[Base];
		RootQ = m->jnt_qposadr[Root];
		RootV = m->jnt_dofadr[Root];
	}
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

double FGo2Racer::Yaw(const mjData* d) const
{
	const double W = d->qpos[RootQ + 3], X = d->qpos[RootQ + 4], Y = d->qpos[RootQ + 5], Z = d->qpos[RootQ + 6];
	return std::atan2(2.0 * (W * Z + X * Y), 1.0 - 2.0 * (Y * Y + Z * Z));
}

double FGo2Racer::PlanarSpeed2(const mjData* d) const
{
	const double Vx = d->qvel[RootV], Vy = d->qvel[RootV + 1];
	return Vx * Vx + Vy * Vy;
}

bool FGo2Racer::UpdateState(const mjModel* m, mjData* d)
{
	const double Up = UpZ(d);
	State = Up <= 0.0 ? ERacerState::Fallen : Up < StumbleZ ? ERacerState::Stumble : ERacerState::Racing;
	FallenFor = State == ERacerState::Fallen ? FallenFor + 1 : 0;
	const bool bWants = Target[0] * Target[0] + Target[1] * Target[1] + Target[2] * Target[2] > 0.01;
	StalledFor = bWants && PlanarSpeed2(d) < StallSpeed * StallSpeed ? StalledFor + 1 : 0;
	const bool bNaN = std::isnan(d->qpos[RootQ + 2]) || std::isnan(d->qvel[RootV]);
	if (bNaN || FallenFor > FallenSteps || StalledFor > StallSteps)
	{
		UE_LOG(LogRace, Log, TEXT("%sreset: %s fallen %d stalled %d steps -> (%.1f, %.1f)"), *Prefix,
			bNaN ? TEXT("NaN state,") : TEXT(""), FallenFor, StalledFor, Spawn[0], Spawn[1]);
		ResetToSpawn(m, d);
		++Resets;
		return true;
	}
	return false;
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
