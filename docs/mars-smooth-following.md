# Daha akıcı sürüş: kilit dışı derinlik işleme ve `--smooth-follow`

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
- Servis, GT karelerini kamera bağlantısının tek okuma iş parçacığından ayrı
  bir işçide işliyor:
  - Her zaman en yeni kare işleniyor.
  - Varış zamanı okuma anında damgalanıyor; bekleme ve işleme süresi tazelik
    hesabına dahil.
  - Bir taşıma hatası bekleyen kareyi düşürüyor (nesil sayacı).
- Eşikler, 8 m menzil, tazelik, CPU poz tutarlılık kontrolü ve harita
  sonucu değişmedi. `test_prepared_and_inline_observations_update_the_map_identically`
  iki yolun aynı haritayı verdiğini doğruluyor.

**`--smooth-follow` (isteğe bağlı).** `SmoothRouteFollower` şunları yapıyor:

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

## Native karşılaştırma (aynı seviye, geçici küp, `--allow-replan`)

Her iki sürüş de spawn noktasından (126, 116) hedefine gitti. Değerler
telemetriden ölçüldü.

| | Klasik takipçi (`056de721…`) | Kilit dışı + `--smooth-follow` (`29aa5d42…`) |
|---|---|---|
| Sonuç | vardı, 130 s | vardı, 94 s |
| Hareket süresi / ortalama hız | 111 s / 0,114 m/s | 87 s / 0,135 m/s |
| Ham durma geçişi | 17 | 1 |
| 0,05 m/s altında geçen süre | %10 | %3 |
| 50 ms'yi aşan kontrol turu | 693 / 2177 | 0 / 2643 |
| En uzun tur | 219 ms | 32 ms |
| Süresi dolmuş karar | 7 | 2 |
| Pitch standart sapması | 2,12° | 1,37° |
| Rotadan en büyük sapma | 0,12 m | 0,15 m |
| GT'nin eklediği hücre | 0 | 0 |

Kayıtlar: `Saved/Mars/gorev-izleme-*-ba5b5817…json` ve
`…-fe1c53a8…json`.

Ara sürüm (`1154f222…`), sınıflandırmayı kamera okuma iş parçacığında ve
kare yayımlandıktan sonra yapıyordu. Önbellek ıskaladı, GT yakalama yaşı
0,43–0,50 s'ye çıktı ve sürüş 7,4 s'de `sensor_wait_limit` ile durdu. Mevcut
tasarım bu iki hatayı gideriyor.

## Sınırlar

- Her yapılandırma için yalnızca birer native sürüş var. İki değişikliğin
  etkisi ayrı ayrı ölçülmedi.
- Takipçi kinematik olarak test edildi: gerçek arazi rotalarında rota
  ortasında 0 durma, koridor dışına çıkış yok. Bu fizik, kayma veya çarpışma
  doğrulaması değildir.
- Hareketsiz durumda GT yakalama yaşı 0,2–0,37 s ölçüldü. 0,4 s sınırına
  pay az; 5 Hz kare aralığı ve Unreal'ın render gecikmesi bunun çoğunu
  oluşturuyor.
- Köşelerde rota 0,1–0,15 m kesilebiliyor. Şişirilmiş harita ve 1 s'lik yay
  kontrolü bunu sınırlıyor, ancak rotanın güvenli olduğunu kanıtlamıyor.
