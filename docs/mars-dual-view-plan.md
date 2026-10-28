# Uydu–rover görev görünümü: inceleme ve geliştirme planı

**Tarih:** 28 Ekim 2026, Türkiye. **Durum:** tasarım ve geliştirme planı;
aşağıda önerilen yeni kamera, ekran seçimi ve görev kaydı henüz uygulanmadı.
Bu belge mevcut çalışan Python temelini yeni özellikmiş gibi sunmaz.

İncelenen [PR #1](https://github.com/Poyqraz/MARE-Lunar-Simulator/pull/1):
`b3c27ccb8baca3c72ff039b77f0c65774e856210`, içerik ağacı
`154485d8d3cf5f4d657c09f212b9ac59d9e000f0`. Fork'ta açık tek PR budur;
taslaktır ve birleştirilmemiştir. Bu sürümde 112 Python testi yerelde tekrar
geçti. [Windows/Linux CI](https://github.com/Poyqraz/MARE-Lunar-Simulator/actions/runs/40739224113)
başarılıdır. Native UE 5.7/GPU kabulü yapılmamıştır.

## 1. Ürün yorumu ve önerilen deneyim

İstenen özellik, aynı görevi iki bakış açısından yürütmektir. Uydu görünümü
genel operasyonu; rover görünümü yakın çevreyi ve hedef seçimini destekler.
Rover bir hedefe ilerlerken operatör görüntüyü değiştirebilir. Görev, hedef,
planlanan rota, gerçek geçilen iz ve telemetri aynı oturuma bağlı kalır.
Kamera değiştirmek yeni Play, yeni rover, yeni bağlantı veya yeni görev üretmez.

Önerilen akış:

1. Rover görünümünde arazideki bir noktaya tıklanır. Yüzeye vurulan nokta
   işaretlenir; uygunluk ve harita kapsamı önizlemede gösterilir.
2. Operatör **Hedefe git** ile görevi başlatır. İşaretleme ile görevi yürütme
   ayrı eylemlerdir; bir noktaya bakmak mevcut görevi değiştirmez.
3. **Uydu** düğmesi, kamerayı kontrollü bir hareketle yukarı taşır. Görev ve
   sensörler çalışmayı sürdürür. Geçiş sırasında yeni yüzey seçimi kapalıdır.
4. Genel görünüm başlangıç işaretini, gerçek geçilen izi, güncel rover'ı,
   kalan planı, hedefi ve yeniden planlanan kısmı birlikte gösterir.
5. Operatör pan/zoom yapabilir; **Rover'ı takip et** ve **Görevi çerçevele**
   komutlarıyla otomatik kadraja geri dönebilir. Manuel pan otomatik kadrajı
   geçici olarak bırakır; kamera kullanıcının hareketiyle mücadele etmez.
6. **Rover** düğmesi yakın bakışa döner. Görev kimliği ve hedef değişmez.

| Ana görünüm | Temsil | Etkileşim |
|---|---|---|
| Uydu | Varsayılan kayıtlı MRO/HiRISE haritası + canlı simülasyon katmanları; seçilebilir canlı UE üstten 3B görünümü | Hedef seçme, görev sınırı, rota karşılaştırma, mesafe/eğim sorgusu, pan/zoom |
| Rover | Ayrı operatör kamerası ile birinci şahıs; isteğe bağlı arkadan takip | Yakın yüzeyden hedef seçme, hedef yönü, kalan mesafe, durum paneli ve küçük harita |
| Sensör incelemesi | İki görünümde de açılabilen ayrı navcam/depth/LiDAR paneli | Gerçek sensör akışını, zamanını ve veri kaynağını inceleme |

Operatör kamerası sensörün montaj yerinden bakabilir; navcam'in ölçüm kamerası
ayrı kalır. Operatörün yakınlaştırması sensör FOV'unu, montajını, pozlamasını,
örnekleme hızını veya veri üretimini değiştirmeyecek.

## 2. Uydu kaynağı: MRO, Viking ve diğer seçenekler

MRO, NASA'nın aktif görev listesinde yer alıyor; 2005'te fırlatıldı, 2006'da
Mars yörüngesine girdi [S1]. En yeni görev olması yerine, bu iş için görüntü
ayrıntısı ve DEM ile eşkayıt esas alınmalı. Daha sonra yörüngeye giren TGO'nun
CaSSIS verisi de vardır; nominal ölçeği yaklaşık 4.5 m/pikseldir [S5].

| Kaynak / ürün | İlgili ölçek | Bu projedeki karar |
|---|---|---|
| MRO HiRISE | Tipik yer örneklemesi 25–32 cm/piksel [S2] | Yakın ölçekli operasyon haritası için ilk tercih; kapsama ve eşkayıt kontrolü gerekir |
| MRO CTX | Nominal yaklaşık 6 m/piksel [S3] | İleride çevre/kilometre ölçeğinde bağlam; küçük engel yüksekliği vermez |
| Viking MDIM 2.1 global mozaiği | Ekvator yakınında yaklaşık 231 m/piksel [S4] | Bölgesel/global bağlam; yerel hedefin metre doğruluğunda seçimine uygun değil |
| TGO CaSSIS | Nominal yaklaşık 4.5 m/piksel; renk/stereo [S5] | Bölgesel karşılaştırma için aday; mevcut yerel HiRISE'nin yerine sırf daha yeni araç diye konmaz |

Bu ölçekler belirli ürünlerin örnekleme aralığıdır; bütün Viking karelerinin
veya bütün Mars ürünlerinin tek çözünürlükte olduğu iddiası değildir.
HiRISE yüksek ayrıntılı görüntü de küçük taşın 3B yüksekliğini tek başına vermez.
DTM post aralığı genellikle görüntü pikselinden daha büyüktür [S6].

Mevcut paket zaten **MRO/HiRISE** kullanıyor: `ESP_045994_1985` görüntüsü
19 Mayıs 2016'da çekilmiş; katalogdaki projeksiyon ölçeği 25 cm/pikseldir [S7].
Paketteki USGS türev ürünün yayım tarihi 24 Temmuz 2020'dir. Görüntü edinim,
türev ürün yayım ve dosya indirme tarihleri farklı alanlar olarak tutulmalı.
Şu anki yerel kesit 252 × 252 m, DEM 1 m post aralıklı, kayıtlı PNG 1024²'dir.
Kapsam dışı hedef kabul edilmeyecek; çevreye uydurma arazi eklenmeyecek.

Ekrandaki canlı katman **simülatör telemetrisi** olacak. Harita MRO arşiv
ürünüdür; uydunun rover'ı kesintisiz canlı videoyla izlediği söylenmeyecek.
Gerçek yörünge geçişi, sensör taraması, gözlem zamanı ve haberleşme gecikmesini
modelleyen bir MRO gözlem simülasyonu ayrı bir ileri aşamadır.

## 3. Mevcut PR'ın entegrasyon incelemesi

Aşağıdaki bulgular doğrudan belirtilen sürümün kaynak kodundan çıkarıldı.
Yeni görünüm özelliğinin engelleridir; 112 testin bu özelliği zaten doğruladığı
anlamına gelmez.

| Kimlik / öncelik | Kaynak ve bulgu | Gerekli değişiklik |
|---|---|---|
| R1 / P0 | `navigation.py::step`, hedef yoksa veya görev terminal durumdaysa poz güncellemesinden önce dönüyor | Telemetri/gözlem güncellemesini görev kontrolünden ayır; idle, manuel ve varış sonrası konum da güncellensin |
| R2 / P0 | `nav_service.py` içindeki `/map` cevabı JSON hazırlama ve HTTP yazmasını `session.lock` altında yapıyor | Haritanın tutarlı kopyasını kısa kilitte al, kodlama/ağ yazmasını dışarı taşı; yavaş istemcinin kontrol döngüsünü geciktirme riski giderilsin. Gecikmenin büyüklüğü henüz ölçülmedi |
| R3 / P0 | `NavigationSession` başlangıç/gerçek geçilen iz/kalıcı görev kimliği saklamıyor; `RouteFollower.index` dışarı verilmemiş | Ortak görev modeli, plan sürümleri ve gerçek poz örneklerinden yol izi ekle; planı geçilen yol gibi çizme |
| R4 / P0 | `rover_cameras.py` takip/orbit/top geçişleri yapıyor; dashboard bağlantısı `5001/viewport_camera` için, yeni servis `8766` kullanıyor | Tek kamera sahibi belirle; yeni istemci ve eski GNC kamera bağlantısının aynı viewport'u yönetmesini önle |
| R5 / P1 | `top()` varsayılanı rover üstünde 8 m'de perspektif kamera; `follow()` rover'ın etkin kamerasına dönüyor | Bunları gerçek uydu haritası veya ham navcam yayını diye adlandırma; görev kadrajı ve açık görüntü türleri ekle |
| R6 / P0 | `mars_materials.py` ve `mars_scene.py` içindeki `simulation` / `orbital_reference` ayrı seviye kurulum modları | Görünüm düğmesinden seviye/malzeme/ışık değiştirme; bu işlem sensör RGB girdisini de değiştirir |
| R7 / P1 | Mevcut `/status` rota/konum/hedef/sensör özeti, HTML ise 2B harita sunuyor; canlı kamera HTTP çıktısı ve ekran-ışın seçimi yok | Frame deposu, görüntü metadata'sı, seçimin koordinat sözleşmesi ve yeni görünüm UI'si gerekli |
| R8 / P1 | `bridge.status` ham poz ve `wire_command` verir. `drive.py` teker hızını negatif ölçekle wire komutuna çevirir | Komutlanan m/s ile wire değerini ve ölçülmüş motor hızını ayır; wire sayısını RPM diye gösterme |
| R9 / P1 | Sensör dışa aktarımı depth ve stereo kimliklerini içerir; merkez RGB kimliği ayrıca kaydedilmez | RGB akışı gösterilecekse gerçek `center_cam_id` ve ilgili kalibrasyon da dışa aktarılmalı; varsayılan 0 tahmin edilmemeli |
| R10 / P0 | Python kameraları editor/PIE tick'ine bağlıdır; proje kökünde runtime oyun C++ modülü yoktur | Kalıcı oyun benzeri özellik için bağımsız küçük UE runtime eklentisi; editor kodu yalnız prototip/kaynak referansı |

Kullanılacak mevcut parçalar: gerçek DEM/manifest/hash, Mars dönüşümü,
`TerrainMap`, `RouteFollower`, LIDR/NAVF çözücüleri, pose history, motor
köprüsü, hedef doğrulama ve mevcut native collision kabul araçları.
Mevcut ROS'suz kontrol korunur; ROS entegrasyonu bu özellik için önkoşul değildir.

## 4. Ortak görev kaydı ve telemetri

Önerilen `MissionSession` sunucudaki tek görev kaydıdır. Görünümler bu kaydın
istemcileri olur; kendi rota/hedef kopyalarını kontrol otoritesine dönüştürmez.
İzleme her yeni geçerli telemetride çalışır; hareket kararı ayrı 20 Hz döngüdedir.

| Alan | Anlam / üretim |
|---|---|
| `session_id`, `mission_id`, `goal_revision` | Play oturumu, görev ve onaylanmış hedef sürümü; yeni kamera modu bunları değiştirmez |
| `terrain_manifest_sha256`, `frame_id` | Kullanılan arazi ve yerel koordinat tanımı; eski haritalı istek reddedilir |
| `start_pose`, `goal`, `initial_plan` | Görevin ilk başlangıcı, onaylanmış hedefi ve başlangıç planı |
| `active_plan`, `plan_revision`, `progress_index` | Güncel plan ve izleme ilerlemesi; yeniden planlanınca yeni sürüm |
| `actual_trail` | Yalnız gerçek geçerli telemetri pozları; kamera hareketinden veya plan noktalarından üretilmez |
| `pose`, `attitude`, `speed_estimate` | Simülasyon poz/roll/pitch/yaw; hız poz farkından türetiliyorsa açıkça tahmin etiketi |
| `wheel_command_m_s`, `wire_command` | Komutlanan dört çevresel hız ve ayrı ham motor iletim değeri |
| `sensor_health`, `capture_age`, `snapshot_age` | Seçilen depth kaynağı, akışın tazeliği, sonlu nokta sayıları ve panelin güncelliği |
| `remaining_route_m`, `travelled_m`, `status`, `events` | Rota boyunca kalan mesafe, gerçek iz mesafesi, görev durumu ve dur/yeniden planlama nedenleri |

Batarya, akım, sıcaklık, tork ve gerçek motor RPM'i mevcut protokolde
doğrulanmış kanallar değildir. Veri yoksa `null` / **veri yok** gösterilir.
Tahmini varış süresi, planlanan hızla hesaplanan bir tahmin olarak etiketlenir;
toprak/kayma veya enerji modeli varmış gibi sunulmaz.

Zaman damgaları epoch nanosaniye için JSON'da **string** taşınır; JavaScript
`Number` hassasiyetiyle tam sayı kimliği kaybedilmez. `snapshot_seq` gibi küçük
sıralama değerleri ayrı sayıdır. Simülasyon zamanı ve panelin duvar saatiyle
ölçülen veri yaşı ayrılır; pause sırasında gerçekte ilerleme kaydedilmez.
Geri giden saat, yeni Play veya teleport izde kesinti yaratır; iki uzak nokta
kesintisiz sürülmüş gibi birleştirilmez.

İz 5 Hz üst sınırla ve mesafe/yön eşiğiyle örneklenebilir; bu değerler deney
ayarlarıdır. Bellek ve çizim sınırları tanımlanır; uzun oturumlarda parçalı
JSONL/SQLite kayıt ayrı yazıcıyla yapılır. Kontrol döngüsü diski beklemez.
Özetlenmiş çizim gerçek kayıt yerine geçmez. Durdurulan/bitirilen görevin izi
arşivlenir; aktif motor hedefinin silinmesi geçmişi silmez.

## 5. Unreal kamera ve görüntü mimarisi

Kalıcı çözüm olarak önerilen yeni `MarsMissionControl` runtime eklentisi;
görsel kamera rig'i, giriş/seçim ve HUD katmanını içerir. Küçük bağımsız bir
eklenti, mevcut Blueprint rover'ının fizik grafiğini değiştirmeden kurulabilir.
Önce PIE, ardından paketlenmiş uygulama kabul edilir. Şu an eklenti yoktur.

`PlayerController` rover'ı sürmeye devam eder; kamera için başka pawn possess
edilmez. Mevcut `SetViewTargetWithBlend` yaklaşımı [S8] ve kamera yerleştirme
mantığı referans alınır. Yeni rig ana oyun thread'inde kamerayı yönetir;
HTTP yanıtları asenkron alınır. Kameralar rover'ın fizik bileşenleri dışında
yaşar; kamera geçişinde constraint, kütle, teker veya sensör montajına dokunulmaz.

Görünüm durumu `rover`, `transitioning`, `orbital` olarak tutulur. İstenen ve
gerçekte uygulanmış görünüm ayrı alanlardır. Native onay gelmeden düğme
başarılı geçiş göstermeyecek. Eski `rover_cameras` dashboard tick'i, yeni rig'in
sahip olduğu Mars dünyasında kamera otoritesini bırakmalı; Ay seviyesinin eski
akışı bu opt-in özellikten etkilenmemeli.

Geçiş için başlangıç hedefi **1.5 s**'dir; ölçülmüş performans garantisi değildir.
Kamera önce araziye çarpmayacağı yüksekliğe çıkar, sonra nadir/genel kadraja
yerleşir. Tek doğrusal blend'in yamaçtan geçmesi engellenir. Hızlı art arda
isteklerde son istek uygulanır; hareket güncel kamera pozundan sürer.

Uydu görünümünün iki temsili açıkça seçilebilir:

- **MRO haritası:** HUD/harita katmanında gerçek kayıtlı PNG, üzerine canlı
  rover simgesi ve görev katmanları. Yakınlaştırma görüntüde yeni ayrıntı üretmez.
- **Canlı 3B üstten:** Aynı simülasyon dünyasının bağımsız operatör kamerası.
  Arazi ölçülmüş geometriyi, yüzey malzemesi mevcut temsili görünümü taşır.

Oyun benzeri geçiş, 3B kamera yükselişinin sonunda kayıtlı haritaya kontrollü
fade ile tamamlanabilir. Bu iki temsilin piksel piksel aynı fotoğraf olduğu
iddia edilmez; işaretler her birinin kendi projeksiyonuyla aynı dünya noktasına
çizilir. MRO görünümü için dünya malzemesi, güneşi veya sensör SceneCapture
ayarları değiştirilmez. Böylece görünüm seçimi stereo deneyinin girdisini bozmaz.

252 m kesitte operasyon kadrajı onlarca/yüzlerce metre sanal yükseklikte olur;
bu değer MRO'nun fiziksel yörünge irtifası değildir. Kadraj hedef/rover/kalan
rotanın sınır kutusu, ekran oranı ve güvenlik payından hesaplanır. Harita dışı
alan **veri kapsamı dışında** görünür. Bütün Mars'a çıkış v1'e dahil değildir.

## 6. Her iki görünümden hedef seçimi

Yerel koordinatlar `x=doğu, y=kuzey, z=yukarı` metredir. UE dönüşümü
`(-x,y,z)*100 cm`; harita UV'si `u=x/252`, `v=1-y/252` olarak aynı manifestten
hesaplanır. Sabit ekran boyutu veya varsayılan en/boy oranı kullanılmaz.

**Uydu haritası:** İmleç koordinatı önce gerçek çizim dikdörtgenine, sonra
harita metrelerine çevrilir. Pan, zoom, letterbox ve HiDPI hesaba katılır.
Kapsam, no-go/footprint ve geçilebilirlik önizlenir. Tıklanan hedef sessizce
başka bir hücreye taşınmaz.

**Native rover/üstten 3B:** Etkin kameranın projeksiyonu ile ekran noktası dünya
ışınına çevrilir [S9]. Bu ışın doğru dünya ve collision kanalında araziye
vurmalıdır. Gökyüzü, HUD, rover gövdesi, sensör debug çizimi veya desteklenmeyen
nesne seçilmez. Arazi arkasındaki hedef görülüyormuş gibi oluşturulmaz.
Yatay düzlem varsayımıyla uzak mesafe tahmini yapılmaz. Native seçim simülasyonun
dünya/collision bilgisini kullanır; sensörle keşfedilmiş bir hedef diye etiketlenmez.

**Web navcam görüntüsü:** Ayrı sonraki teslimdir. RGB kare, capture zamanı,
kamera kimliği, intrinsics, montaj ve eşleşen depth gerekir. Aynı merkez
kameranın ground-truth depth'i ile sol stereo çıktısı karıştırılmaz. Bayat veya
depth'i olmayan pikselden uydurma hedef çıkmaz. Küçültülmüş/letterbox görüntü
pikseli özgün render target pikseline doğru çevrilir; şimdiki poz eski kareye
uygulanmaz. V1 native seçim, bu web görüntüsü seçimi hazırmış gibi sunulmaz.

Önizleme salt okunur; onaylı hedef değişimi atomiktir. Yeni API isteği oturum,
harita hash'i, harita sürümü ve benzersiz istek kimliğini taşır. Eski oturumdan
geç gelen veya yinelenen istek yeni görevi yanlışlıkla başlatamaz. Mevcut basit
`/goal` ve motor istemcisi korunur; zengin sözleşme ayrı yol kullanır.

## 7. Katmanlar, parametreler ve adaptif davranış

| Katman | Gösterim | Doğruluk kuralı |
|---|---|---|
| Başlangıç | Sabit başlangıç işareti | Yeniden planlanınca rover'ın yeni konumuna taşınmaz |
| Gerçek geçilen iz | Mavi sürekli parçalar | Telemetri boşluğunda kesilir; enterpolasyonlu ekran animasyonu kayda eklenmez |
| İlk plan | Açılıp kapanan gri kesikli çizgi | Gerçek sürülmüş yol değildir |
| Güncel kalan plan | Sarı/yeşil çizgi ve hedef işareti | Plan sürümü ve takip ilerlemesinden çıkarılır |
| Yeniden planlama | Eski plan soluk, yeni bölüm vurgulu | Neden ve simülasyon zamanı olay kaydında saklanır |
| Engel/eğim | Seçilebilir harita kaplama katmanı | Footprint ile genişletilmiş kapalı alan, ham engel ve eğim farklı lejantlarla sunulur |
| Sensör gözlemi | Son geçerli noktalar ve tazelik | Nominal görüş konisi tüm alanın gözlendiği veya güvenli olduğu anlamına gelmez |

Panelde görev durumu, yerel/Mars koordinatı, heading/roll/pitch, komutlanan dört
teker hızı, türetilmiş ilerleme hızı, kalan rota mesafesi, geçen simülasyon
süresi, sensör sağlığı ve yeniden planlama nedeni bulunur. Harita verisinin
kaynağı/tarihi ve pozun simülasyon telemetrisi olduğu görünür tutulur.
Ham LiDAR/depth bindirmeleri operatör seçimine bağlıdır; varsayılan görünümü
noktalarla kapatmaz. Yeniden planlama ve duruş olayları katman gizliyken de
görev durumunda görünür.

Adaptif davranışların kapsamı:

- Kadraj, kalan rota ve hedefe göre büyür/küçülür; değişimler yumuşatılır.
  Manuel pan/zoom'dan sonra otomatik takip ancak kullanıcı komutuyla geri gelir.
- Uzak görünümde rover simgesi ve çizgiler okunabilir piksel boyutunda kalır;
  simge boyutu gerçek araç boyu ölçümü olarak yorumlanmaz. Ölçek çubuğu sabittir.
- Haritada zoom artınca veri gerçek çözünürlüğüyle sınırlanır. Daha küçük DEM
  hücresine örnekleme yaparak teker ölçeği ayrıntı varmış gibi gösterilmez.
- GPU/CPU yüküne göre yalnız operatör panelinin örnekleme/çizim ayrıntısı,
  iz çizimi ve isteğe bağlı görünüm kalitesi ayarlanır. Bilimsel sensör
  çözünürlüğü, FOV'u, SendHz'i veya kontrol frekansı otomatik düşürülmez.
- Veri eskidiğinde rover işareti bayat etiketiyle gösterilir; hareket ediyormuş
  gibi tahmin sürdürülmez. Görünüm bağlantısının kopması yeni hedef yaratmaz.
- HUD düğmeleri kamerayı döndürme ve arazide hedef seçme hareketlerinden ayrılır;
  UI tıklaması zemine geçmez. Pan/drag hareketi hedef tıklaması sayılmaz.

## 8. API, istemciler ve performans sınırları

İlk sürümde Python localhost servisi görev ve kontrol kaynağıdır; Unreal rig'i
görüntü ve native ekran seçiminin kaynağıdır. Web paneli aynı API'yi kullanır.
Mevcut portlar ve motor/sensör bağlantıları korunur. Yeni yollar aşağıdaki
**önerilerdir; bugün çalışan endpoint listesi değildir**.

| Önerilen yol | Amaç |
|---|---|
| `GET /mission/snapshot` | Tutarlı küçük görev/poz/parametre/plan-sürümü özeti |
| `GET /mission/trail?after_seq=...` | Son alınandan sonraki gerçek iz parçaları ve kesinti işaretleri |
| `GET /mission/events?after_seq=...` | Başlat, durdur, varış, engel, yeniden planla ve bağlantı olayları |
| `POST /mission/goals/preview` | Harita ve oturumla ilişkili, görevi değiştirmeyen hedef önizlemesi |
| `POST /mission/goals` | İstek kimliği ve sürüm kontrolüyle onaylı hedef değişimi |
| `GET /view/state`, `POST /view/request` | İstenen/uygulanmış görünüm ve tek viewport sahibinin komutları |
| `POST /view/ack` | Unreal'ın uyguladığı görünümü ve kamera sürümünü bildirmesi |
| `GET /frames/...` | Bounded frame deposundan navcam görüntüsü ve capture metadata'sı |

Eski `/status`, `/goal`, `/stop` ve motor `8765` API'si uyumlu kalmalı. Motor
API'sinin manuel komutla aktif hedefi iptal etme davranışı korunur; görüntü
istekleri motor komutu sayılmaz. Stop düğmesi, komutun alındığını ve gözlenen
durumu ayrı gösterir; cevapsız HTTP isteği başarılı duruş diye boyanmaz.

Görev özeti başlangıçta en çok 5 Hz alınır; Unreal kamerası kendi render
döngüsünde hareket eder. 64.009 hücreli harita yalnız `map_revision`
değiştiğinde/cached olarak aktarılır; her telemetri tick'inde tekrar gönderilmez.
Snapshot kopyası kısa kilitte alınır; JSON, görüntü sıkıştırma ve soket yazması
kontrol kilidinin dışında olur. Büyük trail olayları parçalanır; bağlantı,
payload ve kuyruk sınırları tanımlanır. Yalnız son kamera karesini tutmak,
geçmiş kareleri sınırsız biriktirmekten daha uygundur.

İlk ölçüm hedefleri: tanımlanmış yerel donanımda 1080p/30 FPS, panel telemetri
gecikmesi p95 ≤500 ms ve kontrollü kamera geçişi. Bunlar tasarım hedefidir;
ölçülmüş sonuç değildir. Kontrolün mevcut 20 Hz ve veri tazeliği şartları
değiştirilmez. Rendering yükü bu şartları bozarsa UI kalite ayarı azaltılır
ve neden kaydedilir; sensör veya denetleyici sonucu gizlenmez.

## 9. Cesium ve tarayıcı yayını entegrasyonu

**Cesium:** Resmî Unreal rehberi Mars ve özel ellipsoid desteği sunuyor [S10].
Geniş alan/globe ve veri akışı için uygundur. Varsayılan WGS84 Dünya ayarı
kullanılamaz. Mevcut Jezero ürünümüz Mars küresi, yerel AEQD ve çıkarılmış Z
datumu kullanır; Cesium'un planet-fixed/yerel çerçevesine dönüşüm ayrıca
ölçülmelidir. IAU2015 preset'i seçmek, ürünün düşey referansını otomatik
eşleştirdiğini kanıtlamaz. En az beş kontrol noktası, yatay/düşey datum ve
örtüşme testi şarttır [S11]. Aynı yerde iki aktif collision yüzeyi oluşmamalı.
Yerel doğrulanmış fizik sahası değişmeden kalır. İlk teslim Cesium hesabı veya
internet olmadan çalışır; global bağlam ayrı opt-in aşamadır. Ion verisinin
varlığı, her yerde HiRISE ayrıntısı veya rover ölçeği mesh olduğu anlamına gelmez.

**Tek tarayıcı ekranında gerçek UE görüntüsü:** Pixel Streaming, Unreal'ın
ürettiği görüntüyü ve kullanıcı girdilerini WebRTC ile taşıyabilir [S12].
Kamera özelliği ve native seçim çalıştıktan sonra eklenmesi önerilir. İlk
yerel teslim, Unreal viewport'u + aynı görev servisine bağlı paneldir.
Pixel Streaming eklenmeden web HTML'sine bir düğme koymak, Unreal görüntüsünü
tarayıcıya getirmiş sayılmaz. Paketli uygulama yayını ayrıca denenir; editor
yayınının deneysel niteliği paketli runtime desteğiyle karıştırılmaz.

**Gerçek MRO geçişi:** Sonraki araştırma, SPICE yörünge/attitude ve gerçek
gözlem geometrisiyle belirli tarihteki taramayı yeniden oynatmak olabilir.
Bu, serbestçe pan/zoom yapılan operasyon kamerasından ayrı bir deneydir.
V1 kapsamında gerçek zamanlı uydu haberleşmesi veya görev gecikmesi modeli yoktur.

## 10. Teslim sırası ve entegrasyon noktaları

Mevcut PR temel veri/navigasyon değişikliği olarak korunmalı. Native temel
kabulü beklerken aşağıdaki geliştirmeler ayrı feature dalında küçük PR'lara
bölünmeli. Temel PR henüz birleşmediyse ilk yeni PR onun dalını base alabilir;
bağımlılık açıkça yazılır. Bu planın eklenmesi işlevsel özelliklerin teslimi değildir.

| Aşama | Önerilen dosya/alan | Teslim ve geçiş ölçütü |
|---|---|---|
| A0 — temel kabul | Mevcut `unreal_check`, `mars_setup`, sensör düzlem deneyi | UE 5.7 plugin derlemesi, height readback, 520 collision sorgusu ve gerçek sensör montaj/zaman testi; native sürüş altyapısı bozuksa kamera özelliğine başarı etiketi verilmez |
| A1 — sürekli görev kaydı | Yeni `mars_rover/mission.py`; `navigation.py`, `nav_service.py`, `bridge.py` entegrasyonu | R1–R3 giderilir; idle/manual/arrived poz güncellenir, gerçek trail ve plan sürümleri korunur; kısa snapshot kilidi ve yavaş istemci testi |
| A2 — görünüm yöneticisi | Yeni `Plugins/MarsMissionControl/`; `mars_scene.py`, `mars_setup.py`, `rover_cameras.py` opt-in entegrasyonu | Tek runtime kamera sahibi; rover/üstten geçiş; görev/bağlantı kimliği ve sensör ayarları değişmez |
| A3 — hedef seçimi | Eklentinin pointer/picking bölümü, ortak dönüşüm fonksiyonları, hedef önizleme API'si | Harita ve native 3B rover ekranı aynı dünya hedefini üretir; yanlış dünya/eski istek/UI/sky tıklaması reddedilir |
| A4 — katmanlar ve panel | Yeni native HUD; `mission_control.html`, snapshot/trail/event API'si | Başlangıç, gerçek iz, ilk/kalan plan, hedef ve olaylar iki görünümde tutarlı; komut/ölçüm ayrımı; stale göstergesi |
| A5 — sensör paneli ve adaptif kalite | Yeni bounded frame deposu; `mars_sensor_setup.py` RGB metadata; kamera kadraj/panel ayarları | Aynı capture zamanlı görüntü bilgisi; per-view kalite; 30 FPS/5 Hz hedefleri donanım raporuyla ölçülür; bilimsel akış değişmez |
| A6 — uçtan uca kabul | Yeni native kabul senaryosu + Windows/Linux Python CI | Aynı görevi tamamlayarak tekrarlı geçiş, engelde yeniden planlama, durdurma, yeniden Play ve uzun oturum testleri |
| Sonraki genişleme | Cesium/global katman; Pixel Streaming; web görüntüsünden hedef | Düşey/yatay referans ve video/girdi koordinatları ayrıca kabul edilir; V1'in zorunlu bağımlılığı değildir |

Yeni dosya adları mimari öneridir; bu commit'te mevcut değiller. Her iş
paketinde veri sözleşmesi ve başarısızlık testi önce yazılır, en küçük çalışan
uygulama eklenir, sonra mevcut testlerle regresyon kontrolü yapılır. Bilinmeyen
native derleme/GPU süresine dayanarak kesin takvim taahhüdü verilmez.

## 11. TDD ve native kabul matrisi

| Senaryo | Önce yazılacak test / beklenen sonuç |
|---|---|
| Aktif görev yok, manuel sürüş var | Yeni poz ve trail görünür; izleme için hayali hedef gerekmez |
| Varış sonrası rover hareket ettiriliyor | Görev arşivi değişmez, güncel simülasyon pozisyonu güncellenir |
| 100 kez görünüm değişimi | `session_id`, `mission_id`, hedef ve sensör config hash sabit; yalnız view revision değişir |
| İki kamera istemcisi / hızlı düğme tekrarı | Tek sahibi ve son istek kuralı; eski onay yeni isteği geri alamaz |
| İlk plan sonrası yeni engel | Motor önce durur; yeni plan sürümü gelir; başlangıç ve gerçek iz değişmez |
| Harita north/east ve ekran köşeleri | Pan/zoom/aspect/HiDPI dahil bilinen kontrol noktaları doğru metreye döner |
| Rover ekranı yamaç, krater, farklı pitch | Native ışın gerçek yüzeye vurur; düzlem varsayımıyla hedef çıkmaz; round-trip toleransı ≤2 ekran pikseli deney hedefi |
| UI üstüne, göğe veya rover gövdesine tıklama | Önizleme reddedilir; mevcut görev ve motor hedefi değişmez |
| Geçiş anında tıklama | Kamera kararlı/onaylı olana kadar seçim yok; yanlış projeksiyonla hedef oluşmaz |
| Geç gelen/yinelenen hedef | Oturum/hash/revision/idempotency denetimi; eski görevi yeniden başlatmaz |
| Saat geri gidiyor, paket sırası bozuk, teleport | İzde açık kesinti; yanlış mesafe veya iki nokta arasında sahte sürüş yok |
| Navcam görüntüsü eski veya depth eşleşmiyor | Web görüntüsü seçimi reddedilir; güncel rover pozu eski kareye uygulanmaz |
| Yavaş harita istemcisi / büyük trail | Network/JSON kontrol kilidini tutmaz; kontrol döngüsü ve watchdog ölçülür |
| MRO haritası / 3B görünüm değişimi | Seviye, world materyali, güneş, navcam montaj/FOV/SendHz değişmez |
| LiDAR/kamera bağlantısı kopuyor | Mevcut duruş davranışı sürer; panel veri tazeliğini doğru gösterir |
| UI/görünüm kapanıyor | Hayali hedef veya manuel motor komutu oluşmaz; görev yalnız açık kontrol politikasıyla değişir |
| Yeni Play / servis yeniden başlama | Eski hareket hedefi otomatik sürdürülmez; geçmiş görev kaydı ayrı oturumdur |
| Bilinmeyen parametre | Batarya/RPM/sıcaklık için uydurma değer yerine veri yok |
| Uzun oturum / kayıt hatası | Bellek/çizim sınırları, iz parçaları ve kayıt durumu açık; kayıp parçalar gizlenmez |
| Paketli UE uygulaması | Editor Python olmadan kamera/HUD/picking çalışır; PIE testi bunu tek başına kanıtlamaz |

Saf Python görev/koordinat/API testleri Linux ve Windows CI'da koşar. C++
matematik/sözleşme ve kamera yaşam döngüsü testleri UE Automation/Functional
Test ile gerçek 5.7 kurulumu ister. Mock kamera nesnesi veya HTML görüntüsü,
native geçişin ve collision seçiminin kanıtı değildir. İki ekran pikseli hedefi
sayısal seçim/projeksiyon toleransıdır; DEM'in Mars gerçeğine doğruluğu değildir.

Asgari demo kaydı: rover görünümünden hedef seç → hareket et → uyduya geç →
başlangıç ve gerçek izi göster → yeni engelde yeni rota → rover'a dön → hedefte
dur. Aynı kayıtta görev kimliği, zamanlar, görünüm onayları ve sensör ayarları
bulunmalı. Native video/rapor olmadan bu özelliğe tamamlandı denmeyecek.

## 12. Kaynaklar ve sınırlar

Kaynaklar 28 Ekim 2026'da birincil kurum/ürün belgelerinden incelendi.
API belgeleri gerçek kurulumda derleme/çalıştırma yerine geçmez; Epic'in sürümsüz
bazı sayfaları bugün 5.8 gösteriyor, proje hedefi ise 5.7 olarak kalıyor.

- **S1:** [NASA MRO görev sayfası](https://science.nasa.gov/mission/mars-reconnaissance-orbiter/): aktif görev ve başlangıç tarihleri.
- **S2:** [NASA PDS HiRISE instrument context](https://pds.nasa.gov/ds-view/pds/viewContext.jsp?identifier=urn%3Anasa%3Apds%3Acontext%3Ainstrument%3Ahirise.mro&version=1.2): örnekleme ve stereo yeteneği.
- **S3:** [NASA MRO instruments](https://science.nasa.gov/mission/mars-reconnaissance-orbiter/science-instruments/): CTX ve HiRISE ölçekleri.
- **S4:** [USGS Viking MDIM 2.1 ürünü](https://astrogeology.usgs.gov/search/map/viking_mdim2_1_grayscale_global_mosaic_232m): belirli global mozaiğin çözünürlüğü ve koordinat bilgisi.
- **S5:** [ESA CaSSIS calibrated collection](https://esdcdoi.esac.esa.int/doi/html/data/planetary/EXOMARS-2016/em16_tgo_cas_calibrated.html): 4.5 m/piksel kamera; [TGO/CaSSIS araştırma ekibinin makalesi](https://isprs-archives.copernicus.org/articles/XLII-3-W1/133/2017/): 2016 yörünge girişi.
- **S6:** [HiRISE DTM açıklaması](https://www.uahirise.org/dtm/about.php): post aralığı, stereo ve artifact sınırları.
- **S7:** [ESP_045994_1985 gözlem kataloğu](https://www.uahirise.org/ESP_045994_1985): gerçek görüntü tarihi ve ölçeği. USGS türev ürün bilgisi repodaki `source_ortho.xml` dosyasındadır.
- **S8:** [Epic Set View Target with Blend](https://dev.epicgames.com/documentation/unreal-engine/BlueprintAPI/Game/Player/SetViewTargetwithBlend?lang=en-US): görüntü hedefi geçişi.
- **S9:** [Epic DeprojectScreenPositionToWorld](https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/APlayerController/DeprojectScreenPositionToWorld): ekran-dünya ışını.
- **S10:** [Cesium for Unreal Moon/Mars rehberi](https://cesium.com/learn/unreal/unreal-moon-mars/): Mars/özel ellipsoid ve veri akışı desteği.
- **S11:** [CesiumGeoreference API](https://cesium.com/learn/cesium-unreal/ref-doc/classACesiumGeoreference.html): gezegen merkezli ve yerel koordinat dönüşümleri.
- **S12:** [Epic UE 5.7 Pixel Streaming](https://dev.epicgames.com/documentation/en-us/unreal-engine/pixel-streaming-in-unreal-engine?application_version=5.7): tarayıcıda gerçek UE görüntüsü/girdi ve editor yayını ayrımı.

Bu plan topografik kaynak çözünürlüğünü yükseltmez. Küçük gerçek Mars taşları,
teker ölçekli çukurlar ve boşluklar için ölçülmüş daha ince mesh/veri hâlâ ayrı
gerekliliktir. Kum, batma ve çekiş bu aşamanın dışında kalır. Gerçek MRO canlı
videosu, SLAM konumu, uçuş yeterliliği veya kullanıcının CAD/motor kalibrasyonu
olduğu iddia edilmez.
