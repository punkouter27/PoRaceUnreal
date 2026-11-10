// URacerController: the Go2's brain loop on URLab's physics thread, and the parity gate's replay and recording.
// Every step here has a twin in training/go2/sim.py; change both or the parity check (training/parity_check.py) fails.

#include "RacerController.h"

#include "Async/Async.h"
#include "HAL/FileManager.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "NNE.h"
#include "NNEModelData.h"
#include "NNERuntimeCPU.h"
#include "RaceContract.gen.h"
#include "RaceNames.h"

DEFINE_LOG_CATEGORY(LogRace);

using namespace RaceContract;

static_assert(mjVERSION_HEADER == RaceContract::MuJoCoVersionHeader, "URLab's MuJoCo is not the version the brains are gated on (training/contract.py)");

namespace
{
	/** The fingerprint's solver options onto the compiled model: URLab attaches the MJCF as a child spec, which drops
	 *  the file's <option> block, and its own override is single precision. */
	void ApplyOptions(mjModel* m, const FJsonObject& O)
	{
		mjOption& Opt = m->opt;
		auto D = [&O](const TCHAR* K) { return O.GetNumberField(K); };
		auto I = [&O](const TCHAR* K) { return (int)O.GetNumberField(K); };
		auto V = [&O](const TCHAR* K, mjtNum* Out, int32 N)
		{
			const TArray<TSharedPtr<FJsonValue>>& A = O.GetArrayField(K);
			for (int32 k = 0; k < N && k < A.Num(); ++k) Out[k] = A[k]->AsNumber();
		};
		Opt.timestep = D(TEXT("timestep"));
		Opt.impratio = D(TEXT("impratio"));
		Opt.tolerance = D(TEXT("tolerance"));
		Opt.ls_tolerance = D(TEXT("ls_tolerance"));
		Opt.noslip_tolerance = D(TEXT("noslip_tolerance"));
		Opt.ccd_tolerance = D(TEXT("ccd_tolerance"));
		Opt.density = D(TEXT("density"));
		Opt.viscosity = D(TEXT("viscosity"));
		Opt.o_margin = D(TEXT("o_margin"));
		Opt.integrator = I(TEXT("integrator"));
		Opt.cone = I(TEXT("cone"));
		Opt.jacobian = I(TEXT("jacobian"));
		Opt.solver = I(TEXT("solver"));
		Opt.iterations = I(TEXT("iterations"));
		Opt.ls_iterations = I(TEXT("ls_iterations"));
		Opt.noslip_iterations = I(TEXT("noslip_iterations"));
		Opt.ccd_iterations = I(TEXT("ccd_iterations"));
		Opt.disableflags = I(TEXT("disableflags"));
		Opt.enableflags = I(TEXT("enableflags"));
		Opt.sdf_initpoints = I(TEXT("sdf_initpoints"));
		Opt.sdf_iterations = I(TEXT("sdf_iterations"));
		V(TEXT("gravity"), Opt.gravity, 3);
		V(TEXT("wind"), Opt.wind, 3);
		V(TEXT("magnetic"), Opt.magnetic, 3);
		V(TEXT("o_solref"), Opt.o_solref, mjNREF);
		V(TEXT("o_solimp"), Opt.o_solimp, mjNIMP);
		V(TEXT("o_friction"), Opt.o_friction, 5);
	}

	/** Copies a JSON number array into N mjtNum slots; false when the array is shorter. */
	bool Put(const FJsonObject& O, const TCHAR* Key, mjtNum* Out, int32 N)
	{
		const TArray<TSharedPtr<FJsonValue>>* A;
		if (!O.TryGetArrayField(Key, A) || A->Num() < N) return false;
		for (int32 k = 0; k < N; ++k) Out[k] = (*A)[k]->AsNumber();
		return true;
	}

