import streamlit as st
import os
import io
import re
import pandas as pd
from pdfminer.high_level import extract_text
from pypdf import PdfReader
from unidecode import unidecode

# ─── Configuração da página ───────────────────────────────────────────────────
st.set_page_config(
    page_title="Buscador de Termos em PDFs",
    page_icon="🔍",
    layout="wide",
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

    html, body, [class*="css"] { font-family: 'IBM Plex Sans', sans-serif; }

    .block-container { padding-top: 1.5rem; padding-bottom: 2rem; max-width: 1100px; }

    .header {
        background: #0a0a0a;
        color: #f0f0f0;
        padding: 1.4rem 2rem;
        border-radius: 10px;
        margin-bottom: 1.5rem;
        border-left: 5px solid #e63946;
    }
    .header h1 { margin: 0; font-size: 1.5rem; letter-spacing: -0.5px; }
    .header p  { margin: 0.3rem 0 0; font-size: 0.85rem; color: #aaa; }

    .file-chip {
        display: inline-flex; align-items: center; gap: 6px;
        background: #f0f4ff; border: 1px solid #c5d0f5;
        border-radius: 20px; padding: 4px 12px;
        font-size: 0.8rem; color: #1a237e; margin: 3px;
    }

    .result-card {
        background: white;
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        padding: 1rem 1.2rem;
        margin-bottom: 0.8rem;
        border-left: 4px solid #e63946;
    }
    .result-title { font-weight: 600; font-size: 0.95rem; color: #0a0a0a; }
    .result-meta  { font-size: 0.78rem; color: #666; margin-top: 2px; }
    .result-count {
        display: inline-block; background: #e63946; color: white;
        border-radius: 12px; padding: 2px 10px; font-size: 0.78rem;
        font-family: 'IBM Plex Mono', monospace; font-weight: 600;
        margin-left: 8px;
    }
    .snippet {
        background: #fafafa; border-left: 3px solid #ccc;
        padding: 6px 10px; margin-top: 8px;
        font-size: 0.8rem; font-family: 'IBM Plex Mono', monospace;
        color: #333; border-radius: 0 4px 4px 0;
        white-space: pre-wrap; word-break: break-word;
    }
    mark { background: #fff176; padding: 0 2px; border-radius: 2px; }

    .stat-box {
        background: #0a0a0a; color: white;
        border-radius: 8px; padding: 1rem;
        text-align: center;
    }
    .stat-box .num { font-size: 1.8rem; font-weight: 700; font-family: 'IBM Plex Mono', monospace; color: #e63946; }
    .stat-box .lbl { font-size: 0.78rem; color: #aaa; margin-top: 2px; }
</style>
""", unsafe_allow_html=True)

# ─── Header ───────────────────────────────────────────────────────────────────
st.markdown("""
<div class="header">
    <h1>🔍 Buscador de Termos em PDFs</h1>
    <p>Localize nomes, frases, números ou qualquer termo em múltiplos documentos PDF simultaneamente</p>
</div>
""", unsafe_allow_html=True)

with st.expander("ℹ️ Como usar — modos de busca", expanded=False):
    st.markdown("""
| Modo | Como digitar | Comportamento |
|---|---|---|
| **Flexível** *(padrão)* | `joao silva` | Ignora acentos e maiúsculas. `joão` encontra `João`, `JOÃO`, `joao` |
| **Exato** | `"João Silva"` | Respeita acentos e grafia. Só encontra exatamente `João Silva` (case-insensitive) |

**Dicas:**
- Use a busca **flexível** para nomes de pessoas — ela tolera variações de digitação nos PDFs.
- Use a busca **exata** (entre aspas `"..."`) para termos técnicos, números de matrícula, datas ou frases onde a grafia precisa ser precisa.
- Exemplo exato: `"127.884-5"` localiza apenas esse número de PM específico, sem falsos positivos.
""")


# ─── Inicialização do estado ───────────────────────────────────────────────────
if "uploaded_files_data" not in st.session_state:
    st.session_state.uploaded_files_data = {}
if "df_resultados" not in st.session_state:
    st.session_state.df_resultados = None
if "snippets_map" not in st.session_state:
    st.session_state.snippets_map = {}
if "ultimo_termo" not in st.session_state:
    st.session_state.ultimo_termo = ""
if "ultimo_modo" not in st.session_state:
    st.session_state.ultimo_modo = "normal"
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

# ─── Funções auxiliares ────────────────────────────────────────────────────────

def norm(s: str) -> str:
    return unidecode(s or "").lower()


def extrair_texto_pdf(content_bytes: bytes) -> str:
    """Tenta extrair texto com pdfminer, cai para pypdf se falhar."""
    file_like = io.BytesIO(content_bytes)
    try:
        file_like.seek(0)
        texto = extract_text(file_like) or ""
        if texto.strip():
            return texto
    except Exception:
        pass
    try:
        file_like.seek(0)
        reader = PdfReader(file_like)
        partes = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(partes)
    except Exception:
        return ""


def obter_titulo_pdf(content_bytes: bytes, fallback: str) -> str:
    """Tenta ler o título dos metadados do PDF."""
    try:
        reader = PdfReader(io.BytesIO(content_bytes))
        md = reader.metadata or {}
        titulo = md.get("/Title") or md.get("Title")
        if titulo and titulo.strip():
            return titulo.strip()
    except Exception:
        pass
    return fallback


def extrair_snippets(texto: str, termo_norm: str, max_snippets: int = 3, contexto: int = 120) -> list[str]:
    """Retorna trechos ao redor de cada ocorrência do termo."""
    texto_norm = norm(texto)
    snippets = []
    start = 0
    count = 0
    while count < max_snippets:
        pos = texto_norm.find(termo_norm, start)
        if pos == -1:
            break
        # Expande para capturar contexto em torno da ocorrência
        ini = max(0, pos - contexto)
        fim = min(len(texto), pos + len(termo_norm) + contexto)
        trecho = texto[ini:fim].strip().replace("\n", " ")
        # Destaca o termo no trecho (case-insensitive)
        trecho_norm = norm(trecho)
        pos_local = trecho_norm.find(termo_norm)
        if pos_local != -1:
            original = trecho[pos_local: pos_local + len(termo_norm)]
            trecho = trecho[:pos_local] + f"**{original}**" + trecho[pos_local + len(termo_norm):]
        snippets.append(("…" if ini > 0 else "") + trecho + ("…" if fim < len(texto) else ""))
        start = pos + len(termo_norm)
        count += 1
    return snippets


def detectar_modo(termo: str) -> tuple[str, str]:
    """
    Detecta se o termo está entre aspas (busca exata) ou não (busca flexível).
    Retorna (modo, termo_limpo).
    - modo "exato": preserva acentos, maiúsculas e espaços exatamente como digitado.
    - modo "normal": ignora acentos e maiúsculas via unidecode.
    """
    t = termo.strip()
    if (t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")):
        return "exato", t[1:-1]
    return "normal", t


def extrair_snippets_exato(texto: str, termo: str, max_snippets: int = 3, contexto: int = 120) -> list[str]:
    """Snippets para busca exata — preserva capitalização original, busca case-insensitive mas SEM remover acentos."""
    texto_lower = texto.lower()
    termo_lower = termo.lower()
    snippets = []
    start = 0
    count = 0
    while count < max_snippets:
        pos = texto_lower.find(termo_lower, start)
        if pos == -1:
            break
        ini = max(0, pos - contexto)
        fim = min(len(texto), pos + len(termo) + contexto)
        trecho = texto[ini:fim].strip().replace("\n", " ")
        # Destaca no trecho
        trecho_lower = trecho.lower()
        pos_local = trecho_lower.find(termo_lower)
        if pos_local != -1:
            original = trecho[pos_local: pos_local + len(termo)]
            trecho = trecho[:pos_local] + f"**{original}**" + trecho[pos_local + len(termo):]
        snippets.append(("…" if ini > 0 else "") + trecho + ("…" if fim < len(texto) else ""))
        start = pos + len(termo)
        count += 1
    return snippets


def processar_pdfs(files_data: dict, termo: str, mostrar_snippets: bool) -> tuple[pd.DataFrame, dict, str]:
    if not termo.strip():
        st.warning("⚠️ Digite um termo para buscar.")
        return pd.DataFrame(), {}, "normal"

    modo, termo_limpo = detectar_modo(termo)
    resultados = []
    snippets_map = {}

    barra = st.progress(0, text="Iniciando processamento…")
    total = len(files_data)

    for i, (filename, content_bytes) in enumerate(files_data.items()):
        barra.progress((i + 1) / total, text=f"Processando {i+1}/{total}: {filename}")

        try:
            titulo = obter_titulo_pdf(content_bytes, os.path.basename(filename))
            texto = extrair_texto_pdf(content_bytes)

            if modo == "exato":
                # Preserva acentos — apenas case-insensitive
                ocorrencias = len(re.findall(re.escape(termo_limpo), texto, re.IGNORECASE)) if texto else 0
                if ocorrencias > 0 and mostrar_snippets:
                    snippets_map[filename] = extrair_snippets_exato(texto, termo_limpo)
            else:
                # Flexível: ignora acentos e maiúsculas
                texto_norm = norm(texto)
                termo_norm = norm(termo_limpo)
                ocorrencias = len(re.findall(re.escape(termo_norm), texto_norm)) if texto_norm else 0
                if ocorrencias > 0 and mostrar_snippets:
                    snippets_map[filename] = extrair_snippets(texto, termo_norm)

            if ocorrencias > 0:
                resultados.append({
                    "Documento": titulo,
                    "Arquivo": filename,
                    "Ocorrências": ocorrencias,
                })
        except Exception as e:
            st.error(f"Erro em '{filename}': {e}")

    barra.empty()

    if not resultados:
        return pd.DataFrame(), {}, modo

    df = pd.DataFrame(resultados).sort_values(
        ["Ocorrências", "Documento"], ascending=[False, True]
    ).reset_index(drop=True)
    return df, snippets_map, modo


# ─── Sidebar: gerenciar arquivos ──────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📁 Arquivos carregados")

    uploaded = st.file_uploader(
        "Adicionar PDFs",
        type=["pdf"],
        accept_multiple_files=True,
        label_visibility="collapsed",
        key=f"uploader_{st.session_state.uploader_key}",
    )

    if uploaded:
        novos = 0
        for f in uploaded:
            if f.name not in st.session_state.uploaded_files_data:
                st.session_state.uploaded_files_data[f.name] = f.read()
                novos += 1
        if novos:
            st.toast(f"{novos} arquivo(s) adicionado(s)!", icon="✅")

    total_arqs = len(st.session_state.uploaded_files_data)

    if total_arqs == 0:
        st.info("Nenhum arquivo carregado ainda.")
    else:
        st.markdown(f"**{total_arqs} arquivo(s) na fila:**")

        # Lista com botão de remover individual
        para_remover = []
        for nome in list(st.session_state.uploaded_files_data.keys()):
            col_nome, col_btn = st.columns([5, 1])
            col_nome.markdown(
                f"<div class='file-chip'>📄 {nome[:30]}{'…' if len(nome)>30 else ''}</div>",
                unsafe_allow_html=True,
            )
            if col_btn.button("✕", key=f"rm_{nome}", help=f"Remover {nome}"):
                para_remover.append(nome)

        for nome in para_remover:
            del st.session_state.uploaded_files_data[nome]
            st.rerun()

        st.divider()

        # Botão de limpar tudo — CORRIGIDO
        if st.button("🗑️ Limpar tudo", use_container_width=True, type="secondary"):
            st.session_state.uploaded_files_data = {}
            st.session_state.df_resultados = None
            st.session_state.snippets_map = {}
            st.session_state.ultimo_termo = ""
            st.session_state.ultimo_modo = "normal"
            st.session_state.uploader_key += 1  # força recriação do widget file_uploader
            st.rerun()

# ─── Área principal ────────────────────────────────────────────────────────────
col_busca, col_opts = st.columns([3, 1])

with col_busca:
    termo_busca = st.text_input(
        "Termo de busca",
        placeholder='Ex.: João da Silva  ·  12345  ·  "grafia exata"',
        help='Busca flexível por padrão (ignora acentos). Para busca exata, coloque entre aspas: "João Silva"',
    )

with col_opts:
    mostrar_snippets = st.toggle("Mostrar trechos", value=True, help="Exibe contexto ao redor de cada ocorrência")

col_btn, col_info = st.columns([2, 5])

with col_btn:
    buscar = st.button(
        "🔍 Buscar",
        type="primary",
        disabled=(not st.session_state.uploaded_files_data or not termo_busca),
        use_container_width=True,
    )

with col_info:
    if not st.session_state.uploaded_files_data:
        st.caption("⬅️ Carregue PDFs na barra lateral para habilitar a busca.")
    elif not termo_busca:
        st.caption("Digite um termo para buscar.")
    else:
        st.caption(f"Pronto para buscar em **{len(st.session_state.uploaded_files_data)}** arquivo(s).")

# ─── Processar ────────────────────────────────────────────────────────────────
if buscar:
    df, snips, modo = processar_pdfs(
        st.session_state.uploaded_files_data,
        termo_busca,
        mostrar_snippets,
    )
    st.session_state.df_resultados = df
    st.session_state.snippets_map = snips
    st.session_state.ultimo_termo = termo_busca
    st.session_state.ultimo_modo = modo

# ─── Exibir resultados ─────────────────────────────────────────────────────────
df = st.session_state.df_resultados

if df is not None:
    if df.empty:
        st.warning(f"Nenhum documento contém o termo **'{st.session_state.ultimo_termo}'**.")
    else:
        termo_exibido = st.session_state.ultimo_termo
        modo_exibido = st.session_state.ultimo_modo
        _, termo_limpo_exibido = detectar_modo(termo_exibido)
        total_docs = len(df)
        total_ocorr = int(df["Ocorrências"].sum())
        total_pdfs = len(st.session_state.uploaded_files_data)

        # Estatísticas
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"""
            <div class="stat-box">
                <div class="num">{total_pdfs}</div>
                <div class="lbl">PDFs pesquisados</div>
            </div>""", unsafe_allow_html=True)
        c2.markdown(f"""
            <div class="stat-box">
                <div class="num">{total_docs}</div>
                <div class="lbl">Documentos com resultado</div>
            </div>""", unsafe_allow_html=True)
        c3.markdown(f"""
            <div class="stat-box">
                <div class="num">{total_ocorr}</div>
                <div class="lbl">Ocorrências totais</div>
            </div>""", unsafe_allow_html=True)

        badge = ('🎯 **Exato** — acentos preservados' if modo_exibido == "exato"
                 else '🔠 **Flexível** — acentos e maiúsculas ignorados')
        st.markdown(f"<br>**Resultados para:** `{termo_limpo_exibido}` &nbsp;·&nbsp; {badge}", unsafe_allow_html=True)

        # Cards de resultado
        for _, row in df.iterrows():
            filename = row["Arquivo"]
            snips = st.session_state.snippets_map.get(filename, [])

            with st.container():
                st.markdown(
                    f"""<div class="result-card">
                        <span class="result-title">📄 {row['Documento']}</span>
                        <span class="result-count">{row['Ocorrências']} ocorrência(s)</span>
                        <div class="result-meta">{filename}</div>
                    </div>""",
                    unsafe_allow_html=True,
                )
                if snips:
                    with st.expander("Ver trechos encontrados"):
                        for s in snips:
                            # Renderiza negrito como destaque
                            s_html = re.sub(r"\*\*(.+?)\*\*", r"<mark>\1</mark>", s)
                            st.markdown(
                                f'<div class="snippet">{s_html}</div>',
                                unsafe_allow_html=True,
                            )

        st.divider()

        # Exportar CSV
        csv_bytes = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button(
            label="⬇️ Exportar resultados (CSV)",
            data=csv_bytes,
            file_name=f"busca_{norm(termo_exibido)[:30]}.csv",
            mime="text/csv",
        )
