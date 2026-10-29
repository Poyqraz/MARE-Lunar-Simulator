# Windows'ta Unreal Engine 5.7: kurulum ve tam native test

28 Ekim 2026. Bu prosedür kullanıcı bilgisayarında çalıştırılacak; burada
UE/GPU çalıştırıldığı iddia edilmez. Hedef mevcut Mars ortamı, ROS'suz
navigasyon ve A1 görev geçmişidir. Planlanan yeni uydu–rover runtime arayüzü,
ekrandan native hedef seçimi ve otomatik disk günlüğü henüz yoktur.

## 1. Merge kararı

İlgili PR'lar #1 ve #2'dir. Anlık dal uçları, taslak/merge durumu ve CI
sonuçları için GitHub'daki PR kayıtlarını kontrol edin. Python CI'ı tek başına
native kabul sonucu değildir.

**Şimdilik merge gerekmiyor.** `codex/mars-mission-history` dalı iki PR'ın
kodunu da içerir ve doğrudan test edilebilir. Native sonuçları görmeden
`main`e alınması önerilmez. Testler ve gerekiyorsa düzeltmelerden sonra sıra:
**PR #2 → `codex/mars-jezero-reviewed`; PR #1 → `main`**. Başarısız veya
ölçülmemiş zorunlu native kontroller varken tamamlandı denmez. Bu belge
eklenirken hiçbir PR merge edilmedi.

## 2. İndirilecekler

