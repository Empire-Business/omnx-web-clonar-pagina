#!/usr/bin/env python3
"""Salva uma cópia local de uma página pública, para estudo de referência.

Uso:
    clonar.py <url> --pasta <pasta-onde-salvar> [--pagina-publica-confirmada]

O que faz: abre a página num navegador sem janela (Chrome, Edge ou Chromium já instalado),
guarda o HTML como ficou depois de carregar, baixa CSS, imagens e fontes, remove os scripts
e grava index.html, assets/, duas capturas (original.png e copia.png) e relatorio.json.

O que não faz: não usa o perfil nem o login da pessoa, não passa por captcha ou bloqueio,
não publica nada. Formulários da cópia ficam desligados e a página leva noindex.

Códigos de saída:
    0 copiada | 1 pedido inválido | 2 site bloqueou o acesso | 3 pede login
    4 falta navegador | 5 página não abriu
"""
import argparse
import datetime
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

AGENTE = "Mozilla/5.0 (compatible; copia-de-referencia/1.0)"
LARGURA_CAPTURA = 1280
ALTURA_CAPTURA = 2400
ESPERA_MS = 8000
TEMPO_LIMITE_NAVEGADOR = 60
TEMPO_LIMITE_ARQUIVO = 30
MAX_ARQUIVO = 25 * 1024 * 1024
MAX_TOTAL = 200 * 1024 * 1024
MAX_ARQUIVOS = 500
PAUSA_ENTRE_ARQUIVOS = 0.15  # não sobrecarregar o site de origem

CAMINHOS_LOGIN = re.compile(r"/(login|signin|sign-in|entrar|wp-login|auth|conta/entrar)(\.|/|$)", re.I)
TITULOS_BLOQUEIO = re.compile(
    r"<title[^>]*>\s*(just a moment|attention required|access denied|verify you are human|"
    r"um momento|acesso negado|checking your browser)", re.I)
CAMPO_SENHA = re.compile(r"<input\b[^>]*\btype\s*=\s*[\"']?password", re.I)
URL_CSS = re.compile(r"url\(\s*(['\"]?)([^'\")]+?)\1\s*\)", re.I)
IMPORT_CSS = re.compile(r"@import\s+(?:url\(\s*)?(['\"]?)([^'\"\)\s;]+)\1\s*\)?", re.I)
SRCSET_ITEM = re.compile(r"\s*(\S+?)(?:\s+([\d.]+)([wx]))?\s*(?:,(?=\s|$)|$)")
PULAR_REL = {"preload", "prefetch", "dns-prefetch", "preconnect", "modulepreload", "manifest"}
ICONE_REL = {"icon", "shortcut", "apple-touch-icon", "mask-icon"}
ATRIBUTOS_LAZY = ("data-src", "data-lazy-src", "data-original")


def sair(codigo, status, mensagem, o_que_fazer, **extra):
    corpo = {"status": status, "mensagem": mensagem, "o_que_fazer": o_que_fazer}
    corpo.update(extra)
    print(json.dumps(corpo, ensure_ascii=False, indent=2))
    sys.exit(codigo)


def achar_navegador():
    candidatos = [os.environ.get("CHROME_PATH", "")]
    for nome in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "chrome", "msedge"):
        candidatos.append(shutil.which(nome) or "")
    if sys.platform == "darwin":
        for app, binario in (("Google Chrome", "Google Chrome"), ("Chromium", "Chromium"),
                             ("Microsoft Edge", "Microsoft Edge"), ("Brave Browser", "Brave Browser")):
            candidatos.append("/Applications/{}.app/Contents/MacOS/{}".format(app, binario))
    if os.name == "nt":
        for base in (os.environ.get("PROGRAMFILES", ""), os.environ.get("PROGRAMFILES(X86)", ""), os.environ.get("LOCALAPPDATA", "")):
            if base:
                candidatos.append(str(Path(base) / "Google/Chrome/Application/chrome.exe"))
                candidatos.append(str(Path(base) / "Microsoft/Edge/Application/msedge.exe"))
    for caminho in candidatos:
        if caminho and Path(caminho).is_file():
            return caminho
    return None


def rodar_navegador(navegador, argumentos):
    """Roda o navegador com perfil temporário: nunca vê os logins da pessoa."""
    with tempfile.TemporaryDirectory(prefix="copia-ref-") as perfil:
        comando = [navegador, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                   "--hide-scrollbars", "--user-data-dir=" + perfil] + argumentos
        try:
            return subprocess.run(comando, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=TEMPO_LIMITE_NAVEGADOR)
        except subprocess.TimeoutExpired:
            return None


