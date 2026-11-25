# Sensör incelemesi: GT tazeliği, GPU LiDAR, kamera karanlığı (2026-11-25)

Bu belge [Terrain Lab](mars-terrain-lab.md) artımında açık kalan üç sorunu
inceler. Ölçümler BelvaLab01 ve BelvaRockLab01 test seviyelerinde, Play (PIE)
içinde yapıldı. Sayılar [docs/data/sensor-investigation-20261125.json](data/sensor-investigation-20261125.json)
dosyasındadır.

**Kanıt etiketleri:**
- **[ölçüldü]**: bu oturumda çalışan servisten, editörden ya da veriden okundu.
- **[hipotez]**: ölçümlerle uyumlu, ama doğrulanmadı.
- **[çürütüldü]**: ölçümle elendi.
- **[doğrulanmış düzeltme]**: Unreal'da önce/sonra ölçümüyle denendi.

Windows'ta `time.monotonic()` çözünürlüğü ~15,6 ms'dir. Servisin işleme süreleri
bu adımlarla raporlanır.

## 1. GT derinlik tazeliği

**Bulunamadı.** GT yakalama ve işleme süresini azaltan doğrulanmış bir düzeltme
yok. 0,35 s eşiği değiştirilmedi.

**Ölçülenler [ölçüldü]**

Boşta GPU LiDAR, 198 örnek:
- **Gecikme (poz damgası − GT yakalama damgası):** p50 0,267 s, p90 0,333 s, en fazla 0,400 s.
- Örneklerin %93'ü 0,35 s'nin altında.

Boşta CPU LiDAR, 148 örnek:
- **Gecikme:** p50 0,267 s, p90 0,367 s.
- Örneklerin %90'ı 0,35 s'nin altında.

Gecikmenin bileşenleri:

| Bileşen | Süre |
|---|---|
| Yakalama periyodu (5 Hz, oyun zamanı) | 0,200 s |
| Unreal yakalaması → Python'a varış | ±0,1 s içinde ayırt edilemiyor (küçük) |
| İzdüşüm (okuyucu iş parçacığı) | ~0,062 s |
| Dünya dönüşümü + sınıflandırma (işçi) | ~0,062 s |
| Kilitli harita güncellemesi | ≤0,016 s |

Aynı işlem çevrimdışı, tek iş parçacığında ölçüldü (640×480 kare, ~209 bin
nokta, 8 m içinde):
- izdüşüm ve filtre ~28 ms;
- dönüşüm ~4 ms;
- sınıflandırma ~32 ms.

Sınıflandırma süresi Belva (1281²) ve Jezero_C (253²) haritalarında aynı çıktı.

**Ön kontrol yeniden üretildi [ölçüldü]**

`mars_detour_probe` ön kontrolü BelvaLab01'de geçici CPU LiDAR ile, salt okunur
olarak 6 kez denendi; 6'sı da reddedildi ("ön kontrol sırasında eskidi").
- **İkinci anlık görüntüde GT gecikmesi:** 0,233–0,333 s.
- **Ön kontrolün kendi süresi:** ~0,13 s; bunun 0,11 s'si 1281² haritada rota önizlemesi.
- Kontrol `gecikme + süre ≤ 0,35` istediği için en iyi denemede bile 0,233 + 0,13 > 0,35.

`/map` yanıtı Belva'da 4,9 MB ve servis tarafında 0,17–0,28 s sürüyor. Hemen
ardından alınan anlık görüntüde GT gecikmesinin ortalaması 0,267 s'den 0,325 s'ye
çıktı (8 çift).

**Elenenler ve denenenler**

- **[çürütüldü]** "Büyük harita GT işlemesini yavaşlatıyor": sınıflandırma iki
  haritada da ~32 ms. Harita boyutu yalnız ön kontrolün kendi önizlemesini ve
  `/map` boyutunu etkiliyor.
- **[ölçüldü, geri alındı]** Sonuçları bit düzeyinde aynı kalan daha hızlı bir
  izdüşüm denendi: 27,4 → 25,2 ms. Kazanç değmediği için geri alındı.
