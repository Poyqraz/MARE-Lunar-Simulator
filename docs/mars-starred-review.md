# Yıldızlı Mars ve robotik depolarının entegrasyon incelemesi

İnceleme: **28 Ekim 2026**. `Poyqraz` hesabının 508 açık yıldızı tarandı.
[Mars listesinin](https://github.com/stars/Poyqraz/lists/mars?page=1) iki
sayfasındaki **35 depo tek tek** envantere alındı; ilgili diğer yıldızlarla
toplam **44 deponun** ağaç/README kapsamı değerlendirildi. Uygun adayların
çekirdek planlama, sensör veya yöntem dosyaları ayrıca okundu. Bütün depoların
her satırının denetlendiği ya da uygulamalarının çalıştırıldığı iddia edilmez.
Kaynak betikler çalıştırılmadı; bu fork'a dış kaynak kodu veya varlık kopyalanmadı.

Ayrı açık bir **İKA listesi** görünmedi. Bu nedenle böyle bir listenin tamamı
incelendi denmez; ilgili yarışma/robotik yıldızları aşağıda ayrı kaydedilir.
GitHub bağlantısı yıldız/list API'sini sunmadığından yalnızca bu envanter için
açık GitHub liste sayfaları ve public API kullanıldı. Depo dosyaları GitHub
bağlantısından okundu. Gizli liste/depo erişimi varsayılmadı.

Makine tarafından okunabilir [kayıt](data/starred-navigation-review.json),
repo başına tarih, dal, **commit SHA ve ayrı Git tree SHA**, kök README
blob kimliği, seçili çekirdek dosyalar ve API lisans bilgisini saklar. Dallar
değişebilir; kimlikler commit metadata'sıyla ayrıca çapraz kontrol edildi.
Kayıt incelenen commit'i ve onun içerik ağacını tanımlar. `null` lisans izin
varsayımı değildir; `NOASSERTION` da tek başına kullanılabilir lisans sayılmaz.

## Mars listesinin tamamı

Kararlar bu aşamadaki ölçülmüş Mars geometrisi, ROS kullanmadan Python kontrolü
ve dört teker skid-steer hedefi içindir. Kaynak projenin genel kalitesine puan
verilmez. Geniş ölçekli GIS/yerleşim araştırması, küçük rover tehlike haritasının
yerini tutmaz.

| Depo | İncelenen kapsam | Karar | API lisansı |
|---|---|---|---|
| [stiles/mars-perseverance-waypoints](https://github.com/stiles/mars-perseverance-waypoints) | NASA rover waypoint/GeoJSON history | Historical mission context only; README says collection stopped in June 2025. No terrain heights or local traversability. | Belirlenmedi |
| [rishab-sharma/Cross-a-Crater](https://github.com/rishab-sharma/Cross-a-Crater) | e-Yantra image-guided arena and bridge/cavity task | Competition abstraction; overhead image maze is not a measured 3D Mars surface. No import. | Belirlenmedi |
| [rubenandrebarreiro/mars-rover](https://github.com/rubenandrebarreiro/mars-rover) | Search/genetic-algorithm project description | Reviewed tree contains only README; described Java implementation is absent. No runnable planner to integrate. | Belirlenmedi |
| [Estiakk/Martin-Habitat-Pathfinder](https://github.com/Estiakk/Martin-Habitat-Pathfinder) | Habitat/environment decision support, RL/LLM prototypes | Habitat suitability is not rover-scale collision navigation; avoid treating generated environment scores as measured terrain. Defer. | MIT |
| [gowrijsuria/MarsPathfinder](https://github.com/gowrijsuria/MarsPathfinder) | Web route-planning application | UI/route abstraction; no demonstrated measured rover-scale terrain/sensor contract. No source import. | Belirlenmedi |
| [nawailkhan/Mars-Rover-Path-Planner](https://github.com/nawailkhan/Mars-Rover-Path-Planner) | MOLA DEM terrain-cost A* and other search algorithms | Adopt terrain cost as an independently implemented idea. Reject hardcoded 463 m spacing, NaN-to-mean and block averaging for local hazards. | Belirlenmedi |
| [jblevins32/MPPI](https://github.com/jblevins32/MPPI) | Sampling/model predictive path integral control | Model-dependent rollouts are promising after steering/slip calibration. No license detected; no code copied. Defer. | Belirlenmedi |
| [ethz-asl/scouting-ipp](https://github.com/ethz-asl/scouting-ipp) | Cooperative informative planning for scout and rover, ROS/C++ | Adopt known/unknown observation distinction as an independent method. Full ROS1/scout stack is outside the current Python-only stage. | MIT |
| [ChasingTheDream369/Location-finder-and-TortOS-Upgrade-for-H.A.R.E-Mars-Rover](https://github.com/ChasingTheDream369/Location-finder-and-TortOS-Upgrade-for-H.A.R.E-Mars-Rover) | HARE location/storage design narrative | Two-file tree mostly documentation; no validated DEM/sensor/planning pipeline to integrate. | Belirlenmedi |
| [edumigueis/Mars-Map-Router](https://github.com/edumigueis/Mars-Map-Router) | Shortest path between named cities | Graph routing is not local 3D hazard evaluation. GPL source not imported. | GPL-3.0 |
| [SudeepthaG/Optimal-Path-Finder-for-Mars-Rover](https://github.com/SudeepthaG/Optimal-Path-Finder-for-Mars-Rover) | BFS/UCS/A* on height-grid exercise | Retain standard search concept only; independent metric A*, hard constraints and exact-goal validation implemented here. No source copied. | Belirlenmedi |
| [sivasini/PathFinder](https://github.com/sivasini/PathFinder) | Obstacle matrix and search comparison | Useful algorithm teaching reference; binary grids lack measured Mars geometry and sensor timing. No import. | Belirlenmedi |
| [aditya-an1l/mars-rover-path-finder](https://github.com/aditya-an1l/mars-rover-path-finder) | Motion-primitive A* and arc tracker, Pygame | Independently implement short-command arc/corridor checks. Its procedural bumps/rocks are not imported as real Mars terrain. | MIT |
| [likhitan1-design/marspath-ai](https://github.com/likhitan1-design/marspath-ai) | Mars route web prototype | Not a demonstrated UE geometry/sensor adapter. No code/data import. | Belirlenmedi |
| [aashiverma/PhoenixMarsQuesters](https://github.com/aashiverma/PhoenixMarsQuesters) | Mars colonisation path-finder web application | Web route abstraction; no measured local height/collision contract. No import. | Belirlenmedi |
| [italiana83/Mars](https://github.com/italiana83/Mars) | C#/OpenTK/GDAL MOLA/MEGDR globe-height viewer | Metadata and byte-order discipline are relevant. Global 128 px/degree MOLA is approximately 463 m sampling, unsuitable for wheel-scale obstacles. No import. | MIT |
| [sadia-zannat/ares-pathfinder](https://github.com/sadia-zannat/ares-pathfinder) | NASA/PDS-derived Jezero mission/Marswalk prototype | Source provenance and directed-cost concepts are relevant; inspected terrain is 12 m, not wheel-scale. Complex asset licensing and native/prototype distinction retained. No source/assets imported. | NOASSERTION |
| [AnderssonProgramming/cnn-architectural-aws-ai](https://github.com/AnderssonProgramming/cnn-architectural-aws-ai) | Mars image-classification/CNN experiments | Image class is not elevation or clearance. Defer perception research until labeled rover imagery/calibration are available. | MIT |
| [AlejoMalia/NOArCO](https://github.com/AlejoMalia/NOArCO) | Planetary engineering feasibility and inventories | System-scale forcing/power/throughput screening, not local rover navigation. No import. | NOASSERTION |
| [Samuelson777/Space-Scientific-Technological-Human-and-Governance-Dimensions-of-Contemporary-Space-Research](https://github.com/Samuelson777/Space-Scientific-Technological-Human-and-Governance-Dimensions-of-Contemporary-Space-Research) | Multidisciplinary space research document | Context only, no local terrain/sensor/planner implementation. No import. | MIT |
| [ryan320-cyber/mars-mission-intelligence](https://github.com/ryan320-cyber/mars-mission-intelligence) | NASA-data mapping/analysis/AI platform | Potential mission context; does not establish rover-scale collision geometry or native UE driving. No import. | Belirlenmedi |
| [loggger101/Mars_Terrestrial_GlobalMosaic_GIS-Data](https://github.com/loggger101/Mars_Terrestrial_GlobalMosaic_GIS-Data) | ArcGIS global mosaics, THEMIS/Viking/HRSC-MOLA | Geological/global context only; resolution and registration must be respected. Not the local navigation surface. | MIT |
| [MJFradi/mars-landing-site-suitability](https://github.com/MJFradi/mars-landing-site-suitability) | AHP/weighted-overlay landing-site GIS | Landing-site suitability is distinct from footprint/step clearance. General hard/soft criteria concept only; no scores imported. | MIT |
| [Rishit-katiyar/mars-river](https://github.com/Rishit-katiyar/mars-river) | Terrain hydrographic/river analysis | Hydrology and random starting points are not rover collision planning. No claim that this source fills pits; no algorithm/data copied. | GPL-3.0 |
| [SimranPenyuli/MARSNOVA](https://github.com/SimranPenyuli/MARSNOVA) | Mars GIS/ML suitability proposal | Reviewed tree contains only README; no executable model/pipeline to integrate. | Belirlenmedi |
| [EarthViewer/mars](https://github.com/EarthViewer/mars) | Planetary imagery/terrain viewer | Useful broad-context visualization; no verified wheel-scale DEM/native collision/sensor path. No import. | MIT |
| [Hyradus/MARSIS-xDR-READER](https://github.com/Hyradus/MARSIS-xDR-READER) | MARSIS radar formats and GIS/array conversion | Subsurface radar is not the surface microtopography required for rover collision. GPL source not imported. | GPL-3.0 |
| [NASA-AMMOS/MMGIS](https://github.com/NASA-AMMOS/MMGIS) | Planetary GIS and mission-operation mapping | Adopt map/goal/provenance separation in our own small UI. Viewshed is line-of-sight analysis, not a rover path planner. No MMGIS code/assets imported. | Apache-2.0 |
| [opengeos/RustGIS](https://github.com/opengeos/RustGIS) | GIS viewer with planetary basemap sources | planets.rs supplies Web Mercator planetary raster basemaps; not a fine DEM. Do not use Earth tile metres as Mars local distances. | Apache-2.0 |
| [kimhoyun-robotair/MarsLab](https://github.com/kimhoyun-robotair/MarsLab) | Isaac Sim Mars scenes and sensor/optional ROS2 bridge | Adopt capture stamp, organized-point and applied-setting verification as independent adapter practices. Scene-generation tools absent and engine differs; no source/assets imported. | Belirlenmedi |
| [ViraatC22/extraterrestrial-autonomy](https://github.com/ViraatC22/extraterrestrial-autonomy) | EXONAUT adaptive risk planning and synthetic environments | Retain distinction between terrain prior and evidence. Slip/energy/Bayesian/RL models need calibrated data and are deferred. No learned policy or procedural terrain imported. | MIT |
| [J-Varela/lunar-pathfinder](https://github.com/J-Varela/lunar-pathfinder) | Real-data lunar terrain classes and risk-aware A* | Adopt hard-constraint versus cost distinction independently. Its 8/15/25 degree classes are explicitly provisional and not rover-certified Mars limits. No code copied. | Belirlenmedi |
| [spaceuma/baseprod](https://github.com/spaceuma/baseprod) | Earth field dataset for Mars-analogue rover sensing | Useful later calibration/timestamp validation dataset, explicitly Earth analogue rather than measured Mars. No assets imported. | MIT |
| [kalesha681/ARES-Autonomous-Surveyor](https://github.com/kalesha681/ARES-Autonomous-Surveyor) | UAV survey, boustrophedon coverage and visual landmarks | Aerial coverage is distinct from skid-steer rover footprint/collision planning. Defer coverage features. | MIT |
| [raulcastar/MARE-Lunar-Simulator](https://github.com/raulcastar/MARE-Lunar-Simulator) | Current Unreal project, TCP rover and sensor plugins | Direct integration uses existing LIDR/NAVF plugins, measured DEM import and motor protocol; runtime plugins made explicit and shared clock/wire contract reviewed. | MIT |

## Mars listesi dışındaki ilgili yıldızlar

| Depo | Kapsam ve karar | API lisansı |
|---|---|---|
| [ShisatoYano/AutonomousVehicleControlBeginnersGuide](https://github.com/ShisatoYano/AutonomousVehicleControlBeginnersGuide) | Modular vehicle-control/planning examples. Algorithm reference for separated planning/tracking responsibilities; independent implementation, no source copied. | MIT |
| [ethz-asl/mav_active_3d_planning](https://github.com/ethz-asl/mav_active_3d_planning) | ROS-based active 3D UAV planning. Informative exploration may later complement a rover; different vehicle/stack, not imported. | BSD-3-Clause |
| [bwalsh0/Stereo-Camera-Path-Planning](https://github.com/bwalsh0/Stereo-Camera-Path-Planning) | Calibrated stereo/SGBM, obstacle map and planning. Independently implement paired capture, SGBM metre depth and transform into the map. No external calibration or source copied. | MIT |
| [JeanetteMueller/OpenPerseverance](https://github.com/JeanetteMueller/OpenPerseverance) | Open rover project. Potential future vehicle/model reference; user CAD/kinematics are separate and no model imported. | CC0-1.0 |
| [kevinbalicot/html5-mars-project](https://github.com/kevinbalicot/html5-mars-project) | HTML5 Mars visualization. Presentation context, not native 3D rover clearance. No import. | Belirlenmedi |
| [mars-sim/mars-sim](https://github.com/mars-sim/mars-sim) | Mars settlement/system simulation. Human/settlement simulation is outside the local geometric driving task. No import. | GPL-3.0 |
| [FredJ21/MarsRover2020](https://github.com/FredJ21/MarsRover2020) | Alternative Mars rover simulator. Different project/engine and runtime contract; no direct drop-in navigation integration demonstrated. No import. | MIT |
| [selamet/maze-solver-teknofest](https://github.com/selamet/maze-solver-teknofest) | İHA/İKA competition image/maze solving. 2D image arena, not measured Mars DEM. No public separate İKA list was visible; this relevant star was reviewed individually. No source copied. | Belirlenmedi |
| [sieuwe1/Autonomous-Ai-drone-scripts](https://github.com/sieuwe1/Autonomous-Ai-drone-scripts) | Autonomous drone scripts. Different vehicle and sensing assumptions; no demonstrated measured Mars rover integration. No import. | Belirlenmedi |

## Bu fork'a aktarılan geliştirme kararları

| Araştırmadan çıkan yöntem | Bağımsız uygulama | Kanıt / sınır |
|---|---|---|
| Sert geçilebilirlik sınırı ile yumuşak maliyeti ayırma | `mars_rover/planning.py`: quad eğimi, basamak, NaN/sınır, footprint; sonra A* maliyeti | Krater/çukur/NaN/köşe/geçit ve gerçek Jezero testleri; araç eşikleri deneysel |
| Kavisli komutun koridor dışına taşmasını önleme | `mars_rover/navigation.py`: kısa komut yayı, önce dur sonra yeniden planla | Yeni engelle rota bozulması ve kinematik takip testleri; kalibre dinamik model değil |
| Harita önbilgisi ile sensör kanıtını ayırma | Aynı manifest/r16 + ek pozitif/negatif engel; gözlenmeyen dönüşler yeni zemin sayılmaz | Tam negatif engel kapsaması henüz yok; önceden bilinen DEM'e dayanır |
| Capture zamanı, montaj ve ölçeği birlikte işleme | `sensors.py`, `mars_sensor_setup.py`: GncSimTime, full attitude, gerçek bileşen dönüşümleri | Parçalı/coalesced TCP ve eğimli rover zemini; native mount/akış kabulü bekliyor |
| Stereo ile ground truth'u ayırma | `stereo.py`: gerçek OpenCV SGBM; ayrı seçilen kaynak, sol optik çerçeve | 8 px disparity düzlemi 2.4 m verir; Mars görüntüsü kalibrasyonu değil |
| Görev hedefini jeolojik referansla seçme | `nav_service.py` ve küçük görev arayüzü | Harita/HTTP/TCP entegrasyonu; MMGIS kodu veya görüş hattı algoritması kullanılmadı |

Buradaki A*, geometrik projeksiyon ve stereo formülleri standart yöntemlerdir.
Eşikler bir blogdan veya başka rover'dan fiziksel sertifika olarak alınmadı.
MOLA'nın 463 m hücresini 1 m'ye büyütmek, görüntüyü mesh'e kaplamak veya
prosedürel taş dağıtmak ölçülmüş küçük Mars geometrisi üretmez. Aynı şekilde
hidrolojik modelleme için uygun olabilecek bir DEM düzeltmesi, korunması
gereken rover çukurlarını silmeye gerekçe olmaz; mevcut yüzeyde çukur
doldurma/yumuşatma uygulanmaz.

MPPI, D* Lite, RL, scout/UAV ve enerji/kayma modelleri doğrudan eklenmedi.
Önce referans rover'ın gerçek UE hareketi, dönüş oranı, durma gecikmesi ve
sensör ölçümü kabul edilmelidir. Bu modeller için deneysel veri oluşmadan
daha karmaşık bir kontrolcüye geçiş doğruluk kazanımı sayılmaz.

## Mevcut MARE/GNC ile karşılaştırma

Asıl ROS 2 otonomisi ayrı
[GNC-Moon-Simulator](https://github.com/raulcastar/GNC-Moon-Simulator)
deposundadır. DEM küresel planlayıcı, stereo/LiDAR yerel algılama ve rover
kontrolü farklı bileşenlerdir. Bu fork'taki ROS'suz adaptör aynı sensör ve
motor wire protokollerine bağlanır; GNC kaynaklarını bu repo içine kopyalamaz.
İki motor/kamera/LiDAR sunucusu aynı portta çalıştırılmaz.

GNC'de incelenen LiDAR engel yaklaşımı zemin düzleminden **yukarıdaki** noktaları
ayıkladığı için tek başına negatif çukur algılama kanıtı değildir. Yeni yöntem
tam capture pozunda DEM'e göre hem yüksek hem alçak dönüşleri işler; hâlâ
örtülü ya da dönüş olmayan çukur için tam kapsama garantisi yoktur. LiDAR
başlığındaki zamanın world-seconds sanılması da düzeltildi: gerçek clock
epoch tabanlıdır. Mevcut beş plugin `GncSimTime.h` kopyasının aynı olduğu test
ediliyor; eski NAVF v1 akışı navigasyonda kabul edilmiyor.

## Bir sonraki kabul ve veri aşaması

Uygulama, komutlar ve tamamlandı/bekliyor ölçütleri
[navigasyon rehberinde](mars-navigation.md) bulunur. Öncelik: native plugin
derleme, yükseklik/collision kabulü, düzlemde sensör mesafe/poz deneyi ve
kısa hedefli sürüş. Sonra eşkayıtlı rover stereo ürünleriyle ölçülmüş daha
ince mesh/Landform yolu değerlendirilebilir. 2.5D Landscape, overhang,
mağara veya gerçek boşluk geometrisini temsil etmez; bunlar mesh ister.
Kum/batma/çekiş bu aşamada ertelendi.

Bağımsız bilimsel dayanaklar: [HiRISE DTM üretim ve artifact sınırları](https://www.uahirise.org/dtm/about.php),
[NASA/JPL AutoNav yükseklik haritası ve wheel-drop değerlendirmesi](https://science.nasa.gov/resource/computer-simulation-of-perseverances-first-autonav-drive/),
[JPL stereo, eğim/basamak/roughness ve VO](https://robotics.jpl.nasa.gov/what-we-do/flight-projects/mars-science-laboratory/surface-system-software-and-rover-navigation/),
[OpenCV SGBM API](https://docs.opencv.org/4.x/d2/d85/classcv_1_1StereoSGBM.html).
Bu yöntemler uçuş yazılımının eşdeğerini geliştirdiğimiz veya test ettiğimiz
anlamına gelmez. NASA verisinin açık olması, bu GitHub projelerinin bütün
kod/varlıklarının aynı lisansla dağıtıldığı anlamına da gelmez.
