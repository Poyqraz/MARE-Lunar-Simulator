# Daha akıcı sürüş: kilit dışı derinlik işleme ve varsayılan yumuşak takip

Unreal sürüşlerinde rover kısa aralıklarla durup kalkıyordu. Kayıtlardan iki
ayrı neden ölçüldü:

1. **Zamanlama.** 640×480 GT derinlik karesi (~220 bin nokta) kontrol
   kilidinin içinde haritaya işleniyordu: medyan 94 ms, p90 125 ms. Kontrol
   periyodu 50 ms olduğu için turların %32'si 50 ms'yi aştı ve bazı kararlar
   süresi dolmuş veriye dayandı (`waiting_for_fresh_data`, sıfır komut).
2. **Geometri.** `RouteFollower` her ızgara köşesine ayrı ayrı yöneliyor ve
   yön hatası 14°'yi geçince durup yerinde dönüyordu. Komutlar 0 ile
   0,15 m/s arasında rampasız sıçrıyordu.

## Değişiklikler

**Kilit dışı derinlik ve LiDAR hazırlığı (her zaman açık).**

- `TerrainMap.observe` iki aşamaya ayrıldı:
  - `classify` saf bir işlemdir; yalnızca değişmeyen DEM'i okur.
  - Harita güncellemesi kısa ve kilit altındadır.
- Sensör kareleri, servise yayımlanmadan önce yakalama pozuyla dönüştürülüp
  sınıflandırılıyor. Sonuç kareyle aynı kilit bölümünde saklanıyor.
- `_consume` bu sonucu yalnızca aynı kare, aynı gözlem dönemi (epoch) ve aynı
  yakalama matrisi için kullanıyor. Aksi halde eskisi gibi tam işi kendisi
  yapıyor.
- GT işi iki iş parçacığına bölünüyor:
  - Kamera okuma iş parçacığı, eskisi gibi pozdan bağımsız projeksiyonu
    yapıyor (~65 ms).
  - Ayrı bir işçi yalnızca poza bağlı sınıflandırmayı yapıyor (medyan
    63–78 ms).
  - İşçide en yeni kare kazanıyor. Atlanan kareler
    `sensor_transport.camera.depth_frames_superseded` ile sayılıyor.
  - Varış zamanı okuma anında damgalanıyor; bekleme ve işleme süresi tazelik
    hesabına dahil.
  - Bir taşıma hatası bekleyen kareyi düşürüyor (nesil sayacı).
  - Sınıflandırma süresi sağlık raporunda `classification_s` olarak
    görünüyor.
- Eşikler, 8 m menzil, tazelik, CPU poz tutarlılık kontrolü ve harita
  sonucu değişmedi. `test_prepared_and_inline_observations_update_the_map_identically`
  iki yolun aynı haritayı verdiğini doğruluyor.