	/**
	 * The training model's own numbers over URLab's rebuild of it (training/contract.py model_numbers): the free joint's
	 * damping and armature, the foot sites, and every value URLab passed through single precision. Then mj_setConst,
	 * so the constants MuJoCo derives from these (invweight0, M0, acc0, subtree masses) follow. Returns the count of
	 * names it could not find (0 = the whole model was matched).
	 */
	int32 ApplyModel(mjModel* m, mjData* d, const FJsonObject& Model)
	{
		int32 Missing = 0;
		for (const TPair<FString, TSharedPtr<FJsonValue>>& B : Model.GetObjectField(TEXT("bodies"))->Values)
		{
			const int32 b = Race::Find(m, mjOBJ_BODY, m->nbody, B.Key);
			if (b < 0) { ++Missing; UE_LOG(LogRace, Error, TEXT("model: no body %s"), *B.Key); continue; }
			const FJsonObject& O = *B.Value->AsObject();
			m->body_mass[b] = O.GetNumberField(TEXT("mass"));
			Put(O, TEXT("inertia"), m->body_inertia + 3 * b, 3);
			Put(O, TEXT("ipos"), m->body_ipos + 3 * b, 3);
			Put(O, TEXT("iquat"), m->body_iquat + 4 * b, 4);
			Put(O, TEXT("pos"), m->body_pos + 3 * b, 3);
			Put(O, TEXT("quat"), m->body_quat + 4 * b, 4);
		}
		for (const TSharedPtr<FJsonValue>& V : Model.GetArrayField(TEXT("joints")))
		{
			const FJsonObject& O = *V->AsObject();
			const FString Name = O.GetStringField(TEXT("name"));
			int32 j = -1;
			if (Name.IsEmpty())	// an unnamed joint (the Go2's root): the first joint of its body
			{
				const int32 b = Race::Find(m, mjOBJ_BODY, m->nbody, O.GetStringField(TEXT("body")));
				if (b >= 0 && m->body_jntnum[b] > 0) j = m->body_jntadr[b];
			}
			else j = Race::Find(m, mjOBJ_JOINT, m->njnt, Name);
			if (j < 0) { ++Missing; UE_LOG(LogRace, Error, TEXT("model: no joint %s (body %s)"), *Name, *O.GetStringField(TEXT("body"))); continue; }
			const int32 Nd = m->jnt_type[j] == mjJNT_FREE ? 6 : m->jnt_type[j] == mjJNT_BALL ? 3 : 1;
			const int32 D0 = m->jnt_dofadr[j];
			Put(O, TEXT("range"), m->jnt_range + 2 * j, 2);
			Put(O, TEXT("pos"), m->jnt_pos + 3 * j, 3);
			Put(O, TEXT("axis"), m->jnt_axis + 3 * j, 3);
			m->jnt_stiffness[j] = O.GetNumberField(TEXT("stiffness"));
			m->jnt_margin[j] = O.GetNumberField(TEXT("margin"));
			Put(O, TEXT("solref"), m->jnt_solref + mjNREF * j, mjNREF);
			Put(O, TEXT("solimp"), m->jnt_solimp + mjNIMP * j, mjNIMP);
			Put(O, TEXT("damping"), m->dof_damping + D0, Nd);
			Put(O, TEXT("armature"), m->dof_armature + D0, Nd);
			Put(O, TEXT("frictionloss"), m->dof_frictionloss + D0, Nd);
		}
		for (const TPair<FString, TSharedPtr<FJsonValue>>& A : Model.GetObjectField(TEXT("actuators"))->Values)
		{
			const int32 a = Race::Find(m, mjOBJ_ACTUATOR, m->nu, A.Key);
			if (a < 0) { ++Missing; UE_LOG(LogRace, Error, TEXT("model: no actuator %s"), *A.Key); continue; }
			const FJsonObject& O = *A.Value->AsObject();
			Put(O, TEXT("gainprm"), m->actuator_gainprm + mjNGAIN * a, mjNGAIN);
			Put(O, TEXT("biasprm"), m->actuator_biasprm + mjNBIAS * a, mjNBIAS);
			Put(O, TEXT("ctrlrange"), m->actuator_ctrlrange + 2 * a, 2);
			Put(O, TEXT("forcerange"), m->actuator_forcerange + 2 * a, 2);
			Put(O, TEXT("gear"), m->actuator_gear + 6 * a, 6);
		}
		for (const TPair<FString, TSharedPtr<FJsonValue>>& S : Model.GetObjectField(TEXT("sites"))->Values)
		{
			const int32 s = Race::Find(m, mjOBJ_SITE, m->nsite, S.Key);
			if (s < 0) { ++Missing; UE_LOG(LogRace, Error, TEXT("model: no site %s"), *S.Key); continue; }
			Put(*S.Value->AsObject(), TEXT("pos"), m->site_pos + 3 * s, 3);
			Put(*S.Value->AsObject(), TEXT("quat"), m->site_quat + 4 * s, 4);
		}
		for (const TSharedPtr<FJsonValue>& V : Model.GetArrayField(TEXT("geoms")))
		{
			const FJsonObject& O = *V->AsObject();
			const FString Body = O.GetStringField(TEXT("body"));
			const int32 b = Body == TEXT("world") ? 0 : Race::Find(m, mjOBJ_BODY, m->nbody, Body);
			const int32 k = (int32)O.GetNumberField(TEXT("index"));
			const int32 g = b >= 0 && k < m->body_geomnum[b] ? m->body_geomadr[b] + k : -1;
			if (g < 0 || m->geom_type[g] != (int32)O.GetNumberField(TEXT("type")))
			{
				++Missing;
				UE_LOG(LogRace, Error, TEXT("model: no geom %d of body %s (or another shape there)"), k, *Body);
				continue;
			}
			m->geom_margin[g] = O.GetNumberField(TEXT("margin"));
			m->geom_gap[g] = O.GetNumberField(TEXT("gap"));
			if (O.HasField(TEXT("visual"))) continue;	// a drawn mesh: URLab re-centred it, so its pose stays URLab's
			Put(O, TEXT("pos"), m->geom_pos + 3 * g, 3);
			Put(O, TEXT("quat"), m->geom_quat + 4 * g, 4);
			Put(O, TEXT("size"), m->geom_size + 3 * g, 3);
			Put(O, TEXT("friction"), m->geom_friction + 3 * g, 3);
			Put(O, TEXT("solref"), m->geom_solref + mjNREF * g, mjNREF);
			Put(O, TEXT("solimp"), m->geom_solimp + mjNIMP * g, mjNIMP);
			m->geom_solmix[g] = O.GetNumberField(TEXT("solmix"));
		}
		mj_setConst(m, d);
		return Missing;
	}

