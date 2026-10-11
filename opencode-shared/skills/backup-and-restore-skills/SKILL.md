---
name: backup-and-restore-skills
description: Skill klasörlerini destek dosyaları ve farklı sürümleriyle tek taşınabilir ZIP dosyasında yedekle ve çevrimdışı geri yükle. Bilgisayara format atma, laptop ile ofis arasında taşıma, tüm skilleri kaydetme veya yeniden kurma isteklerinde kullan.
---

# Skill yedekleme ve geri yükleme

Linux/WSL içinde Python 3.10 veya üzerini kullan. Önce bulunduğun ortamın kullanıcının gerçek bilgisayarı olup olmadığını doğrula. Uzak bir çalışma ortamındaki taramayı laptop yedeği olarak sunma.

Bu klasördeki `scripts/skills_backup.py` dosyasını kullan. Güncel ev klasörünü ve proje köklerini tara; var olan laptop/ofis envanterlerini otomatik olarak kontrol et. Ek disklerdeki projeleri `--root /mnt/d/projeler` ile ekle. SKILL.md dosyalarıyla birlikte scripts, references, assets ve klasör içindeki diğer kaynakları koru. Aynı isimli farklı içerikleri birleştirme.

```bash
python3 scripts/skills_backup.py backup --device laptop --output "$HOME/digicut-skills-yedek.zip"
```

Çıkış kodunu ve arşivdeki SKILLS.md raporunu kontrol et. Yalnızca komut 0 döndüğünde ve "Yedek doğrulandı" yazdığında doğrulanmış yedek olarak bildir. Eksik envanter konumlarını veya okunamayan skill kaynaklarını çözmeden format için hazır olduğunu söyleme. Tarama kapsamını ve uyarıları açıkla. Oluşan ZIP'i formatlanmayacak bir NAS, USB veya diğer bilgisayarda saklat.

Korunmuş ZIP tek başına çalışır; kaynak repo, eski kullanıcı adı ve internet gerekmez. Yeni cihazda Python ve OpenCode'u kur, projeleri Git'ten klonla, ardından:

```bash
python3 digicut-skills-yedek.zip list
python3 digicut-skills-yedek.zip restore --dry-run
python3 digicut-skills-yedek.zip restore
```

Ev klasörünü yeni kullanıcıya otomatik eşle. Değişen proje köklerini `--map /eski/projeler=/yeni/projeler` ile eşle. Başka disklerden alınan kökler için mutlaka eşleme ver. Mevcut farklı skill klasörlerinin otomatik geri dönüş kopyalarını koru. Projelere özel skilleri topluca globale taşıma; inceleme koleksiyonlarını etkin kullanım diye tanıtma.

Geri yükleme sonrası OpenCode'u yeniden aç ve yerel `skill` aracıyla yüklemeyi doğrula. Dosyanın geri gelmesini, gerekli haricî araçların kurulu veya modelin skill'i yüklemiş olmasıyla eşitleme. Bağımlılık, kapsam, symlink ve istisna ayrıntıları için `references/restore.md` dosyasını oku.
