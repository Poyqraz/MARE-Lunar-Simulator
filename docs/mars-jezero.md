# Jezero Krateri'ni Unreal Engine 5.7'de oluşturma

Bu fork'un mevcut odağı **doğru ölçekli Mars ortamıdır**. Kendi rover modeliniz
veya kontrol kodunuz gerekmez. Başlangıç verisi gerçek Jezero topografyasından
252 × 252 m'lik yerel bir kesit ve aynı bölgeden kaydedilmiş gri tonlu
HiRISE ortogörüntüsüdür. Dünya/Ay verisi Mars diye kabul edilmez.

## Kurulum

Windows, Unreal Engine **5.7**, Visual Studio 2022 C++ araçları ve Git LFS
gerekir. Yeni editor betikleri için PythonScriptPlugin, EditorScriptingUtilities
ve UnrealDEMLandscape proje dosyasında açıkça etkindir. Mevcut Unreal varlıkları
LFS'dedir; yeni küçük Jezero veri kesiti normal Git commit'inde bulunur.

```bash
git lfs install
git clone --branch codex/mars-jezero-reviewed https://github.com/Poyqraz/MARE-Lunar-Simulator.git
cd MARE-Lunar-Simulator
git lfs pull
```

`Moon_Simulator.uproject` açılırken plugin modüllerini derletin. Play kapalı
olmalı ve açık çalışmanız kaydedilmiş olmalıdır. Ay seviyeleri korunur;
henüz üretilmemiş bir Mars haritası proje başlangıç haritası yapılmaz.

## İki ayrı görünüm

| Mod | İçerik | Kullanım |
|---|---|---|
| `simulation` | Ölçülmüş arazi, temsili renk/pürüzlülük, hareketli güneş ve Mars yarıçaplı SkyAtmosphere | Geometri, ışık ve daha sonra rover denemeleri |
| `orbital_reference` | Aynı arazide kayıtlı, yeniden ışıklandırılmayan gri HiRISE görüntüsü | Yön/yerleşim karşılaştırması ve yüzeyin kaynak görüntüdeki görünümü |

Ortogörüntü zaten çekim anındaki ışık ve gölgeleri taşır. Bu nedenle normal
simülasyon malzemesine albedo diye yapıştırılmaz; referans modunda dinamik
güneş/atmosfer eklenmez. Gri bant gerçek renk değildir. Temsili malzeme de
ölçülmüş toprak bileşimi veya albedo değildir.

Unreal Output Log konsolunu **Python** yapıp simülasyon ortamını oluşturun:

```python
import mars_setup
job = mars_setup.build(report_path=r"C:/temp/jezero-import.json")
```

`job['status']` önce `importing`, sonra `saved` veya `failed` olur. Betik,
yükseklikleri plugin üzerinden geri okuyup dosyayla eşleştirmeden haritayı
kaydetmez. Başarı log'u: **heightmap verified and level saved**.
Beklerken Play'e geçmeyin veya başka dünya açmayın. Dünya değişirse, Play
başlarsa, hedef harita zaten varsa veya ikinci içe aktarım başlatılırsa
işlem kaydetmek yerine durur. Sonuç `/Game/Mars/Jezero` seviyesidir.

Ayrı referans seviyesini oluşturmak için önce mevcut çalışmayı kaydedin:

```python
reference = mars_setup.build(
    level_path="/Game/Mars/JezeroReference",
    mode="orbital_reference",
    report_path=r"C:/temp/jezero-reference-import.json",
)
```

Varsayılan olarak rover yerleştirilmez. Editor viewport'unda araziyi inceleyin;
Play'de Unreal'ın serbest kamera/pawn davranışı seçili GameMode'a bağlıdır.
İsteğe bağlı referans rover ve Python motor köprüsü ayrı
[rover rehberinde](python-rover-bridge.md) anlatılır.

## Terminal kontrolleri

Veri hazırlama ve Python testleri için **Python 3.12** kullanın. Unreal'ın
gömülü Python'una NumPy/rasterio kurmayın; editor betikleri standart kütüphane kullanır.

```bash
python -m pip install -r requirements-mars-dev.txt
python -m pytest tests -q
python -m ruff check mars_rover tests Content/Python/mars_setup.py Content/Python/mars_scene.py Content/Python/mars_materials.py tools/unreal_mars_smoke.py
```

Gerçek Windows editor denetimi ayrı UE işlemi açar, benzersiz bir QA seviyesi
oluşturur, dosyadan yükseklik geri okumasını karşılaştırır ve JSON raporu arar:

```powershell
python -m mars_rover.unreal_check --editor "C:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor.exe"
python -m mars_rover.unreal_check --editor "C:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor.exe" --mode orbital_reference
```