	FString JsonRow(const double* X, int32 N)
	{
		FString Out = TEXT("[");
		for (int32 i = 0; i < N; ++i) Out += FString::Printf(TEXT("%s%.17g"), i ? TEXT(", ") : TEXT(""), X[i]);
		return Out + TEXT("]");
	}

	FString JsonRow(const float* X, int32 N)
	{
		FString Out = TEXT("[");
		for (int32 i = 0; i < N; ++i) Out += FString::Printf(TEXT("%s%.9g"), i ? TEXT(", ") : TEXT(""), X[i]);
		return Out + TEXT("]");
	}
}

void URacerController::Bind(mjModel* m, mjData* d, const TMap<int32, UMjActuator*>& ActuatorIdMap)
{
	Super::Bind(m, d, ActuatorIdMap);
	const TCHAR* Cmdline = FCommandLine::Get();
	StepCount = 0;
	bReady = bDumped = false;
	Act.Reset(); Qadr.Reset(); Vadr.Reset(); Home.Reset(); DumpSlots.Reset();
	ReplayAct.Reset(); ReplayCtrl.Reset(); Recorded.Reset(); RecordedObs.Reset(); RecordedAct.Reset();
	RecordSteps = 0;

	FString S;
	if (FParse::Value(Cmdline, TEXT("RaceMode="), S)) Mode = S == TEXT("Replay") ? ERaceControlMode::Replay : ERaceControlMode::Policy;
	FParse::Value(Cmdline, TEXT("RaceReplay="), ReplayFile);
	FParse::Value(Cmdline, TEXT("RaceDump="), DumpFile);
	bQuitWhenDone = FParse::Param(Cmdline, TEXT("RaceQuit"));
	if (FParse::Value(Cmdline, TEXT("RaceCommand="), S, false))
	{
		TArray<FString> P;
		S.ParseIntoArray(P, TEXT(","));
		if (P.Num() == 3) Command = FVector(FCString::Atod(*P[0]), FCString::Atod(*P[1]), FCString::Atod(*P[2]));
	}

	const TSharedPtr<FJsonObject> Fp = Race::LoadJson(Fingerprint);
	if (!Fp) return;
	ApplyOptions(m, *Fp->GetObjectField(TEXT("option")));
	UE_LOG(LogRace, Log, TEXT("MuJoCo %s, options from %s: timestep %.17g, integrator %d, cone %d, impratio %g, iterations %d/%d, disableflags %d"),
		UTF8_TO_TCHAR(mj_versionString()), *Fingerprint, m->opt.timestep, m->opt.integrator, m->opt.cone, m->opt.impratio,
		m->opt.iterations, m->opt.ls_iterations, m->opt.disableflags);
	bool bOk = true;
	const TSharedPtr<FJsonObject>* Model;
	if (Fp->TryGetObjectField(TEXT("model"), Model))
	{
		const int32 Missing = ApplyModel(m, d, **Model);
		bOk &= Missing == 0;
		// The model as it now runs, for the parity gate's readback (URLab's own scene_compiled.mjb is saved before this)
		const FString Bound = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("PoRace"), TEXT("model_bound.mjb"));
		IFileManager::Get().MakeDirectory(*FPaths::GetPath(Bound), true);
		mj_saveModel(m, TCHAR_TO_UTF8(*Bound), nullptr, 0);
		UE_LOG(LogRace, Log, TEXT("model: training numbers written over URLab's (%s), %d names missing; saved %s"),
			*Fingerprint, Missing, *Bound);
	}
	else UE_LOG(LogRace, Warning, TEXT("%s has no model section: running URLab's rebuild of the model as is"), *Fingerprint);

	// the motors and their joints, contract order
	const TArray<TSharedPtr<FJsonValue>>& Actuators = Fp->GetArrayField(TEXT("actuators"));
	const TArray<TSharedPtr<FJsonValue>>& Joints = Fp->GetArrayField(TEXT("joints"));
	for (int32 i = 0; i < Actuators.Num(); ++i)
	{
		const int32 A = Race::Find(m, mjOBJ_ACTUATOR, m->nu, Actuators[i]->AsString());
		const int32 J = Race::Find(m, mjOBJ_JOINT, m->njnt, Joints[i]->AsString());
		UE_CLOG(A < 0, LogRace, Error, TEXT("no actuator %s"), *Actuators[i]->AsString());
		UE_CLOG(J < 0, LogRace, Error, TEXT("no joint %s"), *Joints[i]->AsString());
		bOk &= A >= 0 && J >= 0;
		Act.Add(A);
		Qadr.Add(J >= 0 ? m->jnt_qposadr[J] : -1);
		Vadr.Add(J >= 0 ? m->jnt_dofadr[J] : -1);
	}
	bOk &= Act.Num() == Go2::Nu;
	ImuSite = Race::Find(m, mjOBJ_SITE, m->nsite, Fp->GetStringField(TEXT("imu_site")));
	const int32 Gyro = Race::Find(m, mjOBJ_SENSOR, m->nsensor, Fp->GetStringField(TEXT("gyro_sensor")));
	const int32 Linvel = Race::Find(m, mjOBJ_SENSOR, m->nsensor, Fp->GetStringField(TEXT("linvel_sensor")));
	UE_CLOG(ImuSite < 0 || Gyro < 0 || Linvel < 0, LogRace, Error, TEXT("imu site %d, gyro %d, local_linvel %d: missing"), ImuSite, Gyro, Linvel);
	bOk &= ImuSite >= 0 && Gyro >= 0 && Linvel >= 0;
	AdrGyro = Gyro >= 0 ? m->sensor_adr[Gyro] : -1;
	AdrLinvel = Linvel >= 0 ? m->sensor_adr[Linvel] : -1;

	// the start pose and the dump's column order: the fingerprint's qpos slots
	const TArray<TSharedPtr<FJsonValue>>& Names = Fp->GetArrayField(TEXT("qpos_names"));
	TArray<double> Q0 = Race::Numbers(Fp->GetArrayField(TEXT("qpos_home")));

	if (Mode == ERaceControlMode::Replay)
	{
		const TSharedPtr<FJsonObject> Ref = Race::LoadJson(ReplayFile);
		if (!Ref) return;
		for (const TSharedPtr<FJsonValue>& V : Ref->GetArrayField(TEXT("actuators")))
		{
			const int32 A = Race::Find(m, mjOBJ_ACTUATOR, m->nu, V->AsString());
			UE_CLOG(A < 0, LogRace, Error, TEXT("replay: no actuator %s"), *V->AsString());
			bOk &= A >= 0;
			ReplayAct.Add(A);
		}
		for (const TSharedPtr<FJsonValue>& Row : Ref->GetArrayField(TEXT("ctrl")))
			for (const TSharedPtr<FJsonValue>& V : Row->AsArray()) ReplayCtrl.Add(V->AsNumber());
		Q0 = Race::Numbers(Ref->GetArrayField(TEXT("qpos0")));
		RecordSteps = (int64)(ReplayCtrl.Num() / FMath::Max(1, ReplayAct.Num())) * Go2::Decimation;
		UE_LOG(LogRace, Log, TEXT("replay %s: %d actuators, %lld physics steps"), *ReplayFile, ReplayAct.Num(), RecordSteps);
	}
	else
	{
		double Seconds = 0.0;
		if (FParse::Value(Cmdline, TEXT("RaceRecord="), Seconds)) RecordSteps = FMath::RoundToInt64(Seconds / m->opt.timestep);
		UNNEModelData* Data = Brain.Get();
		FString Path;
		if (FParse::Value(Cmdline, TEXT("RaceBrain="), Path))
		{
			TArray<uint8> Bytes;
			if (FFileHelper::LoadFileToArray(Bytes, *(FPaths::IsRelative(Path) ? FPaths::Combine(FPaths::ProjectDir(), Path) : Path)))
			{
				Data = NewObject<UNNEModelData>(this);
				Data->Init(TEXT("onnx"), Bytes);
				LoadedBrains.Add(Data);
			}
			else UE_LOG(LogRace, Error, TEXT("-RaceBrain=%s: no such file"), *Path);
		}
		if (!MakeNet(Data)) UE_LOG(LogRace, Warning, TEXT("no brain: the racer holds its home pose"));
	}

	for (int32 i = 0; i < Names.Num() && i < Q0.Num(); ++i)
	{
		const int32 Slot = Race::QposSlot(m, Names[i]->AsString());
		UE_CLOG(Slot < 0, LogRace, Error, TEXT("no qpos slot %s"), *Names[i]->AsString());
		bOk &= Slot >= 0;
		DumpSlots.Add(Slot);
		if (Slot >= 0) Home.Emplace(Slot, Q0[i]);
	}
	UE_CLOG(DumpSlots.Num() != m->nq, LogRace, Warning, TEXT("the fingerprint names %d qpos slots, the model has %d"), DumpSlots.Num(), m->nq);

	LastAction.Init(0.f, Go2::Nu);
	Action.Init(0.f, Go2::Nu);
	Obs.Init(0.f, Go2::ObsJoystick);
	Cmd[0] = Cmd[1] = Cmd[2] = 0.f;
	bReady = bOk;
	UE_LOG(LogRace, Log, TEXT("racer bound: %s, nq %d nv %d nu %d nbody %d, mode %s, command (%.2f, %.2f, %.2f), record %lld steps"),
		bOk ? TEXT("ok") : TEXT("FAILED"), m->nq, m->nv, m->nu, m->nbody,
		Mode == ERaceControlMode::Replay ? TEXT("Replay") : TEXT("Policy"), Command.X, Command.Y, Command.Z, RecordSteps);
}

