# Jezero Terrain Lab: ilk artım (2026-11-25)

Bu artım dört şey ekler:

1. Mevcut Jezero_C paketini kaynaktan yeniden üretip doğrulayan bir taban çizgisi.
2. Belva kraterini içeren, ölçülmüş yeni bir 1,28 km'lik bölge ve onun Unreal sahnesi.
3. Rover ölçülerine bağlı, açıkça etiketlenmiş sentetik kaya senaryosu.
4. Çalışan Unreal dünyasında ölçülmüş yerçekimi ve rover fiziği taban çizgisi.

Bütün sayılar [docs/data/terrain-lab-20261125.json](data/terrain-lab-20261125.json)
dosyasındadır.

**Kanıt etiketleri:**
- **[ölçüldü]**: bu oturumda veriden ya da çalışan editörden okundu.
- **[kaynak metni]**: yayıncının belgesinden alındı.
- **[varsayım]**: ölçülmedi.

## 1. Taban çizgisi: Jezero_C

`python -m mars_rover.prepare --output generated/jezero-baseline-20261125` komutu
paketi resmi kaynaktan HTTP aralık okumasıyla yeniden üretti. Sonuç **[ölçüldü]**:

- **Bayt bayt aynı dosyalar:** `heightmap.r16`, `soil.csv`, `source_dem.xml`,
  `source_ortho.xml`.
- **`elevation.csv`:** 64.009 postta en büyük fark 1e-9 m. Bu, metin yuvarlamasından
  kaynaklanır; hash farkı bu yüzdendir.
- **`ortho_reference.png`:** piksel piksel aynı. Hash farkı PNG kodlayıcısından gelir.
- **Manifest:** yalnızca bu iki dosyanın hash'i farklı. Kapsam, ölçek, CRS dönüşümü,
  datum ve kuantalama aynı.
- **Yoğun kaynak denetimi** (`mars_rover.fidelity --source-dem <HTTP>`): en büyük
  fark 5,0e-10 m.

Kapsam ve ölçekler değişmedi:

| Özellik | Değer |
|---|---|
| Grid | 253 × 253 köşe, 1 m |
| Kapsam | 252 × 252 m |
| Yerel projeksiyon | AEQD, 18.4287659°K 77.4421842°D merkezli |
| Kaynak doğu-batı ölçek faktörü | 0,9487 |
| Düşey kuantalama | 0,12 mm |

## 2. Belva bölgesi

Belva neden yeni bir kaynak gerektiriyor? **[ölçüldü]**

- Belva'nın merkezi Jezero_C DTM'inin batı kenarının ~188 m dışında.
- Belva merkezli 1,3 km'lik pencere Jezero_C'de %97,7 NoData olur.
- Aynı USGS Mars 2020 TRN setindeki **Jezero_DL** DTM'i ise 2 km'lik
  pencerede %0 NoData verir.

**Kaynak** (preset: [Config/Mars/belva.json](../Config/Mars/belva.json)):

- **Ürün:** USGS "High-Resolution Imaging Science Experiment Digital Terrain Model
  Jezero_DL; PSP_002387_1985, PSP_003798_1985".