| Uygulama | Sürüm / seçim | Resmî kaynak |
|---|---|---|
| Epic Games Launcher | Unreal Engine Library'den **5.7.x** seç; varsayılan en yeni sürüm farklı olabilir | [Unreal indirme](https://www.unrealengine.com/download), [kurulum](https://dev.epicgames.com/documentation/unreal-engine/install-unreal-engine) |
| Visual Studio Community **2022** | 17.14 güncel servicing sürümü; 2026 sürümü yerine hedeflenen 2022 araçları | [Microsoft 2022 release history](https://learn.microsoft.com/en-us/visualstudio/releases/2022/release-history), Current 17.14 → Community |
| Git for Windows x64 | Git CLI | [Git](https://git-scm.com/install/windows) |
| Git LFS | `git lfs version` çalışmıyorsa ayrıca kur | [Git LFS](https://git-lfs.com/) |
| Python x64 | Ayrı Windows Python **3.12**; venv kullanılacak | [Python Windows](https://www.python.org/downloads/windows/), [install manager](https://docs.python.org/3/using/windows.html) |
| GPU sürücüsü | Kart üreticisinin güncel kararlı sürücüsü | [NVIDIA](https://www.nvidia.com/Download/index.aspx), [AMD](https://www.amd.com/en/support), [Intel](https://www.intel.com/content/www/us/en/download-center/home.html) |

VS Installer'da **Game development with C++** ve **Desktop development with C++**
seç. Individual components içinde **MSVC v143 14.44.35214** ve **Windows SDK
10.0.22621.0 veya yenisi** bulunduğunu denetle. UE 5.7 belgesi .NET 8.0'ı
belirtir; Launcher'ın UE prerequisites kurulumu tamamlanmalı. VS Tools for
Unreal Engine / debugger / test adapter, hata incelemeyi kolaylaştıran ek
araçlardır. Kaynaklar: [Epic 5.7 toolchain](https://dev.epicgames.com/documentation/en-us/unreal-engine/setting-up-visual-studio-development-environment-for-cplusplus-projects-in-unreal-engine?application_version=5.7),
[Microsoft VS–UE araçları](https://learn.microsoft.com/en-us/visualstudio/gamedev/unreal/get-started/vs-tools-unreal-install).

Epic'in genel donanım önerisi 32 GB RAM, 8 GB+ VRAM ve DX12 GPU'dur.
Bu projenin ayarları DX12, SM6, Lumen, Substrate ve ray tracing içerir.
Donanımın uygunluğu gerçek kart/sürücüyle kaydedilmeli; daha düşük ayarla
yapılan koşu aynı referans koşusu diye sunulmamalı. SSD boşluğu seçilen motor
bileşenleri, LFS varlıkları ve shader cache'e bağlıdır; Launcher boyutunu
kontrol et. [Donanım/sürücü kaynağı](https://dev.epicgames.com/documentation/en-us/unreal-engine/hardware-and-software-specifications-for-unreal-engine).

Bu ROS'suz test için Docker, WSL, ROS, Cesium, Terrain Studio, SolidWorks ve
kullanıcının CAD modeli gerekmez. Referans Leo_Raph rover kullanılır.

## 3. Temiz test klasörü ve Python doğrulaması

PowerShell aç. Aşağıda repo yolu `C:\work\MARE-Lunar-Simulator` kabul edilir.
Mevcut çalışmanı taşıma/silme; gerekirse başka yeni klasör seç ve bütün
yollarda aynı değişikliği yap.

```powershell
New-Item -ItemType Directory -Force C:\work | Out-Null
Set-Location C:\work
git lfs install
git clone --branch codex/mars-mission-history https://github.com/Poyqraz/MARE-Lunar-Simulator.git
Set-Location MARE-Lunar-Simulator
git lfs pull
git lfs fsck
git rev-parse HEAD
```

LFS indirmesi hata verirse `.uasset`/`.umap` varlıkları hazır kabul edilmez.
Son satırdaki commit'i test raporuna yaz. Test süresince dalı güncelleme;
kod değişirse sonuç yeni commit için tekrar değerlendirilir.

Python install manager ile henüz 3.12 yoksa `pymanager install 3.12`
kullanılabilir. Zaten kuruluysa yeniden kurmak gerekmez. Ardından:

```powershell
py -3.12 --version
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-mars-dev.txt
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m ruff check mars_rover tests Content/Python/mars_setup.py Content/Python/mars_scene.py Content/Python/mars_materials.py Content/Python/mars_collision.py Content/Python/mars_sensor_setup.py tools/unreal_mars_smoke.py tools/mars_fidelity_figure.py tools/mars_navigation_benchmark.py tools/capture_rover_telemetry.py
.\.venv\Scripts\python.exe tools/mars_navigation_benchmark.py --output generated/native-preflight.json
```

Beklenen mevcut test sayısı **165** ve dört başarılı offline rotadır.
`generated/native-preflight.json` varsa yeni çıktı adı seç. Venv'i aktive
etmek veya PowerShell execution policy değiştirmek zorunlu değildir.
**Unreal'ın gömülü Python'una pip/NumPy/rasterio/OpenCV kurulmaz.**

## 4. Motoru ve pluginleri ilk açılışta hazırlama

1. Epic Launcher → Unreal Engine → Library → Engine Versions `+` → **5.7**.
   Windows editor/Win64 araçlarını kur. 5.8'e yükseltme yapma.
2. `Moon_Simulator.uproject` dosyasını 5.7 ile aç; eksik modülleri rebuild
   istemine izin ver. Kaynak pluginler repoda; keyfî farklı prebuilt sürüm
   kullanmak bu kodun testini oluşturmaz.
3. İlk shader/asset hazırlamasının bitmesini bekle. Derleme başarısızsa,
   ilk gerçek derleme hatası ve build log'u saklanır; sonraki aşama geçmez.
4. Başlangıçta Ay seviyesi açılması normaldir; projenin default map'i budur.
5. Edit → Plugins içinde Python Editor Script Plugin, Editor Scripting
   Utilities, UnrealDEMLandscape, UnrealStereoCam, UnrealLidarCam ve
   UnrealSimClock'un etkin olduğunu denetle. Gerekli yeniden başlatmayı yap.
6. Project Settings'de Windows Default RHI **DirectX 12**, SM6, Lumen ve
   Substrate ayarlarını mevcut repo profiliyle karşılaştır. Başlangıç
   log'unda gerçek GPU adaptörünü ve D3D12 RHI'ı kaydet.

Bu content/plugin projesinde olmayan bir `Moon_SimulatorEditor` target'ı
varmış gibi manuel `.sln` build adımı varsayılmaz. Rebuild çalışmazsa log'a
göre plugin/host build yolu ayrıca çözülür. Genel bir hata üzerine pluginleri
silerek veya UE sürümünü değiştirerek teste devam edilmez.

### 4.1. UE 5.7.4'te gözlenen materyal giriş hatasından dönüş

29 Ekim 2026'da kullanıcı bilgisayarındaki motor
`5.7.4-51494982+++UE5+Release-5.7`, `DEMLandscapeLibrary=True` ve
`mars_setup.py` yolu doğrulandı. İlk gerçek `simulation` kurulumu,
`MaterialExpressionNoise` düğümünde `Position` yerine **`World Position`**
girişi sunulduğu için durdu:

```text
Material input not exposed; available pins: ['World Position', 'FilterWidth']
```

Bu, betiğin giriş adı uyarlamasındaki hatadır. `mars_materials.connect_input`
artık motorun bildirdiği girişler arasında `Position` → `World Position`
eşlemesini de çözer. Eski `Position` adı desteklenir; `FilterWidth` veya
rastgele ilk girişe bağlantı yapılmaz. Unreal bağlantıyı reddederse hata
korunur. Kaynak:
[Epic 5.7 MaterialEditingLibrary](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/MaterialEditingLibrary?application_version=5.7).
Bu API giriş adlarının sorgulanmasını ve bağlantının başarı sonucunu açıklar;
gözlenen `World Position` yazımı kullanıcının native log'undan gelir.

Test önce aynı hatayı üretti: iki başarısız, 17 başarılı ilgili test. Düzeltme
sonrası 19 ilgili test başarılıdır. Bunlar gerçek pin listesiyle modellenen
Python sözleşme testleridir; shader derlemesi veya native kurulumun geçtiği
anlamına gelmez. `build()` dönmeden kesildiği için `job` ataması gerçekleşmez;
sonraki `NameError` bu ilk hatanın sonucudur.

Yarım kalmış `Untitled` haritası doğrulanmış Mars seviyesi değildir. Kurtarma:

1. Editörü kapat. Yalnız bu başarısız denemenin başlıksız haritası ve üretilen
   Mars materyali için **Kaydetme / Don't Save** seç. Kullanıcıya ait başka
   değişiklikleri ayrı koru; hiçbir kaynak seviyeyi veya varlığı silme.
2. PowerShell'de kaynak dalı güncelle:

   ```powershell
   Set-Location C:\work\MARE-Lunar-Simulator
   git fetch origin
   git switch codex/mars-mission-history
   git pull --ff-only
   git rev-parse HEAD
   ```

   Git yerel değişiklik/çakışma nedeniyle durursa çıktıyı incele; hard reset,
   clean veya dosyaların üzerine zorla yazma uygulanmaz.
3. Projeyi 5.7.4 ile yeniden aç. Açılıştaki normal sahnede bekleyen değişiklik
   varsa kontrol ederek kaydet; Play kapalı kalsın. Editörü yeniden açmak eski
   Python modül önbelleğinin düzeltilmiş dosyayı kullanmasını sağlar.
4. Önceki denemenin adı yerine yeni bir ad kullan. Python konsolunda:

   ```python
   import mars_setup
   job = None
   job = mars_setup.build(level_path="/Game/Mars/JezeroQA02", report_path=r"C:/work/MARE-Lunar-Simulator/Saved/Mars/jezero-qa02.json")
   ```

   Bu satırlar konsolda ayrı ayrı çalıştırılabilir. Hata yoksa, bekledikten
   sonra sonuç sorgulanır. `importing` durumunda yalnız sorguyu tekrar et;
   `build()` çağrısını tekrarlama. `job is None` ise ilk traceback incelenir:

   ```python
   print({k: job.get(k) for k in ("status", "heightmap_verified", "collision_verified", "error")} if isinstance(job, dict) else "Kurulum donmedi; ilk traceback'i inceleyin.")
   ```

   `saved`, iki doğrulama için `True` ve `error=None` gereklidir. İşlem boyunca
   Play başlatma veya dünya değiştirme. Yeni denemenin JSON raporu ve log'u
   saklanır. Yükseklik/collision, görsel GPU ve sensör/sürüş kabulü, yeni gerçek
   sonuçlar gelene kadar **PENDING** kalır.

### 4.2. Güneş bileşeni ve önceki denemeden kalan Assets klasörü

29 Ekim 2026'da ikinci native log, `M_MarsProcedural` materyalinin oluşturulup
kaydedildiğini gösterdi: önceki Noise giriş düzeltmesi bu aşamayı geçti.
Sonraki hata `DirectionalLightComponent` üzerinde `source_angle` özelliğinin
bulunamamasıydı. UE 5.7 Python editor özelliğinin doğru adı
**`light_source_angle`** ve birimi derecedir. Hesaplanan nominal Mars güneş
açısı yaklaşık 0.349723° olarak korunur; yalnız API adı düzeltilir.

Kalan `_lighting` özellik adları aşağıdaki resmî 5.7 API sayfalarıyla
karşılaştırıldı. İki modda toplam 23 farklı editor özelliği için testte
bileşene özgü izin listeleri kullanılır; bilinmeyen adlar artık sınırsız
`MagicMock` tarafından kabul edilmez. Bu fixture tip, shader veya native
render doğrulaması değildir.

| API | Denetlenen alan |
|---|---|
| [DirectionalLightComponent](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/DirectionalLightComponent?application_version=5.7) | Güneş bağlantısı ve `light_source_angle` |
| [SkyAtmosphereComponent](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/SkyAtmosphereComponent?application_version=5.7) | Yarıçap, yükseklik, gaz/toz dağılımı ve saçılma/soğurma |
| [SkyLightComponent](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/SkyLightComponent?application_version=5.7) | `real_time_capture`; `recapture_sky` yöntemi de belgede mevcut |
| [PostProcessVolume](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PostProcessVolume?application_version=5.7) | `unbound` ve `settings` |
| [PostProcessSettings](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/PostProcessSettings?application_version=5.7) | Pozlama sınırları ve override bayrakları |

TDD önce iki başarısız / 19 başarılı ilgili test verdi; API adı düzeltildikten
sonra 21 ilgili test başarılıdır. Tam Python test sayısı 128'dir. Native
yükseklik/collision, GPU görüntüsü ve rover/sensör kabulü hâlâ bekler.

Materyal bu hatadan önce kaydedildiği için `/Game/Mars/JezeroQA02_Assets`
klasörü kalır. Aynı adla tekrar çağrı yapılınca görülen `Assets folder exists`
hatası, varlığın üzerine yazmayı engelleyen doğru önkoşuldur. İzin listesi veya
bu koruma kaldırılmaz. Aynı log'da elle `/Game/Untitled` adıyla kaydedilen
yarım harita da betiğin yükseklik/collision kabul raporu yerine geçmez.

Kurtarma için 4.1'deki dal güncellemesini editör kapalıyken uygula, editörü
yeniden aç ve normal kaynak sahnede bekleyen değişiklikleri kontrol et.
Eski QA varlıklarını silmek yerine yeni bir adla, Play kapalıyken bir kez çalıştır:

```python
import mars_setup
job = None
job = mars_setup.build(level_path="/Game/Mars/JezeroQA03", report_path=r"C:/work/MARE-Lunar-Simulator/Saved/Mars/jezero-qa03.json")
```

4.1'deki durum sorgusunu kullan. `importing` ise sadece sorguyu tekrar et;
kurulumu tekrar başlatma. İlk hata varsa onu ve varsa yeni JSON'u sakla.

### 4.3. QA03: iç içe Slate callback'i ve tutarsız rapor

29 Ekim 2026 QA03 log'unda sahne oluşturma tamamlandı ve harita kaydı başladı.
Kayıt sürerken `Target appeared during import`, ardından kayıt başarı mesajı
ve `pending.pop(token)` üzerinde `KeyError` görüldü. JSON `failed` ve iki
doğrulama bayrağı `false` iken bellekteki `job`, `saved` / `true` / `true`
ile eski hata metnini birlikte taşıyordu. Bu çelişkili koşu **kabul edilmez**;
mevcut JSON elle başarılıya çevrilmez.

Log sırasıyla tutarlı yeniden giriş senaryosu testte üretildi: editor API
çağrısı bitmeden aynı Slate callback'i yeniden çağrılıyor. Düzeltme:

- Meşgul callback'e yeniden giriş ve tamamlandıktan sonra kuyruktan gelen
  callback çağrıları işlem yapmaz.
- Doğrulama, harita kaydı ve rapor sonlandırması bir kez çalışır; callback
  kaydı tek sefer kaldırılır. Tek import kilidi rapor sonlandırılana kadar
  korunur. Gerçekten başka bir hedef oluştuğunda mevcut
  `Target appeared during import` koruması çalışmaya devam eder.
- JSON önce `.json.tmp` dosyasına yazılıp nihai ada atomik taşınır. Terminal
  `saved`/`failed` durumu, callback temizliği ve rapor yazımı tamamlandıktan
  sonra görünür olur; smoke runner erken çıkamaz. Başarıda `error=None` olur.
- Rapor I/O hatası başarı yayımlamaz. Dünya/Play durumu kayıt öncesi ve sonrası
  yeniden kontrol edilir; değişen bağlam kabul edilmez. Kayıt sırasında dünya
  değişirse diskte kısmi/tamamlanmış bir map kalabilir; bu kabul sonucu değildir.
- `unreal_check`, `saved` ve iki `true` bayrağı bulunsa bile `error` alanı dolu
  bir raporu reddeder.

TDD'de önce 10 başarısız / 6 başarılı ilgili test görüldü. Bağlam değişikliği
incelemesinde dört ek regresyon üretildi ve kapatıldı; sonlandırma boyunca
tek import kilidinin korunması da önce başarısız testle denetlendi. Son durumda 20 ilgili
test başarılıdır. Bunlar iç içe height/collision/save çağrıları, geç callback,
geciken import/collision, gerçek hedef çakışması, başarısız save, rapor I/O ve
smoke kabul sözleşmesini modeller; burada native motor çalıştırılmaz.

QA03'te önceki materyal ve güneş API hataları tekrar görülmedi. Ancak tutarlı
yükseklik/collision raporu, GPU görünümü ve rover/sensör kabulü yeni gerçek
koşu gelene kadar bekler. Kaynak Mars verisi ve sayısal toleranslar değiştirilmez.

4.1'deki git güncellemesini editör kapalıyken uygula, sonra Play kapalı ve
bekleyen değişiklikler kontrol edilip kaydedilmişken yeni isimle çalıştır:

```python
import mars_setup
job = None
job = mars_setup.build(level_path="/Game/Mars/JezeroQA04", report_path=r"C:/work/MARE-Lunar-Simulator/Saved/Mars/jezero-qa04.json")
```

Durum sorgusu ve JSON **aynı** `saved`, iki `true`, `error=null` sonucunu
taşımalıdır. `importing` iken yalnız durum sorgusunu tekrarla. Eski QA03
seviyesi/raporu korunabilir; üzerine yazarak önceki kanıt değiştirilmez.

### 4.4. QA04: ilk native simulation arazi sonucu

29 Ekim 2026'da kullanıcı tarafından sağlanan UE **5.7.4** log ve
[QA04 JSON raporu](data/native-jezero-qa04.json) birbiriyle tutarlıdır:
`/Game/Mars/JezeroQA04`, `simulation`, `saved`, `heightmap_verified=true`,
`collision_verified=true`, `error=null`. Manifest SHA-256 değeri
`aea08f2fbc305462a0b9c59f2566197fa33d08da3312cedb4c921e5e59230f88`,
bu daldaki veri paketi manifestiyle eşleşir. Çalıştırılan commit ve GPU
modeli bu raporda yoktur; ayrıca kaydedilmelidir.

Rapor 260 konum ve 520 basit/karmaşık trace için en büyük konum farkını
0,000084457 m (yaklaşık 0,084 mm), sayısal toleransı 0,002 m olarak bildirir.
Geri okuma, 253 × 253 kodlanmış yükseklik değerinin tamamını beklenen diziyle
eşleştiren mevcut betiğe göre başarılıdır. Bu sonuç arazi içe aktarımı ve
**örneklenmiş** collision için kabul edilir; tüm üçgenleri, teker temaslarını
veya kaynak DTM'in saha doğruluğunu doğrulamaz. Kullanıcı log'unda ilk kayıt
sonrası Landscape fiziksel materyal oluşturma ve haritanın yeniden kaydı da
görülür; harita kapatılıp açıldıktan sonraki ölçümler ayrı kanıttır.

QA04 yalnız `simulation` modunu kapsar; `orbital_reference` için sonraki
QA03 sonucuna bakın. GPU performans, LiDAR, depth, rover ve görev testleri
beklemektedir. QA04 raporundaki `gpu_render_verified`,
`visual_qa_passed`, `photometry_validated` ve
`wheel_scale_obstacles_validated` alanları `false` olarak kalır. Bu rapor
elle değiştirilmez. Yeni reference seviyesi ayrı isimle oluşturulur; mevcut
QA04 üstüne yazılmaz.

### 4.5. HiRISE referansında adsız ComponentMask girişi

29 Ekim 2026'da kullanıcının UE 5.7.4 log'u, `JezeroRefQA01` denemesinde
HiRISE gri PNG'sinin içe aktarıldığını ve kaydedildiğini; ardından
`MaterialExpressionComponentMask` için sunulan tek girişin `['None']`
olarak raporlandığını gösterdi. `connect_input` bunu `Input` adıyla
eşleştiremedi ve materyal tamamlanmadan durdu. Daha sonra aynı isimle yapılan
denemeler, kalan `JezeroRefQA01_Assets` klasörüne yanlışlıkla yazmayı
önleyen `Assets folder exists` kontrolünde durdu. Kullanıcının QA02 ekranında
da içe alınmış doku ve tamamlanmamış materyal görünür; QA02'nin ilk traceback'i
ayrıca sağlanmamıştır.

[Epic'in 5.7 API açıklamasına](https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/MaterialEditingLibrary?application_version=5.7)
göre boş giriş adı ilk girişi seçer. Düzeltme bunu yalnızca mantıksal
`Input` istendiğinde ve düğüm **tam olarak bir adsız giriş** (`None` veya boş
isim) bildirdiğinde kullanır. Birden çok girişli belirsiz durumda ilk giriş
seçilmez, Unreal bağlantıyı reddederse hata korunur. Diğer bilinen pin
eşleştirmeleri ve kaynak veri değişmez.

TDD'de önce 4 başarısız / 24 başarılı ilgili test görüldü; düzeltme sonrası
28 ilgili test ve 149 tam Python testi başarılıdır. Orbital materyal grafiği,
pin seçimi ve bağlantı reddi kontrollü sahte Unreal API'siyle test edilir;
bunlar gerçek shader, görüntü hizalaması veya GPU render kabulü değildir.

Kurtarma: Kullanıcının başka çalışmalarını koruyarak başarısız denemeye ait
başlıksız haritayı ve yarım materyal değişikliklerini kaydetmeden editörü kapat.
4.1'deki gibi dalı güncelle ve editörü yeniden aç. QA01/QA02 klasörlerini
silme; Play kapalı ve bekleyen paketler temizken **yeni** adla dene:

```python
import mars_setup
ref = None
ref = mars_setup.build(level_path="/Game/Mars/JezeroRefQA03", mode="orbital_reference", report_path=r"C:/work/MARE-Lunar-Simulator/Saved/Mars/jezero-refqa03.json")
```

`ref` için 4.1'deki sorgunun değişken adı uyarlanır; `importing` ise yalnız
durum sorgusu tekrarlanır. Yeni JSON ve log birlikte istenir. `saved` ve iki
doğrulama bayrağı geçse bile görüntü/hizalama ve GPU görünümü ayrıca incelenir.

### 4.6. QA03: native HiRISE referansı

29 Ekim 2026'da kullanıcının UE 5.7.4 log'u, konsolu ve
[QA03 raporu](data/native-jezero-refqa03.json) birlikte incelendi. Referans
modu `/Game/Mars/JezeroRefQA03` olarak kaydedilmiş, tüm kodlanmış
yüksekliklerin geri okuması ve 260 noktada 520 basit/karmaşık collision
sorgusu geçmiş; en büyük sayısal konum farkı yaklaşık 0,084 mm'dir. Manifest
SHA-256'sı QA04 ve bu daldaki veri paketiyle eşleşir.

Kullanıcının ekran görüntüsünde tek gri HiRISE kesiti arazi üzerinde görünür.
Ekran görüntüsü ile paketteki PNG arasında özellik eşleştirme ve perspektif
dönüşümü, benzer motiflerin aynı görünür yönde olduğunu destekler. Bu yalnız
görüntü uzayında bir kontroldür; DEM ile görüntünün yer koordinatlarındaki
hatasını, Mars'taki gerçek ölçüm doğruluğunu veya bütün pikselleri bağımsız
doğrulamaz. Gözlenen görüntü testi, `gpu_render_verified` veya
`visual_qa_passed` alanlarını elle değiştirme gerekçesi değildir. Teker
ölçeğinde 3B taşlar veya çukurlar PNG'den yaratılmaz.

Logda editör başlatılırken, Mars kurulumundan önce altı kez genel
`LogAutomationTest: Error: Condition failed` vardır; kaynak test adı veya
stack verilmediğinden nedeni henüz kesinleştirilmemiştir. Epic'in
[UE-305638 kaydı](https://issues.unrealengine.com/issue/UE-305638) virgül
kullanan locale'lerde aynı metni üreten motor içi bir sorunu açıklar;
kayıtta etkilenen sürüm 5.6'dır. Kullanıcının 5.7.4 oturumunda bu hata ile
aynı nedenin geçerli olduğu yalnızca bir olasılıktır. Başlangıç logunu
otomatik olarak rover TCP telemetrisiyle eşitlemeyin; gerçek
3003 hat verisi ayrıca incelenmelidir. Raporlanan D3D12 desteği, seçilen GPU
adaptörü ve tamamlanmış performans kabulüyle eşdeğer değildir.

QA03 referans kurulum ve görüntüleme smoke testi geçmiştir; kesin görüntü/DEM
yer hizası, sensör kalibrasyonu, uzun GPU performans koşusu, rover hareketi
ve paketli uygulama kabulü beklemektedir.

### 4.7. İlk rover kurulumu: LiDAR eksenleri

29 Ekim 2026'da kullanıcının `JezeroFullTest01` log'unda rover aktörü ve
simülasyon sahnesi oluşturuldu, ancak `configure_and_export()` LiDAR'ın
seçtiği montaj bileşeninde `Sensor axes are not an orthonormal rigid basis`
hatasıyla, seviye doğrulanıp kaydedilmeden durdu. Bileşen adı ve vektörler
eski hata mesajında bulunmadığından, bu koşunun kesin nedeni bilinmez. Aynı
log daha sonra başlıksız dünya için Play başlatıldığını gösterir; bu, sensör
veya rover hareketi kabulü değildir. Yarım sahne üzerinde tekrar Play yapma.

TDD incelemesi ayrıca iki koruma eksikliği ortaya çıkardı: iki birim vektör
birbirine yeterince dik olmasa da eski kontrol geçirebiliyordu ve LiDAR
montajı doğrulanmadan bazı sensör ayarları değiştiriliyordu. Güncel kod
vektör uzunluğunu, dikliğini ve sonlu konumu denetler; montajlar ve rapor
hesaplanmadan sensör ayarlarına dokunmaz. Hata, bileşen adı ile ham ileri/yukarı
vektörlerini içerir. Testler bunları modeller; **kullanıcının gerçek LiDAR
hatasının nedeni ve çözümü henüz doğrulanmış değildir**. Tolerans gevşetilmez,
vektörler sessizce normalize edilmez ve gerçek ölçüm yerine tahmin yazılmaz.
TDD'de önce 4 başarısız / 4 başarılı ilgili test, düzeltmeden sonra 8 başarılı
ilgili test ve 154 başarılı tam Python testi görüldü; bunlar native test değildir.

Sonraki UE 5.7.4 teşhisinde önceki rover artık açık editör dünyasında yoktu.
`Lunar_Terrain_Raph` dünyasında aynı Blueprint'ten geçici bir rover oluşturulup
hemen ölçüldü ve başarıyla kaldırıldı. Bu bağımsız örnekte `LidarCam`,
`Navcam_Center` bileşenini takip ediyordu; kamera ileri/yukarı vektörlerinin
uzunluk kareleri yaklaşık 1, skaler çarpımları yaklaşık −5.6e−17 idi ve
`map_frame()` geçti. Ölçülen kamera ölçeği `(0.1, 0.1, 0.1)` idi. Bu, kamera
ölçeğini değiştirmenin gerektiğine dair kanıt değildir: yön vektörleri bu
örnekte zaten geçerlidir. Bu ölçüm önceki Mars dünyasındaki aynı aktör ve
ayar değişiklikleriyle yapılmadığı için ilk hatanın nedenini veya çözümünü
kanıtlamaz.

Ek incelemede, bir ayar değişikliği sonrasında editör bileşenlerinin veya
dönüşümlerinin değişmesi halinde eski ölçümün dosyaya yazılabileceği görüldü.
Unreal `set_editor_property` çağrıları editörün değişiklik işleme kodunu
çalıştırabilir; bu durumun ilk hatayı oluşturduğu henüz gösterilmemiştir.
Kurulum artık her ayarda güncel sensör bileşenini yeniden bulur, ayarların
uygulandığını okur ve **tüm ayarlardan sonra** güncel sensör geometrisini
yeniden doğrulayıp yazar. Geometri geçersizse veya ayar korunmamışsa config
oluşturmaz. İlgili yeniden oluşturma ve dönüşüm senaryoları test çiftleriyle
modellenmiştir: yeni korumalar öncesinde 4 test başarısızdı; sonrasında ilgili
14 test ve tam 160 Python testi geçti. Bunlar gerçek UE kabul testi değildir;
gerçek UE ile yeniden deneme hâlâ gereklidir. Eski başarısız
`JezeroFullTest01_Assets` klasörü ve kullanıcı çalışmaları silinmez.

### 4.8. Rover telemetrisi ayrışmıyorsa ham TCP tanısı

29 Ekim 2026'da kullanıcı `f4b8a44` ile rover'lı Jezero seviyesini başarıyla
kaydetti. Başlangıç aktör konumu `(-12600,12600,633.47)` cm doğrulandı.
Play logunda LiDAR GPU modu başladı, 3007'ye bağlandı; merkez kameradan 640×480
ground-truth depth oluşturuldu ve stereo 3004'e bağlandı. Bu, gerçek paket
doğruluğunun veya kesintisiz sensör sağlığının kabulü değildir.

Köprü bir bağlantı gördü, ancak `Telemetry exceeded 64 KiB without a complete
JSON object` sonrasında bağlantı kesildi; poz gelmedi, bütün teker komutları
sıfırda kaldı. Blueprint logundaki örnek `"time": 0,033, "x": -12.600,019`
geçerli JSON sayıları içermez ve yerel sayı biçimlendirmesi olası bir nedendir.
Fakat Blueprint logu TCP baytları değildir; **hat üzerindeki veri henüz
yakalanmamıştır** ve neden kesinleştirilmez. İngilizce yerel ayar da basamak
gruplaması ekleyebileceğinden tek başına güvenli bir JSON çözümü sayılmaz.

Köprü artık kapama ayracı gelmiş bozuk JSON nesnesini 64 KiB beklemeden hata
olarak raporlar; tamamlanmamış/çok parçalı JSON, dizgilerdeki ayraçlar ve
kaçışlar ayrı test edilir. Bu iyileştirme veriyi dönüştürmez ve neden
doğrulanmadan yerel biçimlendirilmiş sayıları kabul etmez.

Ham kanıt için önce Unreal'da Play'i, sonra navigasyon servisini durdurun.
Güncel dalda repo kökünden çalıştırın:

```powershell
.\.venv\Scripts\python.exe tools/capture_rover_telemetry.py
```

`TCP 3003 hazir` yazınca 60 saniye içinde Unreal'da Play'e basın. Araç yalnız
sıfır teker komutları gönderir, ilk en fazla 2048 baytı aynen Base64 olarak
yazdırır ve bağlantıyı kapatır; ardından Play'i durdurun. Çıktıların
`HAM_TCP_BOYUT` ve `HAM_TCP_BASE64` satırlarını saklayın. 3003 kullanımda
ise diğer süreçleri rastgele kapatmayın; önce port hatasını inceleyin.
Bu kısa kayıt uydu görüntüsü, sensör verimi veya gerçek sürüş kabulü değildir.

## 5. Otomatik native yükseklik ve collision testi

Önce editor'daki çalışmayı kaydet ve editor'ı kapat. Repo kökündeki PowerShell:

```powershell
.\.venv\Scripts\python.exe -m mars_rover.unreal_check --editor "C:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor.exe" --mode simulation --timeout 1200
.\.venv\Scripts\python.exe -m mars_rover.unreal_check --editor "C:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor.exe" --mode orbital_reference --timeout 1200
```

Motor başka diskteyse `--editor` yolunu değiştir. Araç ayrı gerçek editor
işlemi açar; benzersiz `/Game/Mars/QA_...` seviyeleri oluşturur. Çıktılar
`Saved/Mars/acceptance_....json` ve `editor_....log` dosyalarındadır.
`UnrealEditor.exe` kullanılmalı; `-NullRHI` eklemek GPU deneyi değildir.

Her mod için beklenenler:

- `status="saved"`, `heightmap_verified=true`, `collision_verified=true`;
- 260 konumda toplam 520 simple/complex collision sorgusu;
- doğru terrain actor, mip 0 ve 2 mm sayısal karşılaştırma toleransı.

Bu 2 mm, Mars DTM'inin gerçek doğruluğu değildir. Bütün teker temasları da
bu örneklerle doğrulanmış sayılmaz. `gpu_render_verified` ve
`visual_qa_passed` otomatik true olmaz; ayrı insan/GPU incelemesi gerekir.
CLI'nin dış timeout'u 1200 s olsa da mevcut editor betiğinde import için
120 s iç süre vardır. İlk shader hazırlamasını önceden tamamlamak önemlidir;
iç timeout hatası yalnız dış süre artırılarak çözülmüş sayılmaz.

## 6. Rover'lı yeni Mars test seviyesini oluşturma

Editor'ı yeniden aç. Play kapalı ve açık çalışma kaydedilmiş olsun.
Window → Developer Tools → Output Log aç; alt komut türünü **Python** seç.

```python
import mars_setup
job = mars_setup.build(
    level_path="/Game/Mars/JezeroFullTest02",
    rover_blueprint="/Game/Blueprints/Leo_Raph",
    navigation_config_path=r"C:/work/MARE-Lunar-Simulator/Saved/Mars/fulltest02-sensors.json",
    report_path=r"C:/work/MARE-Lunar-Simulator/Saved/Mars/fulltest02-import.json",
)
```

`job['status'] == 'saved'` ve rapordaki heightmap/collision doğrulamalarını
bekle. Sensör JSON'u harita doğrulaması tamamlanmadan oluşturulabilir; yalnız
dosyanın varlığı başarı anlamına gelmez. İçe aktarım sırasında Play veya dünya
değişimi yapma. Seviye, varlık klasörü veya JSON zaten varsa üçü için de yeni
adlar seç. Kendi CAD'i gerekmez.

Ayrı orbital referans incelemesi için `rover_blueprint` ve sensör config'i
olmadan yeni seviyede `mode="orbital_reference"` kullanılabilir; örnek
[Mars rehberinde](mars-jezero.md). Bu iki seviye kurulumu, planlanan oyun
benzeri canlı görünüm değiştirme özelliği değildir.

## 7. GPU görsel ve performans koşusu

1. 1920×1080 çözünürlükte aynı viewport / New Editor Window PIE profiliyle
   çalış. Kullanılan Scalability, screen percentage ve GPU/sürücü sürümünü yaz.
2. Görsel ilk koşuda eksik/damalı materyal, siyah/beyaz hatalı yüzey, seam,
   floating rover, terrain'e gömülme veya yanlış ölçekte arazi var mı incele.
   Referans görüntü kuzey/yön işaretleriyle aynı konumda olmalı.
3. Güneş, gölge ve atmosferi birkaç konumdan ekran görüntüsüyle kaydet.
   Turuncu görünmesi bilimsel radyometri doğrulaması değildir.
4. Output Log'da komut türünü **Cmd** yap; Python komutu olarak çalıştırma:

```text
stat fps
stat unit
stat gpu
stat unitgraph
```

Frame/Game/Draw/GPU sürelerini kaydet. Projede sabit 30 FPS ayarı vardır;
30 FPS görmek tek başına yeterli GPU payı olduğunu kanıtlamaz. İlk referans
koşuda fixed frame rate veya sensör kalitesi değiştirilmez. FPS düşüşü,
device-removed, VRAM uyarısı ve sensor stale olaylarını birlikte kaydet.
[Epic performans komutları](https://dev.epicgames.com/documentation/unreal-engine/guidelines-for-optimizing-rendering-for-real-time-in-unreal-engine?lang=en-US).

Hedef 30 FPS / yaklaşık 33.3 ms frame bütçesidir; kabul edilmiş ölçüm değildir.
5 dakika boşta, kısa sürüş ve 10–15 dakika daha uzun koşuda ayrı değer al.
Ekran kaydı yapılıyorsa kayıt yükünü belirt; temel benchmark'ı kayıtsız da yap.

## 8. Gerçek LiDAR/depth akışı ve kısa görev

GNC/başka bridge varsa aynı portları kullanan süreçleri durdur. ROS'suz
servisi **önce**, Play'i **sonra** başlat:

```powershell
.\.venv\Scripts\python.exe -m mars_rover.nav_service --sensors Saved/Mars/fulltest02-sensors.json
```

Tarayıcıda `http://127.0.0.1:8766` aç, sonra UE'de Play. İlk fizik yerleşmesini
bekle; otomatik en az 2 s kararlılık penceresi aranır. Gerekirse toplam
yerleşme daha uzun sürebilir. İlk test varsayılan **ground_truth** depth ile.

Kontrol edilecekler:

- `http://127.0.0.1:8765/status`: bağlı rover ve taze ham telemetri;
- ham telemetride `x,y,z,roll,pitch,yaw,t_ns`; tam zaman yoksa hareket etmez;
- `http://127.0.0.1:8766/mission/snapshot`: `pose_fresh`, string nanosaniye,
  ilerleyen capture clock, `lidar` ve `ground_truth` health;
- Unreal log'unda **etkin `UnrealLidarCam: GPU`**; yalnız config'te GPU yazması
  yetmez, eklenti setup başarısızsa CPU'ya dönebilir;
- kamera render/float depth ve LiDAR'dan harita içinde sonlu dönüşler.

`valid_inside_points >= 20` ve taze paketler yalnız temel akış/koordinat
kontrolüdür; doğru mesafe ölçümü veya tüm çukur görünürlüğü kanıtı değildir.
LiDAR Draw Points yalnız debug için ayrı koşuda açılabilir; performans
karşılaştırmasını debug çizimi kapalıyken de yap.

Başlangıç (126,126) civarında açık bir hedef için ilk kısa deneme **(136,126)**
olabilir. Hücre kapalı görünürse açık yakın nokta seç; UI bloke hedefi kabul
etmemelidir. 0.15 m/s ile 10 m'nin ideal süresi yaklaşık 67 s; dönüş ve
bekleme süreleri buna eklenir. İlk testte uzun rota verme.

| Test | Beklenen sonuç |
|---|---|
| Açık hedefe git | Başlangıç yönü doğru, fizik stabil, rota takip ediliyor |
| Hedefte varış | `arrived`, ardından sıfır dört teker komutu; 0.25 m hedef toleransı |
| Panel Durdur | Görev kapanır, motor komutları sıfır olur |
| Yeni Play | Önceki hedef otomatik sürdürülmez |
| Manuel komut | Aktif otonom hedef iptal edilir; komutlanan m/s ile raw wire değerleri farklı alanlarda |
| Idle / varış sonrası hareket | Canlı poz ilerler; kapalı görev kaydı değişmez |
| Kapsam dışı / kapalı hedef | Kabul edilmez; hedef başka yere sessizce taşınmaz |

## 9. Kontrollü hata, engel ve stereo testleri

**Engel:** Ayrı bir test seviyesinde, rotayı kesecek görünür collision'lı
sentetik kutu hazırla. Test nesnesini gerçek Mars taşı diye kaydetme. Motor ve
rover constraint'lerini Play sırasında değiştirme. Engel sensör görüşüne
girdiğinde önce duruş, ardından yeni plan sürümü veya gerekçeli `blocked`
beklenir. Sensörün kutuyu gördüğü kanıtlanmadan çevresinden geçmesi sensör
başarısı sayılmaz.

**Sensör kaybı:** Önce yalnız duruş testi için düşük hızlı kısa görev kullan.
Kameranın/streamer'ın bağlantısını kontrollü kes veya duraklat; yeni komut
sıfıra dönmeli. Mevcut eşikler sensör varış/capture yaşı 0.4 s ve poz yaşı
0.3 s'dir. Motor/servis işlemini zorla öldürmek bunun eşdeğeri değildir;
bağımsız UE motor watchdog'u henüz yoktur. Olağan durdurma için paneli kullan,
test takılırsa Play'i bitir.

**Stereo:** Play'i bitir, varsayılan servisi normal kapat. Ayrı koşuda:

```powershell
.\.venv\Scripts\python.exe -m mars_rover.nav_service --sensors Saved/Mars/fulltest02-sensors.json --depth-source stereo
```

Sonra yeniden Play ve **yeni hedef**. Bu sefer `depth_source=stereo` görülmeli.
Doku/gölge/örtüşme nedeniyle yeterli güvenilir nokta yoksa durması beklenebilir;
ground truth başarı sonucu stereo sonucu yerine yazılmaz. Önce stationary
ground-truth koşusu, sonra stereo koşusu raporlanır.

**Niceliksel sensör kalibrasyonu:** Bunu ayrıca ölçmeden tam sensör doğruluğu
satırını PASS yapma. Yeni bir QA sahnesinde bilinen düzlem/kutu boyutları,
optik eksene uzaklık ve sensörün tam capture pozu kaydedilerek depth ve LiDAR
karşılaştırılmalı. Depth **kamera ekseni cm**, decoder çıktısı metre;
LiDAR verisi sensör FLU metre/range geometrisidir. Birbirinin sayısını
doğrudan eşitlemek doğru değildir. Mevcut CLI bunu otomatik kabul testine
dönüştürmez; native frame/point kayıtları ve kalibrasyon raporu henüz ayrı
çalışma gerektirir. Sahne açılması veya health sayısı bu satırı kapatmaz.

## 10. Mevcut kamera smoke testi ve henüz olmayan testler

Eski editör kameraları manuel denenebilir; Play sürerken Output Log → Python:

```python
import rover_cameras as rc
rc.top(height=30, heading_up=False)
rc.orbit(radius=6, height=3)
rc.follow()
```

Her komutu ayrı dene, görünümü ve rover'ın hareketini gözle. Bu, mevcut
follow/orbit/top helper'ının smoke testidir. Yeni ortak runtime kamera
yöneticisi, MRO katmanlı adaptif geçiş, rover ekranından native hedef seçimi,
100 geçiş testi ve paketli yeni arayüz **henüz uygulanmadığı için N/A**.
N/A satırları başarılı gibi raporlanmaz; yeni özellik PR'larında test edilecek.

## 11. Geçmişi ve kanıtları kaydetme

Servis çalışırken repo kökünde:

```powershell
Invoke-WebRequest http://127.0.0.1:8766/mission/snapshot -OutFile Saved/Mars/fulltest01-snapshot.json
Invoke-WebRequest http://127.0.0.1:8766/mission/export -OutFile Saved/Mars/fulltest01-history.json
git rev-parse HEAD
```

Snapshot/export dosyaları ve aşağıdaki kanıtlar birlikte saklanmalı:

- UE tam sürümü, GPU modeli/VRAM, sürücü, CPU/RAM, Windows build;
- VS/MSVC/SDK ve dış Python sürümü; test edilen Git commit;
- `Saved/Mars/acceptance_*.json`, `editor_*.log`, `fulltest01-import.json`,
  sensör config'i, snapshot ve history;
- `Saved/Logs/` ilgili editor log'u; varsa `Saved/Crashes/`;
- simulation ve orbital reference ekranları; stat unit/GPU ekranı;
- kısa hedefli sürüş, durdurma, engel/replan ve yeni Play için kısa video;
- test başına PASS / FAIL / PENDING / N/A, beklenen–gözlenen sonuç.

Geçmiş bellektedir; **export servis kapanmadan** alınır. Varsayılan limitler
4096 iz noktası/8 görev/256 olay/16 plan; `truncated` ve silinen kayıt
sayılarını kontrol et. Uzun koşuda tam kayıt gerektiğinde ara export al;
otomatik kalıcı günlük varmış gibi davranma.

## 12. Test kapanışı ve merge kapısı

| Grup | Kapanış koşulu |
|---|---|
| Python/CI | 154 test + lint + dört rota raporu başarılı; güncel CI'yı kontrol et |
| Native import/collision | Her iki modda saved + verified raporları |
| GPU görünüm | Gerçek DX12/SM6 adaptörü, shader/asset hatası yok, ekran kanıtı |
| GPU LiDAR / depth | Etkin GPU modu ve taze gerçek paketler; niceliksel kalibrasyon ayrı kaydedilmiş |
| Rover ve görev | Kısa rota, hedefte duruş, stop, yeni Play ve arşiv senaryoları başarılı |
| Performans | Donanım/profil/süre belirtilmiş, hata ve stale olaylarıyla birlikte frame süreleri raporlanmış |
| Gelecek kamera/arayüz | Şimdilik N/A; bu özellik teslim edildiğinde native kabul gerekir |

Ölçülmeyen zorunlu satır **PENDING** kalır. İlk native koşu derleme veya Unreal
Python API sorunu çıkarırsa bu bir test bulgusudur: log ve rapor üzerinden
düzeltme yapılır, başarısız adım yeniden koşulur. `verified` alanları elle true
yapılmaz. Mevcut PR'ların native kapsamı kabul edildiğinde #2 → #1 dalı → main
sırası uygulanabilir; gelecek kamera işlerinin şimdiden tamamlanmış olması
gerekmez ama mevcut kodda çalışıyor diye iddia edilen özellikler doğrulanmalıdır.