- **[ölçüldü, geri alındı]** GT gönderim hızı 5 → 10 Hz yapıldı (test seviyesi,
  geçici):
  - GT gecikmesi 1,6–3,9 s'ye çıktı ve 6 ön kontrolün 6'sı reddedildi.
  - Servisin tazelik kapısı bunu `capture_stale` olarak doğru yakaladı; derinlik
    işçisi hiç kare atlamadı.
  - Değer 5 Hz'e geri alındı.

**Hipotez [hipotez]**

Servis tek bir Python sürecinde çalışıyor. GT işleme (~65 ms CPU/kare), renkli
kamera akışlarının ayrıştırılması (5 Hz'de ~8,6 MB/0,2 s), LiDAR, telemetri ve
HTTP aynı GIL'i paylaşıyor.

Destekleyen ölçümler:
- Unreal'la birlikte işleme süresi, çevrimdışının ~2 katı.
- 10 Hz'de ardışık düzen doyuyor.

Doğrulanmayan: süreç başına CPU payı ve GIL bekleme süresi ölçülmedi.

**Öneriler (uygulanmadı)**

1. GT izdüşüm ve sınıflandırmasını ayrı bir sürece ya da derlenmiş koda taşımak,
   ardından 5 ve 10 Hz'de yeniden ölçmek.
2. `/map` yanıtını ikili ya da vektörel JSON olarak üretmek; ön kontrol anındaki
   GIL duraklamasını azaltır.
3. Ön kontrolde yetkilendiren anlık görüntüyü rota önizlemesinden sonra almak.
   Rover ve harita revizyonu aynı kalmalı. Eşik aynı kalır, ama kapının sırası
   değişir; bu yüzden operatör onayı gerekir.

## 2. GPU LiDAR sahte engelleri

**[doğrulanmış düzeltme, isteğe bağlı]** `--lidar-pose-source telemetry_post_physics`

**Ölçülenler [ölçüldü]**

- **Hareketsizken:** boşta GPU LiDAR'ın son karesinde pozitif ve negatif engel 0.
  Play başlangıcında harita revizyonu 1'den 5'e çıktı.
- **Engellenen GPU sürüşü (Terrain Lab):** 214 sahte hücre.
  - Rover'a uzaklık 3,7–9,7 m (medyan 6,7 m); hücre sayısı mesafeyle artıyor.
  - O sırada gövde eğimi 29,9°'ye çıktı ve rover ~108° döndü.
  - Aynı sahnede CPU sürüşünün en yüksek eğimi 6,6°.
- **Tick grupları (editör):** rover aktörü `TG_PrePhysics`, LiDAR bileşeni
  `TG_PostPhysics`. İkisi de aynı karenin dünya zamanını damga olarak kullanıyor.
- **Önceki ölçüm** ([mars-gnc-dashboard.md](mars-gnc-dashboard.md), 2026-11-24):
  - CPU yakalama pozu bir sonraki telemetri örneğine 0,001° içinde eşitti.
  - 43 sahte GPU örneği istek pozuyla yeniden yerleştirildiğinde hepsi 0,15 m'nin altına indi.

**Neden**

Telemetri pozu fizikten önce okunuyor. GPU taraması ise aynı damgayla fizikten
sonra yapılıyor. Servis taramaya aynı damgalı telemetri pozunu verince ~1 karelik
açısal hata oluşuyor. Bu hata menzille büyüyor ve hızlı eğim değişimlerinde 4–9 m'de
eşiği aşıyor. CPU modu bundan etkilenmiyor, çünkü yakalama pozunu pakette gönderiyor.

**Düzeltme**

- `PoseHistory.at(..., post_physics=True)` bir taramaya, damgasından sonraki
  telemetri örneğinin pozunu verir.
- Servis bunu yalnız `--lidar-pose-source telemetry_post_physics` ile GPU
  LiDAR'da kullanır. Varsayılan (`telemetry`) değişmedi.
- Kısayol: her karede bir telemetri örneği olduğu varsayılır. Telemetri FPS'in
  altına kısılırsa bu varsayım yeniden ele alınmalı.

**A/B sürüşleri [ölçüldü]** (GPU LiDAR, aynı hedef ve bayraklar)

| Koşu | Poz eşleşmesi | Sonuç | Harita rev. | LiDAR-önce hücre | En yüksek eğim |
|---|---|---|---|---|---|
| A, BelvaLab01 (180, 275) | `telemetry_post_physics` | `arrived`, 164,9 s, hedefe 0,245 m (mission `7f8e86d2…`) | 0 → 0 | 0 | 5,0° |
| B, BelvaLab01 (180, 275) | `telemetry` | 39,7 s'de `blocked` (mission `01e32be0…`) | 5 → 36 | başlangıçta 65, sonda 195; 4,2–9,5 m | 14,1° |
| C, BelvaRockLab01 dolaşma | `telemetry_post_physics` | `arrived`, 91,7 s, hedefe 0,24 m (mission `a22e3342…`) | 1 → 4 | 4 (kayalarda) | 6,2° |

C koşusunda harita:
- threshold, blocker ve detour_blocker kayaları LiDAR'la engel işaretlendi;
- pebble ve belly serbest kaldı;
- kayalardan 1,5 m'den uzakta sahte hücre yok.

Varsayılan mod, daha önceki engellenen koşuyla birlikte 2 koşunun 2'sinde engellendi.

**Sınırlar**

- Her koşu bir kez yapıldı; istatistik değildir.
- GPU render pozu doğrudan ölçülmedi.
- Varsayılanın değiştirilmesi operatör onayı ve daha fazla sürüş gerektirir.

## 3. Kamera karanlığı

**[ölçüldü, kalıcı değişiklik yapılmadı]** Baskın neden sabit EV100 13 pozlaması.

**Ayarlar [ölçüldü]**

- **NavCam akışı:** `UnrealStereoCam` 5 Hz, `min_ev100 = max_ev100 = 13`; arka kamera 12.
- **Post-process hacmi:** EV 13.
- **Proje ayarı:** `ExtendDefaultLuminanceRange=True`, yani değerler EV100.
- **Işık:** güneş 30 000 lux, 35° yükseklik; atmosfer güneşi zayıflatıyor
  (Mie ~0,038/km, τ880 = 0,45).
- **Arazi albedosu:** lineer ~(0,23, 0,10, 0,05).

**Ölçümler**

- **[çürütüldü]** "Görüntü tonemap edilmemiş HDR": editör `SCS_SCENE_COLOR_HDR`
  gösteriyor, ama eklenti BeginPlay'de `SCS_FinalColorLDR`'yi zorluyor.
- **[ölçüldü]** Editör dünyasında geçici yakalama:

  | Durum | Zemin | Gökyüzü |
  |---|---|---|
  | EV13 | 15/255 | 64/255 |
  | EV10 | 116/255 | 191/255 |

  - Albedo yakalaması yapılandırılan rengi verdi.
  - Atmosfer zayıflatması kapatılınca zemin ~1,7× parladı. Beklenen ~2× ile uyumlu;
    ek bir kayıp yok.
- **[ölçüldü]** PIE, BelvaLab01, spawn noktası, boşta, tek koşu:

  | Durum | Zemin (alt %50) | Gökyüzü | Siyah piksel (<10) | Doygun piksel |
  |---|---|---|---|---|
  | EV13 | 3/255 | 44/255 | %80 | – |
  | EV10 | 90/255, RGB ~(138, 81, 44) | 176/255 | %0 | %0 |

  - Değer 13'e geri alındı ve seviye kaydedildi.
  - Görüntüler yerelde: `Saved/Mars/navcam-ev13-vs-ev10-belvalab01.png`.

**Öneri (uygulanmadı)**

- Yeni seviyelerde navcam ve post-process pozlamasını ~EV100 10 yapmak:
  `Config/Mars/scene.json` ve `Content/Python/mars_sensor_setup.py`.
- Mevcut referans seviyeler kullanıcıya ait; onları değiştirmek onay gerektirir.
- `min = max` korunursa stereo kameralar aynı pozlamayı paylaşmaya devam eder.

**Doğrulanmayanlar**

- Başka güneş yükseklikleri.
- Sürüş sırasında görüntü.
- Stereo derinlik kalitesi.
- Arka kamera (bu koşularda `--rear-camera-id` verilmediği için akış yoktu).
