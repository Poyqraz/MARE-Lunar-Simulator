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
- **[birim testli]**: kod değişikliği testlerle doğrulandı, Unreal'da doğrulanmadı.
- **[kod incelemesi]**: koddan okundu, çalıştırılarak ölçülmedi.

Belge üç turdan oluşur. İkinci tur (aynı gün, PR #5 açıldıktan sonra) ve
üçüncü tur (26 Kasım, bilgisayar Unreal'a bırakıldıktan sonra) her bölümün
sonunda kendi başlığı altındadır.

Windows'ta `time.monotonic()` çözünürlüğü ~15,6 ms'dir. Servisin işleme süreleri
bu adımlarla raporlanır.

## 1. GT derinlik tazeliği

**Birinci tur:** GT yakalama ve işleme süresini azaltan doğrulanmış bir düzeltme
bulunamadı. **İkinci tur:** işleme yavaşlığının baskın nedeni ölçüldü (Windows
çekirdek zamanlaması, GIL değil) ve ön kontrolün başarısızlık nedeni kodda
giderildi (birim testli; Unreal doğrulaması tamamlanamadı). 0,35 s eşiği hiçbir
turda değiştirilmedi.

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

**Birinci tur önerileri:** ayrı süreç ya da derlenmiş kod, ikili `/map`, ön
kontrolde yetkilendirmeyi planlamadan sonraya almak. Üçüncüsü ikinci turda
uygulandı; ilki aşağıdaki ölçümle yeniden değerlendirildi.

### İkinci tur: saat alanlarına göre ayrıştırma

**Yöntem [ölçüldü]**

Servis, davranışını değiştirmeyen bir ölçüm sarmalayıcısıyla çalıştırıldı
(geçici betik, depoda değil). Tek fark, oturum kilidinin bekleme süresini ölçen
bir sarmalayıcı. BelvaLab01, GPU LiDAR, rover boşta, PIE.

Saat alanları:
- **Unreal GncSimTime** (yakalama ve poz damgaları): sabit 1/30 s adım.
  - Host saatine göre koşu boyunca %1,7 geri kaldı.
  - Takılmalarda tek seferde 1,07 s'ye kadar sıçradı.
  - Bu yüzden sim ile host arasında sabit bir ofset kullanılmadı.
- **Host saati:** `perf_counter` (QPC, süreçler arasında ortak). Referans
  noktası, GT karesiyle aynı damgayı taşıyan telemetri örneğinin varış anı.
- **İş parçacığı CPU süresi:** `thread_time`, Windows'ta 15,6 ms adımlı. Yalnız
  ortalamalar karşılaştırıldı.

**Kare başına aşamalar [ölçüldü]** (koşu 1, A evresi, varsayılan zamanlama, 126 kare)

| Aşama | Ortalama | p90 |
|---|---|---|
| İlk bayt, aynı karenin telemetrisinden sonra (Unreal yakalama, okuma, gönderim) | 53 ms | 61 ms |
| Soketten aktarım + çözme | 6 + 1,6 ms | 10 + 1,9 ms |
| İzdüşüm (okuyucu iş parçacığı), duvar / CPU | 65 / 56 ms | 74 / 78 ms |
| İşçi kuyruğunda bekleme | 0,3 ms | 0,4 ms |
| Dönüşüm + sınıflandırma + yayın (işçi), duvar / CPU | 75 / 63 ms | 92 / 78 ms |
| Oturum kilidi bekleme | 0,02 ms | 0,01 ms |
| Yayından kontrol döngüsünde tüketime (20 Hz) | 29 ms | 54 ms |
| Tüketim anı, aynı karenin telemetrisinden sonra | 234 ms | 275 ms |

- Tüketim anında sim gecikmesi (poz damgası − GT damgası): p50 0,200 s.
- 5 Hz anlık görüntü sorgusunda GT gecikmesi: p50 0,267 s, p90 0,367 s; %71'i
  ≤ 0,35 s. Anlık görüntü, tüketimden sonraki 0–0,2 s içinde herhangi bir anda
  alındığı için tüketimdeki gecikmeye 5 Hz periyodunun bir kısmı eklenir.

**GIL hipotezi [çürütüldü, ana neden olarak]**

- Aşamalarda duvar − CPU farkı 9–12 ms. Bu, GIL ve işletim sistemi beklemesinin
  toplam üst sınırı.
- Aynı iş, servisle GIL paylaşmayan **ayrı bir süreçte**, aynı Play sırasında
  56 / 63 ms sürdü (izdüşüm / sınıflandırma). Editör boştayken aynı ölçüm
  23 / 28 ms.
- Yani yavaşlık servise özgü değil; Unreal Play'le eşzamanlı çalışmaktan geliyor.

**Çekirdek zamanlaması [ölçüldü]**

İşlemci i7-14700HX: 8 performans (P, mantıksal 0–15) ve 12 verimlilik (E,
16–27) çekirdeği. Güç planı "Dengeli".

- Editör boşta, ayrı süreç: P-çekirdekte 25 / 31 ms, E-çekirdekte 58 / 67 ms.
  E-çekirdek değerleri Play sırasındaki yavaş değerlerle örtüşüyor.
- Koşu 3: aynı Play oturumunda servisin modu çalışırken değiştirildi (her biri
  20 s):

  | Servis modu | İzdüşüm | İşçi | Tüketim, aynı-kare telemetriden sonra | Tüketimde sim gecikmesi p50 |
  |---|---|---|---|---|
  | Varsayılan | 77 ms | 88 ms | 304 ms | 0,233 s |
  | EcoQoS kısıtlaması kapalı | 45 ms | 51 ms | 236 ms | 0,200 s |
  | Yalnız P-çekirdekler | 46 ms | 47 ms | 217 ms | 0,200 s |
  | Yeniden varsayılan | 57 ms | 59 ms | 239 ms | 0,200 s |

- Aynı koşuda ayrı süreç: varsayılan 59 / 65 ms, kısıtlama kapalı 43 / 51 ms.
- Koşu 2'de ayrı süreç: varsayılan 83 / 96, kısıtlama kapalı 42 / 49,
  P-çekirdek 45 / 53, yüksek öncelik 74 / 82 ms. Yüksek öncelik tek başına
  yardımcı olmadı.

**Yorum [hipotez]:** Unreal ön plandayken Windows arka plandaki Python sürecini
EcoQoS ile verimlilik çekirdeklerine yerleştiriyor. Bunu kapatmak ya da
P-çekirdeğe sabitlemek işlemeyi yaklaşık yarıya indiriyor. P-çekirdekte bile
Play sırasında 45 ms (boşta 25 ms) sürmesinin nedeni ölçülmedi.

**Sınırlar**
- Tek bir oturum içi karşılaştırma; varsayılana dönüş tam geri dönmedi
  (57 / 59 ms).
- Koşular arası fark büyük: ayrı süreçteki varsayılan ölçüm 56–83 ms arasında
  değişti.
- Kodda uygulanmadı. İyileşmeyle bile GT yaşı rastgele bir anda 0,2–0,4 s; 5 Hz
  periyodu baskın kalıyor.

### İkinci tur: planlamadan sonra yetkilendiren ön kontrol

**[birim testli, Unreal doğrulaması tamamlanamadı]** commit `c9548a1`

- Rota önizlemesi artık sensör verisini yaşlandırmıyor. Planlamadan sonra en
  fazla 1,0 s (beş GT periyodu), 25 ms aralıkla yeni bir anlık görüntü bekleniyor.
- Yetki için o anlık görüntüde:
  - LiDAR ve GT yakalamaları planlanan verilerden **daha yeni** olmalı;
  - aynı eşikler geçilmeli (poz 0,3 s, sensörler 0,35 s), kendi isteğinin ve
    köprü kontrolünün süresi de sayılarak;
  - geçerli nokta bulunmalı ve `capture_stale` olmamalı;
  - oturum, harita revizyonu ve durağan poz planlanan değerlerle aynı olmalı.
- Harita revizyonu değişirse yeni haritada yeniden planlanır. Oturum ya da poz
  değişirse reddedilir. Hiçbir retde hedef gönderilmez.
- Ön kontrol sonucu ölçülen tazeliği taşır; salt okunur önizleme
  `ON_KONTROL_TAZELIK` satırını yazar.
- Testler: 6 yeni durum (yavaş planlamaya rağmen yeni örnekle yetki, yeni örnek
  gelmemesi, yeni ama eski örnek, harita değişimi, oturum değişimi, poz değişimi).

**Kalan yarış [kod incelemesi]:** hedef, yetkilendiren anlık görüntüden sonra
gönderiliyor. Arada yeni bir harita revizyonu ya da eskiyen bir sensör
oluşabilir. Servis rotayı kendi canlı haritasında, ancak sensör tazeliği
geçtikten sonra planlıyor ve her hareket kararında tazeliği yeniden denetliyor.
Prob ise yeniden planlamada (izin verilmediyse), oturum ya da görev değişiminde
ve uzun sensör beklemesinde duruyor. Bu pencereyi engellemiyor; yalnız sonrasını
sınırlıyor.

**Unreal doğrulaması, 25 Kasım:** BelvaRockLab01'de geçici CPU LiDAR ile 3 × 8
salt okunur deneme planlandı. Play başladıktan 11 s sonra editör penceresi
arayüzden kapatıldı (bkz. §4). Ardından çalışan 24 deneme Unreal olmadan koştu
ve kanıt değildir.

**Unreal doğrulaması, 26 Kasım [ölçüldü]** (BelvaRockLab01, geçici CPU LiDAR,
gerçek servis, ölçüm sarmalayıcısı yok)

- **Koşu 1, salt okunur, 8 tek deneme:** 3'ü geçti.
  - 5 ret planlamadan önce geldi: ilk ya da planlama anlık görüntüsü, var olan
    0,35 s kontrolü. Yeni aşamaya hiç ulaşmadılar.
  - Geçenlerde: planlama 0,08–0,10 s; planlamadan sonra bekleme 0,007–0,113 s;
    yetkilendiren isteğin süresi 0,007–0,034 s; GT gecikmesi 0,233 s; GT varış
    yaşı 0,17–0,22 s.
- **Aynı oturumda prob ile denetimli dolaşma** (`--send --allow-replan`):
  - Önizleme ve gönderim ön kontrolü geçti (planlama 0,062 s, bekleme 0,125 s,
    GT gecikmesi 0,200 s).
  - Rover 12,05 m yol aldı; en büyük rota sapması 0,16 m; harita revizyonu
    1 → 4; plan revizyonu 1 (yeniden planlama yok).
  - Yaklaşık 83 s'de `pose_stale` ile durdu, hedefe ~1,5 m kala. Stop isteği
    onaylandı. Servisin poz yaşı 1,0 s'ye çıktı; Unreal log'u ise Play bitene
    kadar telemetri üretmeye devam etti. Neden belirlenmedi.
- **Bulunan ve düzeltilen hata [birim testli]** commit `ee378ab`: yetkilendirme
  döngüsü 0,35 s'den eski bir anlık görüntüde beklemek yerine denemeyi
  bitiriyordu. Koşu 1'de tetiklenmedi.
- **Koşu 2, salt okunur, 10 tek deneme (düzeltmeden sonra):** 0 geçti; hepsi
  planlamadan önce reddedildi (eski GT, eksik GT damgası, eksik CPU LiDAR pozu).
  Koşudan hemen sonra ön planda başka bir uygulama vardı. Unreal arka planda
  yavaşlıyor [hipotez]; bu koşu temsil edici değil.

**Güncel öneriler:** 1 ve 2 üçüncü turda yapıldı (aşağıda); `/map` yanıtını
ikili üretmek hâlâ uygulanmadı.

### Üçüncü tur: Unreal'da ön kontrol ve EcoQoS bayrağı

Hepsi BelvaRockLab01'de, geçici CPU LiDAR ile, gerçek servisle. Ön plan
uygulaması 2 s'de bir kaydedildi.

**Editör arka plan kısıtlaması:** bu koşular için editörün "arka planda daha az
CPU kullan" ayarı (`bThrottleCPUWhenNotForeground`) **yalnız bellekte**
kapatıldı. Yapılandırma dosyasının SHA-1'i değişmedi; ayar sonunda `True`'ya
geri alındı. Unreal'ı öne çekmeden çalışmak için gerekiyordu, çünkü bilgisayar
aynı anda kullanılıyordu.

**Ön kontrol [ölçüldü]**
- Unreal ön plandayken, bayraksız: 10 tek denemenin 7'si geçti; 3 ret
  planlamadan önce geldi. Aynı oturumda prob ile gönderilen denetimli dolaşma
  hedefe vardı (90,6 s; 13,30 m; en büyük rota sapması 0,153 m). Bu, dolaşma
  sürüşünün ilk kez probun kendi ön kontrolüyle gönderilip tamamlanmasıdır.
- Unreal arka plandayken, bayraksız: 10'da 3; probun kendi önizlemesi 10 s
  içinde onay alamadı (GT sağlık kaydı boş).

**EcoQoS bayrağı [doğrulanmış düzeltme, isteğe bağlı]** commit `fb254f0`,
`--windows-no-power-throttling`. Unreal arka planda, kullanıcı uygulamaları
önde; koşular dönüşümlü:

| Koşu | Bayrak | Ön kontrol | GT işleme p50 | GT gecikmesi p50 / p90 | Boş GT kaydı |
|---|---|---|---|---|---|
| a1 | yok | 0/10 | 78 ms | 0,333 / 0,400 s | 10/69 örnek |
| b1 | var | 7/10 | 62 ms | 0,267 / 0,367 s | 0/83 |
| a2 | yok | 0/10 | 78 ms | 0,333 / 0,400 s | 5/69 |
| b2 | var | 10/10 | 47 ms | 0,233 / 0,333 s | 0/82 |

- "GT işleme" burada servisin sağlık kaydındaki `processing_s` (izdüşüm +
  kilitli işleme).
- Bayrakla, arka planda: ön kontrol 6/6 ve prob ile denetimli dolaşma hedefe
  vardı (13,30 m; rota sapması en fazla 0,161 m).
- Dört karşılaştırmalı koşu; istatistik değil. Bayrak varsayılan olarak kapalı.

**Bulunan ikinci hata [birim testli]** commit `ee378ab`: yetkilendirme döngüsü
eski bir anlık görüntüde beklemek yerine denemeyi bitiriyordu (§1, 26 Kasım
koşu 1'de bulundu).

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

### İkinci tur: sağlamlık incelemesi

**Varış gecikmesi [ölçüldü]:** GPU taraması servise vardığında köprüdeki son
telemetri, tarama damgasından 2 kare ileride (821 örnek) ya da 3 kare ileride
(36 örnek); üç boşta koşu. Yani "bir sonraki örnek" normalde hazır.

**Atlanan telemetri karesi [birim testli]** commit `3e8965b`
- Önceki kod, t'den sonraki kare hiç raporlanmadıysa taramaya sessizce bir kare
  geç pozu veriyordu.
- Artık `[a, b)` aralığındaki bir damga, `b − a` ortanca kare süresinin 1,75
  katını aşıyorsa reddediliyor (atlanan kare yaklaşık iki kare boşluk bırakır).
- Telemetride kare sayacı yok; bu yüzden tek bir uzun takılma da reddediliyor.
  Bu yalnız o taramayı düşürür.
- Tekdüze kısılmış telemetri (her ikinci kare) hâlâ fark edilemez.

**Diğer durumlar [birim testli]**
- Değişken kare süresi (25/40 ms, atlamasız) kabul ediliyor.
- Aynı damga tekrarlanınca örnek değiştiriliyor; daha eski damga geçmişi
  temizliyor.
- Dönen poz yakalama damgasını taşıyor; sağlık kaydı telemetri damgasını değil,
  tarama damgasını tutuyor.
- Sonraki örnek gelene kadar tarama bekletiliyor, sonra yerleştiriliyor.
- Eski bir tarama sonradan gelen pozla tazelenmiyor; `capture_stale` raporlanıyor.
- Oturum değişiminden önceki tarama haritaya yerleşmiyor.

**[kod incelemesi]** `_consume` içinde LiDAR "poz bekle" hatası verirse aynı
döngüde GT de tüketilmiyor ve sürüşte o döngüde sıfır komut gidiyor. Bu iki modda
da var; yeni mod "bekle" durumunu daha sık üretebilir. Ölçülmedi.

**Tekrar sürüşleri:** ikinci turda yapılamadı (editör kapandı, §4); üçüncü
turda yapıldı (aşağıda).

### Üçüncü tur: tekrar sürüşleri [ölçüldü]

GPU LiDAR; bayraklar `--obstacle-diagnostics --max-turn-rate-deg-s 20
--prefer-short-direct --windows-no-power-throttling`; başlangıç (180, 300).
Sürüşler sırasında Unreal öndeydi (ön plan kaydı).

| Koşu | Poz eşleşmesi | Sonuç | LiDAR-önce hücre |
|---|---|---|---|
| BelvaLab01 (180, 275) #1 | `telemetry_post_physics` | vardı, 165,2 s, hedefe 0,243 m | 0 |
| BelvaLab01 (180, 275) | `telemetry` (varsayılan) | 34,0 s'de `blocked`, harita rev. 39 | 219 (rover'a 1,4–11,7 m, medyan 7,3 m) |
| BelvaLab01 (180, 275) #2 | `telemetry_post_physics` | vardı, 165,0 s, hedefe 0,240 m | 0 |
| BelvaRockLab01 dolaşma #1 | `telemetry_post_physics` | vardı, 90,8 s, hedefe 0,244 m | 4; hepsi eşik üstü üç kayanın 1,5 m içinde |
| BelvaRockLab01 dolaşma #2 | `telemetry_post_physics` | vardı, 90,7 s, hedefe 0,241 m | 4; aynı |

İki günün toplamı: Belva açık zeminde varsayılan mod 3 sürüşün 3'ünde
engellendi; yeni mod 6 sürüşün 6'sında vardı (açık zemin 3, kayalar 3). Kaya
sürüşlerinde çakıl ve gövde altı kayası engel sayılmadı. Hâlâ tek sahne ve tek
güneş açısı; GPU render pozu doğrudan ölçülmedi.

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

### İkinci tur

Yapılamadı: kamera görünümleri, aydınlık ve gölgeli zemin ve kaya sahnesi
karşılaştırması için Unreal gerekiyordu; editör kapandı (§4).

### Üçüncü tur: görünümler, gölgeler, kaya sahnesi [ölçüldü]

**Yöntem**
- Port 3004'ten ham 640×480 kareler alındı; her yapılandırmada Play'in
  16. saniyesinden sonraki son kare kullanıldı.
- Rover köprüsü çalışıyordu (sıfır komut, farlar kapalı).
- EV, navcam ve arka kamera akışında `min = max` yapıldı ve eklentinin
  logunda her koşu için doğrulandı.
- Parlaklık 8 bit son renk çıktısından hesaplandı.
- Zemin/gök ayrımı merkez kameranın GT derinliğinden yapıldı.
- Gölge maskesi: güneş gölgeleri kapalıyken aynı pikselin %60'ından karanlık
  olan zemin.
- Rover yönü Play'den önce editörde değiştirildi ve her koşudan sonra geri
  alındı.
  - Yön 0'da navcam güneş azimutuna 53° bakıyor (zemin ters ışıkta).
  - Yön 180'de güneş arkada.
- İlk denemede yalnız alt EV sınırı uygulanmıştı (bileşen yeniden oluşturuluyor);
  o kareler atıldı ve matris baştan alındı.

**BelvaLab01, dört yön** (merkez navcam zemini; sol/sağ ortancalar merkezden en fazla 0,7 farklı):

| EV100 | Zemin ortancası | Siyah zemin (<10) | Gök ortancası | Arka kamera ortancası / siyah |
|---|---|---|---|---|
| 13 | 3,6–6,4 | %86–99 | 10–47 | 4–7 / %70–82 |
| 12 | 16,8–25,0 | %5–8 | 36–96 | 18–26 / %2–6 |
| 11 | 47,8–62,4 | %0–2,5 | 80–146 | 51–64 / ≤%0,1 |
| 10 | 95,4–113,7 | %0 | 133–187 | 100–115 / %0 |

- EV10'da en parlak değerler: gök p95 ≤ 217, arka kamera p95 ≤ 224.
  Hiçbir kamerada ve yönde ≥ 250 piksel yok.
- EV9 (yalnız kaya sahnesi, yön 180): zemin ortancası 158, arka kamera p95 232.
  Güneşe bakan arka kamerada lens parlaması halkaları görünüyor.

**Gölgeler**
- Rover'ın kendi gölgesi (yön 180, zeminin %2,3'ü): EV10'da ortanca 19,6,
  siyah piksel yok; aydınlık zemin 109,7.
- Kayaların düşen gölgeleri bu görünümlerde çok küçük (87 piksel); ölçüm
  için yetersiz.
- **Ters ışıktaki kaya yüzleri** (yön 0; kayasız aynı görünümle derinlik
  farkından ~540 piksel): EV13'te %99,8'i siyah; EV10'da ortanca 4/255 ve
  %59'u siyah. Pozlama zemini düzeltiyor, gölgedeki kaya yüzlerini düzeltmiyor.
- **[hipotez]** Gölgeyi dolduran ışık (gök ışığı) çok zayıf: rover gölgesi 8
  bitte aydınlık zeminin ~%18'i. Sahnedeki gök ışığı ölçülmedi.

**Yan gözlem [ölçüldü]:** köprü komut göndermezse rover'ın farları açık kalıyor
ve navcam önünde büyük parlak bir leke oluşuyor. Servisle çalışırken farlar
kapalı.

**Sahneye özgü ayar [birim testli]** commit `0e0b9ca`
- `configure_and_export(camera_ev100=13.0, rear_camera_ev100=None)`:
  varsayılanlar eski davranışı korur. Kullanılan değerler dışa aktarılan
  sensör yapılandırmasına (`camera_exposure_ev100`) yazılır.
- Sahne presetleri `navigation_camera_ev100` ve `rear_camera_ev100`
  tanımlayabilir.
- `Config/Mars/scene-belva-ev10.json`: varsayılan sahnenin EV100 10'lu kopyası
  (post-process, navcam, arka kamera). Bir test, pozlama dışındaki her değerin
  `scene.json` ile aynı kaldığını denetler.
- Kullanım: `mars_setup.build(..., scene_path="Config/Mars/scene-belva-ev10.json",
  navigation_config_path=<yeni dosya>)`.
- Mevcut seviyeler değiştirilmedi. Bu preset'le Unreal'da seviye kurulmadı;
  gerçek rover'da arka akış araması salt okunur kontrol edildi (tek eşleşme,
  `RearCam_Stream`).

