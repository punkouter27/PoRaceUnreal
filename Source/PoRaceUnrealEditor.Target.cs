using UnrealBuildTool;
using System.Collections.Generic;

public class PoRaceUnrealEditorTarget : TargetRules
{
	public PoRaceUnrealEditorTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Editor;
		DefaultBuildSettings = BuildSettingsVersion.V7;
		IncludeOrderVersion = EngineIncludeOrderVersion.Unreal5_8;
		ExtraModuleNames.Add("PoRaceUnreal");
	}
}
