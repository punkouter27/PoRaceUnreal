#include "RaceModel.h"

#include "HAL/FileManager.h"
#include "Misc/Paths.h"
#include "RaceNames.h"

namespace
{
	/** Copies a JSON number array into N mjtNum slots; false when the field is missing or short. */
	bool Put(const FJsonObject& O, const TCHAR* Key, mjtNum* Out, int32 N)
	{
		const TArray<TSharedPtr<FJsonValue>>* A;
		if (!O.TryGetArrayField(Key, A) || A->Num() < N) return false;
		for (int32 k = 0; k < N; ++k) Out[k] = (*A)[k]->AsNumber();
		return true;
	}

	void PutNumber(const FJsonObject& O, const TCHAR* Key, mjtNum& Out)
	{
		double V;
		if (O.TryGetNumberField(Key, V)) Out = V;
	}

	bool Optional(const FJsonObject& O)
	{
		bool B = false;
		return O.TryGetBoolField(TEXT("optional"), B) && B;
	}
}

void RaceModel::ApplyOptions(mjModel* m, const FJsonObject& O)
{
	mjOption& Opt = m->opt;
	auto I = [&O](const TCHAR* K) { return (int)O.GetNumberField(K); };
	Opt.timestep = O.GetNumberField(TEXT("timestep"));
	Opt.impratio = O.GetNumberField(TEXT("impratio"));
	Opt.tolerance = O.GetNumberField(TEXT("tolerance"));
	Opt.ls_tolerance = O.GetNumberField(TEXT("ls_tolerance"));
	Opt.noslip_tolerance = O.GetNumberField(TEXT("noslip_tolerance"));
	Opt.ccd_tolerance = O.GetNumberField(TEXT("ccd_tolerance"));
	Opt.density = O.GetNumberField(TEXT("density"));
	Opt.viscosity = O.GetNumberField(TEXT("viscosity"));
	Opt.o_margin = O.GetNumberField(TEXT("o_margin"));
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
	Put(O, TEXT("gravity"), Opt.gravity, 3);
	Put(O, TEXT("wind"), Opt.wind, 3);
	Put(O, TEXT("magnetic"), Opt.magnetic, 3);
	Put(O, TEXT("o_solref"), Opt.o_solref, mjNREF);
	Put(O, TEXT("o_solimp"), Opt.o_solimp, mjNIMP);
	Put(O, TEXT("o_friction"), Opt.o_friction, 5);
}

