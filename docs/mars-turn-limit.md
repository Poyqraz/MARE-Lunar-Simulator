# Simülasyonda dönüş hızı sınırı

Navigasyon servisine isteğe bağlı `--max-turn-rate-deg-s 20` eklenirse rota
takipçisinin komutladığı açısal hız 20 derece/s ile sınırlandırılır. Seçenek
verilmezse mevcut 0,6 rad/s (yaklaşık 34,38 derece/s) sınırı korunur. Seçenek
sıfırdan büyük olmalı ve varsayılan sınırı aşmamalıdır.

Bu ayar ivme sınırlaması veya kademeli komut geçişi değildir. Fizik motorunun
gerçek açısal hızını, teker temasını ya da aracın devrilmesini garanti etmez.
Yavaş dönme rota takibini değiştirebilir; sonucu Unreal simülasyonunda gözleyin.
Engel, bayat sensör veya poz, bağlantı kaybı ve dur komutu için mevcut anlık
durdurma davranışı korunur.