def conferir_acesso(url):
    """Confere a resposta antes de abrir: login e bloqueio param aqui."""
    pedido = urllib.request.Request(url, headers={"User-Agent": AGENTE, "Accept": "text/html,*/*"})
    try:
        with urllib.request.urlopen(pedido, timeout=TEMPO_LIMITE_ARQUIVO) as resposta:
            return resposta.geturl(), resposta.status
    except urllib.error.HTTPError as erro:
        return erro.geturl() or url, erro.code
    except (urllib.error.URLError, OSError, ValueError) as erro:
        sair(5, "nao_abriu", "Não consegui abrir a página: {}".format(erro),
             "Confira o endereço e a internet.")


def caminho_relativo(de, para):
    return Path(os.path.relpath(para, de)).as_posix()


class Baixador:
    """Baixa cada arquivo uma vez e guarda em assets/<tipo>/ com nome estável."""

    TIPOS = {
        ".css": "css", ".woff": "fontes", ".woff2": "fontes", ".ttf": "fontes", ".otf": "fontes", ".eot": "fontes",
        ".png": "img", ".jpg": "img", ".jpeg": "img", ".gif": "img", ".webp": "img", ".avif": "img", ".svg": "img", ".ico": "img",
    }
    EXTENSOES = {
        "text/css": ".css", "image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp",
        "image/avif": ".avif", "image/svg+xml": ".svg", "image/x-icon": ".ico", "image/vnd.microsoft.icon": ".ico",
        "font/woff2": ".woff2", "font/woff": ".woff", "font/ttf": ".ttf", "font/otf": ".otf",
    }

    def __init__(self, pasta, origem):
        self.pasta = pasta
        self.origem = origem
        self.mapa = {}
        self.falhas = []
        self.contagem = {"css": 0, "img": 0, "fontes": 0, "outros": 0}
        self.total = 0

    def falhar(self, url, motivo):
        self.falhas.append({"url": url, "motivo": motivo})
        self.mapa[url] = None
        return None

    def baixar(self, url):
        if url in self.mapa:
            return self.mapa[url]
        if sum(self.contagem.values()) >= MAX_ARQUIVOS:
            return self.falhar(url, "limite de {} arquivos atingido".format(MAX_ARQUIVOS))
        time.sleep(PAUSA_ENTRE_ARQUIVOS)
        pedido = urllib.request.Request(url, headers={"User-Agent": AGENTE, "Referer": self.origem})
        try:
            with urllib.request.urlopen(pedido, timeout=TEMPO_LIMITE_ARQUIVO) as resposta:
                tipo_http = resposta.headers.get_content_type()
                dados = resposta.read(MAX_ARQUIVO + 1)
        except urllib.error.HTTPError as erro:
            return self.falhar(url, "HTTP {}".format(erro.code))
        except (urllib.error.URLError, OSError, ValueError) as erro:
            return self.falhar(url, str(erro))
        if len(dados) > MAX_ARQUIVO:
            return self.falhar(url, "arquivo maior que o limite")
        if self.total + len(dados) > MAX_TOTAL:
            return self.falhar(url, "limite total da cópia atingido")

        caminho_url = urllib.parse.urlsplit(url).path
        extensao = Path(caminho_url).suffix.lower()
        if extensao not in self.TIPOS:
            extensao = self.EXTENSOES.get(tipo_http, extensao if len(extensao) <= 6 else "")
        tipo = self.TIPOS.get(extensao, "outros")
        base = re.sub(r"[^a-z0-9]+", "-", Path(caminho_url).stem.lower()).strip("-")[:40] or "arquivo"
        assinatura = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
        destino = self.pasta / "assets" / tipo / "{}-{}{}".format(base, assinatura, extensao)
        destino.parent.mkdir(parents=True, exist_ok=True)
        self.mapa[url] = destino
        if tipo == "css":
            texto = dados.decode("utf-8", errors="replace")
            dados = self.reescrever_css(texto, url, destino.parent).encode("utf-8")
        destino.write_bytes(dados)
        self.total += len(dados)
        self.contagem[tipo] += 1
        return destino

    def reescrever_css(self, texto, base_url, pasta_css):
        def trocar(url_original, formato):
            if url_original.startswith(("data:", "#")):
                return None
            absoluta = urllib.parse.urldefrag(urllib.parse.urljoin(base_url, url_original))[0]
            if not absoluta.startswith(("http://", "https://")):
                return None
            arquivo = self.baixar(absoluta)
            return formato.format(caminho_relativo(pasta_css, arquivo)) if arquivo else None

        def trocar_url(achado):
            return trocar(achado.group(2), 'url("{}")') or achado.group(0)

        def trocar_import(achado):
            return trocar(achado.group(2), '@import "{}"') or achado.group(0)

        return URL_CSS.sub(trocar_url, IMPORT_CSS.sub(trocar_import, texto))