bool URacerController::MakeNet(UNNEModelData* Data)
{
	Net.Reset();
	if (!Data) return false;
	// ORT on desktop (the bit-exact parity gate). Android has no ORT in UE 5.8: Slice 12 adds the Basic CPU path.
	TWeakInterfacePtr<INNERuntimeCPU> Runtime = UE::NNE::GetRuntime<INNERuntimeCPU>(TEXT("NNERuntimeORTCpu"));
	TSharedPtr<UE::NNE::IModelCPU> Model = Runtime.IsValid() ? Runtime->CreateModelCPU(Data) : nullptr;
	Net = Model ? Model->CreateModelInstanceCPU() : nullptr;
	if (!Net)
	{
		UE_LOG(LogRace, Error, TEXT("brain %s: NNERuntimeORTCpu could not load it"), *Data->GetName());
		return false;
	}
	const TConstArrayView<int32> In = Net->GetInputTensorDescs()[0].GetShape().GetData();
	NumIn = In.Num() > 1 && In[1] > 0 ? In[1] : Go2::ObsJoystick;
	const uint32 Shape[] = { 1, (uint32)NumIn };
	Net->SetInputTensorShapes({ UE::NNE::FTensorShape::Make(Shape) });
	UE_LOG(LogRace, Log, TEXT("brain %s: %d inputs"), *Data->GetName(), NumIn);
	return NumIn == Go2::ObsJoystick;
}

