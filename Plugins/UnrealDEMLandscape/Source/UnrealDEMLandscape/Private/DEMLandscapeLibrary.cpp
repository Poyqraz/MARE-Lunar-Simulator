#include "DEMLandscapeLibrary.h"

#include "Editor.h"
#include "Engine/World.h"
#include "Landscape.h"
#include "LandscapeDataAccess.h"
#include "LandscapeEdit.h"
#include "LandscapeInfo.h"
#include "LandscapeProxy.h"
#include "Misc/FileHelper.h"
#include "Modules/ModuleManager.h"
#include "ScopedTransaction.h"

IMPLEMENT_MODULE(FDefaultModuleImpl, UnrealDEMLandscape)

DEFINE_LOG_CATEGORY_STATIC(LogDEMLandscape, Log, All);

#define LOCTEXT_NAMESPACE "DEMLandscape"

ALandscape* UDEMLandscapeLibrary::CreateLandscape(const FTransform& Transform, int32 SectionSize, int32 SectionsPerComponent,
                                                   int32 ComponentCountX, int32 ComponentCountY, const FString& HeightmapFile)
{
	UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	if (!World)
	{
		UE_LOG(LogDEMLandscape, Error, TEXT("No editor world to create the Landscape in."));
		return nullptr;
	}
	if (SectionSize <= 0 || SectionsPerComponent <= 0 || ComponentCountX <= 0 || ComponentCountY <= 0)
	{
		UE_LOG(LogDEMLandscape, Error, TEXT("Invalid Landscape layout."));
		return nullptr;
	}

	const int32 QuadsPerComponent = SectionsPerComponent * SectionSize;
	const int32 SizeX = ComponentCountX * QuadsPerComponent + 1;
	const int32 SizeY = ComponentCountY * QuadsPerComponent + 1;

	TArray<uint16> Heights;
	if (HeightmapFile.IsEmpty())
	{
		Heights.Init(static_cast<uint16>(LandscapeDataAccess::MidValue), SizeX * SizeY);
	}
	else
	{
		TArray<uint8> Bytes;
		if (!FFileHelper::LoadFileToArray(Bytes, *HeightmapFile))
		{
			UE_LOG(LogDEMLandscape, Error, TEXT("Could not read %s."), *HeightmapFile);
			return nullptr;
		}
		if (Bytes.Num() != 2 * SizeX * SizeY)
		{
			UE_LOG(LogDEMLandscape, Error, TEXT("%s holds %d heights, the Landscape needs %d x %d."),
			       *HeightmapFile, Bytes.Num() / 2, SizeX, SizeY);
			return nullptr;
		}
		Heights.SetNumUninitialized(SizeX * SizeY);
		for (int32 Index = 0; Index < Heights.Num(); ++Index)   // .r16 is little-endian
		{
			Heights[Index] = static_cast<uint16>(Bytes[2 * Index] | (Bytes[2 * Index + 1] << 8));
		}
	}

	TMap<FGuid, TArray<uint16>> HeightDataPerLayers;
	HeightDataPerLayers.Add(FGuid(), MoveTemp(Heights));
	TMap<FGuid, TArray<FLandscapeImportLayerInfo>> MaterialLayerDataPerLayers;
	MaterialLayerDataPerLayers.Add(FGuid(), TArray<FLandscapeImportLayerInfo>());

	const FScopedTransaction Transaction(LOCTEXT("CreateLandscape", "Create Landscape from DEM"));

	ALandscape* Landscape = World->SpawnActor<ALandscape>(Transform.GetLocation(), Transform.Rotator());
	if (!Landscape)
	{
		UE_LOG(LogDEMLandscape, Error, TEXT("Could not spawn the Landscape."));
		return nullptr;
	}
	Landscape->SetActorRelativeScale3D(Transform.GetScale3D());
	// Same lighting LOD rule as the editor's New Landscape tool.
	Landscape->StaticLightingLOD = FMath::DivideAndRoundUp(FMath::CeilLogTwo((SizeX * SizeY) / (2048 * 2048) + 1), (uint32)2);

	Landscape->Import(FGuid::NewGuid(), 0, 0, SizeX - 1, SizeY - 1, SectionsPerComponent, SectionSize,
	                  HeightDataPerLayers, *HeightmapFile, MaterialLayerDataPerLayers,
	                  ELandscapeImportAlphamapType::Additive, TArrayView<const FLandscapeLayer>());

	if (ULandscapeInfo* Info = Landscape->GetLandscapeInfo())
	{
		Info->UpdateLayerInfoMap(Landscape);
	}
	return Landscape;
}

TArray<int32> UDEMLandscapeLibrary::GetHeightmapData(ALandscapeProxy* Landscape)
{
	TArray<int32> Result;
	ULandscapeInfo* Info = Landscape ? Landscape->GetLandscapeInfo() : nullptr;
	int32 MinX, MinY, MaxX, MaxY;
	if (!Info || !Info->GetLandscapeExtent(MinX, MinY, MaxX, MaxY))
	{
		return Result;
	}
	const int32 Width = MaxX - MinX + 1;
	const int32 Height = MaxY - MinY + 1;
	TArray<uint16> Heights;
	Heights.SetNumZeroed(Width * Height);
	FLandscapeEditDataInterface EditData(Info);
	EditData.GetHeightDataFast(MinX, MinY, MaxX, MaxY, Heights.GetData(), 0);

	Result.SetNumUninitialized(Heights.Num());
	for (int32 Index = 0; Index < Heights.Num(); ++Index)
	{
		Result[Index] = Heights[Index];
	}
	return Result;
}

#undef LOCTEXT_NAMESPACE
