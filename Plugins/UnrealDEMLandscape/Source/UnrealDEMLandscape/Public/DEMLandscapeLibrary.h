#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "DEMLandscapeLibrary.generated.h"

class ALandscape;
class ALandscapeProxy;

/**
 * Landscape functions for editor Python (unreal.DEMLandscapeLibrary) and
 * Blueprints. Unreal's Python API cannot create Landscape components, so this
 * library does what the editor's New Landscape tool does.
 */
UCLASS()
class UNREALDEMLANDSCAPE_API UDEMLandscapeLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/**
	 * Spawns a Landscape in the editor world with the given layout and imports
	 * its heights from a little-endian 16-bit .r16 file of
	 * (ComponentCountX * SectionsPerComponent * SectionSize + 1) x
	 * (ComponentCountY * SectionsPerComponent * SectionSize + 1) values, row by row.
	 * An empty HeightmapFile gives a flat Landscape. Returns nullptr on failure
	 * (the reason is logged under LogDEMLandscape).
	 */
	UFUNCTION(BlueprintCallable, Category = "DEM Landscape")
	static ALandscape* CreateLandscape(const FTransform& Transform, int32 SectionSize, int32 SectionsPerComponent,
	                                   int32 ComponentCountX, int32 ComponentCountY, const FString& HeightmapFile);

	/** The Landscape's final heights, row by row (empty if it has no data). */
	UFUNCTION(BlueprintCallable, Category = "DEM Landscape")
	static TArray<int32> GetHeightmapData(ALandscapeProxy* Landscape);
};