void URacerController::StartPose(const mjModel* m, mjData* d) const
{
	// sim.py reset(): the home keyframe, zero velocity, ctrl at the default pose, then forward
	mj_resetData(m, d);
	for (const TPair<int32, double>& Q : Home) d->qpos[Q.Key] = Q.Value;
	for (int32 j = 0; j < Act.Num(); ++j) d->ctrl[Act[j]] = Go2::DefaultPose[j];
	mj_forward(m, d);
}

void URacerController::Decide(const mjModel* m, mjData* d)
{
	// sim.py step_joystick. State is read as mj_step left it (sensordata and site_xmat are from the last step's
	// forward pass, exactly as the trainer's recorder read them): no mj_forward here, or parity is lost.
	for (int32 k = 0; k < 3; ++k)
	{
		const float Target = (float)Command[k];
		Cmd[k] += FMath::Clamp(Target - Cmd[k], -Go2::CmdSlewStep, Go2::CmdSlewStep);
	}
	float* O = Obs.GetData();
	for (int32 k = 0; k < 3; ++k) *O++ = (float)d->sensordata[AdrLinvel + k];
	for (int32 k = 0; k < 3; ++k) *O++ = (float)d->sensordata[AdrGyro + k];
	const mjtNum* R = d->site_xmat + 9 * ImuSite;	// world down in the imu frame: -(third row)
	for (int32 k = 0; k < 3; ++k) *O++ = (float)(-R[6 + k]);
	for (int32 j = 0; j < Go2::Nu; ++j) *O++ = (float)(d->qpos[Qadr[j]] - (double)Go2::DefaultPose[j]);
	for (int32 j = 0; j < Go2::Nu; ++j) *O++ = (float)d->qvel[Vadr[j]];
	for (int32 j = 0; j < Go2::Nu; ++j) *O++ = LastAction[j];
	for (int32 k = 0; k < 3; ++k) *O++ = Cmd[k];

	if (Net)
	{
		const UE::NNE::FTensorBindingCPU In{ Obs.GetData(), (uint64)NumIn * sizeof(float) };
		const UE::NNE::FTensorBindingCPU Out{ Action.GetData(), (uint64)Go2::Nu * sizeof(float) };
		if (Net->RunSync({ In }, { Out }) != UE::NNE::EResultStatus::Ok)
		{
			UE_LOG(LogRace, Error, TEXT("brain run failed at step %lld"), StepCount.load());
			for (float& A : Action) A = 0.f;
		}
	}
	for (int32 j = 0; j < Go2::Nu; ++j)
	{
		const float A = FMath::Clamp(Action[j], -1.f, 1.f);
		const float T = Go2::DefaultPose[j] + Go2::ActionScale * A;	// float32, as the trainer computes it
		d->ctrl[Act[j]] = (double)T;
		LastAction[j] = A;
	}
	if (RecordSteps > 0 && !bDumped)
	{
		RecordedObs.Append(Obs);
		RecordedAct.Append(LastAction);
	}
}

