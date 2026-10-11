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
device-record --device laptop
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

Yedek yolu yazdırılır. Kaynak dosyalar silinmez. Daha önce bu sistemin yönetmediği `oc`, `skills-list`, `skills-sync`, `device-record` veya `device-import` komutları varsa üzerine yazılmaz.

## Laptop ve ofis repo/skill kaydı

`devices.json` ortak cihaz adlarını tanımlar: `laptop` ve `office`. Gerçek disk listeleri bir tarama yapıldıktan sonra kayıt edilir; taranmamış bir cihazın sayıları sıfır olarak gösterilmez.

Envanter aracı bütün bulunan Git checkout/worktree konumlarını, origin repo kimliğini, dalı, commit'i, yerel değişiklik durumunu ve global/proje skill dosyalarını listeler. Git durumunu optional locks kapalı alır. Proje dosyaları, Git indeksi ve ayarları değiştirilmez. `.env`, API anahtarları, SSH anahtarları ve OpenCode auth dosyaları okunmaz. Remote adreslerinden kullanıcı adı/parola/query çıkarılır; raporda host ve repo kimliği bulunur.

Ortak depoyu güncelledikten sonra laptopta:

```bash
bash "$HOME/.local/share/digicut-opencode-skills/opencode-shared/record-device.sh" laptop
```

Ofiste aynı komutta `laptop` yerine `office` kullan. Bu başlatıcı WSL ana klasörünü, ortak araç deposunu ve varsa `/mnt/c/Users` altını tarar. Başka disk veya klasör için `--root /mnt/d/projeler` ekleyebilirsin. Dizin symlink'leri, gizli/cache/bağımlılık klasörleri atlanır; symlink'li bir proje için gerçek yolunu ayrıca `--root` ile ver. Global skill bağlantıları ayrıca okunur. Tarama kökleri ve sınırları rapora yazılır. Windows kullanıcı klasörlerindeki `.agents/skills`, `.claude/skills` ve `.config/opencode/skills` de bulunur; bu dosyaların WSL OpenCode tarafından yüklenmesi ayrıca değerlendirilir.

İlk kurulumu yapmadan da güncel kaynak deposundaki `record-device.sh` çalıştırılabilir. Python ve Git yeterli; bir skill veya DeepSeek oturumu başlatmaz.

Raporlar varsayılan olarak `$HOME/.local/share/digicut-environment/inventory/` altındadır (XDG_DATA_HOME varsa ona göre):

- `laptop.json` / `laptop.md`: laptopun en son taraması.
- `office.json` / `office.md`: ofis bilgisayarının en son taraması.
- `registry.json` / `registry.md`: bu klasördeki iki cihazı aynı listede toplar.
- `history/`: yenilenen önceki cihaz kayıtları korunur.

Bu raporlar herkese açık ortak Git deposuna gönderilmez. Raporları aynı özel klasöre getirerek veya JSON dosyasını buradan paylaşarak tek kayıt defterinde toplamak mümkündür. Cihazlar arasında gerçek envanter eşitlemesi bu aşamada elle yapılır; ortak araç ve skill tanımları Git üzerinden güncellenir.

Kurulumdan sonra kısayollar:

```bash
~/.local/bin/device-record --device laptop --root /mnt/c/Users
~/.local/bin/device-import /bir/yerden/office.json
```

Kısayollar yoksa doğrudan Python aracı:

```bash
python3 opencode-shared/scripts/device_inventory.py record --device laptop --root /mnt/c/Users
python3 opencode-shared/scripts/device_inventory.py import /bir/yerden/office.json
```

Okuma hataları veya tarama sınırı varsa raporda görünür. Repo checkout sayısı aynı repoya ait birden fazla worktree içerir; skill konumu sayısı aynı adlı birden fazla skill dosyası içerebilir. Dosya keşfi OpenCode izinlerini veya modelin skill'i gerçekten yüklediğini kanıtlamaz.

## DeepSeek ve makineye özel bilgiler

OpenCode içinde `/models` ile mevcut DeepSeek modelini seç. Skill kurulum araçları OpenCode model, API anahtarı veya kimlik doğrulama dosyalarını okumaz/kopyalamaz. Gerekiyorsa DeepSeek bağlantısını her bilgisayarda `/connect` üzerinden bir kez ayarla. SSH anahtarları ve Git kimlik doğrulaması makineye özeldir.

Bu düzen ortak skill'leri senkronlar. Proje kodu, veritabanları, `.env` ve geliştirme bağımlılıkları ayrıca kendi proje düzenleriyle yönetilir.

## Gereken araçlar ve testler

Kurulum: Linux/WSL, Python 3, Git ve ilk indirme için GitHub erişimi. OpenCode'u başlatmak için o ortamda `opencode` komutu bulunmalı. Güvenlik raporu doğrulayıcıları için Node.js gerekir.

```bash
python3 -m unittest discover -s opencode-shared/tests -v
bash -n opencode-shared/setup.sh
bash -n opencode-shared/record-device.sh
```

Yerel testler kurulumun tekrar çalıştırılmasını, mevcut skill ve komutların korunmasını, yedekleme davranışını, başarısız indirmede mevcut bağlantının korunmasını ve komut argümanlarının aktarılmasını doğrular. Envanter testleri gerçek Git repoları/worktree'leriyle salt okunur taramayı, gizli bilgilerin rapora alınmamasını, skill konumlarını, tarama sınırlarını, bilinmeyen cihaz sayılarının korunmasını ve rapor birleştirme/geçmişini doğrular. Gerçek DeepSeek/OpenCode denetimi ayrıca yapılmalıdır.

Skill listesi: [SKILLS.md](SKILLS.md).