class Reescritor(HTMLParser):
    """Reescreve o HTML: tira scripts e rastreio, aponta os arquivos para a cópia local."""

    def __init__(self, url_base, baixador):
        super().__init__(convert_charrefs=False)
        self.url_base = url_base
        self.baixador = baixador
        self.saida = []
        self.pulando = None
        self.profundidade = 0
        self.em_style = False
        self.em_midia = 0
        self.removidos = {"scripts": 0, "noscript": 0, "pre_carregamentos": 0}
        self.externos = []
        self.formularios = 0

    def absoluta(self, url):
        url = (url or "").strip()
        if not url or url.startswith(("data:", "#", "mailto:", "tel:", "javascript:")):
            return None
        return urllib.parse.urljoin(self.url_base, url)

    def local(self, url):
        absoluta = self.absoluta(url)
        if not absoluta or not absoluta.startswith(("http://", "https://")):
            return None
        arquivo = self.baixador.baixar(urllib.parse.urldefrag(absoluta)[0])
        return caminho_relativo(self.baixador.pasta, arquivo) if arquivo else None

    def maior_do_srcset(self, valor):
        melhor, nota = None, -1.0
        for achado in SRCSET_ITEM.finditer(valor or ""):
            if achado.group(1) and float(achado.group(2) or 1) > nota:
                melhor, nota = achado.group(1), float(achado.group(2) or 1)
        return melhor

    def css_local(self, texto):
        pasta = self.baixador.pasta
        return self.baixador.reescrever_css(texto, self.url_base, pasta)

    def tratar(self, tag, atributos):
        """Devolve os atributos novos, ou None para remover a tag."""
        attrs = {nome: (valor if valor is not None else "") for nome, valor in atributos}
        if tag == "base":
            if attrs.get("href"):
                self.url_base = urllib.parse.urljoin(self.url_base, attrs["href"])
            return None
        if tag == "meta":
            equivalente = attrs.get("http-equiv", "").lower()
            if equivalente in ("refresh", "content-security-policy", "content-type") or "charset" in attrs:
                return None
        if tag == "link":
            rels = set(attrs.get("rel", "").lower().split())
            if rels & PULAR_REL:
                self.removidos["pre_carregamentos"] += 1
                return None
            if "stylesheet" in rels or rels & ICONE_REL:
                novo = self.local(attrs.get("href"))
                attrs["href"] = novo or self.absoluta(attrs.get("href")) or ""
                attrs.pop("integrity", None)
                attrs.pop("crossorigin", None)
        if tag in ("img", "source"):
            for lazy in ATRIBUTOS_LAZY:
                if attrs.get(lazy) and (not attrs.get("src") or attrs["src"].startswith("data:")):
                    attrs["src"] = attrs[lazy]
            if not self.em_midia:
                escolhida = self.maior_do_srcset(attrs.get("srcset"))
                if tag == "img":
                    fonte = escolhida or attrs.get("src")
                    novo = self.local(fonte)
                    if novo:
                        attrs["src"] = novo
                    elif attrs.get("src"):
                        attrs["src"] = self.absoluta(attrs["src"]) or attrs["src"]
                    attrs.pop("srcset", None)
                    attrs.pop("sizes", None)
                else:
                    novo = self.local(escolhida or attrs.get("src"))
                    if novo:
                        attrs["srcset"] = novo
                        attrs.pop("sizes", None)
                        attrs.pop("src", None)
                attrs.pop("integrity", None)
                attrs.pop("crossorigin", None)
            elif attrs.get("src"):
                attrs["src"] = self.absoluta(attrs["src"]) or attrs["src"]
        if tag in ("video", "audio"):
            if attrs.get("src"):
                attrs["src"] = self.absoluta(attrs["src"]) or attrs["src"]
                self.externos.append({"tipo": tag, "url": attrs["src"]})
            if attrs.get("poster"):
                attrs["poster"] = self.local(attrs["poster"]) or self.absoluta(attrs["poster"]) or attrs["poster"]
        if tag in ("iframe", "embed", "object"):
            campo = "data" if tag == "object" else "src"
            if attrs.get(campo):
                attrs[campo] = self.absoluta(attrs[campo]) or attrs[campo]
                self.externos.append({"tipo": tag, "url": attrs[campo]})
        if tag in ("a", "area") and "href" in attrs:
            attrs["href"] = "#" if attrs["href"].strip().lower().startswith("javascript:") else (self.absoluta(attrs["href"]) or attrs["href"])
        if tag == "form":
            attrs["action"] = "#"
            attrs["method"] = "get"
            self.formularios += 1
        if tag in ("use", "image"):
            for campo in ("href", "xlink:href"):
                if attrs.get(campo) and not attrs[campo].startswith("#"):
                    attrs[campo] = self.local(attrs[campo]) or self.absoluta(attrs[campo]) or attrs[campo]
        if attrs.get("style") and "url(" in attrs["style"]:
            attrs["style"] = self.css_local(attrs["style"])
        return {nome: valor for nome, valor in attrs.items() if not nome.startswith("on")}

    def montar(self, tag, attrs, fecha=False):
        partes = [tag]
        for nome, valor in attrs.items():
            partes.append('{}="{}"'.format(nome, html.escape(valor, quote=True)))
        return "<{}{}>".format(" ".join(partes), " /" if fecha else "")

    def handle_starttag(self, tag, attrs):
        if self.pulando:
            if tag == self.pulando:
                self.profundidade += 1
            return
        if tag in ("script", "noscript"):
            self.removidos["scripts" if tag == "script" else "noscript"] += 1
            self.pulando, self.profundidade = tag, 1
            return
        if tag in ("video", "audio"):
            self.em_midia += 1
        if tag == "style":
            self.em_style = True
        novos = self.tratar(tag, attrs)
        if novos is None:
            return
        self.saida.append(self.montar(tag, novos))
        if tag == "head":
            self.saida.append('<meta charset="utf-8"><meta name="robots" content="noindex,nofollow">')

    def handle_startendtag(self, tag, attrs):
        if self.pulando or tag in ("script", "noscript"):
            return
        novos = self.tratar(tag, attrs)
        if novos is not None:
            self.saida.append(self.montar(tag, novos, fecha=True))

    def handle_endtag(self, tag):
        if self.pulando:
            if tag == self.pulando:
                self.profundidade -= 1
                if self.profundidade == 0:
                    self.pulando = None
            return
        if tag == "style":
            self.em_style = False
        if tag in ("video", "audio") and self.em_midia:
            self.em_midia -= 1
        if tag != "base":
            self.saida.append("</{}>".format(tag))

    def handle_data(self, data):
        if self.pulando:
            return
        self.saida.append(self.css_local(data) if self.em_style else data)

    def handle_entityref(self, name):
        if not self.pulando:
            self.saida.append("&{};".format(name))

    def handle_charref(self, name):
        if not self.pulando:
            self.saida.append("&#{};".format(name))

    def handle_decl(self, decl):
        self.saida.append("<!{}>".format(decl))


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Salva uma cópia local de uma página pública, para referência.")
    parser.add_argument("url")
    parser.add_argument("--pasta", required=True, help="pasta onde criar a cópia (a pessoa escolhe)")
    parser.add_argument("--pagina-publica-confirmada", action="store_true",
                        help="use só depois que a pessoa confirmar que a página é pública apesar do campo de senha")
    args = parser.parse_args()

    partes = urllib.parse.urlsplit(args.url)
    if partes.scheme not in ("http", "https") or not partes.hostname:
        sair(1, "pedido_invalido", "Isto não é um endereço de página: {}".format(args.url), "Peça o endereço completo, com https://.")
    if partes.username or partes.password:
        sair(1, "pedido_invalido", "O endereço traz usuário e senha.", "Não use credenciais. Peça uma página pública.")
    base = Path(args.pasta).expanduser().resolve()
    pasta_skill = Path(__file__).resolve().parent.parent
    if base == pasta_skill or pasta_skill in base.parents:
        sair(1, "pedido_invalido", "A cópia não pode ficar dentro da pasta da skill.", "Pergunte à pessoa outra pasta.")

    navegador = achar_navegador()
    if not navegador:
        sair(4, "falta_navegador", "Não encontrei Chrome, Edge ou Chromium neste computador.",
             "Peça para instalar o Google Chrome ou indique o caminho na variável CHROME_PATH.")

    url_final, status = conferir_acesso(args.url)
    if status in (401, 407) or CAMINHOS_LOGIN.search(urllib.parse.urlsplit(url_final).path):
        sair(3, "pede_login", "Esta página exige login. A skill não entra em contas.",
             "Pare. Peça uma página pública, ou a própria pessoa salva com Ctrl+S ou Cmd+S.", url=url_final)
    if status in (403, 429, 503):
        sair(2, "bloqueado", "O site recusou o acesso automático (HTTP {}).".format(status),
             "Pare e não insista. A pessoa pode salvar a página à mão com Ctrl+S ou Cmd+S.", url=url_final)
    if status >= 400:
        sair(5, "nao_abriu", "A página respondeu com erro HTTP {}.".format(status), "Confira o endereço.", url=url_final)

    resultado = rodar_navegador(navegador, ["--virtual-time-budget={}".format(ESPERA_MS), "--dump-dom", url_final])
    if resultado is None or resultado.returncode != 0 or not resultado.stdout.strip():
        sair(5, "nao_abriu", "O navegador não conseguiu carregar a página.", "Tente de novo. Se repetir, salve à mão com Ctrl+S ou Cmd+S.", url=url_final)
    dom = resultado.stdout.decode("utf-8", errors="replace")

    if TITULOS_BLOQUEIO.search(dom):
        sair(2, "bloqueado", "O site mostrou uma tela de verificação contra robôs.",
             "Pare. Não tente passar pela verificação. A pessoa pode salvar a página à mão.", url=url_final)
    if CAMPO_SENHA.search(dom) and not args.pagina_publica_confirmada:
        sair(3, "campo_de_senha", "A página tem campo de senha.",
             "Pergunte se é uma página pública com formulário de login. Se for, rode de novo com --pagina-publica-confirmada. Se o conteúdo está atrás do login, pare.", url=url_final)

    dominio = re.sub(r"[^a-z0-9]+", "-", (urllib.parse.urlsplit(url_final).hostname or "pagina").lower()).strip("-")
    hoje = datetime.date.today().isoformat()
    nome, tentativa = "copia-{}-{}".format(dominio, hoje), 1
    pasta = base / nome
    while pasta.exists():
        tentativa += 1
        pasta = base / "{}-{}".format(nome, tentativa)
    pasta.mkdir(parents=True)

    baixador = Baixador(pasta, url_final)
    reescritor = Reescritor(url_final, baixador)
    reescritor.feed(dom)
    reescritor.close()
    aviso_topo = "<!-- Cópia local para estudo de referência. Origem: {} em {}. Não publique nem use como se fosse sua. -->\n".format(
        url_final.replace("--", "%2D%2D"), hoje)
    conteudo = "".join(reescritor.saida)
    if conteudo.lower().startswith("<!doctype"):
        fim = conteudo.index(">") + 1
        conteudo = conteudo[:fim] + "\n" + aviso_topo + conteudo[fim:]
    else:
        conteudo = "<!doctype html>\n" + aviso_topo + conteudo
    indice = pasta / "index.html"
    indice.write_text(conteudo, encoding="utf-8")

    janela = "--window-size={},{}".format(LARGURA_CAPTURA, ALTURA_CAPTURA)
    avisos = []
    for arquivo, endereco, espera in (("original.png", url_final, True), ("copia.png", indice.as_uri(), False)):
        extra = ["--virtual-time-budget={}".format(ESPERA_MS)] if espera else []
        retorno = rodar_navegador(navegador, extra + [janela, "--screenshot={}".format(pasta / arquivo), endereco])
        if retorno is None or not (pasta / arquivo).exists():
            avisos.append("Não consegui tirar a captura {}.".format(arquivo))
    if CAMPO_SENHA.search(dom):
        avisos.append("A página tem campo de senha; a pessoa confirmou que é pública.")

    relatorio = {
        "status": "parcial" if baixador.falhas else "ok",
        "origem": url_final,
        "data": hoje,
        "pasta": str(pasta),
        "index": str(indice),
        "baixados": baixador.contagem,
        "tamanho_bytes": baixador.total,
        "falhas": baixador.falhas,
        "continuam_no_site_original": reescritor.externos,
        "removidos": dict(reescritor.removidos),
        "formularios_desligados": reescritor.formularios,
        "avisos": avisos,
        "regra": "Cópia para estudo. Não publicar, não passar por marca real.",
    }
    (pasta / "relatorio.json").write_text(json.dumps(relatorio, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(relatorio, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
