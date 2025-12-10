import streamlit as st
import os
import io
import re
import pandas as pd
from pdfminer.high_level import extract_text
from pypdf import PdfReader
from unidecode import unidecode

# --- Funções auxiliares ---

def norm(s: str) -> str:
    return unidecode(s or "").lower()

def process_pdfs(uploaded_files_data, nome_busca):
    if not nome_busca:
        st.warning("Nome não informado. Por favor, digite um nome para buscar.")
        return pd.DataFrame()

    if not uploaded_files_data:
        st.warning("Nenhum PDF carregado. Por favor, carregue os arquivos primeiro.")
        return pd.DataFrame()

    st.info(f"Buscando por: '{nome_busca}' em {len(uploaded_files_data)} PDFs...")
    alvo = norm(nome_busca)
    resultados = []

    progress_bar = st.progress(0)
    status_text = st.empty()

    for i, (filename, content_bytes) in enumerate(uploaded_files_data.items()):
        status_text.text(f"Processando arquivo {i+1}/{len(uploaded_files_data)}: {filename}")
        progress_bar.progress((i + 1) / len(uploaded_files_data))

        try:
            file_like_object = io.BytesIO(content_bytes)

            titulo = os.path.basename(filename)
            try:
                file_like_object.seek(0)
                reader = PdfReader(file_like_object)
                md = reader.metadata or {}
                meta_title = md.get("/Title") or md.get("Title")
                if meta_title:
                    titulo = meta_title.strip()
            except Exception:
                pass

            texto = ""
            try:
                file_like_object.seek(0)
                texto = extract_text(file_like_object) or ""
            except Exception:
                try:
                    file_like_object.seek(0)
                    txt = []
                    r = PdfReader(file_like_object)
                    for page in r.pages:
                        txt.append(page.extract_text() or "")
                    texto = "\n".join(txt)
                except Exception:
                    texto = ""

            texto_norm = norm(texto)
            encontrado = alvo in texto_norm if texto_norm else False

            if encontrado:
                ocorrencias = len(re.findall(re.escape(alvo), texto_norm))
                resultados.append({
                    "TituloDocumento": titulo,
                    "Arquivo": filename,
                    "Ocorrencias": ocorrencias
                })
        except Exception as e:
            st.error(f"Erro ao processar o arquivo '{filename}': {e}")
            resultados.append({
                "TituloDocumento": os.path.basename(filename),
                "Arquivo": filename,
                "Ocorrencias": 0
            })
    
    progress_bar.empty() # Remove progress bar after completion
    status_text.empty() # Remove status text after completion

    if not resultados:
        st.info("Nenhum documento contém o nome informado.")
        return pd.DataFrame()
    else:
        df_results = pd.DataFrame(resultados).sort_values(["Ocorrencias", "TituloDocumento"], ascending=[False, True])
        st.success("Processamento concluído!")
        return df_results

# --- Interface Streamlit ---
st.set_page_config(layout="wide")
st.title("Buscador de Nomes em PDFs")

st.markdown("--- Busca por nomes em múltiplos arquivos PDF --- ")

# Campo de texto para o nome do servidor
nome_busca = st.text_input("Nome do servidor:", placeholder="Ex.: João da Silva")

# Botão para upload dos PDFs
uploaded_files = st.file_uploader("1. Carregar PDFs", type=["pdf"], accept_multiple_files=True)

# Variável de estado para armazenar arquivos carregados
if 'uploaded_files_data' not in st.session_state:
    st.session_state['uploaded_files_data'] = {}

# Adiciona novos arquivos à sessão, mantendo os antigos
if uploaded_files:
    for uploaded_file in uploaded_files:
        # Verifica se o arquivo já foi carregado para evitar duplicação
        if uploaded_file.name not in st.session_state['uploaded_files_data']:
            st.session_state['uploaded_files_data'][uploaded_file.name] = uploaded_file.read()
    st.success(f"Arquivos carregados no total: {len(st.session_state['uploaded_files_data'])}")
    
    # Mostrar lista de arquivos carregados
    with st.expander("Ver arquivos carregados"): # Usar expander para não poluir a tela
        for filename in st.session_state['uploaded_files_data'].keys():
            st.write(f"- {filename}")

# Botão para processar os PDFs
if st.button("2. Processar PDFs", type="primary", disabled=not st.session_state['uploaded_files_data']):
    with st.spinner('Processando PDFs... isso pode levar um tempo.'):
        df_resultados = process_pdfs(st.session_state['uploaded_files_data'], nome_busca)
        st.session_state['df_resultados_global'] = df_resultados # Armazena no estado da sessão

# Exibir resultados e botão de exportar CSV
if 'df_resultados_global' in st.session_state and not st.session_state['df_resultados_global'].empty:
    st.subheader("Documentos que contêm o nome:")
    st.dataframe(st.session_state['df_resultados_global'], use_container_width=True)

    out_csv = "resultado_busca_servidor.pdfs.csv"
    csv_data = st.session_state['df_resultados_global'].to_csv(index=False, encoding="utf-8-sig").encode('utf-8-sig')
    st.download_button(
        label="3. Exportar CSV",
        data=csv_data,
        file_name=out_csv,
        mime="text/csv",
        help="Baixar os resultados como um arquivo CSV."
    )
else:
    st.info("Nenhum resultado para exibir ainda. Carregue os PDFs e processe-os.")

# Botão para limpar arquivos e resultados (opcional)
if st.button("Limpar Todos os Arquivos e Resultados", help="Remove todos os PDFs carregados e os resultados atuais."):
    st.session_state['uploaded_files_data'] = {}
    st.session_state['df_resultados_global'] = pd.DataFrame() # Limpa os resultados
    st.experimental_rerun() # Reinicia o app para refletir a limpeza