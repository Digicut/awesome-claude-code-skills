# İki bilgisayar için ortak OpenCode skill ortamı

Laptop ve ofis bilgisayarındaki mevcut WSL/Ubuntu geliştirme ortamlarını kullanır. Skill listesi ve kurulum araçları aynı Git dalından gelir. Her makine kendi yerel kaynağını kullanır; `oc` başlatıcısı Git kaynağını güncelleyip ortak listedeki sürümleri eşitler.

## İlk kurulum — her bilgisayarda bir kez

Git ve Python 3 kurulu WSL/Ubuntu terminalinde çalıştır:

```bash
git clone --branch opencode-shared-skills --single-branch https://github.com/Digicut/awesome-claude-code-skills.git "$HOME/.local/share/digicut-opencode-skills"
bash "$HOME/.local/share/digicut-opencode-skills/opencode-shared/setup.sh"
```

Hedef klasör zaten varsa tekrar klonlama. İçindeki origin ve dalın bu kaynakla eşleştiğini doğrula; ardından setup.sh'yi çalıştır. Bu iki komut Windows PowerShell/CMD yerine OpenCode'un çalıştığı WSL terminalinde çalıştırılmalı.

Kurulum, ortak skill'leri OpenCode'un global skill klasörüne bağlar. Bütün destek dosyaları resmi kaynak deposunun sabitlenmiş commit'inden indirilir. Skill kaynakları kullanıcının yerel veri klasöründe, kurulum durumu yerel durum klasöründe tutulur. XDG klasör ayarları varsa kullanılır.

## Her projede kullanım

Proje klasöründeyken:

```bash
~/.local/bin/oc
```

`~/.local/bin` PATH içinde ise kısa komutlar kullanılabilir:

```bash
oc
skills-list
skills-sync
```

`oc`, güncellemeden sonra gerçek `opencode` komutunu aynı proje klasöründe ve verilen argümanlarla başlatır. İnternet veya Git güncellemesi başarısızsa uyarı verir ve mevcut yerel kurulumla devam eder. Doğrudan `opencode` ile açmak da skill'leri kullanır fakat başlangıçta ortak kaynak eşitlemesi yapmaz.

İlk kurulumdan sonra açık OpenCode oturumunu yeniden başlat. Skill'in model tarafından yüklenmesini doğrulamak için `security-audit skill'ini yükle ve adını, kaynak klasörünü ve çalışma modlarını bildir; denetim başlatma` isteğini ver. Bu adım makinedeki gerçek OpenCode oturumunda yapılır.

## Güncelleme ve yeni skill ekleme

Ortak paketin tek listesi `manifest.json` dosyasıdır. Yeni skill için adı, kaynak deposu, tam commit SHA, skill klasörü ve gereken dosyaları ekle; değişikliği bu dala commit/push et. Her iki bilgisayarda sonraki `oc` başlangıcı veya `skills-sync` çalıştırması yeni listeyi uygular.

Upstream'in latest sürümü kendiliğinden alınmaz. Güncellemeden önce sürümü incele, dene ve manifest'teki sabit commit'i değiştir. Ortak depoda veya kaynak skill'de yerel değişiklikler varsa otomatik üzerine yazılmaz. Yeni kaynak indirmesi başarısız olursa kurulu bağlantı değiştirilmez.

## Mevcut skill ve komutlar

Aynı adlı yönetilmeyen bir skill varsa kurulum durur ve konumunu gösterir. Onu yedekleyerek ortak kaynağa geçirmek istediğinde:

```bash
bash "$HOME/.local/share/digicut-opencode-skills/opencode-shared/setup.sh" --adopt-existing
```

Yedek yolu yazdırılır. Kaynak dosyalar silinmez. Daha önce bu sistemin yönetmediği `oc`, `skills-list` veya `skills-sync` komutları varsa üzerine yazılmaz.

## DeepSeek ve makineye özel bilgiler

OpenCode içinde `/models` ile mevcut DeepSeek modelini seç. Skill kurulum araçları OpenCode model, API anahtarı veya kimlik doğrulama dosyalarını okumaz/kopyalamaz. Gerekiyorsa DeepSeek bağlantısını her bilgisayarda `/connect` üzerinden bir kez ayarla. SSH anahtarları ve Git kimlik doğrulaması makineye özeldir.

Bu düzen ortak skill'leri senkronlar. Proje kodu, veritabanları, `.env` ve geliştirme bağımlılıkları ayrıca kendi proje düzenleriyle yönetilir.

## Gereken araçlar ve testler

Kurulum: Linux/WSL, Python 3, Git ve ilk indirme için GitHub erişimi. OpenCode'u başlatmak için o ortamda `opencode` komutu bulunmalı. Güvenlik raporu doğrulayıcıları için Node.js gerekir.

```bash
python3 -m unittest discover -s opencode-shared/tests -v
bash -n opencode-shared/setup.sh
```

Yerel testler kurulumun tekrar çalıştırılmasını, mevcut skill ve komutların korunmasını, yedekleme davranışını, başarısız indirmede mevcut bağlantının korunmasını, komut argümanlarının aktarılmasını ve proje tarama kapsamını doğrular. Gerçek DeepSeek/OpenCode denetimi ayrıca yapılmalıdır.

Skill listesi: [SKILLS.md](SKILLS.md).
