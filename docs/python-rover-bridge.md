# Python rover kontrolu (istege bagli)

Mars ortamı rover olmadan da kurulabilir; bu motor köprüsü isteğe bağlıdır.
Haritadan hedef seçimi ve mevcut TCP LiDAR/derinlikle kapalı çevrim için
[ROS'suz navigasyon servisini](mars-navigation.md) kullanın. Servis bu motor
köprüsünü içerir; ikisini aynı anda başlatmayın. Aşağıdaki bağımsız motor
akışı hâlâ kendi Python kontrol kodunu bağlamak için kullanılabilir.
Ana kurulum icin [Mars rehberi](mars-jezero.md) kullanilir.
Referans rover istenirse Unreal Python konsolunda ayri bir yeni seviyede:

```python
import mars_setup
job = mars_setup.build(level_path="/Game/Mars/JezeroRover", rover_blueprint="/Game/Blueprints/Leo_Raph")
```

Kendi CAD ve kontrol yazilimi bu degisiklikte yoktur. Referans rover'in
Mars fizigi/surus kalibrasyonu halen gercek Unreal testi gerektirir.
Veri hazirlama/test bagimliliklari Python 3.12 gerektirir; standart kutuphane
kullanan motor koprusu Unreal disinda bagimsiz olarak calisir.

## 3. ROS kullanmadan Python'dan sürme

Köprü Python standart kütüphanesini kullanır; ROS kurmak zorunlu değildir.
Normal bir Windows Python 3.11/3.12 terminalinde, repo kökünde:

```bash
python -m mars_rover.bridge --max-speed 0.15
```

Varsayılan tel biçimi katı JSON'dur. Yalnız ham TCP kaydıyla Türkçe sayı
biçimi doğrulanan simülasyon için `--telemetry-format unreal-tr-v1` seçeneği
vardır; üreticinin yerel ayarının değişmediğini denetlemek gerekir. Sınırlama
ve tanı adımları [Windows test rehberi §4.8](mars-windows-full-test.md#48-rover-telemetrisi-ayrışmıyorsa-ham-tcp-tanısı)
içindedir. Bu uyumluluk modu üreticideki JSON sorununu kalıcı olarak çözmez.

**Önce köprüyü başlatın, sonra Unreal'da Play yapın.** Rover TCP 3003'e
bağlanır, yerel HTTP API 8765'te açılır. Referans rover'ın bağlantı ayarları
korunur. Köprü yalnızca `127.0.0.1` üzerinden dinler.

Mevcut GNC Docker sistemi açıksa `component_rover_leo_raph` aynı portu
kullanır. GNC repo terminalinde şu iki bileşeni durdurun:

```bash
docker compose stop component_rover_leo_raph component_path_planner
```

Ardından köprüyü başlatın ve Play'i yeniden başlatın. Bu mod GNC'nin odometri
ve TF yayınlayan rover düğümünün yerini tutmaz; sadece motor komutları ile ham
poz telemetrisini taşır. Kamera/LiDAR ROS topic'leriyle çalışılacaksa ilgili GNC
sensör düğümleri ve uygun adaptör ayrıca gereklidir. Yeni navigasyon servisi
ise kamera/LiDAR TCP paketlerini ROS kullanmadan doğrudan okur.

Kendi Python kontrol döngünüzde:

```python
import time
from mars_rover.client import RoverClient

rover = RoverClient()
print(rover.status())  # connected=True olmalı
try:
    for _ in range(10):
        rover.wheels(FL=0.05, FR=0.08, BL=0.05, BR=0.08)
        time.sleep(0.1)
finally:
    rover.stop()
```

`FL/FR/BL/BR` sırasıyla ön sol, ön sağ, arka sol, arka sağdır. Değerler
**tekerlek çevresindeki doğrusal hız, m/s** cinsindedir; PWM veya RPM değildir.
RPM kullanıyorsanız `m/s = RPM × 2π × yarıçap(m) / 60` dönüşümünü yapın.
PWM için gerçek motor kalibrasyonu gerekir. Dört değer birbirinden farklı
olabilir. Hız sınırı aşılırsa dört hız birlikte ölçeklenerek oran korunur.

Üst düzey ileri/dönüş komutları için `rover.twist(0.1, 0.0)` kullanılır;
ilk değer m/s, ikincisi rad/s'dir. Pozitif dönüş sola doğrudur. Bu komut da
kontrol döngüsü içinde düzenli yenilenmelidir; örneğin yukarıdaki `wheels`
çağrısı yerine kullanılabilir. `/status` içinde `telemetry_unreal` ayrıştırılmış
UE telemetrisidir; `pose_local_m` metre ve yerel harita yönelimini verir. Bunlar
simülasyon pozudur, sensörden kestirilmiş SLAM konumu değildir.

Köprü **çalışırken**, varsayılan 0.3 saniye boyunca yeni komut gelmezse sıfır
hız gönderir; her yeni Play bağlantısı duruşla başlar. Geçersiz hız komutu da
duruşa geçirir. Kontrol kodu her koşulda `finally: stop()` kullanmalıdır.
Köprü işleminin zorla öldürülmesi veya ağın tamamen kopması halinde durmayı
garanti eden bir Unreal içi watchdog henüz yoktur. Bu geliştirme gerçek motor
sürücüsüne bağlanmış bir güvenlik sistemi olarak kullanılmamalıdır.

Varsayılan `--track 0.89` ve `--wheel-scale 1.82`, orijinal Leo_Raph ayarlarıdır;
kullanıcının aracının ölçüleri değildir ve Mars yerçekiminde yeniden
kalibre edilmelidir. İlk sürüşü düşük hızda, kısa süreli, görsel olarak izleyin.

## 4. Hazır GNC otonomisini Mars haritasıyla kullanma

Python köprüsü ile hazır GNC rover düğümü aynı anda kullanılmaz. Hazır GNC
otonomisine dönmek için köprüyü kapatın; aşağıdaki haritaları ayarlayıp GNC'yi
yeniden başlatın, sonra Play'i yeniden başlatın.

1. `Content/Mars/Jezero/elevation.csv` dosyasını GNC'deki
   `component_path_planner/maps/jezero_elevationMap.csv` yoluna kopyalayın.
2. `soil.csv` dosyasını aynı klasöre `jezero_soilMap.csv` adıyla kopyalayın.
3. Mevcut `component_path_planner/config/params.yaml` içinde yalnızca ilgili
   değerleri değiştirin; diğer ayarları koruyun:

```yaml
elevation_map_path: "maps/jezero_elevationMap.csv"
soil_map_path: "maps/jezero_soilMap.csv"
global_res: 1.0
```

4. `component_imu/config/params.yaml` içindeki yerçekimini `3.71` yapın.
5. Rover/planner hız, ivme, dönüş ve tork ayarlarını Mars için düşük hızdan
   başlayarak kalibre edin. Hazır Dünya ayarları doğrulanmış Mars ayarı değildir.
6. Haritalar ve ayarlar paket içine kurulduğu için GNC bileşenlerini yeniden
   derleyin/oluşturun; yalnızca restart yeterli değildir. GNC'nin
   [uygulama talimatlarını](https://github.com/raulcastar/GNC-Moon-Simulator/blob/main/docs/setup.md#applying-code-changes)
   izleyin.

Bu akışın gerçek Unreal içinde hedefe sürüş kabul testi henüz yapılmamıştır.
GNC'nin küresel haritası önceden bilinen arazidir; bunu bilinmeyen Mars'ta
tamamen sensörden harita çıkaran SLAM başarısı olarak yorumlamayın.

## 5. SolidWorks modelini bağlama

`.SLDASM` ile referans verdiği tüm `.SLDPRT` ve alt montajları birlikte tutun.
UE 5.7/SolidWorks sürümünüzle uyumlu Datasmith CAD veya dışa aktarma yolunu
doğrulayın; gerekirse STEP kullanın. Görsel aktarım, CAD montaj ilişkilerini
otomatik olarak Unreal motor/fizik bağlantılarına dönüştürmez.

`Leo_Raph` Blueprint'ini kopyalayarak gövde ve dört tekerlek mesh'ini değiştirin.
Tekerlek pivotları, constraint eksenleri, kütle, ağırlık merkezi, çarpışma
şekilleri ve sürtünme ölçülmelidir. İlk kopyada TCP grafiği ve FL/FR/BL/BR
eşlemesini koruyun; bağlantıların bu komutları gerçekten dört ayrı tekerleğe
uyguladığını düşük hızla kontrol edin. Gerekli veri henüz sağlanmadığı için
bu PR kullanıcıya özel CAD veya motor kalibrasyonu içermez.

Yeni seviye oluştururken `rover_blueprint="/Game/Blueprints/KendiRover"`
verilebilir. Kamera takip kodundaki `ROVER_PREFIXES` ve sensor/TF tanımları da
yeni Blueprint için uyarlanmalıdır. Kamera/LiDAR taşınırsa GNC URDF/TF,
stereo baseline ve FOV ayarları birlikte güncellenir.

## 6. Testler ve sonraki geliştirme

Repo kökünde:

```bash
python -m pip install -r requirements-mars-dev.txt
python -m pytest tests -q
```

CI aynı testleri Windows ve Linux Python 3.12'de çalıştırır. Testler gerçek
soket haberleşmesini ve GeoTIFF okumasını kapsar; Unreal API çağrıları sahte
engine ile sözleşme düzeyinde test edilir. Gerçek kaynak rasterden bağımsız
okunan beş nokta, paketlenen Jezero kesitinin yönünü/yüksekliğini denetler.
CI için ağdan arazi indirilmez ve Unreal kurulumu gerekmez.

| Sıra | Geliştirme | Kabul ölçütü |
|---|---|---|
| Şimdi | Gerçek DEM, koordinatlar, motor köprüsü | Python testleri; UE içe aktarım ve düşük hızlı manuel sürüş kontrolü |
| Sonra | Kullanıcının CAD ve Python yazılımı | Dört motor doğru eşleşir; fiziksel ölçüler tutar; komut kaybında UE içinde durur |
| Ardından | Jezero üzerinde hedef/parkur takibi | Birden çok başlangıçtan hedef hatası, süre, çarpışma ve yeniden planlama ölçülür |
| Algılama | LiDAR/kamera ve sensörden konum | Gürültü, gölge, gecikme ve konum hatasında davranış ölçülür |
| İleri fizik | Kayma, batma, gevşek zemin | Ölçülmüş motor/zemin verisiyle karşılaştırılır; varsayılan sürtünme başarı sayılmaz |

Beyin fırtınası için üç yararlı deney: motor başına tork/hız sınırlandırma ile
yokuşta denge; aynı rotayı farklı başlangıç/güneş koşullarında kıyaslama;
komut edilen hareketle ölçülen hareketin farkından kayma göstergesi üretme.
Bunlar henüz uygulanmış özellikler değil, test edilebilir sonraki deneylerdir.
