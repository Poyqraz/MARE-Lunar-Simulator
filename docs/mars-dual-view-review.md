# Uydu–rover planının yeniden incelemesi ve A1 teslimi

28 Ekim 2026. İncelenen plan: `8b6243ec90afeac2f9b268763b0282d7b4df9883`,
ağaç `bafe1885b677bb37b267c00464b885f441247781`. Bu inceleme kameranın gerçekten
çalıştığına onay değildir. Kontrol kodu, kaynak/koordinat sözleşmeleri ve
geliştirme sırası ayrı değerlendirildi. A1 değişikliği temel PR'ın üzerine
bağımlı bir feature dalında tutulur.

## Sonuç ve düzeltilen plan kararları

İki görünümün aynı görevi okuması, operatör kamerasının sensör kameralarından
ayrı olması ve dünya malzemelerinin görünüm düğmesiyle değiştirilmemesi doğru
entegrasyon yönüdür. Yalnız görüntü düğmesi eklemek görev geçmişi ve hedef
koordinatları için yeterli değildir. Yeniden inceleme şu düzeltmeleri getirdi:

1. **Bağımlılık:** A0 native kabulü, saf Python A1 geliştirmesini engellemez.
   Gerçek UE kabulü A2/A3/A6'nın tamamlandı sayılması için gereklidir.
2. **Tek kayıt:** İkinci bağımsız kontrol otoritesi oluşturmak yerine
   `NavigationSession` bir `MissionHistory` tutar. İzleme görev yokken ve
   terminal durumlarda da çalışır; motor kararı ayrı bir adımdır.
3. **Mesafe:** Köprüden her kontrol çevrimindeki son poz alınır; bütün ara
   paketler tutulmaz. Hesaplanan XY kiriş toplamı tam sürekli yol uzunluğu
   diye sunulmaz. Boşlukların mesafesi eklenmez ve eksiklik açıkça işaretlenir.
4. **Kalıcılık:** Bellekte görünümden bağımsız geçmiş ile crash-durable disk
   günlüğü farklı işlerdir. A1 sınırlı belleği ve açık JSON export'u teslim eder.
   Otomatik disk günlüğü/recovery sonraki iştir; tamamlandı sayılmaz.
5. **Kontrol otoritesi:** Rover'ın mevcut possession ilişkisi korunur;
   motorları Python köprüsü yönetir. Yeni kamera için pawn değiştirmek gerekmez.
6. **Kimlikler:** `coordinate_frame_id`, sensörün `frame_id` alanından ayrılır.
   Nanosaniye damgaları yeni JSON API'de string'dir. Harita/oturumla ilişkili
   zengin hedef onayı A3'te kalır; bugünkü basit `/goal` buna sahipmiş gibi sunulmaz.

## Kaynak ve koordinat doğrulaması

Mevcut manifest/DEM/ortogörüntü dosyaları değiştirilmedi. Yerel metre ve UE
`(-x,y,z)*100 cm`, harita `u=x/252, v=1-y/252` sözleşmeleri korunur.
Yeni `coordinate_frame_id` bu yerel referansı belirtir; sensor FLU ve optik
çerçevelerle karıştırılmaz. Ekrandan native collision seçimi henüz yoktur;
mevcut koordinat testlerinin geçmesi mouse raycast'in çalıştığını kanıtlamaz.

