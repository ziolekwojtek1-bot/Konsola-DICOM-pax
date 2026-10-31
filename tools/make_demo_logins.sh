#!/bin/sh
# Tworzy konta pokazowe (wspólne hasło) w nginx/htpasswd. Użycie: sh tools/make_demo_logins.sh 'HASLO'
set -e
[ -n "$1" ] || { echo "Podaj hasło: sh tools/make_demo_logins.sh 'HASLO'"; exit 1; }
cd "$(dirname "$0")/.."
: > nginx/htpasswd
for login in radiolog radiolog2 lekarz lekarz2 dyzurny ordynator technik rejestracja; do
  printf '%s:%s\n' "$login" "$(openssl passwd -apr1 "$1")" >> nginx/htpasswd
done
echo "Utworzono konta: radiolog, radiolog2, lekarz, lekarz2, dyzurny, ordynator, technik, rejestracja"