void URacerController::ComputeAndApply(mjModel* m, mjData* d, uint8 Source)
{
	if (!bReady) return;
	const int64 Step = StepCount.load(std::memory_order_relaxed);
	if (Step == 0) StartPose(m, d);

	// qpos before this step; sample RecordSteps is the state the last recorded step left
	if (RecordSteps > 0 && !bDumped && Step <= RecordSteps)
	{
		for (const int32 Slot : DumpSlots) Recorded.Add(Slot >= 0 ? d->qpos[Slot] : 0.0);
		if (Step == RecordSteps) WriteDump(m);
	}

	if (Mode == ERaceControlMode::Replay)
	{
		const int64 C = Step / Go2::Decimation;
		const int32 N = ReplayAct.Num();
		if (N > 0 && (C + 1) * N <= ReplayCtrl.Num())
			for (int32 a = 0; a < N; ++a) d->ctrl[ReplayAct[a]] = ReplayCtrl[C * N + a];
	}
	else if (Step % Go2::Decimation == 0) Decide(m, d);
	++StepCount;
}

void URacerController::WriteDump(const mjModel* m)
{
	bDumped = true;
	const int32 Nq = DumpSlots.Num();
	const int32 Steps = Recorded.Num() / FMath::Max(1, Nq);
	FString Out = FString::Printf(TEXT("{\"mujoco\": \"%s\", \"timestep\": %.17g, \"mode\": \"%s\", \"command\": [%.9g, %.9g, %.9g],\n\"qpos\": ["),
		UTF8_TO_TCHAR(mj_versionString()), m->opt.timestep, Mode == ERaceControlMode::Replay ? TEXT("replay") : TEXT("policy"),
		Command.X, Command.Y, Command.Z);
	for (int32 s = 0; s < Steps; ++s) Out += (s ? TEXT(",\n") : TEXT("\n")) + JsonRow(Recorded.GetData() + s * Nq, Nq);
	Out += TEXT("],\n\"obs\": [");
	for (int32 k = 0; k < RecordedObs.Num() / Go2::ObsJoystick; ++k) Out += (k ? TEXT(",\n") : TEXT("\n")) + JsonRow(RecordedObs.GetData() + k * Go2::ObsJoystick, Go2::ObsJoystick);
	Out += TEXT("],\n\"action\": [");
	for (int32 k = 0; k < RecordedAct.Num() / Go2::Nu; ++k) Out += (k ? TEXT(",\n") : TEXT("\n")) + JsonRow(RecordedAct.GetData() + k * Go2::Nu, Go2::Nu);
	Out += TEXT("]}\n");
	const FString Path = FPaths::IsRelative(DumpFile) ? FPaths::Combine(FPaths::ProjectDir(), DumpFile) : DumpFile;
	const bool bSaved = FFileHelper::SaveStringToFile(Out, *Path);
	UE_LOG(LogRace, Log, TEXT("parity dump: %d steps -> %s (%s)"), Steps, *Path, bSaved ? TEXT("saved") : TEXT("SAVE FAILED"));
	if (bQuitWhenDone) AsyncTask(ENamedThreads::GameThread, [] { FPlatformMisc::RequestExit(false); });
}