[HiRISE gözlem kataloğu](https://www.uahirise.org/ESP_045994_1985) tekrar
kontrol edildi: 19 Mayıs 2016 edinim tarihi, 28.1 cm/piksel özgün ölçek ve
25 cm/piksel harita projeksiyonu. Arşiv görüntüsü ile canlı simülasyon katmanı
ayrımı doğrulanır. Görüntü örneklemesi, DEM veya taş doğruluğu değildir.
[Cesium resmî rehberi](https://cesium.com/learn/unreal/unreal-moon-mars/)
Mars/özel ellipsoid desteğini ve Dünya varsayılanlarını doğrular; bunlar
mevcut AEQD/düşey referansın kendiliğinden eşleştiğini kanıtlamaz. Cesium ve
global collision entegrasyonu ileri aşamada kalır.

## Gerçek başarısızlık testleri ve yapılan düzeltmeler

İlk beş yeni test eski kodda başarısız oldu: idle poz `None`, görev snapshot
ve geçmiş sınıfı eksik, yavaş `/map` yanıtı kontrol kilidini tutuyordu.
Sonraki inceleme testleri üç ek hatayı gösterdi: gözlem başlamadan iptal edilen
göreve eski bitiş pozu atanması, eski görev izinin yeni oturum kimliğiyle
sunulması ve kayıp olmayan cursor'ın eksik sayılması. Bunlar düzeltilip
testler tekrar geçirildi.

| Kanıt | Sonuç |
|---|---|
| Idle, manuel duruş sonrası ve varış sonrası gözlem | Güncel poz ilerler; kapanmış görev kaydı değişmez |
| Yeni engel/replan | İlk plan ve başlangıç korunur, aktif plan sürümü değişir |
| Yeni Play / saat geri gitmesi / ani sıçrama | Eski hedef iptal; geçmiş ayrı oturumda korunur; sahte yol bağlantısı yok |
| Uzun poz boşluğu | Mesafe eklenmez, iz parçası kesilir, sensör sağlığı yeniden kurulmadan otonomi sürmez |
| Pause veya bayat poz | Önceki hız yeni ölçüm gibi sunulmaz |
| Bounded geçmiş / cursor / detached export | Limitler, kayıp sayıları ve kesinti açık; dışa aktarılan kopya canlı kaydı değiştiremez |
| Gerçek HTTP isteğinde geciktirilen map cevabı | Başka thread kontrol kilidini alabilir; eski kodda test başarısızdı |
| Snapshot/trail/events/export GET istekleri | Hedef ve görev kimliği değişmez |

Yavaş yanıt testi `threading.Event` ile cevabı durdurur; kontrol kilidi için
ayrı thread'de erişimi sınar. Gerçek localhost HTTP kullanır. Bu, toplam
native render/control gecikmesinin ölçüldüğü veya 30 FPS hedefine ulaşıldığı
anlamına gelmez.

Yerel tam paket: **122 test geçti**, Ruff ve compile kontrolleri başarılı.
Mevcut dört ölçülmüş Jezero rota/kinematik benchmark'ı tekrar geçti. Native UE
ve GPU çalıştırılmadı. Yeni test dosyası `tests/test_mars_mission.py`.

## A1'in sınırı ve izlenebilirliği

- R1: Sürekli poz gözlemi uygulandı; stale/invalid pozda hareket durur.
- R2: `/map` array snapshot'ı kısa kilitte alınır; liste/JSON ve ağ yazısı
  dışarı taşındı. Export kopyasının büyük kısmı da kilit dışında hazırlanır.
- R3: Başlangıç, ilk/aktif plan, sürümler, gözlenen iz, olaylar ve bounded
  arşiv uygulandı. Otomatik disk günlüğü kapsam dışıdır.
- R8: Yeni snapshot komutlanan teker m/s ile ham wire değerini ayırır.
  Ölçülmüş RPM/batarya/akım/sıcaklık kanalları hâlâ yoktur.
- R4–R7, R9–R10 ve native kamera/HUD/picking kabulü sonraki aşamalardadır.

Tam API ve sınırlar [navigasyon rehberinde](mars-navigation.md).
Görünüm geçişi henüz olmadığı için 100 gerçek kamera geçişi, native ekran
seçimi, paketli UE çalışma ve sensörlerin GPU davranışı testi henüz yapılmadı.
Bu maddeler Python testleriyle kapatılmadı. Zemin fiziği ve kullanıcının
CAD/motor kalibrasyonu bu paket tarafından değiştirilmedi.
