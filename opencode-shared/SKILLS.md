# Ortak OpenCode skill listesi

Bu liste ortak paketin içeriğidir. Laptop veya ofis PC'sine kurulmuş olduğunu tek başına göstermez. Her bilgisayarda kurulum sonunda gerçek keşif listesi yazdırılır.

| Skill | İşlev | Kaynak | Sabit sürüm | Kullanım |
| --- | --- | --- | --- | --- |
| security-audit | Kod tabanında güvenlik açıklarını araştırır, bağımsız ajanlarla doğrular ve kanıta dayalı rapor üretir. | [Cloudflare](https://github.com/cloudflare/security-audit-skill) | c1c8a8c14710 | OpenCode içinde security-audit skill'ini yükleyerek güvenlik incelemesi iste. |

Skill modeli zorunlu kılmaz. OpenCode içinde DeepSeek sağlayıcısını seç; alt ajanlara ayrı bir model atanmışsa onları da kontrol et.

Tam denetim için Node.js, alt ajan yetkileri ve kaynak koddan türetilen testlerin çalıştırılabileceği uygun işletim sistemi izolasyonu gerekir. Kurulum bu test izolasyonunu oluşturmaz. Bu skill bir güvenlik raporu ve düzeltme önerileri üretir; uygulama kodunu değiştiren bir otomatik düzeltme akışı değildir.

## Bilgisayarda bulunan diğer skill'ler

```bash
~/.local/bin/skills-list
~/.local/bin/skills-list --project /tam/proje/yolu
~/.local/bin/skills-list --json
```

Liste global OpenCode, `.agents` ve `.claude` skill klasörlerini; belirtilen proje ve Git çalışma ağacı içindeki üst klasörlerdeki skill'leri tarar. Proje dışındaki başka repo'ları taramaz. Aynı adlı birden fazla skill'i belirtir. Liste dosya keşfini gösterir; OpenCode izinleri ve modelin skill'i yüklemesi ayrıca doğrulanmalıdır.

Ortak paketin makineye bağlı olmayan içeriği `manifest.json` dosyasındadır. Bilgisayarda bulunan kişisel skill'ler ortak listeye kendiliğinden eklenmez.