Rapor/log `Saved/Mars/` altındadır. Yalnızca editor çıkış kodu 0 diye başarı
verilmez; raporun `status=saved` ve `heightmap_verified=true` olması gerekir.
Başlangıç betikleri editor varlıklarını kirletirse kaydetme önkoşulu hata
verebilir; log'u inceleyin ve interaktif editor akışıyla doğrulayın.

**Bu terminal denetimi GPU görüntüsünün doğru göründüğünü veya rover'ın
başarıyla sürdüğünü kanıtlamaz.** `visual_qa_passed` ve `gpu_render_verified`
kendiliğinden true yapılmaz. Bu geliştirme ortamında UE kurulu değildir;
Windows'taki gerçek editor denetimi henüz çalıştırılmamıştır.

## Veri hattı ve doğruluk sınırları

Kaynak equirectangular harita enlemi yaklaşık 18.4288° olan Jezero'da
doğu–batı ölçekte `0.9487174` zemin/harita oranına sahiptir. Bu nedenle kaynak
harita metresi doğrudan Unreal metresi sayılmaz. Önce aynı Mars referans küresi
üzerinde yerel azimutal eşuzaklıklı haritaya geçilir; 253 × 253 köşe, 1 m
aralıkla 252 × 252 m yerel referans-küre kapsamı oluşturur.

- Yerel x doğu, y kuzey, z yukarı; Unreal konumu `(-x, y, z) × 100 cm`.
- CSV satırları kuzeye artar. PNG satırları normal görüntü yönünde güneye artar.
- Görüntü UV'si `u=x/252`, `v=1-y/252`; aynalama ile dikey çevirme karıştırılmaz.
- Z için kesitin minimum yüksekliği çıkarılır; gerçek datum ofseti manifestte saklanır.
- Yükseklik enterpolasyonu iki doğrultuda noktasal bilineerdir; transform yaklaşımı kapalıdır.
- Sıfır/negatif yükseklik geçerlidir. Eksik veri uydurma çukur/düzlükle doldurulmaz.
- `soil.csv` yalnızca sınır/no-go maskesidir; jeoloji veya çekiş ölçümü değildir.

1 m örnekleme aralığı, 1 m veya santimetre doğruluk garantisi değildir.
Tekerlek ölçeğindeki taşlar/gevşek zemin eksiktir. Yerel düz yükseklik alanında
gezegen eğriliği ayrıca yer değiştirme olarak uygulanmaz; bu kesitin en uzak
köşesinde referans-küreye göre ihmal edilen sag yaklaşık 4.7 mm'dir. Datum,
stereo eşleme ve gerçek zemin belirsizlikleri bunun üzerindedir.

Sahnenin nominal yerçekimi 3.71 m/s²'dir. SkyAtmosphere yarıçapı veri referans
küresinden alınır, Dünya ozon katmanı kaldırılır. NASA'nın nominal 11 km ölçek
yüksekliği kullanılır; RGB saçılma/toz katsayıları, güneş pozu, 30 klux ve pozlama
**kalibre edilmemiş görüntüleme tercihleridir**. Bir Mars gününe/mevsimine ait
ölçülmüş atmosfer veya radyometrik sensör modeli olduğu iddia edilmez.

## Daha büyük veya başka kesit

Hazır veri internet gerektirmez. Yeniden üretim resmi kaynaklardan HTTP aralık
okuması yapar; yeni çıktı klasörü seçin:

```bash
python -m mars_rover.prepare --output generated/jezero
```

`Config/Mars/jezero.json` kaynak, pencere ve yerel grid ayarlarını kaydeder.
Kendi Mars DEM'iniz için `--source`, `--window COL ROW WIDTH HEIGHT`,
`--metric-size` ve `--resolution`; eşleşen görüntü için `--ortho-source`
kullanılabilir. `--source` değiştiğinde bölge adını açıkça `--region` ile verin.
Kaynak pencere hedefi tamamen kapsamalıdır. Dünya/Ay CRS'si,
derece birimi, döndürülmüş/kare olmayan DEM ve NoData kesitleri reddedilir.
Gereken projeksiyon/yeniden örnekleme GIS aşamasında açıkça yapılmalıdır.

Tek Landscape otomatik yolunda en fazla 4097 köşe/kenar ve 1024 component
desteklenir; yerel grid aracı standart boyutlar için tek sayı 3..4033 ve
en fazla 4096 m kapsam kullanır. Büyük dünya/tiled World Partition ayrı
geliştirme gerektirir; bu kesiti tüm Mars'ın simülasyonu saymayın.

[Kaynak ve araştırma kararları](mars-research.md) · [Test/review raporu](mars-validation.md)