int32 RaceModel::ApplyNumbers(mjModel* m, const FJsonObject& Numbers, const FString& Prefix)
{
	int32 Missing = 0;
	auto Miss = [&](const FJsonObject& O, const FString& What)
	{
		if (Optional(O)) return;
		++Missing;
		UE_LOG(LogRace, Error, TEXT("model numbers: no %s (prefix \"%s\")"), *What, *Prefix);
	};

	const TSharedPtr<FJsonObject>* Bodies;
	if (Numbers.TryGetObjectField(TEXT("bodies"), Bodies))
		for (const TPair<FString, TSharedPtr<FJsonValue>>& B : (*Bodies)->Values)
		{
			const FJsonObject& O = *B.Value->AsObject();
			const int32 b = Race::Find(m, mjOBJ_BODY, m->nbody, Prefix + B.Key);
			if (b < 0) { Miss(O, TEXT("body ") + B.Key); continue; }
			PutNumber(O, TEXT("mass"), m->body_mass[b]);
			Put(O, TEXT("inertia"), m->body_inertia + 3 * b, 3);
			Put(O, TEXT("ipos"), m->body_ipos + 3 * b, 3);
			Put(O, TEXT("iquat"), m->body_iquat + 4 * b, 4);
			Put(O, TEXT("pos"), m->body_pos + 3 * b, 3);
			Put(O, TEXT("quat"), m->body_quat + 4 * b, 4);
		}

	const TArray<TSharedPtr<FJsonValue>>* Joints;
	if (Numbers.TryGetArrayField(TEXT("joints"), Joints))
		for (const TSharedPtr<FJsonValue>& V : *Joints)
		{
			const FJsonObject& O = *V->AsObject();
			const FString Name = O.GetStringField(TEXT("name"));
			int32 j = -1;
			if (Name.IsEmpty())	// an unnamed joint (the Go2's root): the first joint of its body
			{
				const int32 b = Race::Find(m, mjOBJ_BODY, m->nbody, Prefix + O.GetStringField(TEXT("body")));
				if (b >= 0 && m->body_jntnum[b] > 0) j = m->body_jntadr[b];
			}
			else j = Race::Find(m, mjOBJ_JOINT, m->njnt, Prefix + Name);
			if (j < 0) { Miss(O, TEXT("joint ") + Name + TEXT(" of body ") + O.GetStringField(TEXT("body"))); continue; }
			const int32 Nd = m->jnt_type[j] == mjJNT_FREE ? 6 : m->jnt_type[j] == mjJNT_BALL ? 3 : 1;
			const int32 D0 = m->jnt_dofadr[j];
			Put(O, TEXT("range"), m->jnt_range + 2 * j, 2);
			Put(O, TEXT("pos"), m->jnt_pos + 3 * j, 3);
			Put(O, TEXT("axis"), m->jnt_axis + 3 * j, 3);
			PutNumber(O, TEXT("stiffness"), m->jnt_stiffness[j]);
			PutNumber(O, TEXT("margin"), m->jnt_margin[j]);
			Put(O, TEXT("solref"), m->jnt_solref + mjNREF * j, mjNREF);
			Put(O, TEXT("solimp"), m->jnt_solimp + mjNIMP * j, mjNIMP);
			Put(O, TEXT("damping"), m->dof_damping + D0, Nd);
			Put(O, TEXT("armature"), m->dof_armature + D0, Nd);
			Put(O, TEXT("frictionloss"), m->dof_frictionloss + D0, Nd);
		}

	const TSharedPtr<FJsonObject>* Actuators;
	if (Numbers.TryGetObjectField(TEXT("actuators"), Actuators))
		for (const TPair<FString, TSharedPtr<FJsonValue>>& A : (*Actuators)->Values)
		{
			const FJsonObject& O = *A.Value->AsObject();
			const int32 a = Race::Find(m, mjOBJ_ACTUATOR, m->nu, Prefix + A.Key);
			if (a < 0) { Miss(O, TEXT("actuator ") + A.Key); continue; }
			Put(O, TEXT("gainprm"), m->actuator_gainprm + mjNGAIN * a, mjNGAIN);
			Put(O, TEXT("biasprm"), m->actuator_biasprm + mjNBIAS * a, mjNBIAS);
			Put(O, TEXT("ctrlrange"), m->actuator_ctrlrange + 2 * a, 2);
			Put(O, TEXT("forcerange"), m->actuator_forcerange + 2 * a, 2);
			Put(O, TEXT("gear"), m->actuator_gear + 6 * a, 6);
		}

	const TSharedPtr<FJsonObject>* Sites;
	if (Numbers.TryGetObjectField(TEXT("sites"), Sites))
		for (const TPair<FString, TSharedPtr<FJsonValue>>& S : (*Sites)->Values)
		{
			const FJsonObject& O = *S.Value->AsObject();
			const int32 s = Race::Find(m, mjOBJ_SITE, m->nsite, Prefix + S.Key);
			if (s < 0) { Miss(O, TEXT("site ") + S.Key); continue; }
			Put(O, TEXT("pos"), m->site_pos + 3 * s, 3);
			Put(O, TEXT("quat"), m->site_quat + 4 * s, 4);
		}

	const TArray<TSharedPtr<FJsonValue>>* Geoms;
	if (Numbers.TryGetArrayField(TEXT("geoms"), Geoms))
		for (const TSharedPtr<FJsonValue>& V : *Geoms)
		{
			const FJsonObject& O = *V->AsObject();
			FString Name;
			int32 g = -1;
			FString What;
			if (O.TryGetStringField(TEXT("name"), Name) && !Name.IsEmpty())	// by name (track and world geoms)
			{
				g = Race::Find(m, mjOBJ_GEOM, m->ngeom, Prefix + Name);
				What = TEXT("geom ") + Name;
			}
			else	// by body and order inside it (most of the Go2's geoms are unnamed)
			{
				const FString Body = O.GetStringField(TEXT("body"));
				const int32 b = Body == TEXT("world") ? 0 : Race::Find(m, mjOBJ_BODY, m->nbody, Prefix + Body);
				const int32 k = (int32)O.GetNumberField(TEXT("index"));
				g = b >= 0 && k < m->body_geomnum[b] ? m->body_geomadr[b] + k : -1;
				What = FString::Printf(TEXT("geom %d of body %s"), k, *Body);
			}
			if (g < 0 || m->geom_type[g] != (int32)O.GetNumberField(TEXT("type"))) { Miss(O, What); continue; }
			PutNumber(O, TEXT("margin"), m->geom_margin[g]);
			PutNumber(O, TEXT("gap"), m->geom_gap[g]);
			bool bVisual = false;
			if (O.TryGetBoolField(TEXT("visual"), bVisual) && bVisual) continue;	// a drawn mesh: its pose stays URLab's
			Put(O, TEXT("pos"), m->geom_pos + 3 * g, 3);
			Put(O, TEXT("quat"), m->geom_quat + 4 * g, 4);
			Put(O, TEXT("size"), m->geom_size + 3 * g, 3);
			Put(O, TEXT("friction"), m->geom_friction + 3 * g, 3);
			Put(O, TEXT("solref"), m->geom_solref + mjNREF * g, mjNREF);
			Put(O, TEXT("solimp"), m->geom_solimp + mjNIMP * g, mjNIMP);
			PutNumber(O, TEXT("solmix"), m->geom_solmix[g]);
		}
	return Missing;
}

FString RaceModel::Save(const mjModel* m, const TCHAR* FileName)
{
	const FString Path = FPaths::ConvertRelativePathToFull(FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("PoRace"), FileName));
	IFileManager::Get().MakeDirectory(*FPaths::GetPath(Path), true);
	mj_saveModel(m, TCHAR_TO_UTF8(*Path), nullptr, 0);
	return Path;
}