**Yumuşak takip (2026-11-24'ten beri varsayılan).** Aşağıdaki A/B sonuçlarından sonra
`SmoothRouteFollower` servisin varsayılan takipçisi oldu. Eski takipçiye dönmek için
`--classic-follow` kullanılır. `--smooth-follow` mevcut komutlar bozulmasın diye hâlâ
kabul ediliyor, ancak artık etkisi yok; iki bayrak birlikte verilemez.
`tools/mars_navigation_benchmark.py` de varsayılan takipçiyi kullanıyor.

`SmoothRouteFollower` şunları yapıyor:

- Izgara köşesi yerine rota üzerinde 0,7 m ilerideki noktaya yöneliyor
  (pure pursuit).
- Hızı yön hatası (`cos α`), eğrilik (dönüş hızı sınırı) ve son 0,6 m'de
  hedefe yaklaşma ile düşürüyor; alt sınır 0,05 m/s.
- Yalnızca 45°'nin üzerindeki yön hatalarında yerinde dönüyor; dönüşü 20°'ye
  inene kadar sürdürüyor.
- Hız artışlarını sınırlıyor: 0,25 m/s² ve 0,8 rad/s². Her düşüş ve
  oturumun verdiği her durdurma anında uygulanıyor.
- Komutlar arasında 0,2 s'den uzun boşluk olursa rampa sıfırdan başlıyor.

Oturumun güvenlik kapıları aynen duruyor: tazelik, şişirilmiş harita, 1 s'lik
yay kontrolü ve 0,25 m varış toleransı. Parametre isimleri Nav2
RegulatedPurePursuit'tan alındı.

## Upstream incelemesi (2026-11-24)

| Repo | Bulgular | Lisans |
|---|---|---|
| raulcastar/MARE-Lunar-Simulator `2c8195e` | MuJoCo köprüsü tekerlekleri doğrudan ayarlıyor, rampa yok; 1 s komut zaman aşımı. | MIT |
| URLab-Sim/UnrealRoboticsLab `efbc5e2` | Bacaklı robotlar için twist girişi; kaygan yönlü (skid-steer) yol takibiyle ilgili bir şey yok. | Apache-2.0 |
| GNC-Moon-Simulator `77cadaf` | Ayrıntılar aşağıda. | MIT |
| SpaceR-Raph-Rover-ROS2 `6b5722b` | Gerçek Raph Ackermann sürüşlü; rampa firmware'de, repoda yok. | MIT |

GNC-Moon-Simulator ayrıntıları:

- 10 Hz DWA kullanıyor (`local_planner.py`):
  - 4 m ileri bakış,
  - `max_speed·exp(-hata)` ile sürekli hız ölçekleme,
  - ivme penceresi,
  - 4,5 m'de yaklaşma yavaşlaması.
- Rover düğümünde asimetrik rampa var: 0,4 m/s², 1,0/1,5 rad/s².
- **Poz veya sensör yaşı kontrolü yok.** Bu nedenle o kısım
  kopyalanmadı.

Hiçbir repoda Nav2 yapılandırması bulunamadı. Unreal Blueprint tekerlek
mantığı ve RaphCore firmware'i incelenemedi.

## Native A/B (2026-11-24)

Koşullar her sürüşte aynıydı: seviye, geçici küp, CPU LiDAR, (126, 116) hedefi,
`--allow-replan`, sırası karıştırılmış sürüşler. Her sürüş için servis ve Play
yeniden başlatıldı. Taban, `b8145f8` kodunun scratchpad'e çıkarılmış hâliyle
çalıştırıldı. Değerler telemetriden ve görev kaydından ölçüldü. Tablodaki
bütün sürüşler hedefe vardı.

| Yapılandırma (sürüş) | Varış | Durma geçişi | 0,05 m/s altına düşüş | Pitch std | 50 ms aşan tur | Süresi dolmuş karar |
|---|---|---|---|---|---|---|
| Taban, klasik (b1, b2) | 91 / 97 s | 4 / 6 | 2 / 16 | 2,36 / 1,79° | %29 / %31 | 0 / 0 |
| Kilit dışı, klasik (o3, o4) | 91 / 88 s | 5 / 2 | 10 / 1 | 1,70 / 2,38° | 0 / 0 | 0 / 0 |
| Kilit dışı + `--smooth-follow` (s3, s4) | 89 / 94 s | **0 / 0** | 7 / 17 | **1,14 / 1,19°** | 0 / 0 | 1 / 0 |

Sonuçlar:

- **Dur-kalkı `--smooth-follow` gideriyor.** Durma geçişi 2–6'dan 0'a indi,
  pitch salınımı yaklaşık %40 azaldı. Birleşik tasarımdaki üç sürüş de aynı
  yöndeydi: 1, 0 ve 0 durma; pitch std 1,15–1,37°.
- **Kilit dışı işleme kontrol turlarının gecikmesini kaldırıyor** (%30 → 0,
  en uzun tur 94–141 ms → 16–31 ms). İki sürüşle durma sayısına net bir
  etkisi ayırt edilemiyor.
- Varış süreleri benzer (88–97 s), çünkü düz kesimlerdeki hız sınırı aynı
  (0,15 m/s).
- Rotadan en büyük sapma her yapılandırmada 0,09–0,14 m.
- Daha önceki tek taban sürüşü (`056de721…`) 130 s ve 17 durmaydı. Sürüşler
  arası değişkenlik büyük; tek sürüşlük karşılaştırma yanıltıcı olabilir.

**İlk işçi tasarımı neden kötüydü?** İlk sürümde projeksiyon ve
sınıflandırma aynı işçide yapılıyordu (`150046a`, sürüşler o1, o2). GT verisi
sık sık 0,4 s sınırını aştı: 79 ve 22 sensör beklemesi, 9 ve 5 süresi dolmuş
karar, 104–112 s varış. Taban sürüşlerinde bu beklemelerden hiç yoktu. İş iki
iş parçacığına bölününce beklemeler 6 ve 0'a, süresi dolmuş kararlar 0'a indi.
Ölçülen atlanan kare sayısı 0. Eski sürümde kare atlandığı bir hipotezdir;
sayaç o sürümde yoktu.

Ondan önceki ara sürüm (`1154f222…`), sınıflandırmayı kamera okuma iş
parçacığında ve kare yayımlandıktan sonra yapıyordu. Önbellek ıskaladı ve
sürüş 7,4 s'de `sensor_wait_limit` ile durdu.

## Sınırlar

- Her yapılandırma için iki sürüş var. Durma sayısındaki farklar
  istatistiksel olarak sınanmadı; yalnızca `--smooth-follow` farkı tutarlı.
- `--smooth-follow` kilit dışı işleme olmadan ölçülmedi.
- Takipçi kinematik olarak test edildi: gerçek arazi rotalarında rota
  ortasında 0 durma, koridor dışına çıkış yok. Bu fizik, kayma veya çarpışma
  doğrulaması değildir.
- GT yakalama yaşı 0,4 s sınırına yakın. s4'te 23 kısa GT bekleme olayı
  vardı; durma geçişi 0 olsa da pay az. 5 Hz kare aralığı ve Unreal'ın render
  gecikmesi bu payın çoğunu tüketiyor.
- Köşelerde rota 0,1–0,15 m kesilebiliyor. Şişirilmiş harita ve 1 s'lik yay
  kontrolü bunu sınırlıyor, ancak rotanın güvenli olduğunu kanıtlamıyor.
