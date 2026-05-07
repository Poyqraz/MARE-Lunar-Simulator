// Fill out your copyright notice in the Description page of Project Settings.

#include "Velodyne/VelodyneLidarActor.h"

// Sets default values
AVelodyneLidarActor::AVelodyneLidarActor()
{
  // Set this actor to call Tick() every frame.  You can turn this off to improve performance if you don't need it.
  PrimaryActorTick.bCanEverTick = false;

  LidarComponent = CreateDefaultSubobject<UVelodyneBaseComponent>(TEXT("VelodyneComponent"));
  this->AddOwnedComponent(LidarComponent);
}

// Called when the game starts or when spawned
void AVelodyneLidarActor::BeginPlay()
{
  Super::BeginPlay();

  if(UdpScanComponent)
  {
    ConfigureUDPScan();
    UdpScanComponent->OpenSendSocket(UdpScanComponent->Settings.SendIP, UdpScanComponent->Settings.SendPort);
    // UdpScanComponent->OpenReceiveSocket(UdpScanComponent->Settings.ReceiveIP, UdpScanComponent->Settings.ReceivePort);
  }

  // Safely calculate the thread sleep time to prevent Divide-By-Zero and Integer Division bugs
  FTimespan ThreadSleepTime = FTimespan::FromMilliseconds(1.0); // Default fallback
  
  if (LidarComponent && LidarComponent->Sensor.NumberLaserEmitter > 0)
  {
      double ChannelRatio = static_cast<double>(LidarComponent->Sensor.NumberDataChannel) / 
                            static_cast<double>(LidarComponent->Sensor.NumberLaserEmitter);
                            
      double Milliseconds = LidarComponent->Sensor.NumberDataBlock * ChannelRatio * (0.000001 * FIRING_CYCLE);
      ThreadSleepTime = FTimespan::FromMilliseconds(Milliseconds);
  }

  FString UniqueThreadName = "LidarThread";
  LidarThread = new LidarThreadProcess(ThreadSleepTime, *UniqueThreadName, this);

  if(LidarThread)
  {
    LidarThread->Init();
    LidarThread->LidarThreadInit();
    UE_LOG(LogTemp, Warning, TEXT("!!! Lidar thread initialized successfully !!!"));
  }
}

void AVelodyneLidarActor::EndPlay(EEndPlayReason::Type Reason)
{
  if(LidarThread)
  {
    LidarThread->LidarThreadShutdown();
    LidarThread->Stop();
  }

  //!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  //! Wait here until WorkerThread is verified as having stopped!
  //!
  //! This is a safety feature, that will delay PIE EndPlay or
  //! closing of the game while complex calcs occurring on the
  //! thread have a chance to finish
  //!
  while(LidarThread && !LidarThread->ThreadHasStopped())
  {
    FPlatformProcess::Sleep(0.1);
  }
  //!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

  //Do this last
  if (LidarThread)
  {
      delete LidarThread;
      LidarThread = nullptr;
  }

  Super::EndPlay(Reason);
}

// ! On Thread (not game thread)
// Never stop until finished calculating!
// This would be a verrrrry large hitch if done on game thread!
void AVelodyneLidarActor::LidarThreadTick()
{
  float TimeDiffMs = 0;

  //! Make sure to come all the way out of all function routines with this same check
  //! so as to ensure thread exits as quickly as possible, allowing game thread to finish
  //! See EndPlay for more information.
  if(LidarThread && LidarThread->IsThreadPaused())
  {
    return;
  }

  if ( BeginTimestamp == 0 )
  {
    PacketTimestamp = 0;
  }
  else
  {
    PacketTimestamp += (uint32)(1e6 * (FPlatformTime::Seconds() - BeginTimestamp));
  }
  BeginTimestamp = FPlatformTime::Seconds();

  // Prevent thread crashes by ensuring components exist before calling functions on them
  if (LidarComponent && UdpScanComponent)
  {
      // Generate raycasting data
      LidarComponent->GetScanData();

      // Generate velodyne data packet
      LidarComponent->GenerateDataPacket(PacketTimestamp);

      // Multicast Delegate event for broadcasting packet data
      UdpScanComponent->EmitBytes(LidarComponent->Sensor.DataPacket);
  }

  TimeDiffMs = (float)(FPlatformTime::Seconds() - BeginTimestamp);

  if( TimeDiffMs > 0.0f )
  {
    FPlatformProcess::SleepNoStats(TimeDiffMs);
  }
  else
  {
    FPlatformProcess::SleepNoStats(0);
  }
}

void AVelodyneLidarActor::ConfigureUDPScan()
{
  // Safety check, and explicitly assigning ReceivePort to 0 to prevent socket collisions
  if (!UdpScanComponent || !LidarComponent) return;

  UdpScanComponent->Settings.SendIP    = FString("127.0.0.1");
  UdpScanComponent->Settings.ReceiveIP = FString("0.0.0.0"); // The magic wildcard!
  
  UdpScanComponent->Settings.SendPort  = 2368;
  UdpScanComponent->Settings.ReceivePort = 0; 
  
  UdpScanComponent->Settings.SendSocketName = FString(TEXT("ue5-scan-send"));
  UdpScanComponent->Settings.BufferSize = PACKET_HEADER_SIZE + DATA_PACKET_PAYLOAD;
}