**EV10'un kapsamı:** yalnız bu güneş (35°, azimut 135°), Belva arazisi ve
albedosu için; kamera kalibrasyonu değil.

**Doğrulanmayanlar:**
- başka güneş açıları;
- sürüş sırasında görüntü;
- EV10'da stereo derinlik kalitesi;
- dashboard JPEG yolu.

Karşılaştırma görüntüsü yerelde: `Saved/Mars/navcam-exposure-matrix-20261126.png`.

## 4. Kesintiler ve bırakılan durum

- Unreal Editor penceresi iki kez arayüzden kapatıldı (`QUIT_EDITOR`):
  - 18:18:35, rover boştayken; kaydedilmemiş değişiklik yoktu.
  - 18:29:06, Play sırasında. Kapanıştaki kaydet istemi
    `/Game/Mars/BelvaRockLab01`'i geçici CPU LiDAR ayarlarıyla kaydetti.
- Ölçüm betikleri yalnız Play başlatma/durdurma, seviye yükleme, sensör
  ayarlama ve test seviyelerini kaydetme yapıyor; pencere kapatmıyor.
- Editör ilk kapanıştan sonra bir kez BelvaRockLab01 ile yeniden açıldı; ikinci
  kapanıştan sonra açılmadı.
- **BelvaRockLab01 geri yüklendi (26 Kasım, izinle editör yeniden açıldıktan
  sonra):** LiDAR CPU, 160 × 120, 5 Hz, `send_cpu_capture_pose = true` iken
  GPU, 320 × 240, 10 Hz, `send_cpu_capture_pose = false` yapıldı ve seviye
  kaydedildi. BelvaLab01 etkilenmedi.
- 26 Kasım öğlen Unreal koşuları, ön planda başka bir uygulama kullanıldığı
  için durduruldu. Kullanıcı bilgisayarı Unreal'a bıraktıktan sonra koşular
  editör arka plan kısıtlaması bellekte kapatılarak, pencere öne çekilmeden
  sürdürüldü (§1 üçüncü tur).
- Geçici betik klasörü gece boşaltılmıştı; ölçüm yardımcıları yeniden yazıldı.
  Önceki ölçüm sonuçları bu belgedeki JSON'da korunuyordu.
