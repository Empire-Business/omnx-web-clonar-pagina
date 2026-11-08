---
name: omnx-web-clonar-pagina
description: "Salva uma cópia local de uma página pública como referência de estudo: index.html, arquivos, capturas do original e da cópia e um relatório do que faltou. Use quando a pessoa der um endereço e pedir 'clonar esta página', 'copiar esta página para estudar', 'guardar esta página como referência', 'baixar esta página', 'salvar o site localmente'. Não use para publicar a cópia, fazer página igual para passar como outra marca, página atrás de login ou paywall, nem para criar ou redesenhar site (morfo), escrever a copy da página (rita) ou extrair dados de sites (tales)."
---

# Clonar página para referência

Objetivo: guardar uma cópia local de uma página pública, para estudar como ela foi feita. Os caminhos desta skill são
relativos à pasta deste `SKILL.md`.

## As três regras (repita para a pessoa antes de copiar)

1. **Referência não é plágio.** A cópia serve para estudar layout, ritmo e soluções. Para criar algo próprio,
   recombine elementos de várias fontes e acrescente identidade própria. Se ela quiser uma página nova, indique o Morfo.
2. **A cópia não é publicada.** Esta skill não sobe a cópia para lugar nenhum. Nada se passa por marca real (mesmo
   nome, mesmo nicho, mesmo site). Textos, imagens e marcas continuam pertencendo aos donos.
3. **Login é limite.** A skill só copia o que qualquer pessoa vê sem entrar em conta. Nunca peça senha, nunca use a
   conta dela, nunca passe por captcha ou bloqueio. O navegador da skill abre sem nenhum login.

Se o pedido deixar claro que a intenção é publicar a cópia ou se passar por outra marca, recuse essa parte, explique
a regra e ofereça o Morfo para criar uma versão própria.

## Passos

1. Peça o endereço, se faltar. Diga as três regras em poucas linhas.
2. Pergunte em qual pasta salvar, podendo sugerir a pasta atual. Nunca dentro da pasta da skill.
3. Rode:
   ```bash
   python3 scripts/clonar.py "<url>" --pasta "<pasta escolhida>"
   ```
4. Leia o JSON e aja pelo `status` (tabela abaixo).
5. Abra `original.png` e `copia.png` e compare. Conte o que ficou diferente, sem prometer perfeição.
6. Entregue: pasta, `index.html`, o que foi baixado, o que falhou (`falhas`), o que continua vindo do site original
   (`continuam_no_site_original`), e a lembrança de que a cópia é para estudo.

## O que o script faz e o que muda na cópia

Abre a página num navegador sem janela, com perfil temporário, salva o HTML depois de carregado e baixa CSS, imagens e
fontes para `assets/`. Na cópia, **remove os scripts** e os rastreadores e **desliga os formulários**, para ela não
enviar nada ao site original; o HTML leva `noindex` e um aviso de origem no topo. Por isso, menu, carrossel e tudo
o que depende de script fica parado. Vídeo e iframe continuam apontando para o site original.

## Resultado do script

| `status` | Saída | O que fazer |
|---|---|---|
| `ok` | 0 | Entregue. |
| `parcial` | 0 | Entregue e liste o que faltou em `falhas`. |
| `pedido_invalido` | 1 | Peça o endereço completo ou outra pasta. Nunca aceite endereço com usuário e senha. |
| `bloqueado` | 2 | O site recusou acesso automático ou mostrou verificação contra robôs. Pare e não insista. |
| `pede_login` | 3 | Exige login. Pare. |
| `campo_de_senha` | 3 | Pergunte se é página pública com formulário de login. Se a pessoa confirmar, rode de novo com `--pagina-publica-confirmada`. Se o conteúdo fica atrás do login, pare. |
| `falta_navegador` | 4 | Peça para instalar o Google Chrome, com o aceite da pessoa, ou indique `CHROME_PATH`. |
| `nao_abriu` | 5 | Confira o endereço e tente uma vez. Depois, sugira salvar à mão. |

Nos casos de bloqueio ou falha, a saída para a pessoa é abrir a página no navegador dela e salvar com Ctrl+S (Windows
e Linux) ou Cmd+S (Mac). Isso é ela, usando o acesso dela.

## Outro sistema operacional

- Só biblioteca padrão de Python 3 e um navegador Chrome, Edge ou Chromium. No Windows, chame
  `py -3 scripts/clonar.py`; em alguns sistemas, `python3`. O navegador é procurado nos lugares comuns de Mac, Windows e
  Linux; se não achar, defina a variável `CHROME_PATH` com o caminho dele.
- Se aparecer erro de certificado em todos os downloads, o Python da pessoa está sem certificados: no Mac, rode o
  "Install Certificates.command" que vem com o Python oficial; no Windows, atualize o Python.
- A IA testa no computador da pessoa e conta o que realmente funcionou.

## Outra ferramenta (Codex e outras)

Esta skill foi testada no Claude Code. **Não foi testada no Codex.** Ao instalar em outra ferramenta, a IA da pessoa
deve: conferir na documentação atual onde aquela ferramenta guarda skills ou instruções; copiar esta pasta para lá;
ajustar o jeito de rodar o script; testar com uma página pública simples; e dizer à pessoa o que funcionou e o que não
funcionou.