- **Yayın ve DOI:** 2020-07-24, [10.5066/P9REJ9JN](https://doi.org/10.5066/P9REJ9JN).
- **Üreticiler:** Fergason, Galuszka, Hare, Mayer, Redding, Smith.
- **Erişim kısıtı:** metadata'ya göre "None".
- **Metadata:** özgün FGDC XML dosyası pakete bayt bayt eklendi.
- **Dosya:** 114.658.582 bayt, SHA-256
  `1cd061c66ce4a9f38afade744256009b7e5c1fa40d8ddad3d14d6eba887bbdc1`
  (2026-11-25'te tamamı indirildi; `.cache/` altında, Git'e eklenmedi).
- **Doğruluk [kaynak metni]:** metadata'daki doğruluk alanları yatayda 1,1 ve
  düşeyde 0,4 değerlerini birimsiz verir. Bu değerler her post için hata sınırı değildir.

**Krater [ölçüldü]**

- Jezero_DL üzerinde yapılan krater uydurması merkezi 18.48296°K, 77.37946°D verdi.
  Bu, USGS Gazetteer'daki 15872 numaralı kayıtla uyumlu
  ([kaynak metni]: 18.48°K, 77.38°D, çap 0,90 km).
- Kenar çapı ~940 m. Ortalama kenardan tabana derinlik ~74 m; en alçak kenar
  noktasından ~46 m.

**Paket [ölçüldü]**

- **Kaynak penceresi:** sütun 1419, satır 5656, 1401 × 1321.
- **Yerel grid:** 1281 × 1281 köşe, 1 m, 1280 × 1280 m. Krater merkezi yerel
  (640, 640) noktasına mm içinde düşüyor.
- **Unreal Landscape:** 21 × 21 bileşen (63'lük bölüm), 1324 köşe.
- **Yükseklik:** aralık 98,1 m; kuantalama 1,5 mm. r16 ile CSV arasındaki en büyük
  fark 0,75 mm.
- **Kaynak denetimi:** 1.640.961 postun tamamı kaynakla karşılaştırıldı; en büyük
  fark 5,0e-10 m.
- **Eğrilik:** düzlemsel yükseklik alanı köşelerde referans küresinden 0,12 m sapar.
  Bu sapma kabul edilip kaydedildi.
- **Eğim:** 2 m tabanla p95 20,8° ve maksimum 54°. Alanın %15,6'sı 15°'nin üzerinde,
  yani rota için çoğunlukla engel. Krater tabanı da düz değil (merkezde 20 m içinde 11,7°).
- **Ortogörüntü:** bu pakette yok. DL çiftine ait kayıtlı bir ortogörüntü seçilmedi.

Büyük paket (27 MB) Git'e eklenmedi. Üretim komutu ve doğrulama durumu
[7. bölümdedir](#7-yeniden-üretim); dosya hash'leri JSON kanıtındadır.

**Unreal sahneleri [ölçüldü]**

`mars_setup.build` iki yeni seviye oluşturdu: `/Game/Mars/BelvaLab01` (ölçülmüş,
kayasız) ve `/Game/Mars/BelvaRockLab01` (sentetik kayalı).

- **Spawn hücresi:** (180, 300), kraterin batı-güneybatısında. 30 m içinde en büyük
  eğim 5,5°.
- **Doğrulama:** heightmap birebir doğrulandı. Basit ve karmaşık çarpışmada 365
  noktada 730 iz atıldı; en büyük sapma 0,4 mm (tolerans 2 mm).
- **Kapsam dışı:** her üçgen veya tekerlek–zemin fiziği bu doğrulamanın parçası değildir.

## 3. Mars 2020 stereo XYZ örneği

Sol 420 için şu ürün seçildi:

- **XYZ:** `NLF_0420_0704212988_190XYZ_N0232532NCAM13419_0A0195J01.IMG`
  (PDS Imaging Node, `mars2020_navcam_ops_stereo`).
- **Görüntü:** eşleşen sol RAS görüntüsü.
- **Atıf:** NASA/JPL-Caltech. Navcam bundle DOI
  [10.17189/x2k7-1v48](https://doi.org/10.17189/x2k7-1v48).

`python -m mars_rover.m2020_xyz <IMG>` çıktısı **[ölçüldü]**:

- **Ürün tipi ve çerçeve:** `XYZ_FILTER_MAP`, `SITE_FRAME` 23, metre.
- **Boyut:** 2560 × 960, geçerli piksel %38,7. Geçersiz piksel (0, 0, 0) olarak kodlu.
- **Mesafe:** noktaların %56'sı rover'a 10 m'den yakın.
- **SHA-256:** `02840cf2…4df94a`.

Örnek bu artımda **hiçbir sahneye yerleştirilmedi.** Nedenler:

- Rover, PLACES'e göre 18.448788°K, 77.401642°D'de. Bu nokta Jezero_C paketinin
  merkezinden 2,57 km, Belva paketinin merkezinden 2,38 km uzakta.
- Etiketteki telemetri pozu ile PDS PLACES `best_tactical` çözümü ~4,8 m farklı.
- Doğru yerleşim için şu adımlar gerekir:
  1. Noktaları etiketteki pozla ROVER_NAV çerçevesine geri çevirmek.
  2. PLACES pozunu uygulamak.
  3. O konumu kapsayan yeni bir DEM paketi üretmek.
  4. DEM ile mesh arasındaki farkı ölçmek.

## 4. Sentetik kaya senaryosu (ölçülmüş Mars nesnesi DEĞİL)

`python -m mars_rover.rock_scenario` aynı tohumla aynı yerleşimi üretir. Kaya
boyutları rover ölçülerinden türetilir: tekerlek yarıçapı 0,0886 m, gövde boşluğu
0,089 m, harita engel eşiği 0,15 m.

| Kaya | Görünen yükseklik | Kural | Rover yanından geçerken harita **[ölçüldü]** |
|---|---|---|---|
| pebble | 0,044 m | 0,5 × tekerlek yarıçapı | serbest |
| belly | 0,089 m | 1 × gövde boşluğu | serbest |
| threshold | 0,151 m | 1,7 × tekerlek yarıçapı | engel (ground_truth) |
| blocker | 0,301 m | 3,4 × tekerlek yarıçapı | engel (lidar, ground_truth) |
| detour_blocker | 0,301 m | 3,4 × tekerlek yarıçapı, rotanın üstünde | engel (lidar) |

Yerleşim ve doğrulama:

- **Konum:** kayalar, rover'ın ölçülen yönüne (−98,18°) göre yerleştirildi.
- **Biçim:** gömülme oranı %30 olan elipsoitler. `SYNTH_Rock_*` etiketi ve
  `synthetic_rock` tag'i taşırlar.
- **Çarpışma:** "complex as simple"; ölçeklenmiş üçgenleri tam izler.
- **Doğrulama:** `mars_rock_scenario.place` her kayaya basit ve karmaşık dikey iz
  atar. Ölçülen tepe yüksekliği her kayada tasarımla 0,1 mm içinde.
- **Görünürlük:** kayalar kameralarda (GT derinlik), CPU LiDAR'da ve çarpışma
  kanalında görünür.
- **Kapsam dışı:** tekerleğin bir kayanın üstünden geçmesi bu artımda sürülmedi.

## 5. Yerçekimi ve rover fiziği

**Yerçekimi [ölçüldü]**

- **Ayar:** dünya ayarında `global_gravity_z = -371 cm/s²` (proje varsayılanı −980).
- **Düşme testi:** PIE dünyasında 0,1 m yarıçaplı, sönümsüz bir küre 60 m'den
  düşürüldü (`mars_physics_probe`). Her karede kaydedilen 150 serbest düşme örneğine
  parabol uyduruldu.
- **Sonuç:** **g = 3,7100 m/s²**, kalıntı 0,04 mm.
- **Sönümlü koşular:** 0,01 doğrusal sönümlü iki koşu 3,66 ve 3,60 m/s² verdi. Bu,
  hıza orantılı sönümün beklenen sapmasıdır; yerçekimi hatası değildir.

**Rover taban çizgisi [ölçüldü]** (`/Game/Blueprints/Leo_Raph`)

| Özellik | Değer |
|---|---|
| Çalışma anı kütle | gövde 200 kg (150 kg override + kaynaklı 50 kg yük sensörü), 4 × 10 kg tekerlek; toplam 240 kg |
| Tekerlek çarpışması | 0,0886 m yarıçaplı küre (mesh genişliği 0,0836 m) |
| İz / dingil mesafesi | 0,38 / 0,39 m |
| Süspansiyon | Yok. Tekerlek kısıtları tüm doğrusal eksenleri ve swing'i kilitler, yalnız aks dönüşü serbest. |
| Tekerlek materyali | WheelPhysics: sürtünme 0,6, statik 0,2, MIN birleştirme, sekme 0 |
| Arazi materyali | Yok (motor varsayılanı) |
| Fizik adımı | substep açık, 8,33 ms, en fazla 8 |
| Durağan temas | 4,6° eğimde üç tekerlek zemine 0,01 cm içinde değiyor, BR 1 mm havada (rijit gövde) |

Referans karşılaştırma:

- SpaceR Raph URDF'i (`6b5722b`) şu değerleri verir: taban 3 kg, tekerlek 0,5 kg,
  tekerlek çarpışma yarıçapı 0,091 m, kinematik yarıçap 0,08 m, dingil 0,378 m,
  iz 0,384 m.
- Geometri Unreal ile birkaç mm içinde uyumlu, ama **kütle ~48 kat fazla**.
- URDF de bir simülasyon tanımıdır, tartılmış araç değildir.

**Değişiklik yapılmadı.** Nedenleri:

- Kütle, sürtünme veya süspansiyon değişikliği mevcut dönüş davranışını değiştirir.
- Sürtünme 0,6 ve statik 0,2 değerleri **[varsayım]**; Mars regoliti için ölçülmüş
  bir değer elimizde yok.
- `soil.csv` hâlâ yalnızca sınır maskesidir.

## 6. Sürüşler

İki sürüş de servisin `/goal` API'siyle gönderildi; dashboard'daki "Hedefe git"
düğmesi de aynı yolu kullanır. Oturumun tazelik kapıları değişmedi. Ortak koşullar:

- LiDAR geçici olarak CPU modundaydı (`--lidar-pose-source cpu_capture`); her
  sürüşten sonra GPU ayarına geri döndü.
- Telemetri `--telemetry-format unreal-tr-v1` ile okundu; editör log'unda Türkçe
  ondalık biçim görüldü.

| Sürüş | Seviye | Sonuç **[ölçüldü]** |
|---|---|---|
| Engel dolaşma | BelvaRockLab01 | `arrived` (mission `8bed5b13…`): 13,9 m'lik rota, 103 s, hedefe 0,24 m. Dolaşma kayasına kenardan ~1,65 m. 7 kısa sensör beklemesi. En yüksek eğim 8,1°. |
| Açık zemin | BelvaLab01 | `arrived` (mission `cb195e54…`): 25 m, 177 s, hedefe 0,24 m. Rotadan en büyük yanal sapma 3 cm. 0 sahte sensör hücresi. En yüksek eğim 6,6°. |
| Açık zemin, GPU LiDAR | BelvaLab01 | 13,9 s'de `blocked`. Kayasız sahnede rover çevresinde 214 GPU-LiDAR hücresi (bilinen sorun). |

Kayıtlar:

- Görev kaydı: `Saved/Mars/gorev-izleme-*-cffaea67…` ve `…-e91e0d38…`.
- Dashboard görüntüleri: `Saved/Mars/belvarocklab01-detour-dashboard.jpg` ve
  `belvalab01-open-ground-dashboard.jpg`.
- `Saved/` Git dışıdır.

`tools/mars_detour_probe.py --send` dört denemede de ön kontrolde hedef göndermeyi
reddetti. Sebep, GT yakalama yaşının 0,36–0,40 s olması (sınır 0,35 s). Oyun gerçek
zamana yakın çalışıyordu: telemetri 30 Hz, 6,06 s duvar saatinde 5,8 s oyun süresi.
Yani darboğaz FPS değil; 5 Hz GT yakalama, geri okuma ve işleme gecikmesi. Eşik
değiştirilmedi.

## 7. Yeniden üretim

**Git'te olanlar:** kod, preset, bu belge ve JSON kanıtı. JSON kanıtı şunları içerir:
kaynak ve paket hash'leri, kaya senaryosunun tamamı, yerleştirme ölçümleri, yerçekimi
uydurmaları, import özetleri ve sürüş özetleri.

**Yalnız bu makinede olanlar (Git dışı):**
- `generated/belva-lab-20261125/` (27 MB)
- `.cache/mars/jezero_dl.tif` (115 MB)
- `Content/Mars/BelvaLab01*` ve `Content/Mars/BelvaRockLab01*` seviyeleri (binary)
- `Saved/Mars/` altındaki ham import raporları, sensör yapılandırmaları, yerçekimi
  örnekleri, görev kayıtları ve dashboard görüntüleri

Adımlar ve doğrulama durumları:

| # | Adım | Komut | Durum |
|---|---|---|---|
| 1 | Belva paketi | `python -m mars_rover.prepare --preset Config/Mars/belva.json --output generated/belva-lab-NEW` | **Aynı makinede yeniden koşuldu [ölçüldü].** Beş dosya ve manifest bayt bayt aynı çıktı (manifest `9fb81a1a…`). Kaynak HTTPS'ten okundu, süre 12 s. |
| 2 | Kaynak denetimi | `python -m mars_rover.fidelity --manifest generated/belva-lab-NEW/manifest.json --source-dem <preset URL'si veya yerel kopya> --output <yeni.json>` | Bir kez koşuldu. |
| 3 | Kaya senaryosu | `python -m mars_rover.rock_scenario --manifest generated/belva-lab-NEW/manifest.json --start 180 300 --heading-deg -98.18 --output <yeni.json>` | **Aynı makinede yeniden koşuldu [ölçüldü].** SHA-256 `3fd909ba…` ile bayt bayt aynı. |
| 4 | Unreal sahnesi | Editör Python'u: `mars_setup.build(<manifest>, level_path="/Game/Mars/<YeniAd>", rover_blueprint="/Game/Blueprints/Leo_Raph", spawn_cell=(180, 300), navigation_config_path=<yeni sensör json>, report_path=<yeni rapor json>)` | Her seviye için bir kez çalıştırıldı (BelvaLab01, BelvaRockLab01). Yeniden kurulum denenmedi. |
| 5 | Kaya yerleştirme | Adında "Rock" geçen, kayasız yeni seviyede: `mars_rock_scenario.place(<senaryo.json>)` | Bir kez çalıştırıldı. Her kaya basit ve karmaşık izle doğrulandı. |
| 6 | Yerçekimi | Adında "Lab" geçen seviyede `mars_physics_probe.place_drop_probe()`, sonra Play, `start_recording()` ve `stop_recording(<yeni.json>)` | Üç koşu yapıldı. 3. koşuda probun sönümü elle 0'a çekilmişti; `place_drop_probe` artık bunu kendisi yapıyor (editörde yeniden koşulmadı). |
| 7 | Sürüşler | `python -m mars_rover.nav_service --sensors <sensör json> --manifest <manifest> --telemetry-format unreal-tr-v1 --lidar-pose-source cpu_capture`, geçici `mars_cpu_lidar_setup.apply()`, Play, `POST /goal {"x", "y"}` | Her sürüş bir kez yapıldı. |

**Yazılım sürümleri (bu makine):** Python 3.12.10, numpy 2.3.5, rasterio 1.5.2
(GDAL 3.12.2), pyproj 3.8.0 (PROJ 9.8.1), Unreal Engine 5.7.

**Başka bir makinede hiçbir adım denenmedi.** Farklı GDAL ya da PROJ sürümleri farklı
baytlar üretebilir. Bu durumda paketi JSON'daki hash'lerle ve `fidelity` raporuyla
karşılaştırmak gerekir.

## Sınırlar

- Belva yükseklikleri ölçülmüş bir stereo DTM'den gelir. 1 m post aralığı efektif
  çözünürlük değildir; 1 m'nin altındaki taşlar yoktur.
- Sentetik kayalar boru hattı testidir. Tekerlek–kaya teması sürülmedi; yalnız iz
  çarpışmasıyla doğrulandı.
- Yerçekimi ölçümü motorun serbest bir cisme uyguladığı ivmedir. Toprak, kayma ve
  çekiş doğrulanmış değildir.
- Kütle, sürtünme ve süspansiyon yukarıdaki taban değerlerinde kaldı. Gerçek araçla
  karşılaştırma yapılmadı.
- Sürüşler birer kez yapıldı; istatistik değildir.
- Sahnede kameralar hâlâ çok karanlık.
- GPU LiDAR sahte hücreleri çözülmedi.

## Sonraki adımlar

1. GT yakalama gecikmesini azaltmak, örneğin yakalama hızı veya geri okuma
   kuyruğuyla. Eşik değiştirilmeyecek.
2. Sol 420 XYZ'sini PLACES pozuyla yerleştirmek için o konumu kapsayan yeni bir DEM
   paketi üretmek ve DEM–mesh farkını ölçmek.
3. Tekerleğin `belly` ve `threshold` kayalarının üstünden geçtiği kontrollü bir
   sürüş yapmak ve tırmanma ya da takılmayı ölçmek.
4. Eğim rampası testi: 5–20°'de durağan tutunma ve tırmanma.
5. Kütleyi parametrik hale getirip dönüş davranışıyla birlikte A/B ölçmek.
