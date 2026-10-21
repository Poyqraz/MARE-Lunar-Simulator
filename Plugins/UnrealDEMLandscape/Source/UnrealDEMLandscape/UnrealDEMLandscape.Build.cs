using UnrealBuildTool;

public class UnrealDEMLandscape : ModuleRules
{
	public UnrealDEMLandscape(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = ModuleRules.PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine", "Landscape" });
		// Foliage: included by LandscapeEdit.h
		PrivateDependencyModuleNames.AddRange(new string[] { "UnrealEd", "Foliage" });
	}
}
