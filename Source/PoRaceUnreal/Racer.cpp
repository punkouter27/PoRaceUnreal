#include "Racer.h"

#include "NNE.h"
#include "NNEModelData.h"
#include "NNERuntimeCPU.h"
#include "RaceNames.h"
#include <cmath>

std::atomic<int32> FRaceBrain::NanInfCount{ 0 };
std::atomic<uint64> FRaceBrain::InferenceCycles{ 0 };
std::atomic<int32> FRaceBrain::InferenceCalls{ 0 };

void FRaceBrain::AppendZeroInitInputs(TArray<float>& Obs, int32 ExtraCount)
{
	if (ExtraCount <= 0) return;
	const int32 Base = Obs.Num();
	Obs.SetNumUninitialized(Base + ExtraCount);
	for (int32 i = 0; i < ExtraCount; ++i)
	{
		Obs[Base + i] = 0.f;
	}
}

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
	const uint64 T0 = FPlatformTime::Cycles64();
	const bool bOk = Net->RunSync({ In }, { Out }) == UE::NNE::EResultStatus::Ok;
	InferenceCycles.fetch_add(FPlatformTime::Cycles64() - T0, std::memory_order_relaxed);
	InferenceCalls.fetch_add(1, std::memory_order_relaxed);
	if (bOk && OutAction)
	{
		for (int32 i = 0; i < NumAction; ++i)
		{
			if (!std::isfinite(OutAction[i]))
			{
				NanInfCount.fetch_add(1, std::memory_order_relaxed);
				OutAction[i] = 0.f;
			}
		}
	}
	return bOk;
}

bool FRacer::ResolveRoot(const mjModel* m, const FString& RootBody)
{
	Base = Race::Find(m, mjOBJ_BODY, m->nbody, Prefix + RootBody);
	if (Base < 0 || m->body_jntnum[Base] == 0) return false;
	const int32 Root = m->body_jntadr[Base];
	RootQ = m->jnt_qposadr[Root];
	RootV = m->jnt_dofadr[Root];
	return true;
}

double FRacer::Yaw(const mjData* d) const
{
	const double W = d->qpos[RootQ + 3], X = d->qpos[RootQ + 4], Y = d->qpos[RootQ + 5], Z = d->qpos[RootQ + 6];
	return std::atan2(2.0 * (W * Z + X * Y), 1.0 - 2.0 * (Y * Y + Z * Z));
}

double FRacer::PlanarSpeed2(const mjData* d) const
{
	const double Vx = d->qvel[RootV], Vy = d->qvel[RootV + 1];
	return Vx * Vx + Vy * Vy;
}

void FRacer::Hold(mjData* d) const
{
	d->qpos[RootQ] = Spawn[0];
	d->qpos[RootQ + 1] = Spawn[1];
	d->qpos[RootQ + 2] = Spawn[2];
	d->qpos[RootQ + 3] = 1.0;
	d->qpos[RootQ + 4] = d->qpos[RootQ + 5] = d->qpos[RootQ + 6] = 0.0;
	for (int32 k = 0; k < 6; ++k) d->qvel[RootV + k] = 0.0;
	for (const int32 V : JointDofs) d->qvel[V] = 0.0;
}

bool FRacer::AutoReset(const mjModel* m, mjData* d, bool bFallen)
{
	FallenFor = bFallen ? FallenFor + 1 : 0;
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
