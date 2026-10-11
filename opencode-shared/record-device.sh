#!/usr/bin/env bash
# Download/update the shared controller, then record the selected machine.
set -euo pipefail
device_id="${1:-}"
case "$device_id" in
  laptop|office) shift ;;
  *) printf 'Kullanım: bash record-device.sh laptop|office [--root /ek/klasor]\n' >&2; exit 1 ;;
esac
for required_command in git python3; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    printf 'Gerekli komut bulunamadı: %s\n' "$required_command" >&2
    exit 1
  fi
done
shared_checkout="$HOME/.local/share/digicut-opencode-skills"
shared_url='https://github.com/Digicut/awesome-claude-code-skills.git'
shared_branch='opencode-shared-skills'
export GIT_TERMINAL_PROMPT=0 GIT_OPTIONAL_LOCKS=0
if [ ! -e "$shared_checkout" ]; then
  mkdir -p "$(dirname "$shared_checkout")"
  git -c core.hooksPath=/dev/null clone --quiet --branch "$shared_branch" --single-branch "$shared_url" "$shared_checkout"
fi
if [ ! -d "$shared_checkout/.git" ] ||
   [ "$(git -C "$shared_checkout" config --get remote.origin.url)" != "$shared_url" ] ||
   [ "$(git -C "$shared_checkout" branch --show-current)" != "$shared_branch" ]; then
  printf 'Mevcut klasör beklenen ortak depo/dalla uyuşmuyor; korunuyor.\n' >&2
  exit 1
fi
if [ -n "$(git -C "$shared_checkout" -c core.fsmonitor=false status --porcelain)" ]; then
  printf 'Ortak araç deposunda yerel değişiklik var; güncelleme yapılmadı.\n' >&2
  exit 1
fi
if git -C "$shared_checkout" -c core.hooksPath=/dev/null fetch --quiet origin "$shared_branch" 2>/dev/null; then
  git -C "$shared_checkout" -c core.hooksPath=/dev/null -c core.fsmonitor=false merge --quiet --ff-only FETCH_HEAD
elif [ -f "$shared_checkout/opencode-shared/scripts/device_inventory.py" ]; then
  printf 'Ortak kaynak güncellenemedi; mevcut yerel araçla tarama yapılacak.\n' >&2
else
  printf 'Envanter aracı indirilemedi; bağlantıyı kontrol edip tekrar dene.\n' >&2
  exit 1
fi
record_args=("$@")
if [ -d /mnt/c/Users ]; then
  record_args+=(--root /mnt/c/Users)
fi
printf '%s cihazının WSL ana klasörü ve varsa Windows kullanıcı klasörleri taranıyor...\n' "$device_id"
exec python3 "$shared_checkout/opencode-shared/scripts/device_inventory.py" record --device "$device_id" "${record_args[@]}"
