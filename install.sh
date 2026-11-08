#!/usr/bin/env bash
# Instala a skill omnx-web-clonar-pagina no Claude Code, copiando desta pasta para ~/.claude/skills/omnx-web-clonar-pagina.
# Roda de qualquer lugar. Pode rodar de novo para atualizar.
set -euo pipefail
NOME="omnx-web-clonar-pagina"
ORIGEM="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DESTINO="$HOME/.claude/skills/$NOME"
if [ "$ORIGEM" = "$DESTINO" ]; then
  echo "A skill já está instalada nesta pasta. Nada a fazer."
  exit 0
fi
mkdir -p "$DESTINO"
for ITEM in SKILL.md README.md COMO-FUNCIONA.html references scripts; do
  if [ -e "$ORIGEM/$ITEM" ]; then
    cp -R "$ORIGEM/$ITEM" "$DESTINO/"
  fi
done
echo "Skill $NOME instalada em $DESTINO"
echo "Feche e abra a conversa para ela aparecer."
